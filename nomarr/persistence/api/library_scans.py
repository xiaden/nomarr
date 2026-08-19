"""Scan sub-facade for the library persistence surface.

Holds all scan-domain (``library_scans`` table) intent methods. Wired
into ``LibraryDb`` as its ``scans`` namespace (namespaced-forwarding
split per DD-persistence-intent-facade-rebuild §Phase 1). Methods moved
verbatim from ``LibraryDb`` — including the former maintenance surface —
signatures and behavior unchanged.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, scoped_session

    from nomarr.helpers.dto.repo_dto import LibraryScanRow
    from nomarr.persistence.database.scan_repo import ScanRepository


class LibraryScansDb:
    """Persistence sub-facade for library scan lifecycle operations.

    Domain identity: ``library_id``. Scans track per-library scan
    records (add/update/remove) in the ``library_scans`` table.
    """

    def __init__(
        self,
        *,
        session: scoped_session[Session],
        scan_repo: ScanRepository,
    ) -> None:
        self._session = session
        self._scan_repo = scan_repo

    def get_scan(self, library_id: int) -> LibraryScanRow | None:
        """Return the most recent scan record for a library."""
        return self._scan_repo.get_scan_record(library_id)

    def get_latest_successful_scan(self, library_id: int) -> LibraryScanRow | None:
        """Return the latest successful scan summary for a library."""
        return self._scan_repo.get_latest_successful_scan(library_id)

    def add_scan(self, library_id: int, payload: dict[str, Any]) -> int:
        """Create a new scan record for a library."""
        return self._scan_repo.create_scan({**payload, "library_id": library_id})

    def start_scan(self, library_id: int, scan_type: str, started_at: int) -> int:
        """Create the initial record for a scan lifecycle."""
        return self._scan_repo.create_scan(
            {
                "library_id": library_id,
                "scan_type": scan_type,
                "status": "in_progress",
                "started_at": started_at,
                "heartbeat_at": started_at,
            }
        )

    def record_scan_progress(
        self,
        library_id: int,
        *,
        heartbeat_at: int,
        status: str | None = None,
        progress: int | None = None,
        total: int | None = None,
        scan_error: str | None = None,
    ) -> None:
        """Record validated progress fields for the current scan."""
        scan = self._scan_repo.get_scan_record(library_id)
        if scan is None:
            raise ValueError(f"Cannot record progress for library {library_id}: no scan exists")
        fields: dict[str, Any] = {"heartbeat_at": heartbeat_at}
        if status is not None:
            fields["status"] = status
        if progress is not None:
            fields["files_processed"] = progress
        if total is not None:
            fields["files_found"] = total
        if scan_error is not None:
            fields["error"] = scan_error
        self._scan_repo.update_scan(scan["id"], fields)

    def complete_scan(self, library_id: int, finished_at: int) -> None:
        """Mark the current scan as successfully completed."""
        scan = self._scan_repo.get_scan_record(library_id)
        if scan is None:
            raise ValueError(f"Cannot complete scan for library {library_id}: no scan exists")
        self._scan_repo.update_scan(scan["id"], {"status": "completed", "finished_at": finished_at})

    def remove_scan(self, library_id: int) -> None:
        """Delete the scan record for a library if one exists."""
        scan = self._scan_repo.get_scan_record(library_id)
        if scan:
            self._scan_repo.delete_scan_record(scan["id"])

    def truncate_scan_records(self) -> None:
        """Remove all scan records."""
        return self._scan_repo.truncate_scans()
