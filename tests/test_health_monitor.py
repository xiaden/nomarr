"""
Tests for HealthMonitor (services/health_monitor.py).
"""

import pytest

from nomarr.services.health_monitor import HealthMonitor


@pytest.mark.unit
class TestHealthMonitorLifecycle:
    """Test HealthMonitor start/stop lifecycle."""

    def test_create_health_monitor(self):
        """Test creating HealthMonitor instance."""
        monitor = HealthMonitor(check_interval=1)
        assert monitor is not None

    def test_start_and_stop(self):
        """Test starting and stopping the health monitor."""
        monitor = HealthMonitor(check_interval=1)
        monitor.start()
        # Should start without error
        monitor.stop()
        # Should stop without error

    def test_stop_without_start(self):
        """Test stopping monitor that was never started."""
        monitor = HealthMonitor(check_interval=1)
        monitor.stop()  # Should handle gracefully


@pytest.mark.skip(reason="Requires worker thread mock - integration test")
class TestHealthMonitorWorkerTracking:
    """Full worker tracking tests - requires worker infrastructure."""

    def test_register_worker(self):
        """Test registering a worker."""
        pass  # Requires mocking worker thread

    def test_worker_death_callback(self):
        """Test on_death callback when worker dies."""
        pass  # Requires mocking worker death
