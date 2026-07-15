"""FileRepository — CRUD and domain queries for the ``library_files`` table.

Replaces ``nomarr/persistence/database/library_files_aql/``.  Uses Part B
primitives for simple lookups and direct SQLAlchemy Core for filtered
queries, batch operations, and maintenance methods.
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import Table, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from nomarr.helpers.dto.repo_dto import LibraryFileRow
from nomarr.persistence.models.file_tag import FileTag
from nomarr.persistence.models.library_file import LibraryFile
from nomarr.persistence.sql.primitives import (
    delete_by_key,
    insert_one,
    select_by_key,
    update_by_field,
)

_T = cast("Table", LibraryFile.__table__)


def _row_to_dto(row: Row) -> LibraryFileRow:
    """Convert a SQLAlchemy ``Row`` to a ``LibraryFileRow`` TypedDict."""
    m = row._mapping
    return LibraryFileRow(
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


class FileRepository:
    """Repository for the ``library_files`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── basic CRUD ──────────────────────────────────────────────

    async def add_file(self, payload: dict[str, Any]) -> int:
        """Insert a new file row and return its ``id``."""
        row = await insert_one(_T, payload, session=self._session)
        await self._session.commit()
        return int(row._mapping["id"])

    async def get_file(self, file_id: int) -> LibraryFileRow | None:
        """Fetch a single file by primary key."""
        row = await select_by_key(_T, file_id, session=self._session)
        return _row_to_dto(row) if row else None

    async def get_file_by_path(self, path: str, library_id: int) -> LibraryFileRow | None:
        """Fetch a file by path within a specific library."""
        stmt = select(_T).where(_T.c.path == path, _T.c.library_id == library_id)
        result = await self._session.execute(stmt)
        row = result.fetchone()
        return _row_to_dto(row) if row else None

    async def get_file_by_path_unscoped(self, path: str) -> LibraryFileRow | None:
        """Fetch a file by path across all libraries."""
        stmt = select(_T).where(_T.c.path == path).limit(1)
        result = await self._session.execute(stmt)
        row = result.fetchone()
        return _row_to_dto(row) if row else None

    async def get_file_by_normalized_path(self, library_id: int, normalized_path: str) -> LibraryFileRow | None:
        """Fetch a file by normalized path within a specific library."""
        stmt = select(_T).where(
            _T.c.library_id == library_id,
            _T.c.normalized_path == normalized_path,
        )
        result = await self._session.execute(stmt)
        row = result.fetchone()
        return _row_to_dto(row) if row else None

    async def upsert_file(self, payload: dict[str, Any]) -> int:
        """Insert or update a file, keyed on ``(library_id, path)`` unique constraint."""
        stmt = (
            pg_insert(_T)
            .values(**payload)
            .on_conflict_do_update(
                constraint="uq_library_files_library_path",
                set_={k: v for k, v in payload.items() if k not in ("library_id", "path")},
            )
            .returning(_T)
        )
        result = await self._session.execute(stmt)
        row = result.fetchone()
        if row is None:
            raise RuntimeError("upsert returned no row")
        await self._session.commit()
        return int(row._mapping["id"])

    async def upsert_files_for_library(self, library_id: int, payloads: list[dict[str, Any]]) -> list[int]:
        """Batch upsert files for a single library.

        Each payload must contain at least ``path``.  The ``library_id``
        is forced to the supplied value.
        """
        if not payloads:
            return []
        rows_data = [{**p, "library_id": library_id} for p in payloads]
        insert_stmt = pg_insert(_T).values(rows_data)
        set_clause = {col: insert_stmt.excluded[col] for col in rows_data[0] if col not in ("library_id", "path")}
        stmt = insert_stmt.on_conflict_do_update(
            constraint="uq_library_files_library_path",
            set_=set_clause,
        ).returning(_T.c.id)
        result = await self._session.execute(stmt)
        ids = [row[0] for row in result.all()]
        await self._session.commit()
        return ids

    async def update_file(self, file_id: int, fields: dict[str, Any]) -> None:
        """Update arbitrary fields on a file row."""
        await update_by_field(_T, "id", file_id, fields, session=self._session)
        await self._session.commit()

    async def delete_file(self, file_id: int) -> None:
        """Delete a single file by primary key."""
        await delete_by_key(_T, file_id, session=self._session)
        await self._session.commit()

    # ── filtered queries ────────────────────────────────────────

    async def list_files(
        self, *, filters: dict[str, Any] | None = None, limit: int | None = None
    ) -> list[LibraryFileRow]:
        """Return files matching optional field-equality filters."""
        stmt = select(_T)
        if filters:
            for field, value in filters.items():
                stmt = stmt.where(_T.c[field] == value)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return [_row_to_dto(r) for r in result.all()]

    async def count_files(self) -> int:
        """Return total row count of ``library_files``."""
        stmt = select(func.count()).select_from(_T)
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def get_files_by_ids(self, file_ids: list[int]) -> list[LibraryFileRow]:
        """Fetch multiple files by their primary keys."""
        if not file_ids:
            return []
        stmt = select(_T).where(_T.c.id.in_(file_ids))
        result = await self._session.execute(stmt)
        return [_row_to_dto(r) for r in result.all()]

    async def get_library_ids_for_files(self, file_ids: list[int]) -> dict[int, int]:
        """Return ``{file_id: library_id}`` mapping for the given file ids."""
        if not file_ids:
            return {}
        stmt = select(_T.c.id, _T.c.library_id).where(_T.c.id.in_(file_ids))
        result = await self._session.execute(stmt)
        return {row[0]: row[1] for row in result.all()}

    async def list_library_file_ids(self, library_id: int, *, limit: int | None = None) -> list[int]:
        """Return file ids belonging to a library."""
        stmt = select(_T.c.id).where(_T.c.library_id == library_id)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return [row[0] for row in result.all()]

    async def list_library_files(self, library_id: int, *, limit: int | None = None) -> list[LibraryFileRow]:
        """Return full file rows belonging to a library."""
        stmt = select(_T).where(_T.c.library_id == library_id)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return [_row_to_dto(r) for r in result.all()]

    async def list_existing_file_paths(self, paths: list[str]) -> list[str]:
        """Return paths from *paths* that already exist in the table."""
        if not paths:
            return []
        stmt = select(_T.c.path).where(_T.c.path.in_(paths))
        result = await self._session.execute(stmt)
        return [row[0] for row in result.all()]

    async def find_by_chromaprint(self, library_id: int, chromaprint: str) -> LibraryFileRow | None:
        """Find a file by chromaprint within a library."""
        stmt = select(_T).where(
            _T.c.chromaprint == chromaprint,
            _T.c.library_id == library_id,
        )
        result = await self._session.execute(stmt)
        row = result.fetchone()
        return _row_to_dto(row) if row else None

    async def list_files_for_folder(self, library_id: int, folder_rel_path: str) -> list[LibraryFileRow]:
        """Return files whose path starts with the given folder relative path."""
        prefix = folder_rel_path.rstrip("/") + "/"
        stmt = select(_T).where(
            _T.c.library_id == library_id,
            _T.c.path.like(prefix + "%"),
        )
        result = await self._session.execute(stmt)
        return [_row_to_dto(r) for r in result.all()]

    # ── mutation / maintenance ──────────────────────────────────

    async def remove_files(self, file_ids: list[int]) -> None:
        """Delete multiple files by id.  FK CASCADE handles derived data."""
        if not file_ids:
            return
        stmt = delete(_T).where(_T.c.id.in_(file_ids))
        await self._session.execute(stmt)
        await self._session.commit()

    async def list_orphaned_file_ids(self) -> list[int]:
        """Return file ids whose ``library_id`` has no matching library."""
        from nomarr.persistence.models.library import Library

        lib_table = Library.__table__
        stmt = select(_T.c.id).outerjoin(lib_table, _T.c.library_id == lib_table.c.id).where(lib_table.c.id.is_(None))
        result = await self._session.execute(stmt)
        return [row[0] for row in result.all()]

    async def truncate_files(self) -> None:
        """Delete all rows from ``library_files``."""
        await self._session.execute(delete(_T))
        await self._session.commit()

    async def truncate_file_links(self) -> None:
        """Delete all rows from the ``file_tags`` junction table."""
        await self._session.execute(delete(cast("Table", FileTag.__table__)))
        await self._session.commit()

    async def count_library_files(self, library_id: int) -> int:
        """Return the number of files belonging to *library_id*."""
        stmt = select(func.count()).select_from(_T).where(_T.c.library_id == library_id)
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def count_recently_tagged(self, cutoff_ms: int) -> int:
        """Count files with ``last_tagged_at >= cutoff_ms``."""
        stmt = select(func.count()).select_from(_T).where(_T.c.last_tagged_at >= cutoff_ms)
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def list_tracks_for_matching(
        self,
        library_id: int,
        *,
        limit: int | None = None,
    ) -> list[LibraryFileRow]:
        """Return file rows for a library ordered by id (for fuzzy matching)."""
        stmt = select(_T).where(_T.c.library_id == library_id).order_by(_T.c.id)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return [_row_to_dto(r) for r in result.all()]
