"""Unit tests for WorkerSystemService restart integration."""

from threading import Event
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.workers import RestartDecision
from nomarr.helpers.dto.health_dto import StatusChangeContext
from nomarr.services.infrastructure.worker_system_svc import WorkerSystemService


@pytest.fixture
def mock_db():
    """Provide mock Database."""
    db = MagicMock()
    db.meta = MagicMock()
    db.worker_restart_policy = MagicMock()
    db.worker_restart_policy.get_restart_state.return_value = (0, None)
    return db


@pytest.fixture
def mock_health_monitor():
    """Provide mock HealthMonitorService."""
    monitor = MagicMock()
    return monitor


@pytest.fixture
def worker_service(mock_db, mock_health_monitor):
    """Provide WorkerSystemService instance with mocked dependencies."""
    from nomarr.helpers.dto.processing_dto import ProcessorConfig

    processor_config = ProcessorConfig(
        models_dir="/mock/models",
        min_duration_s=30,
        allow_short=False,
        batch_size=11,
        overwrite_tags=False,
        namespace="nom",
        version_tag_key="nom_version",
        tagger_version="test",
        calibrate_heads=False,
    )
    service = WorkerSystemService(
        db=mock_db,
        processor_config=processor_config,
        health_monitor=mock_health_monitor,
        default_enabled=True,
        worker_count=2,
    )
    service._stop_event = Event()
    return service


class TestOnStatusChangeRestartLogic:
    """Test on_status_change() restart decision integration."""

    def test_graceful_shutdown_prevents_restart(self, worker_service):
        """When stop_event is set, no restart attempted."""
        worker_service._stop_event.set()

        worker_service.on_status_change("worker_0", "healthy", "dead", StatusChangeContext())

        # Verify no restart-related DB calls
        assert worker_service.db.worker_restart_policy.get_restart_state.call_count == 0
        assert worker_service.db.worker_restart_policy.increment_restart_count.call_count == 0

    @patch("nomarr.services.infrastructure.worker_system_svc.should_restart_worker")
    def test_restart_decision_schedules_timer(self, mock_should_restart, worker_service, mock_db):
        """When decision is 'restart', schedules timer with backoff."""
        mock_should_restart.return_value = RestartDecision(
            action="restart", backoff_seconds=2.0, reason="Under restart limit",
        )
        mock_db.worker_restart_policy.get_restart_state.return_value = (2, 1234567890)

        with patch("threading.Timer") as mock_timer_class:
            mock_timer = MagicMock()
            mock_timer_class.return_value = mock_timer

            worker_service.on_status_change(
                "worker_1",
                "healthy",
                "dead",
                StatusChangeContext(),
            )

            # Verify timer created with correct backoff
            mock_timer_class.assert_called_once()
            args, kwargs = mock_timer_class.call_args
            assert args[0] == 2.0  # backoff_seconds
            assert args[1] == worker_service._restart_worker
            assert kwargs["args"] == ("worker_1",)

            # Verify timer started and tracked
            mock_timer.start.assert_called_once()
            assert "worker_1" in worker_service._pending_restart_timers
            assert worker_service._pending_restart_timers["worker_1"] == mock_timer

            # Verify restart count incremented
            mock_db.worker_restart_policy.increment_restart_count.assert_called_once_with("worker_1")

    @patch("nomarr.services.infrastructure.worker_system_svc.should_restart_worker")
    def test_mark_failed_decision(self, mock_should_restart, worker_service, mock_db):
        """When decision is 'mark_failed', marks worker as permanently failed."""
        mock_should_restart.return_value = RestartDecision(
            action="mark_failed",
            backoff_seconds=0,
            failure_reason="Restart limit exceeded",
            reason="Too many restarts",
        )
        mock_db.worker_restart_policy.get_restart_state.return_value = (5, 1234567890)

        worker_service.on_status_change("worker_2", "healthy", "dead", StatusChangeContext())

        # Verify health monitor called
        worker_service.health_monitor.set_failed.assert_called_once_with("worker_2")

        # Verify DB persistence
        mock_db.worker_restart_policy.mark_failed_permanent.assert_called_once_with(
            "worker_2", "Restart limit exceeded",
        )

        # Verify no timer scheduled
        assert "worker_2" not in worker_service._pending_restart_timers

    @patch("nomarr.services.infrastructure.worker_system_svc.should_restart_worker")
    def test_idempotent_restart_cancels_existing_timer(self, mock_should_restart, worker_service):
        """When worker crashes again during backoff, cancels old timer."""
        mock_should_restart.return_value = RestartDecision(
            action="restart", backoff_seconds=2.0, reason="Under restart limit",
        )

        with patch("threading.Timer") as mock_timer_class:
            # First crash - create timer
            mock_timer_1 = MagicMock()
            mock_timer_class.return_value = mock_timer_1

            worker_service.on_status_change(
                "worker_3",
                "healthy",
                "dead",
                StatusChangeContext(),
            )

            # Second crash - should cancel first timer
            mock_timer_2 = MagicMock()
            mock_timer_class.return_value = mock_timer_2

            worker_service.on_status_change(
                "worker_3",
                "recovering",
                "dead",
                StatusChangeContext(),
            )

            # Verify old timer cancelled
            mock_timer_1.cancel.assert_called_once()

            # Verify new timer created and tracked
            assert worker_service._pending_restart_timers["worker_3"] == mock_timer_2


