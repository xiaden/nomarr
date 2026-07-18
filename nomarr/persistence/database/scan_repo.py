"""ScanRepository — CRUD for the ``library_scans`` table.

Simple CRUD using Part B primitives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Table, delete, select

from nomarr.helpers.dto.repo_dto import LibraryScanRow
from nomarr.persistence.models.library_scan import LibraryScan
from nomarr.persistence.sql.exceptions import map_persistence_exceptions
from nomarr.persistence.sql.primitives import (
    delete_by_key,
    insert_one,
    update_by_field,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.ext.asyncio import AsyncSession

_T = cast("Table", LibraryScan.__table__)


def _row_to_dto(row: Row) -> LibraryScanRow:
    """Convert a SQLAlchemy ``Row`` to a ``LibraryScanRow`` TypedDict."""
    m = row._mapping
    return LibraryScanRow(
        id=m["id"],
        library_id=m["library_id"],
        scan_type=m["scan_type"],
        status=m["status"],
        started_at=m["started_at"],
        finished_at=m["finished_at"],
        files_found=m["files_found"],
        files_processed=m["files_processed"],
        error=m["error"],
    )


class ScanRepository:
    """Repository for the ``library_scans`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_scan(self, payload: dict[str, Any]) -> int:
        """Insert a new scan record and return its ``id``."""
        async with map_persistence_exceptions():
            async with self._session.begin_nested():
                row = await insert_one(_T, payload, session=self._session)
            await self._session.commit()
            return int(row._mapping["id"])

    async def get_scan_record(self, library_id: int) -> LibraryScanRow | None:
        """Fetch the most recent scan record for a library."""
        async with map_persistence_exceptions():
            stmt = select(_T).where(_T.c.library_id == library_id).order_by(_T.c.id.desc()).limit(1)
            result = await self._session.execute(stmt)
            row = result.fetchone()
            return _row_to_dto(row) if row else None

    async def update_scan(self, scan_id: int, fields: dict[str, Any]) -> None:
        """Update arbitrary fields on a scan record."""
        async with map_persistence_exceptions():
            async with self._session.begin_nested():
                await update_by_field(_T, "id", scan_id, fields, session=self._session)
            await self._session.commit()

    async def delete_scan_record(self, scan_id: int) -> None:
        """Delete a scan record by primary key."""
        async with map_persistence_exceptions():
            async with self._session.begin_nested():
                await delete_by_key(_T, scan_id, session=self._session)
            await self._session.commit()

    async def truncate_scans(self) -> None:
        """Delete all rows from ``library_scans``."""
        async with map_persistence_exceptions():
            async with self._session.begin_nested():
                await self._session.execute(delete(_T))
            await self._session.commit()
