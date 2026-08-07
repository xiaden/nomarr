"""Scan sub-facade for the library persistence surface.

Holds all scan-domain (``library_scans`` table) intent methods. Wired
into ``LibraryDb`` as its ``scans`` namespace (namespaced-forwarding
split per DD-persistence-intent-facade-rebuild §Phase 1). Methods moved
verbatim from ``LibraryDb`` — including the former maintenance surface —
signatures and behavior unchanged.

READ/WRITE classification (AR-2): READ methods use SQLAlchemy autobegin
and need no transaction context; WRITE methods (inserts/updates/deletes)
must be called inside ``LibraryDb.transaction()`` and raise
:class:`FacadeMisuseError` otherwise.

READ:   get_scan
WRITE:  add_scan, update_scan, remove_scan, truncate_scan_records
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.exceptions import FacadeMisuseError

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

    def _require_transaction(self, method_name: str) -> None:
        """Raise :class:`FacadeMisuseError` when no transaction is active (AR-2)."""
        if not cast("Session", self._session).in_transaction():
            raise FacadeMisuseError(
                f"{type(self).__name__}.{method_name}() is a write method — call within a transaction() context"
            )

    def get_scan(self, library_id: int) -> LibraryScanRow | None:
        """Return the most recent scan record for a library."""
        return self._scan_repo.get_scan_record(library_id)

    def add_scan(self, library_id: int, payload: dict[str, Any]) -> int:
        """Create a new scan record for a library."""
        self._require_transaction("add_scan")
        return self._scan_repo.create_scan({**payload, "library_id": library_id})

    def update_scan(self, library_id: int, fields: dict[str, Any]) -> None:
        """Update an existing scan record or create one if none exists."""
        self._require_transaction("update_scan")
        scan = self._scan_repo.get_scan_record(library_id)
        if scan:
            self._scan_repo.update_scan(scan["id"], fields)
        else:
            self._scan_repo.create_scan({**fields, "library_id": library_id})

    def remove_scan(self, library_id: int) -> None:
        """Delete the scan record for a library if one exists."""
        self._require_transaction("remove_scan")
        scan = self._scan_repo.get_scan_record(library_id)
        if scan:
            self._scan_repo.delete_scan_record(scan["id"])

    def truncate_scan_records(self) -> None:
        """Remove all scan records."""
        self._require_transaction("truncate_scan_records")
        return self._scan_repo.truncate_scans()
