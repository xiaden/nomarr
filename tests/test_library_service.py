"""
Tests for LibraryService (services/library.py).
"""

import pytest

from nomarr.data.db import Database
from nomarr.services.library import LibraryService


@pytest.fixture
def library_service(temp_db: str, tmp_path) -> LibraryService:
    """Create a LibraryService instance with fresh database."""
    db = Database(temp_db)
    library_path = str(tmp_path / "music")
    return LibraryService(db, library_path=library_path)


@pytest.fixture
def library_service_no_path(temp_db: str) -> LibraryService:
    """Create a LibraryService without library_path configured."""
    db = Database(temp_db)
    return LibraryService(db, library_path=None)


@pytest.mark.unit
class TestLibraryServiceConfiguration:
    """Test LibraryService configuration detection."""

    def test_is_configured_with_path(self, library_service: LibraryService):
        """Test is_configured when library_path is set."""
        assert library_service.is_configured() is True

    def test_is_configured_without_path(self, library_service_no_path: LibraryService):
        """Test is_configured when library_path is not set."""
        assert library_service_no_path.is_configured() is False


@pytest.mark.unit
class TestLibraryServiceStatus:
    """Test LibraryService.get_status method."""

    def test_get_status_no_scans(self, library_service: LibraryService):
        """Test getting status when no scans have been performed."""
        status = library_service.get_status()

        assert status["configured"] is True
        assert "library_path" in status
        assert "current_scan_id" in status
        assert status["current_scan_id"] is None

    def test_get_status_not_configured(self, library_service_no_path: LibraryService):
        """Test getting status when library not configured."""
        status = library_service_no_path.get_status()

        assert status["configured"] is False
        assert status["library_path"] is None


@pytest.mark.unit
class TestLibraryServiceScanHistory:
    """Test LibraryService.get_scan_history method."""

    def test_get_scan_history_empty(self, library_service: LibraryService):
        """Test getting scan history when no scans exist."""
        history = library_service.get_scan_history()

        assert isinstance(history, list)
        assert len(history) == 0

    def test_get_scan_history_with_limit(self, library_service: LibraryService):
        """Test getting scan history with custom limit."""
        history = library_service.get_scan_history(limit=5)

        assert isinstance(history, list)
        assert len(history) == 0  # No scans yet


@pytest.mark.unit
class TestLibraryServiceScanOperations:
    """Test LibraryService scan operations."""

    def test_cancel_scan_when_no_worker(self, library_service: LibraryService):
        """Test canceling scan when no worker is configured."""
        result = library_service.cancel_scan()
        # Should return False when no worker exists
        assert result is False

    def test_cancel_scan_when_not_running(self, library_service: LibraryService):
        """Test canceling scan when no scan is running."""
        # Even with worker, if no scan is running, should handle gracefully
        result = library_service.cancel_scan()
        assert result is False


@pytest.mark.skip(reason="Requires LibraryScanWorker mock - integration test")
class TestLibraryServiceFullScan:
    """Full scan lifecycle tests - requires worker infrastructure."""

    def test_start_scan_foreground(self, library_service: LibraryService):
        """Test starting a foreground scan."""
        pass  # Requires mocking LibraryScanWorker

    def test_start_scan_background(self, library_service: LibraryService):
        """Test starting a background scan."""
        pass  # Requires mocking LibraryScanWorker
