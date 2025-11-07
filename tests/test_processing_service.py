"""
Tests for ProcessingService (services/processing.py).
"""

import pytest

from nomarr.services.processing import ProcessingService


@pytest.mark.unit
class TestProcessingServiceAvailability:
    """Test ProcessingService availability checks."""

    def test_is_available_without_coordinator(self):
        """Test is_available when no coordinator is provided."""
        service = ProcessingService(coordinator=None)
        assert service.is_available() is False

    def test_get_worker_count_without_coordinator(self):
        """Test get_worker_count when no coordinator is provided."""
        service = ProcessingService(coordinator=None)
        assert service.get_worker_count() == 0


@pytest.mark.unit
class TestProcessingServiceFailFast:
    """Test ProcessingService fail-fast behavior when unavailable."""

    def test_process_file_raises_when_unavailable(self, tmp_path):
        """Test process_file raises RuntimeError when coordinator unavailable."""
        service = ProcessingService(coordinator=None)
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"audio")

        with pytest.raises(RuntimeError, match="ProcessingCoordinator is not available"):
            service.process_file(str(test_file))

    def test_process_batch_raises_when_unavailable(self, tmp_path):
        """Test process_batch returns error dicts when coordinator unavailable."""
        service = ProcessingService(coordinator=None)
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"audio")

        results = service.process_batch([str(test_file)])

        assert len(results) == 1
        assert results[0]["status"] == "error"
        assert "ProcessingCoordinator is not available" in results[0]["error"]


@pytest.mark.skip(reason="Requires ProcessingCoordinator mock - integration test")
class TestProcessingServiceWithCoordinator:
    """Full processing tests - requires ProcessingCoordinator infrastructure."""

    def test_process_file_success(self):
        """Test successful file processing."""
        pass  # Requires mocking ProcessingCoordinator

    def test_process_batch_success(self):
        """Test successful batch processing."""
        pass  # Requires mocking ProcessingCoordinator

    def test_get_worker_count_with_coordinator(self):
        """Test get_worker_count with active coordinator."""
        pass  # Requires mocking ProcessingCoordinator
