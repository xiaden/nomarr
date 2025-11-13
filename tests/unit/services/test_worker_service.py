"""
Unit tests for nomarr.services.worker module.

Tests use REAL fixtures from conftest.py - no redundant mocks.
"""

import pytest


class TestWorkerServiceCleanupOrphanedJobs:
    """Test WorkerService.cleanup_orphaned_jobs() operations."""

    def test_cleanup_orphaned_jobs_success(self, real_worker_service):
        """Should successfully cleanup orphaned jobs."""
        # Arrange

        # Act
        result = real_worker_service.cleanup_orphaned_jobs()

        # Assert
        assert isinstance(result, int)
        assert result >= 0  # Non-negative count


class TestWorkerServiceDisable:
    """Test WorkerService.disable() operations."""

    def test_disable_success(self, real_worker_service):
        """Should successfully disable."""
        # Arrange

        # Act
        real_worker_service.disable()

        # Assert
        # Method returns None - verify it completes without exception


class TestWorkerServiceEnable:
    """Test WorkerService.enable() operations."""

    def test_enable_success(self, real_worker_service):
        """Should successfully enable."""
        # Arrange

        # Act
        real_worker_service.enable()

        # Assert
        # Method returns None - verify it completes without exception


class TestWorkerServiceGetStatus:
    """Test WorkerService.get_status() operations."""

    def test_get_status_success(self, real_worker_service):
        """Should successfully get status."""
        # Arrange

        # Act
        result = real_worker_service.get_status()

        # Assert
        assert isinstance(result, dict)
        # TODO: Verify returned data is correct


class TestWorkerServiceIsEnabled:
    """Test WorkerService.is_enabled() operations."""

    def test_is_enabled_success(self, real_worker_service):
        """Should successfully is enabled."""
        # Arrange

        # Act
        result = real_worker_service.is_enabled()

        # Assert
        assert isinstance(result, bool)


class TestWorkerServicePause:
    """Test WorkerService.pause() operations."""

    def test_pause_success(self, real_worker_service):
        """Should successfully pause."""
        # Arrange

        # Act
        result = real_worker_service.pause()

        # Assert
        assert isinstance(result, dict)


class TestWorkerServiceResume:
    """Test WorkerService.resume() operations."""

    @pytest.mark.skip(reason="Requires event_broker mock - enable() then start_workers() needs event_broker")
    def test_resume_success(self, real_worker_service):
        """Should successfully resume."""
        # Arrange

        # Act
        result = real_worker_service.resume(event_broker=None)

        # Assert
        assert isinstance(result, dict)


class TestWorkerServiceStartWorkers:
    """Test WorkerService.start_workers() operations."""

    def test_start_workers_success(self, real_worker_service):
        """Should successfully start workers."""
        # Arrange

        # Act
        result = real_worker_service.start_workers()

        # Assert
        assert isinstance(result, list)


class TestWorkerServiceStopAllWorkers:
    """Test WorkerService.stop_all_workers() operations."""

    def test_stop_all_workers_success(self, real_worker_service):
        """Should successfully stop all workers."""
        # Arrange

        # Act
        real_worker_service.stop_all_workers()

        # Assert
        # Method returns None - verify it completes without exception


class TestWorkerServiceWaitUntilIdle:
    """Test WorkerService.wait_until_idle() operations."""

    def test_wait_until_idle_success(self, real_worker_service):
        """Should successfully wait until idle."""
        # Arrange

        # Act
        result = real_worker_service.wait_until_idle()

        # Assert
        assert isinstance(result, bool)
