"""LibraryRepository — CRUD and domain queries for the ``libraries`` table.

Uses Part B primitives for simple lookups and direct SQLAlchemy Core for
filtered queries and pipeline-axis operations.
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import Table, select, update
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from nomarr.helpers.dto.repo_dto import LibraryRow
from nomarr.persistence.models.library import Library
from nomarr.persistence.sql.primitives import (
    delete_by_key,
    insert_one,
    select_by_key,
    update_by_field,
)

_T = cast("Table", Library.__table__)


def _row_to_dto(row: Row) -> LibraryRow:
    """Convert a SQLAlchemy ``Row`` to a ``LibraryRow`` TypedDict."""
    m = row._mapping
    return LibraryRow(
        id=m["id"],
        name=m["name"],
        path=m["path"],
        library_type=m["library_type"],
        auto_tag=m["auto_tag"],
        auto_curate=m["auto_curate"],
        created_at=m["created_at"],
        updated_at=m["updated_at"],
    )


class LibraryRepository:
    """Repository for the ``libraries`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── basic CRUD ──────────────────────────────────────────────

    async def add_library(self, payload: dict[str, Any]) -> int:
        """Insert a new library row and return its ``id``."""
        row = await insert_one(_T, payload, session=self._session)
        await self._session.commit()
        return int(row._mapping["id"])

    async def get_library(self, library_id: int) -> LibraryRow | None:
        """Fetch a single library by primary key."""
        row = await select_by_key(_T, library_id, session=self._session)
        return _row_to_dto(row) if row else None

    async def get_library_by_name(self, name: str) -> LibraryRow | None:
        """Fetch a single library by its unique ``name`` field."""
        row = await select_by_key(_T, name, session=self._session, key_col="name")
        return _row_to_dto(row) if row else None

    async def list_libraries(self, *, enabled_only: bool = False) -> list[LibraryRow]:
        """Return all libraries, optionally filtering to enabled types only."""
        stmt = select(_T)
        if enabled_only:
            stmt = stmt.where(_T.c.library_type != "disabled")
        result = await self._session.execute(stmt)
        return [_row_to_dto(r) for r in result.all()]

    async def list_library_keys(self) -> list[int]:
        """Return all library primary-key ids."""
        stmt = select(_T.c.id)
        result = await self._session.execute(stmt)
        return [row[0] for row in result.all()]

    async def update_library(self, library_id: int, fields: dict[str, Any]) -> None:
        """Update arbitrary fields on a library row."""
        await update_by_field(_T, "id", library_id, fields, session=self._session)
        await self._session.commit()

    async def delete_library(self, library_id: int) -> None:
        """Delete a library row by primary key."""
        await delete_by_key(_T, library_id, session=self._session)
        await self._session.commit()

    # ── pipeline axis helpers ───────────────────────────────────

    async def update_pipeline_axis(self, library_id: int, axis_field: str, axis_value: str) -> None:
        """Set a pipeline-axis column (e.g. ``scan_state``) on a library."""
        stmt = update(_T).where(_T.c.id == library_id).values({axis_field: axis_value})
        await self._session.execute(stmt)
        await self._session.commit()

    async def get_pipeline_state(self, library_id: int) -> dict[str, str] | None:
        """Return the four pipeline-axis columns as a dict, or ``None``."""
        row = await select_by_key(_T, library_id, session=self._session)
        if row is None:
            return None
        m = row._mapping
        return {
            "scan_state": m.get("scan_state", "not_scanned"),
            "ml_state": m.get("ml_state", "not_ML_processed"),
            "calibration_state": m.get("calibration_state", "not_calibrated"),
            "tag_write_state": m.get("tag_write_state", "not_written"),
        }

    async def get_libraries_in_axis_state(self, axis_field: str, axis_value: str) -> list[int]:
        """Return ids of libraries whose *axis_field* equals *axis_value*."""
        stmt = select(_T.c.id).where(_T.c[axis_field] == axis_value)
        result = await self._session.execute(stmt)
        return [row[0] for row in result.all()]

    # ── cascade delete (ORM) ────────────────────────────────────

    async def remove_library(self, library_id: int) -> None:
        """Delete a library and all cascaded child data via FK ON DELETE CASCADE.

        Uses the ORM ``session.delete`` so that the identity map stays
        consistent; FK CASCADE handles files, folders, scans, pipeline
        states, etc.
        """
        from sqlalchemy import select as sa_select

        stmt = sa_select(Library).where(Library.id == library_id)
        result = await self._session.execute(stmt)
        library = result.scalar_one_or_none()
        if library is not None:
            await self._session.delete(library)
            await self._session.commit()
