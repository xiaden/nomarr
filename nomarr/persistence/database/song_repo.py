"""SongRepository — CRUD and domain queries for the ``songs`` table.

Uses Part B primitives for simple lookups and direct SQLAlchemy Core for
filtered queries, batch operations, and maintenance methods.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Table, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nomarr.helpers.dto.repo_dto import SongRow
from nomarr.persistence.models.song import Song
from nomarr.persistence.models.song_tag import SongTag
from nomarr.persistence.sql.exceptions import map_persistence_exceptions
from nomarr.persistence.sql.primitives import (
    delete_by_key,
    insert_one,
    select_by_key,
    update_by_field,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, scoped_session

_T = cast("Table", Song.__table__)


def _row_to_dto(row: Row) -> SongRow:
    """Convert a SQLAlchemy ``Row`` to a ``SongRow`` TypedDict."""
    m = row._mapping
    return SongRow(
        id=m["id"],
        library_id=m["library_id"],
        folder_id=m["folder_id"],
        path=m["path"],
        normalized_path=m["normalized_path"],
        file_size=m["file_size"],
        modified_time=m["modified_time"],
        duration_seconds=m["duration_seconds"],
        chromaprint=m["chromaprint"],
        needs_tagging=m["needs_tagging"],
        is_valid=m["is_valid"],
        tagged=m["tagged"],
        calibration_hash=m["calibration_hash"],
        write_claimed_by=m["write_claimed_by"],
        last_tagged_at=m["last_tagged_at"],
        scanned_at=m["scanned_at"],
        created_at=m["created_at"],
    )


class SongRepository:
    """Repository for the ``songs`` table."""

    def __init__(self, session: scoped_session[Session]) -> None:
        self._session = session

    # ── basic CRUD ──────────────────────────────────────────────

    def add_song(self, payload: dict[str, Any]) -> int:
        """Insert a new song row and return its ``id``."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                row = insert_one(_T, payload, session=self._session)
            self._session.commit()
            return int(row._mapping["id"])

    def get_song(self, song_id: int) -> SongRow | None:
        """Fetch a single song by primary key."""
        with map_persistence_exceptions():
            row = select_by_key(_T, song_id, session=self._session)
            return _row_to_dto(row) if row else None

    def get_song_by_path(self, path: str, library_id: int) -> SongRow | None:
        """Fetch a song by path within a specific library."""
        with map_persistence_exceptions():
            stmt = select(_T).where(_T.c.path == path, _T.c.library_id == library_id)
            result = self._session.execute(stmt)
            row = result.fetchone()
            return _row_to_dto(row) if row else None

    def get_song_by_path_unscoped(self, path: str) -> SongRow | None:
        """Fetch a song by path across all libraries."""
        with map_persistence_exceptions():
            stmt = select(_T).where(_T.c.path == path).limit(1)
            result = self._session.execute(stmt)
            row = result.fetchone()
            return _row_to_dto(row) if row else None

    def get_song_by_normalized_path(self, library_id: int, normalized_path: str) -> SongRow | None:
        """Fetch a song by normalized path within a specific library."""
        with map_persistence_exceptions():
            stmt = select(_T).where(
                _T.c.library_id == library_id,
                _T.c.normalized_path == normalized_path,
            )
            result = self._session.execute(stmt)
            row = result.fetchone()
            return _row_to_dto(row) if row else None

    def upsert_song(self, payload: dict[str, Any]) -> int:
        """Insert or update a song, keyed on ``(library_id, path)`` unique constraint."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = (
                    pg_insert(_T)
                    .values(**payload)
                    .on_conflict_do_update(
                        constraint="uq_songs_library_path",
                        set_={k: v for k, v in payload.items() if k not in ("library_id", "path")},
                    )
                    .returning(_T)
                )
                result = self._session.execute(stmt)
                row = result.fetchone()
                if row is None:
                    msg = "upsert returned no row"
                    raise RuntimeError(msg)
            self._session.commit()
            return int(row._mapping["id"])

    def upsert_songs_for_library(self, library_id: int, payloads: list[dict[str, Any]]) -> list[int]:
        """Batch upsert songs for a single library.

        Each payload must contain at least ``path``.  The ``library_id``
        is forced to the supplied value.
        """
        with map_persistence_exceptions():
            if not payloads:
                return []
            with self._session.begin_nested():
                rows_data = [{**p, "library_id": library_id} for p in payloads]
                insert_stmt = pg_insert(_T).values(rows_data)
                set_clause = {
                    col: insert_stmt.excluded[col] for col in rows_data[0] if col not in ("library_id", "path")
                }
                stmt = insert_stmt.on_conflict_do_update(
                    constraint="uq_songs_library_path",
                    set_=set_clause,
                ).returning(_T.c.id)
                result = self._session.execute(stmt)
                ids = [row[0] for row in result.all()]
            self._session.commit()
            return ids

    def update_song(self, song_id: int, fields: dict[str, Any]) -> None:
        """Update arbitrary fields on a song row."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                update_by_field(_T, "id", song_id, fields, session=self._session)
            self._session.commit()

    def delete_song(self, song_id: int) -> None:
        """Delete a single song by primary key."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                delete_by_key(_T, song_id, session=self._session)
            self._session.commit()

    # ── filtered queries ────────────────────────────────────────

    def get_songs_by_ids(self, song_ids: list[int]) -> list[SongRow]:
        """Fetch multiple songs by their primary keys."""
        with map_persistence_exceptions():
            if not song_ids:
                return []
            stmt = select(_T).where(_T.c.id.in_(song_ids))
            result = self._session.execute(stmt)
            return [_row_to_dto(r) for r in result.all()]

    def get_library_ids_for_songs(self, song_ids: list[int]) -> dict[int, int]:
        """Return ``{song_id: library_id}`` mapping for the given song ids."""
        with map_persistence_exceptions():
            if not song_ids:
                return {}
            stmt = select(_T.c.id, _T.c.library_id).where(_T.c.id.in_(song_ids))
            result = self._session.execute(stmt)
            return {row[0]: row[1] for row in result.all()}

    def list_library_song_ids(self, library_id: int, *, limit: int | None = None) -> list[int]:
        """Return song ids belonging to a library."""
        with map_persistence_exceptions():
            stmt = select(_T.c.id).where(_T.c.library_id == library_id)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [row[0] for row in result.all()]

    def list_songs(self, library_id: int, *, limit: int | None = None) -> list[SongRow]:
        """Return full song rows belonging to a library."""
        with map_persistence_exceptions():
            stmt = select(_T).where(_T.c.library_id == library_id)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [_row_to_dto(r) for r in result.all()]

    def list_existing_song_paths(self, paths: list[str]) -> list[str]:
        """Return paths from *paths* that already exist in the table."""
        with map_persistence_exceptions():
            if not paths:
                return []
            stmt = select(_T.c.path).where(_T.c.path.in_(paths))
            result = self._session.execute(stmt)
            return [row[0] for row in result.all()]

    def find_song_by_chromaprint(self, library_id: int, chromaprint: str) -> SongRow | None:
        """Find a song by chromaprint within a library."""
        with map_persistence_exceptions():
            stmt = select(_T).where(
                _T.c.chromaprint == chromaprint,
                _T.c.library_id == library_id,
            )
            result = self._session.execute(stmt)
            row = result.fetchone()
            return _row_to_dto(row) if row else None

    def list_songs_for_folder(self, library_id: int, folder_rel_path: str) -> list[SongRow]:
        """Return songs whose path starts with the given folder relative path."""
        with map_persistence_exceptions():
            prefix = folder_rel_path.rstrip("/") + "/"
            stmt = select(_T).where(
                _T.c.library_id == library_id,
                _T.c.path.like(prefix + "%"),
            )
            result = self._session.execute(stmt)
            return [_row_to_dto(r) for r in result.all()]

    # ── mutation / maintenance ──────────────────────────────────

    def remove_songs(self, song_ids: list[int]) -> None:
        """Delete multiple songs by id.  FK CASCADE handles derived data."""
        with map_persistence_exceptions():
            if not song_ids:
                return
            with self._session.begin_nested():
                stmt = delete(_T).where(_T.c.id.in_(song_ids))
                self._session.execute(stmt)
            self._session.commit()

    def list_orphaned_song_ids(self) -> list[int]:
        """Return song ids whose ``library_id`` has no matching library."""
        with map_persistence_exceptions():
            from nomarr.persistence.models.library import Library

            lib_table = Library.__table__
            stmt = (
                select(_T.c.id).outerjoin(lib_table, _T.c.library_id == lib_table.c.id).where(lib_table.c.id.is_(None))
            )
            result = self._session.execute(stmt)
            return [row[0] for row in result.all()]

    def truncate_songs(self) -> None:
        """Delete all rows from ``songs``."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(delete(_T))
            self._session.commit()

    def truncate_song_links(self) -> None:
        """Delete all rows from the ``song_tags`` junction table."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(delete(cast("Table", SongTag.__table__)))
            self._session.commit()

    def count_songs(self, library_id: int) -> int:
        """Return the number of songs belonging to *library_id*."""
        with map_persistence_exceptions():
            stmt = select(func.count()).select_from(_T).where(_T.c.library_id == library_id)
            result = self._session.execute(stmt)
            return result.scalar() or 0

    def count_recently_tagged(self, cutoff_ms: int) -> int:
        """Count songs with ``last_tagged_at >= cutoff_ms``."""
        with map_persistence_exceptions():
            stmt = select(func.count()).select_from(_T).where(_T.c.last_tagged_at >= cutoff_ms)
            result = self._session.execute(stmt)
            return result.scalar() or 0

    def list_tracks_for_matching(
        self,
        library_id: int,
        *,
        limit: int | None = None,
    ) -> list[SongRow]:
        """Return song rows for a library ordered by id (for fuzzy matching)."""
        with map_persistence_exceptions():
            stmt = select(_T).where(_T.c.library_id == library_id).order_by(_T.c.id)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [_row_to_dto(r) for r in result.all()]