class TestRestartWorkerHelper:
    """Test _restart_worker() private helper method."""

    def test_restart_worker_skips_when_disabled(self, worker_service, mock_db):
        """When worker system disabled during backoff, skips restart."""
        mock_db.meta.get.return_value = "false"  # disabled

        worker_service._restart_worker("worker_0")

        # Verify no worker created
        assert len(worker_service._workers) == 0

    @patch("nomarr.services.infrastructure.worker_system_svc.create_discovery_worker")
    def test_restart_worker_spawns_replacement(self, mock_create_worker, worker_service, mock_db):
        """When enabled, spawns replacement worker and registers with health monitor."""
        mock_db.meta.get.return_value = "true"  # enabled
        mock_worker = MagicMock()
        mock_worker.worker_id = "worker_1"
        mock_worker.health_pipe = MagicMock()
        mock_create_worker.return_value = mock_worker

        worker_service._restart_worker("discovery_worker:1")

        # Verify worker created
        mock_create_worker.assert_called_once()
        call_kwargs = mock_create_worker.call_args[1]
        assert call_kwargs["worker_index"] == 1
        assert "db_hosts" in call_kwargs
        assert "processor_config" in call_kwargs

        # Verify worker started
        mock_worker.start.assert_called_once()

        # Verify registered with health monitor (component_id, handler, pipe_conn)
        worker_service.health_monitor.register_component.assert_called_once()
        args = worker_service.health_monitor.register_component.call_args[0]
        assert args[0] == "worker_1"  # component_id
        assert args[1] == worker_service  # handler  # handler

    def test_restart_worker_handles_invalid_component_id(self, worker_service):
        """When component_id format is invalid, logs error and returns."""
        worker_service._restart_worker("invalid_format")

        # Should not crash, just log error (verify no workers created)
        assert len(worker_service._workers) == 0


class TestStopAllWorkersTimerCleanup:
    """Test stop_all_workers() cancels pending restart timers."""

    def test_stop_all_workers_cancels_pending_timers(self, worker_service):
        """When stopping, cancels all pending restart timers BEFORE setting stop_event."""
        # Setup pending timers
        mock_timer_1 = MagicMock()
        mock_timer_2 = MagicMock()
        worker_service._pending_restart_timers = {
            "worker_0": mock_timer_1,
            "worker_1": mock_timer_2,
        }

        # Add a dummy worker to prevent early return
        mock_worker = MagicMock()
        mock_worker.worker_id = "worker_0"
        mock_worker.is_alive.return_value = False
        worker_service._workers = [mock_worker]

        worker_service.stop_all_workers(timeout=1.0)

        # Verify both timers cancelled
        mock_timer_1.cancel.assert_called_once()
        mock_timer_2.cancel.assert_called_once()

        # Verify dict cleared
        assert len(worker_service._pending_restart_timers) == 0

        # Verify stop_event was set (after timer cancellation)
        assert worker_service._stop_event.is_set()
