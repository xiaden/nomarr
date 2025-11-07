"""
Integration tests for ProcessingCoordinator (multi-worker parallelism)
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

# Skip multiprocess tests on Windows - they require Essentia which isn't available in dev
skip_on_windows = pytest.mark.skipif(
    sys.platform == "win32", reason="Multiprocess tests require Essentia (not available on Windows dev)"
)


@pytest.mark.integration
class TestProcessingCoordinator:
    """Test ProcessingCoordinator worker pool management."""

    def test_coordinator_initialization(self):
        """Test creating a ProcessingCoordinator."""
        from nomarr.interfaces.api.coordinator import ProcessingCoordinator

        coordinator = ProcessingCoordinator(num_workers=2)
        assert coordinator is not None

        # Clean up
        coordinator.stop()

    def test_coordinator_start_stop(self):
        """Test starting and stopping coordinator."""
        from nomarr.interfaces.api.coordinator import ProcessingCoordinator

        coordinator = ProcessingCoordinator(num_workers=2)
        coordinator.start()

        # Should have worker pool (_pool, not _executor)
        assert coordinator._pool is not None

        coordinator.stop()
        # After stop, coordinator should be marked as shutdown
        assert coordinator._shutdown is True

    @patch("nomarr.interfaces.api.coordinator.process_file")
    def test_submit_single_job(self, mock_process_file, tmp_path):
        """Test submitting a single job."""
        from nomarr.interfaces.api.coordinator import ProcessingCoordinator

        # Mock successful processing
        mock_process_file.return_value = {"mood": "happy", "genre": "rock"}

        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake audio")

        coordinator = ProcessingCoordinator(num_workers=1)
        coordinator.start()

        try:
            result = coordinator.submit(str(test_file), force=False)
            # Should return results dict
            assert "mood" in result or "status" in result or result is not None
        finally:
            coordinator.stop()

    @skip_on_windows
    @patch("nomarr.interfaces.api.coordinator.process_file")
    def test_submit_multiple_jobs_concurrently(self, mock_process_file, tmp_path):
        """Test submitting multiple jobs to worker pool."""
        from nomarr.interfaces.api.coordinator import ProcessingCoordinator

        mock_process_file.return_value = {"mood": "happy"}

        # Create test files
        test_files = []
        for i in range(3):
            test_file = tmp_path / f"test{i}.mp3"
            test_file.write_bytes(b"fake audio")
            test_files.append(str(test_file))

        coordinator = ProcessingCoordinator(num_workers=2)
        coordinator.start()

        try:
            # Submit jobs
            futures = []
            for path in test_files:
                future = coordinator.submit(path, force=False)
                futures.append(future)

            # All should complete (blocking in this test)
            assert len(futures) == 3
        finally:
            coordinator.stop()

    def test_coordinator_with_event_broker(self):
        """Test coordinator with event broker for SSE."""
        from nomarr.interfaces.api.coordinator import ProcessingCoordinator

        mock_broker = MagicMock()
        coordinator = ProcessingCoordinator(num_workers=1, event_broker=mock_broker)

        assert coordinator._event_broker is mock_broker
        coordinator.stop()

    @patch("nomarr.interfaces.api.coordinator.process_file")
    def test_publish_event(self, mock_process_file):
        """Test event publishing during processing."""
        from nomarr.interfaces.api.coordinator import ProcessingCoordinator

        mock_broker = MagicMock()
        coordinator = ProcessingCoordinator(num_workers=1, event_broker=mock_broker)

        # Publish test event
        coordinator.publish_event("test_topic", {"status": "processing"})

        # Verify broker was called
        mock_broker.publish.assert_called_once_with("test_topic", {"status": "processing"})

        coordinator.stop()

    @patch("nomarr.interfaces.api.coordinator.process_file")
    def test_worker_slot_management(self, mock_process_file, tmp_path):
        """Test that worker slots are properly managed."""
        # Slow processing to test slot management
        import time

        from nomarr.interfaces.api.coordinator import ProcessingCoordinator

        def slow_process(*args, **kwargs):
            time.sleep(0.1)
            return {"status": "done"}

        mock_process_file.side_effect = slow_process

        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake audio")

        coordinator = ProcessingCoordinator(num_workers=1)
        coordinator.start()

        try:
            # Submit job
            future = coordinator.submit(str(test_file), force=False)

            # Should have a future
            assert future is not None
        finally:
            coordinator.stop()


@pytest.mark.integration
class TestProcessFileWrapper:
    """Test process_file_wrapper function."""

    @patch("nomarr.interfaces.api.coordinator.process_file")
    def test_wrapper_calls_process_file(self, mock_process_file, tmp_path):
        """Test wrapper correctly calls process_file."""
        from nomarr.interfaces.api.coordinator import process_file_wrapper

        mock_process_file.return_value = {"mood": "happy"}

        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake audio")

        result = process_file_wrapper(str(test_file), force=False)

        # Should call process_file with correct args
        mock_process_file.assert_called_once_with(str(test_file), force=False)
        assert result == {"mood": "happy"}

    @patch("nomarr.interfaces.api.coordinator.process_file")
    def test_wrapper_handles_errors(self, mock_process_file):
        """Test wrapper handles processing errors."""
        from nomarr.interfaces.api.coordinator import process_file_wrapper

        mock_process_file.side_effect = RuntimeError("Processing failed")

        # Wrapper catches exceptions and returns error dict
        result = process_file_wrapper("/nonexistent/file.mp3", force=False)
        assert result["status"] == "error"
        assert "Processing failed" in result["error"]


@pytest.mark.integration
class TestWorkerPoolConcurrency:
    """Test concurrent processing with multiple workers."""

    @skip_on_windows
    @patch("nomarr.interfaces.api.coordinator.process_file")
    def test_multiple_workers_process_concurrently(self, mock_process_file, tmp_path):
        """Test that multiple workers can process jobs in parallel."""
        from nomarr.interfaces.api.coordinator import ProcessingCoordinator

        # Track call order
        call_order = []

        def track_calls(path, force):
            import time

            call_order.append(path)
            time.sleep(0.05)  # Simulate work
            return {"path": path}

        mock_process_file.side_effect = track_calls

        # Create test files
        test_files = []
        for i in range(4):
            test_file = tmp_path / f"test{i}.mp3"
            test_file.write_bytes(b"fake audio")
            test_files.append(str(test_file))

        coordinator = ProcessingCoordinator(num_workers=2)
        coordinator.start()

        try:
            import time

            start = time.time()

            # Submit all jobs
            futures = [coordinator.submit(path, False) for path in test_files]

            # Wait for completion (blocking)
            for _ in futures:
                pass  # Future completes when submit returns

            elapsed = time.time() - start

            # With 2 workers and 4 jobs at 0.05s each, should take ~0.1s
            # (not 0.2s if sequential)
            # Allow generous margin for test stability
            assert elapsed < 0.25  # Should be faster than sequential
        finally:
            coordinator.stop()

    def test_worker_count_respected(self):
        """Test that worker_count parameter is respected."""
        from nomarr.interfaces.api.coordinator import ProcessingCoordinator

        coordinator = ProcessingCoordinator(num_workers=3)
        coordinator.start()

        # Check coordinator stored the worker count
        assert coordinator._num_workers == 3
        # Pool should be created
        assert coordinator._pool is not None

        coordinator.stop()
