"""FolderRepository — CRUD and domain queries for the ``library_folders`` table.

Replaces ``folder_has_folder`` edge traversals with ``parent_id``
self-reference FK and ``library_id`` FK column.

Overlap: a concurrent song-domain agent (TASK-song-intent-facade-correction-A)
is mid-refactor of this file (they moved read mapping from ``LibraryFolderRow``
to the domain ``LibraryFolder`` and removed ``_row_to_dto``/``select_by_key``).
This change completes that mapping toward the facade contract of
``TASK-library-domain-facades-A`` (P3-S2): read methods return the domain
``LibraryFolder`` value object, ``parent_id`` is expressed as ``parent_path``,
and folder ids / parent ids / payload dictionaries stay repository-internal.
Write methods keep their storage-shaped signatures so the persistence facade
resolves ids/payloads internally.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Table, delete, select, update

from nomarr.helpers.dataclasses.library_domain_dataclasses import LibraryFolder
from nomarr.persistence.models.library_folder import LibraryFolder as LibraryFolderModel
from nomarr.persistence.sql.exceptions import map_persistence_exceptions
from nomarr.persistence.sql.primitives import insert_one

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, scoped_session

_T = cast("Table", LibraryFolderModel.__table__)


def _row_to_domain(row: Row, parent_path: str | None = None) -> LibraryFolder:
    """Map a storage row to the caller-facing folder value object."""
    m = row._mapping
    return LibraryFolder(
        path=m["path"],
        name=m["name"],
        parent_path=parent_path,
        mtime=m["mtime"],
        file_count=m["file_count"],
        last_scanned_at=m["last_scanned_at"],
    )


class FolderRepository:
    """Repository for the ``library_folders`` table."""

    def __init__(self, session: scoped_session[Session]) -> None:
        self._session = session

    # ── internal helpers ─────────────────────────────────────────

    def _path_by_id(self, library_id: int) -> dict[int, str]:
        """Return ``{folder_id: path}`` for a library (id stays internal)."""
        rows = self._session.execute(select(_T.c.id, _T.c.path).where(_T.c.library_id == library_id)).all()
        return {int(row.id): row.path for row in rows}

    def _resolve_parent_path(self, row: Row, path_by_id: dict[int, str]) -> str | None:
        """Express a row's ``parent_id`` as the parent's domain ``parent_path``."""
        parent_id = row._mapping["parent_id"]
        if parent_id is None:
            return None
        return path_by_id.get(int(parent_id))

    def _single_to_domain(self, row: Row, library_id: int) -> LibraryFolder:
        """Map one row, resolving its parent path with a focused lookup."""
        path_by_id = self._path_by_id(library_id)
        return _row_to_domain(row, self._resolve_parent_path(row, path_by_id))

    # ── basic CRUD ──────────────────────────────────────────────

    def add_folder(self, payload: dict[str, Any]) -> int:
        """Insert a new folder row and return its ``id``."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                row = insert_one(_T, payload, session=self._session)
            self._session.commit()
            return int(row._mapping["id"])

    def add_library_folder(self, library_id: int, payload: dict[str, Any]) -> int:
        """Insert a folder linked to a specific library."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                data = {**payload, "library_id": library_id}
                row = insert_one(_T, data, session=self._session)
            self._session.commit()
            return int(row._mapping["id"])

    def replace_library_folder(self, library_id: int, folder_id: int, payload: dict[str, Any]) -> None:
        """Atomically update one folder row scoped to a library."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(
                    update(_T).where(_T.c.id == folder_id, _T.c.library_id == library_id).values(payload)
                )
            self._session.commit()

    def get_folder_id_by_path(self, library_id: int, path: str) -> int | None:
        """Resolve a folder's storage id by path (id never leaves persistence).

        Used by the persistence facade to translate a domain ``folder_path``
        into the storage id needed for replace/remove mutations.
        """
        with map_persistence_exceptions():
            stmt = select(_T.c.id).where(_T.c.library_id == library_id, _T.c.path == path)
            row = self._session.execute(stmt).fetchone()
            return int(row[0]) if row is not None else None

    def get_folder_by_path(self, library_id: int, path: str) -> LibraryFolder | None:
        """Fetch a folder by path within a specific library."""
        with map_persistence_exceptions():
            stmt = select(_T).where(
                _T.c.library_id == library_id,
                _T.c.path == path,
            )
            result = self._session.execute(stmt)
            row = result.fetchone()
            return None if row is None else self._single_to_domain(row, library_id)

    def get_folder(self, folder_id: int) -> LibraryFolder | None:
        """Fetch a single folder by primary key."""
        with map_persistence_exceptions():
            stmt = select(_T).where(_T.c.id == folder_id)
            result = self._session.execute(stmt)
            row = result.fetchone()
            if row is None:
                return None
            library_id = int(row._mapping["library_id"])
            return self._single_to_domain(row, library_id)

    def list_folders_for_library(self, library_id: int) -> list[LibraryFolder]:
        """Return all folders belonging to a library, with parent paths."""
        with map_persistence_exceptions():
            stmt = select(_T).where(_T.c.library_id == library_id)
            rows = self._session.execute(stmt).all()
            path_by_id = self._path_by_id(library_id)
            return [_row_to_domain(row, self._resolve_parent_path(row, path_by_id)) for row in rows]

    def get_root_folders(self, library_id: int) -> list[LibraryFolder]:
        """Return top-level folders (``parent_id IS NULL``) for a library."""
        with map_persistence_exceptions():
            stmt = select(_T).where(
                _T.c.library_id == library_id,
                _T.c.parent_id.is_(None),
            )
            return [_row_to_domain(r) for r in self._session.execute(stmt).all()]

    def get_by_parent(self, library_id: int, parent_id: int) -> list[LibraryFolder]:
        """Return child folders of a given parent within a library."""
        with map_persistence_exceptions():
            stmt = select(_T).where(
                _T.c.library_id == library_id,
                _T.c.parent_id == parent_id,
            )
            rows = self._session.execute(stmt).all()
            path_by_id = self._path_by_id(library_id)
            return [_row_to_domain(row, self._resolve_parent_path(row, path_by_id)) for row in rows]

    def remove_library_folder(self, library_id: int, folder_id: int) -> None:
        """Delete a folder by id, scoped to a library."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = delete(_T).where(
                    _T.c.id == folder_id,
                    _T.c.library_id == library_id,
                )
                self._session.execute(stmt)
            self._session.commit()

    def replace_library_folders(self, library_id: int, payloads: list[dict[str, Any]]) -> None:
        """Reconcile a library's folders with *payloads*, preserving row ids.

        Songs reference folders by id, so replacing every row would trigger
        ``ON DELETE SET NULL`` for every song in the library.  Match folders by
        their stable path, update those rows in place, insert new paths, and
        remove only paths that are no longer present.
        """
        with map_persistence_exceptions():
            with self._session.begin_nested():
                existing_rows = self._session.execute(
                    select(_T.c.id, _T.c.path).where(_T.c.library_id == library_id)
                ).all()
                existing_ids_by_path = {row.path: row.id for row in existing_rows}
                retained_ids: set[int] = set()

                for payload in payloads:
                    path = payload["path"]
                    folder_id = existing_ids_by_path.get(path)
                    if folder_id is None:
                        row = self._session.execute(
                            _T.insert().values({**payload, "library_id": library_id}).returning(_T.c.id)
                        ).one()
                        folder_id = int(row.id)
                    else:
                        values = {key: value for key, value in payload.items() if key not in {"id", "library_id"}}
                        self._session.execute(update(_T).where(_T.c.id == folder_id).values(values))
                    retained_ids.add(folder_id)

                stale = [folder_id for folder_id in existing_ids_by_path.values() if folder_id not in retained_ids]
                if stale:
                    self._session.execute(delete(_T).where(_T.c.id.in_(stale), _T.c.library_id == library_id))
            self._session.commit()

    # ── maintenance ─────────────────────────────────────────────

    def truncate_folders(self) -> None:
        """Delete all rows from ``library_folders``."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(delete(_T))
            self._session.commit()

    def truncate_folder_links(self) -> None:
        """Clear folder relationship data.

        The ``library_folders`` table uses a self-referencing FK
        (``parent_id``) rather than a junction table, so this is a
        no-op provided for interface symmetry with other repos.
        """
        # No separate junction table — self-referencing FK only.
