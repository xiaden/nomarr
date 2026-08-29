"""Unit tests for ScanRepository."""

from __future__ import annotations

import pytest
from sqlalchemy import insert, select

from nomarr.persistence.database.scan_repo import ScanRepository
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.library_scan import LibraryScan


def _create_library(session) -> int:
    """Helper: insert a library row and return its id."""
    r = session.execute(
        insert(Library).values(
            name="Scan Lib",
            path="/scan/lib",
            library_type="music",
            auto_tag=0,
            auto_curate=0,
            created_at=1000,
            updated_at=1000,
        )
    )
    return r.inserted_primary_key[0]


@pytest.mark.unit
@pytest.mark.integration
class TestScanRepository:
    """Tests for ScanRepository CRUD and query methods."""

    def test_create_scan_returns_id(self, pg_session) -> None:
        """create_scan should insert a row and return its id."""
        lib_id = _create_library(pg_session)
        repo = ScanRepository(pg_session)
        scan_id = repo.create_scan(
            {
                "library_id": lib_id,
                "scan_type": "full",
                "status": "running",
                "started_at": 1000,
                "finished_at": None,
                "files_found": 0,
                "files_processed": 0,
                "error": None,
            }
        )
        assert isinstance(scan_id, int)
        assert scan_id > 0

    def test_create_scan_drops_legacy_keys_at_write_boundary(self, pg_session) -> None:
        """create_scan should drop non-column payload keys before insert.

        Legacy doc-shaped keys (``key``, ``files_total``, ``completed_at``,
        ``scan_heartbeat``) have no ``library_scans`` column; the write-boundary
        filter must strip them so the strict ``insert_one`` does not raise a
        compile error on unknown columns.
        """
        lib_id = _create_library(pg_session)
        repo = ScanRepository(pg_session)
        scan_id = repo.create_scan(
            {
                "library_id": lib_id,
                "scan_type": "full",
                "status": "completed",
                "started_at": 1000,
                "finished_at": 2000,
                # Legacy / scan-doc keys that have no LibraryScan column:
                "key": "1",
                "files_total": 999,
                "completed_at": 2000,
                "scan_heartbeat": 2000,
            }
        )
        assert isinstance(scan_id, int)
        assert scan_id > 0
        result = repo.get_scan_record(lib_id)
        assert result is not None
        assert result["scan_type"] == "full"
        assert result["status"] == "completed"
        assert result["files_found"] == 0

    def test_get_scan_record_existing(self, pg_session) -> None:
        """get_scan_record should return the most recent scan for a library."""
        lib_id = _create_library(pg_session)
        repo = ScanRepository(pg_session)
        repo.create_scan(
            {
                "library_id": lib_id,
                "scan_type": "full",
                "status": "completed",
                "started_at": 2000,
                "finished_at": 3000,
                "files_found": 100,
                "files_processed": 100,
                "error": None,
            }
        )
        result = repo.get_scan_record(lib_id)
        assert result is not None
        assert result["library_id"] == lib_id
        assert result["scan_type"] == "full"
        assert result["status"] == "completed"
        assert result["files_found"] == 100

    def test_get_scan_record_returns_most_recent(self, pg_session) -> None:
        """get_scan_record should return the most recent scan when multiple exist."""
        lib_id = _create_library(pg_session)
        repo = ScanRepository(pg_session)
        repo.create_scan(
            {
                "library_id": lib_id,
                "scan_type": "full",
                "status": "completed",
                "started_at": 2000,
                "finished_at": 3000,
                "files_found": 50,
                "files_processed": 50,
                "error": None,
            }
        )
        repo.create_scan(
            {
                "library_id": lib_id,
                "scan_type": "incremental",
                "status": "completed",
                "started_at": 4000,
                "finished_at": 5000,
                "files_found": 10,
                "files_processed": 10,
                "error": None,
            }
        )
        result = repo.get_scan_record(lib_id)
        assert result is not None
        assert result["scan_type"] == "incremental"

    def test_get_scan_record_nonexistent(self, pg_session) -> None:
        """get_scan_record should return None for library with no scans."""
        repo = ScanRepository(pg_session)
        result = repo.get_scan_record(999999)
        assert result is None

    def test_update_scan(self, pg_session) -> None:
        """update_scan should modify specified fields."""
        lib_id = _create_library(pg_session)
        repo = ScanRepository(pg_session)
        scan_id = repo.create_scan(
            {
                "library_id": lib_id,
                "scan_type": "full",
                "status": "running",
                "started_at": 4000,
                "finished_at": None,
                "files_found": 0,
                "files_processed": 0,
                "error": None,
            }
        )
        repo.update_scan(scan_id, {"status": "completed", "files_processed": 50})
        result = repo.get_scan_record(lib_id)
        assert result is not None
        assert result["status"] == "completed"
        assert result["files_processed"] == 50
        assert result["scan_type"] == "full"  # unchanged

    def test_update_current_scan_does_not_mutate_an_older_scan(self, pg_session) -> None:
        """A stale operation must not update after a newer row is inserted."""
        lib_id = _create_library(pg_session)
        repo = ScanRepository(pg_session)
        old_scan_id = repo.create_scan(
            {
                "library_id": lib_id,
                "scan_type": "full",
                "status": "running",
                "started_at": 4000,
                "finished_at": None,
                "files_found": 0,
                "files_processed": 0,
                "error": None,
            }
        )
        new_scan_id = repo.create_scan(
            {
                "library_id": lib_id,
                "scan_type": "incremental",
                "status": "in_progress",
                "started_at": 6000,
                "finished_at": None,
                "files_found": 0,
                "files_processed": 0,
                "error": None,
            }
        )

        # Stale attempt to mark the older (non-current) scan completed is rejected.
        assert repo.update_current_scan(lib_id, old_scan_id, {"status": "completed"}) is False

        old_row = pg_session.execute(select(LibraryScan).where(LibraryScan.id == old_scan_id)).scalar_one()
        latest_row = pg_session.execute(select(LibraryScan).where(LibraryScan.id == new_scan_id)).scalar_one()
        # The distinguishing status proves the stale write was a no-op.
        assert old_row.status == "running"
        assert old_row.finished_at is None
        assert latest_row.status == "in_progress"

    def test_update_current_scan_updates_latest_scan(self, pg_session) -> None:
        """update_current_scan should update the latest scan and return True."""
        lib_id = _create_library(pg_session)
        repo = ScanRepository(pg_session)
        scan_id = repo.create_scan(
            {
                "library_id": lib_id,
                "scan_type": "full",
                "status": "running",
                "started_at": 4000,
                "finished_at": None,
                "files_found": 0,
                "files_processed": 0,
                "error": None,
            }
        )

        assert (
            repo.update_current_scan(
                lib_id, scan_id, {"status": "completed", "finished_at": 5000, "files_processed": 50}
            )
            is True
        )

        result = repo.get_scan_record(lib_id)
        assert result is not None
        assert result["status"] == "completed"
        assert result["finished_at"] == 5000
        assert result["files_processed"] == 50
        assert result["started_at"] == 4000  # unchanged

    def test_delete_scan_record(self, pg_session) -> None:
        """delete_scan_record should remove the row."""
        lib_id = _create_library(pg_session)
        repo = ScanRepository(pg_session)
        scan_id = repo.create_scan(
            {
                "library_id": lib_id,
                "scan_type": "full",
                "status": "running",
                "started_at": 5000,
                "finished_at": None,
                "files_found": 0,
                "files_processed": 0,
                "error": None,
            }
        )
        repo.delete_scan_record(scan_id)
        result = repo.get_scan_record(lib_id)
        assert result is None

    def test_truncate_scans(self, pg_session) -> None:
        """truncate_scans should remove all scan rows."""
        lib_id = _create_library(pg_session)
        repo = ScanRepository(pg_session)
        repo.create_scan(
            {
                "library_id": lib_id,
                "scan_type": "full",
                "status": "completed",
                "started_at": 6000,
                "finished_at": 7000,
                "files_found": 10,
                "files_processed": 10,
                "error": None,
            }
        )
        repo.truncate_scans()
        result = pg_session.execute(select(LibraryScan))
        rows = result.all()
        assert len(rows) == 0
