"""
Unit tests for nomarr.services.infrastructure.worker_system_svc module.

Tests use REAL fixtures from conftest.py - no redundant mocks.
"""


class TestWorkerSystemServiceEnableDisable:
    """Test WorkerSystemService enable/disable operations."""

    def test_enable_success(self, real_worker_service):
        """Should successfully enable worker system."""
        # Act
        real_worker_service.enable_worker_system()

        # Assert
        assert real_worker_service.is_worker_system_enabled() is True

    def test_disable_success(self, real_worker_service):
        """Should successfully disable worker system."""
        # Act
        real_worker_service.disable_worker_system()

        # Assert
        assert real_worker_service.is_worker_system_enabled() is False


class TestWorkerSystemServiceGetStatus:
    """Test WorkerSystemService.get_workers_status() operations."""

    def test_get_status_success(self, real_worker_service):
        """Should successfully get worker status."""
        # Act
        result = real_worker_service.get_workers_status()

        # Assert
        assert isinstance(result, dict)
        assert "enabled" in result
        assert "workers" in result
        assert "tag" in result["workers"]
        assert "library" in result["workers"]
        assert "calibration" in result["workers"]
