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
    from sqlalchemy.orm import Session, scoped_session

_T = cast("Table", LibraryScan.__table__)

# Columns on the ``library_scans`` table — any payload key that is not a
# column (e.g. legacy ``key``/``files_total``/``completed_at``/``scan_heartbeat``)
# is dropped at the write boundary so ``insert_one`` never receives an unknown
# column (which would raise a compile error on strict insert).
_SCAN_COLUMNS: frozenset[str] = frozenset(_T.columns.keys())


def _row_to_dto(row: Row) -> LibraryScanRow:
    """Convert a SQLAlchemy ``Row`` to a ``LibraryScanRow`` TypedDict."""
    m = row._mapping
    return LibraryScanRow(
        id=m["id"],
        library_id=m["library_id"],
        scan_type=m["scan_type"],
        status=m["status"],
        started_at=m["started_at"],
        heartbeat_at=m["heartbeat_at"],
        finished_at=m["finished_at"],
        files_found=m["files_found"],
        files_processed=m["files_processed"],
        error=m["error"],
    )


class ScanRepository:
    """Repository for the ``library_scans`` table."""

    def __init__(self, session: scoped_session[Session]) -> None:
        self._session = session

    def create_scan(self, payload: dict[str, Any]) -> int:
        """Insert a new scan record and return its ``id``.

        Only keys that map to a ``library_scans`` column are written; any
        unknown/legacy payload keys are silently dropped to keep the strict
        ``insert_one`` from raising a compile error.
        """
        filtered = {k: v for k, v in payload.items() if k in _SCAN_COLUMNS}
        with map_persistence_exceptions():
            with self._session.begin_nested():
                row = insert_one(_T, filtered, session=self._session)
            self._session.commit()
            return int(row._mapping["id"])

    def get_scan_record(self, library_id: int) -> LibraryScanRow | None:
        """Fetch the most recent scan record for a library."""
        with map_persistence_exceptions():
            stmt = select(_T).where(_T.c.library_id == library_id).order_by(_T.c.id.desc()).limit(1)
            result = self._session.execute(stmt)
            row = result.fetchone()
            return _row_to_dto(row) if row else None

    def update_scan(self, scan_id: int, fields: dict[str, Any]) -> None:
        """Update arbitrary fields on a scan record."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                update_by_field(_T, "id", scan_id, fields, session=self._session)
            self._session.commit()

    def delete_scan_record(self, scan_id: int) -> None:
        """Delete a scan record by primary key."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                delete_by_key(_T, scan_id, session=self._session)
            self._session.commit()

    def truncate_scans(self) -> None:
        """Delete all rows from ``library_scans``."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(delete(_T))
            self._session.commit()
