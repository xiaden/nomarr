"""Unit tests for ScanRepository."""

from __future__ import annotations

import pytest
from sqlalchemy import insert, select

from nomarr.persistence.database.scan_repo import ScanRepository
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.library_scan import LibraryScan


async def _create_library(session) -> int:
    """Helper: insert a library row and return its id."""
    r = await session.execute(
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

    @pytest.mark.asyncio
    async def test_create_scan_returns_id(self, pg_session) -> None:
        """create_scan should insert a row and return its id."""
        lib_id = await _create_library(pg_session)
        repo = ScanRepository(pg_session)
        scan_id = await repo.create_scan(
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

    @pytest.mark.asyncio
    async def test_get_scan_record_existing(self, pg_session) -> None:
        """get_scan_record should return the most recent scan for a library."""
        lib_id = await _create_library(pg_session)
        repo = ScanRepository(pg_session)
        await repo.create_scan(
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
        result = await repo.get_scan_record(lib_id)
        assert result is not None
        assert result["library_id"] == lib_id
        assert result["scan_type"] == "full"
        assert result["status"] == "completed"
        assert result["files_found"] == 100

    @pytest.mark.asyncio
    async def test_get_scan_record_returns_most_recent(self, pg_session) -> None:
        """get_scan_record should return the most recent scan when multiple exist."""
        lib_id = await _create_library(pg_session)
        repo = ScanRepository(pg_session)
        await repo.create_scan(
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
        await repo.create_scan(
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
        result = await repo.get_scan_record(lib_id)
        assert result is not None
        assert result["scan_type"] == "incremental"

    @pytest.mark.asyncio
    async def test_get_scan_record_nonexistent(self, pg_session) -> None:
        """get_scan_record should return None for library with no scans."""
        repo = ScanRepository(pg_session)
        result = await repo.get_scan_record(999999)
        assert result is None

    @pytest.mark.asyncio
    async def test_update_scan(self, pg_session) -> None:
        """update_scan should modify specified fields."""
        lib_id = await _create_library(pg_session)
        repo = ScanRepository(pg_session)
        scan_id = await repo.create_scan(
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
        await repo.update_scan(scan_id, {"status": "completed", "files_processed": 50})
        result = await repo.get_scan_record(lib_id)
        assert result is not None
        assert result["status"] == "completed"
        assert result["files_processed"] == 50
        assert result["scan_type"] == "full"  # unchanged

    @pytest.mark.asyncio
    async def test_delete_scan_record(self, pg_session) -> None:
        """delete_scan_record should remove the row."""
        lib_id = await _create_library(pg_session)
        repo = ScanRepository(pg_session)
        scan_id = await repo.create_scan(
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
        await repo.delete_scan_record(scan_id)
        result = await repo.get_scan_record(lib_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_truncate_scans(self, pg_session) -> None:
        """truncate_scans should remove all scan rows."""
        lib_id = await _create_library(pg_session)
        repo = ScanRepository(pg_session)
        await repo.create_scan(
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
        await repo.truncate_scans()
        result = await pg_session.execute(select(LibraryScan))
        rows = result.all()
        assert len(rows) == 0
