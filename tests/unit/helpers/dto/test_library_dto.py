"""
Unit tests for nomarr.helpers.dto.library_dto module.

Tests library-related DTOs for proper structure and behavior.
"""

import pytest

from nomarr.helpers.dto.library_dto import (
    LibraryDict,
    LibraryScanStatusResult,
    LibraryStatsResult,
    ReconcileResult,
    StartScanResult,
)


class TestReconcileResult:
    """Tests for ReconcileResult TypedDict."""

    @pytest.mark.unit
    def test_can_create_reconcile_result(self) -> None:
        """ReconcileResult should be a valid TypedDict."""
        result: ReconcileResult = {
            "total_files": 100,
            "valid_files": 90,
            "invalid_config": 2,
            "not_found": 5,
            "unknown_status": 1,
            "deleted_files": 2,
            "errors": 0,
        }
        assert result["total_files"] == 100
        assert result["valid_files"] == 90

    @pytest.mark.unit
    def test_reconcile_result_sums_correctly(self) -> None:
        """ReconcileResult counts should add up logically."""
        result: ReconcileResult = {
            "total_files": 100,
            "valid_files": 90,
            "invalid_config": 3,
            "not_found": 4,
            "unknown_status": 2,
            "deleted_files": 1,
            "errors": 0,
        }
        non_valid = result["invalid_config"] + result["not_found"] + result["unknown_status"] + result["deleted_files"]
        assert result["valid_files"] + non_valid == result["total_files"]


class TestLibraryScanStatusResult:
    """Tests for LibraryScanStatusResult dataclass."""

    @pytest.mark.unit
    def test_can_create_unconfigured_status(self) -> None:
        """Should handle unconfigured library state."""
        status = LibraryScanStatusResult(
            configured=False,
            library_path=None,
            enabled=False,
            pending_jobs=0,
            running_jobs=0,
        )
        assert not status.configured
        assert status.library_path is None
        assert status.scan_status is None

    @pytest.mark.unit
    def test_can_create_scanning_status(self) -> None:
        """Should handle active scanning state."""
        status = LibraryScanStatusResult(
            configured=True,
            library_path="/music",
            enabled=True,
            pending_jobs=0,
            running_jobs=1,
            scan_status="scanning",
            scan_progress=50,
            scan_total=100,
        )
        assert status.configured
        assert status.scan_status == "scanning"
        assert status.scan_progress == 50
        assert status.scan_total == 100

    @pytest.mark.unit
    def test_can_create_complete_status_with_timestamp(self) -> None:
        """Should handle complete scan with timestamp."""
        status = LibraryScanStatusResult(
            configured=True,
            library_path="/music",
            enabled=True,
            pending_jobs=0,
            running_jobs=0,
            scan_status="complete",
            scanned_at=1700000000000,
        )
        assert status.scan_status == "complete"
        assert status.scanned_at == 1700000000000

    @pytest.mark.unit
    def test_can_create_error_status(self) -> None:
        """Should handle error state with message."""
        status = LibraryScanStatusResult(
            configured=True,
            library_path="/music",
            enabled=True,
            pending_jobs=0,
            running_jobs=0,
            scan_status="error",
            scan_error="Path not found",
        )
        assert status.scan_status == "error"
        assert status.scan_error == "Path not found"


class TestLibraryStatsResult:
    """Tests for LibraryStatsResult dataclass."""

    @pytest.mark.unit
    def test_can_create_empty_stats(self) -> None:
        """Should handle empty library."""
        stats = LibraryStatsResult(
            total_files=0,
            total_artists=0,
            total_albums=0,
            total_duration=None,
            total_size=None,
            needs_tagging_count=0,
        )
        assert stats.total_files == 0
        assert stats.total_duration is None

    @pytest.mark.unit
    def test_can_create_populated_stats(self) -> None:
        """Should handle library with content."""
        stats = LibraryStatsResult(
            total_files=1000,
            total_artists=50,
            total_albums=100,
            total_duration=360000.5,  # 100 hours
            total_size=10_000_000_000,  # 10 GB
            needs_tagging_count=250,  # 250 files awaiting processing
        )
        assert stats.total_files == 1000
        assert stats.total_artists == 50
        assert stats.total_duration == 360000.5
        assert stats.needs_tagging_count == 250


class TestLibraryDict:
    """Tests for LibraryDict dataclass."""

    @pytest.mark.unit
    def test_can_create_basic_library(self) -> None:
        """Should create library with required fields."""
        lib = LibraryDict(
            _id="libraries/12345",
            _key="12345",
            _rev="_abc123",
            name="Music",
            root_path="/music",
            is_enabled=True,
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )
        assert lib._id == "libraries/12345"
        assert lib.name == "Music"
        assert lib.is_enabled

    @pytest.mark.unit
    def test_can_create_library_with_scan_info(self) -> None:
        """Should create library with scan progress."""
        lib = LibraryDict(
            _id="libraries/12345",
            _key="12345",
            _rev="_abc123",
            name="Music",
            root_path="/music",
            is_enabled=True,
            created_at=1700000000000,
            updated_at=1700000000000,
            scan_status="scanning",
            scan_progress=250,
            scan_total=500,
        )
        assert lib.scan_status == "scanning"
        assert lib.scan_progress == 250

    @pytest.mark.unit
    def test_id_contains_collection_prefix(self) -> None:
        """Library ID should contain ArangoDB collection prefix."""
        lib = LibraryDict(
            _id="libraries/abc123",
            _key="abc123",
            _rev="_xyz789",
            name="Test",
            root_path="/test",
            is_enabled=True,
            created_at=0,
            updated_at=0,
        )
        assert lib._id.startswith("libraries/")


class TestStartScanResult:
    """Tests for StartScanResult dataclass."""

    @pytest.mark.unit
    def test_can_create_scan_result(self) -> None:
        """Should create scan result with stats."""
        result = StartScanResult(
            files_discovered=100,
            files_queued=80,
            files_skipped=15,
            files_removed=5,
            job_ids=["task-1", "task-2"],
        )
        assert result.files_discovered == 100
        assert result.files_queued == 80
        assert len(result.job_ids) == 2

    @pytest.mark.unit
    def test_scan_result_math_adds_up(self) -> None:
        """Discovered files should equal queued + skipped."""
        result = StartScanResult(
            files_discovered=100,
            files_queued=80,
            files_skipped=20,
            files_removed=0,
            job_ids=[],
        )
        assert result.files_discovered == result.files_queued + result.files_skipped

    @pytest.mark.unit
    def test_scan_result_accepts_int_job_ids(self) -> None:
        """Should accept legacy integer job IDs."""
        result = StartScanResult(
            files_discovered=10,
            files_queued=10,
            files_skipped=0,
            files_removed=0,
            job_ids=[1, 2, 3],
        )
        assert result.job_ids == [1, 2, 3]
