"""FolderRepository — CRUD and domain queries for the ``library_folders`` table.

Replaces ``folder_has_folder`` edge traversals with ``parent_id``
self-reference FK and ``library_id`` FK column.
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import Table, delete, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from nomarr.helpers.dto.repo_dto import LibraryFolderRow
from nomarr.persistence.models.library_folder import LibraryFolder
from nomarr.persistence.sql.primitives import (
    insert_one,
    select_by_key,
)

_T = cast("Table", LibraryFolder.__table__)


def _row_to_dto(row: Row) -> LibraryFolderRow:
    """Convert a SQLAlchemy ``Row`` to a ``LibraryFolderRow`` TypedDict."""
    m = row._mapping
    return LibraryFolderRow(
        id=m["id"],
        library_id=m["library_id"],
        parent_id=m["parent_id"],
        path=m["path"],
        name=m["name"],
    )


class FolderRepository:
    """Repository for the ``library_folders`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── basic CRUD ──────────────────────────────────────────────

    async def add_folder(self, payload: dict[str, Any]) -> int:
        """Insert a new folder row and return its ``id``."""
        row = await insert_one(_T, payload, session=self._session)
        await self._session.commit()
        return int(row._mapping["id"])

    async def add_library_folder(self, library_id: int, payload: dict[str, Any]) -> int:
        """Insert a folder linked to a specific library."""
        data = {**payload, "library_id": library_id}
        row = await insert_one(_T, data, session=self._session)
        await self._session.commit()
        return int(row._mapping["id"])

    async def get_folder(self, folder_id: int) -> LibraryFolderRow | None:
        """Fetch a single folder by primary key."""
        row = await select_by_key(_T, folder_id, session=self._session)
        return _row_to_dto(row) if row else None

    async def get_folder_by_path(self, library_id: int, path: str) -> LibraryFolderRow | None:
        """Fetch a folder by path within a specific library."""
        stmt = select(_T).where(
            _T.c.library_id == library_id,
            _T.c.path == path,
        )
        result = await self._session.execute(stmt)
        row = result.fetchone()
        return _row_to_dto(row) if row else None

    async def list_folders_for_library(self, library_id: int) -> list[LibraryFolderRow]:
        """Return all folders belonging to a library."""
        stmt = select(_T).where(_T.c.library_id == library_id)
        result = await self._session.execute(stmt)
        return [_row_to_dto(r) for r in result.all()]

    async def get_root_folders(self, library_id: int) -> list[LibraryFolderRow]:
        """Return top-level folders (``parent_id IS NULL``) for a library."""
        stmt = select(_T).where(
            _T.c.library_id == library_id,
            _T.c.parent_id.is_(None),
        )
        result = await self._session.execute(stmt)
        return [_row_to_dto(r) for r in result.all()]

    async def get_by_parent(self, library_id: int, parent_id: int) -> list[LibraryFolderRow]:
        """Return child folders of a given parent within a library."""
        stmt = select(_T).where(
            _T.c.library_id == library_id,
            _T.c.parent_id == parent_id,
        )
        result = await self._session.execute(stmt)
        return [_row_to_dto(r) for r in result.all()]

    async def remove_library_folder(self, library_id: int, folder_id: int) -> None:
        """Delete a folder by id, scoped to a library."""
        stmt = delete(_T).where(
            _T.c.id == folder_id,
            _T.c.library_id == library_id,
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def replace_library_folders(self, library_id: int, payloads: list[dict[str, Any]]) -> None:
        """Delete all folders for a library and re-insert from *payloads*.

        FK CASCADE removes any child folders and disassociated files.
        """
        # Delete existing folders for this library
        await self._session.execute(delete(_T).where(_T.c.library_id == library_id))
        # Insert new folders
        if payloads:
            rows_data = [{**p, "library_id": library_id} for p in payloads]
            await self._session.execute(_T.insert().values(rows_data))
        await self._session.commit()

    # ── maintenance ─────────────────────────────────────────────

    async def truncate_folders(self) -> None:
        """Delete all rows from ``library_folders``."""
        await self._session.execute(delete(_T))
        await self._session.commit()

    async def truncate_folder_links(self) -> None:
        """Clear folder relationship data.

        The ``library_folders`` table uses a self-referencing FK
        (``parent_id``) rather than a junction table, so this is a
        no-op provided for interface symmetry with other repos.
        """
        # No separate junction table — self-referencing FK only.
