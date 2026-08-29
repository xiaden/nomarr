"""ScanRepository — CRUD for the ``library_scans`` table.

Simple CRUD using Part B primitives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Table, delete, func, select, update

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

# Columns on the ``library_scans`` table.  Payloads use the canonical
# ``LibraryScanRow`` names; unknown keys are dropped at the write boundary so
# ``insert_one`` never receives an unknown column.
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

    def get_latest_successful_scan(self, library_id: int) -> LibraryScanRow | None:
        """Fetch the latest completed scan with a non-null finish time.

        Results are ordered by ``finished_at`` descending, with the row id as
        a deterministic tie-breaker for scans completed in the same millisecond.
        """
        with map_persistence_exceptions():
            stmt = (
                select(_T)
                .where(_T.c.library_id == library_id, _T.c.status == "completed", _T.c.finished_at.is_not(None))
                .order_by(_T.c.finished_at.desc(), _T.c.id.desc())
                .limit(1)
            )
            result = self._session.execute(stmt)
            row = result.fetchone()
            return _row_to_dto(row) if row else None

    def update_scan(self, scan_id: int, fields: dict[str, Any]) -> None:
        """Update fields on a scan record, ignoring non-schema aliases."""
        normalized = {
            "progress": "files_processed",
            "total": "files_found",
            "scan_error": "error",
        }
        filtered = {
            normalized.get(key, key): value
            for key, value in fields.items()
            if normalized.get(key, key) in _SCAN_COLUMNS
        }
        with map_persistence_exceptions():
            with self._session.begin_nested():
                update_by_field(_T, "id", scan_id, filtered, session=self._session)
            self._session.commit()

    def update_current_scan(self, library_id: int, scan_id: int, fields: dict[str, Any]) -> bool:
        """Update *scan_id* only while it remains the library's latest scan.

        The latest-row lookup and update must be one SQL statement.  A caller
        may have read an older row before another scan was created; the
        correlated ``MAX(id)`` predicate turns that stale operation into a
        no-op instead of mutating scan history after ownership moved on.
        """
        normalized = {
            "progress": "files_processed",
            "total": "files_found",
            "scan_error": "error",
        }
        filtered = {
            normalized.get(key, key): value
            for key, value in fields.items()
            if normalized.get(key, key) in _SCAN_COLUMNS
        }
        latest_scan_id = select(func.max(_T.c.id)).where(_T.c.library_id == library_id).scalar_subquery()
        stmt = (
            update(_T)
            .where(
                _T.c.id == scan_id,
                _T.c.library_id == library_id,
                _T.c.id == latest_scan_id,
            )
            .values(**filtered)
            .returning(_T.c.id)
        )
        with map_persistence_exceptions():
            with self._session.begin_nested():
                updated = self._session.execute(stmt).fetchone() is not None
            self._session.commit()
        return updated

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
