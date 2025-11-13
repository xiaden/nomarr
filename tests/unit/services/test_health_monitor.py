"""
Unit tests for nomarr.services.health_monitor module.

Tests use REAL fixtures from conftest.py - no redundant mocks.
"""


class TestHealthMonitorRegisterWorker:
    """Test HealthMonitor.register_worker() operations."""

    def test_register_worker_success(self, real_health_monitor):
        """Should successfully register worker."""
        # Arrange

        # Act
        real_health_monitor.register_worker(worker=None)

        # Assert
        # Method returns None - verify it completes without exception


class TestHealthMonitorStart:
    """Test HealthMonitor.start() operations."""

    def test_start_success(self, real_health_monitor):
        """Should successfully start."""
        # Arrange

        # Act
        real_health_monitor.start()

        # Assert
        # Method returns None - verify it completes without exception


class TestHealthMonitorStop:
    """Test HealthMonitor.stop() operations."""

    def test_stop_success(self, real_health_monitor):
        """Should successfully stop."""
        # Arrange

        # Act
        real_health_monitor.stop()

        # Assert
        # Method returns None - verify it completes without exception
