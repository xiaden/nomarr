"""Scan sub-facade for the library persistence surface.

Holds all scan-domain (``library_scans`` table) intent methods. Wired into
``LibraryDb`` as its ``scans`` namespace.

Domain boundary (ADR-032/041/043): every public method accepts a domain
``Library`` (natural ``(name, root_path)`` identity) and returns a domain
``LibraryScan`` value. The storage ``library_scans`` row id, the ``library_id``
foreign key, and row payloads never cross this boundary: the natural key is
resolved to a storage library id internally, and rows are mapped to
``LibraryScan`` via ``nomarr/persistence/mappers/library_mapper.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.persistence.mappers.library_mapper import scan_from_row

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, scoped_session

    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dataclasses.library_domain_dataclasses import LibraryScan
    from nomarr.persistence.database.library_repo import LibraryRepository
    from nomarr.persistence.database.scan_repo import ScanRepository


class LibraryScansDb:
    """Persistence sub-facade for library scan lifecycle operations.

    Domain identity is the natural ``(name, root_path)`` ``Library`` key.
    Scans track per-library scan records in the ``library_scans`` table; the
    facade resolves the library natural key to its storage row id internally
    and maps scan rows to ``LibraryScan`` before returning them.
    """

    # Concurrent library-domain facade work may touch adjacent persistence
    # surfaces. This scan section intentionally keeps storage-id resolution and
    # row mapping private while correcting only the scan intent contract.
    def __init__(
        self,
        *,
        session: scoped_session[Session],
        scan_repo: ScanRepository,
        library_repo: LibraryRepository,
    ) -> None:
        self._session = session
        self._scan_repo = scan_repo
        self._library_repo = library_repo

    # ── natural-key resolution (persistence-internal) ────────────────────

    def _resolve_library_id(self, library: Library) -> int:
        """Resolve a ``Library`` natural key for repository calls only.

        The generated library id is deliberately kept private to this facade;
        callers must pass the domain value rather than reconstructing storage
        identity themselves.
        """
        row = self._library_repo.get_library_by_natural_key(library.name, library.root_path)
        if row is None:
            raise LookupError(f"Library {library.name!r} at {library.root_path!r} does not exist")
        return int(row["id"])

    # ── scan lifecycle ───────────────────────────────────────────────────

    def get_scan(self, library: Library) -> LibraryScan | None:
        """Return the most recent scan for a library, or ``None`` when absent."""
        library_id = self._resolve_library_id(library)
        row = self._scan_repo.get_scan_record(library_id)
        return None if row is None else scan_from_row(row)

    def get_latest_successful_scan(self, library: Library) -> LibraryScan | None:
        """Return the latest successfully-completed scan for a library.

        ``None`` when the library has no completed scan (see
        ``ScanRepository.get_latest_successful_scan`` for the ordering rule).
        """
        library_id = self._resolve_library_id(library)
        row = self._scan_repo.get_latest_successful_scan(library_id)
        return None if row is None else scan_from_row(row)

    def start_scan(self, library: Library, scan_type: str, started_at: int) -> LibraryScan:
        """Create the initial record for a scan lifecycle and return it."""
        library_id = self._resolve_library_id(library)
        self._scan_repo.create_scan(
            {
                "library_id": library_id,
                "scan_type": scan_type,
                "status": "in_progress",
                "started_at": started_at,
                "heartbeat_at": started_at,
            }
        )
        row = self._scan_repo.get_scan_record(library_id)
        # ``create_scan`` inserted the highest-id row for the library, so the
        # just-created scan is the most recent record.
        assert row is not None
        return scan_from_row(row)

    def record_scan_progress(
        self,
        library: Library,
        *,
        heartbeat_at: int,
        status: str | None = None,
        progress: int | None = None,
        total: int | None = None,
        scan_error: str | None = None,
    ) -> LibraryScan:
        """Record validated progress fields for the current scan.

        Stale writes are rejected: if the read scan record is no longer the
        library's latest scan by the time the update runs, a ``ValueError``
        is raised rather than silently mutating scan history. Returns the
        updated ``LibraryScan``.
        """
        library_id = self._resolve_library_id(library)
        scan = self._scan_repo.get_scan_record(library_id)
        if scan is None:
            raise ValueError(f"Cannot record progress for library {library.name!r}: no scan exists")
        fields: dict[str, int | str] = {"heartbeat_at": heartbeat_at}
        if status is not None:
            fields["status"] = status
        if progress is not None:
            fields["files_processed"] = progress
        if total is not None:
            fields["files_found"] = total
        if scan_error is not None:
            fields["error"] = scan_error
        if not self._scan_repo.update_current_scan(library_id, scan["id"], fields):
            # Do not include the repository row id in caller-visible errors; it
            # is an implementation detail of the storage repository.
            raise ValueError(f"Cannot record progress for library {library.name!r}: the scan is no longer current")
        row = self._scan_repo.get_scan_record(library_id)
        assert row is not None
        return scan_from_row(row)

    def complete_scan(self, library: Library, finished_at: int) -> LibraryScan:
        """Mark the current scan as successfully completed and return it.

        Stale writes are rejected: if the read scan record is no longer the
        library's latest scan by the time the update runs, a ``ValueError``
        is raised rather than silently mutating scan history.
        """
        library_id = self._resolve_library_id(library)
        scan = self._scan_repo.get_scan_record(library_id)
        if scan is None:
            raise ValueError(f"Cannot complete scan for library {library.name!r}: no scan exists")
        if not self._scan_repo.update_current_scan(
            library_id,
            scan["id"],
            {"status": "completed", "finished_at": finished_at},
        ):
            # Keep storage-generated identifiers out of the domain-facing error.
            raise ValueError(f"Cannot complete scan for library {library.name!r}: the scan is no longer current")
        row = self._scan_repo.get_scan_record(library_id)
        assert row is not None
        return scan_from_row(row)

    def remove_scan(self, library: Library) -> None:
        """Remove the latest scan for a domain ``Library``.

        The facade resolves and consumes the repository row id internally;
        callers never need to know which ``library_scans`` row is removed.
        """
        library_id = self._resolve_library_id(library)
        scan = self._scan_repo.get_scan_record(library_id)
        if scan:
            self._scan_repo.delete_scan_record(scan["id"])

    def truncate_scan_records(self) -> None:
        """Remove all persisted scan history as a maintenance operation.

        This intentionally has no library argument: it is an administrative
        operation over the complete scan history, not a library lifecycle
        intent. No table or row details are exposed to the caller.
        """
        self._scan_repo.truncate_scans()
