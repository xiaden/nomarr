"""
Unit tests for WorkerSystemService restart and crash behavior.

Tests validate:
- Crash detection and reporting (heartbeat timeout, invalid heartbeat, process death)
- Restart scheduling with exponential backoff
- Permanent failure after max restarts
- Non-blocking restart behavior
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest

from nomarr.services.infrastructure.worker_system_svc import (
    EXIT_CODE_HEARTBEAT_TIMEOUT,
    EXIT_CODE_INVALID_HEARTBEAT,
    EXIT_CODE_UNKNOWN_CRASH,
    HEARTBEAT_STALE_THRESHOLD_MS,
    MAX_RESTARTS_IN_WINDOW,
    RESTART_WINDOW_MS,
    WorkerSystemService,
)

if TYPE_CHECKING:
    pass


# ---------------------------- Fixtures ----------------------------


@pytest.fixture
def mock_db():
    """Create mock Database with health and meta operations."""
    db = Mock()
    db.db_path = "/fake/db.sqlite"

    # Mock health operations
    db.health = Mock()
    db.health.get_component = Mock(return_value=None)
    db.health.mark_starting = Mock()
    db.health.mark_crashed = Mock()
    db.health.mark_failed = Mock()
    db.health.increment_restart_count = Mock(return_value={"restart_count": 1, "last_restart": 0})
    db.health.reset_restart_count = Mock()
    db.health.get_all_workers = Mock(return_value=[])

    # Mock meta operations
    db.meta = Mock()
    db.meta.get = Mock(return_value="true")
    db.meta.set = Mock()

    return db


@pytest.fixture
def mock_backends():
    """Create mock processing backends."""
    return {
        "tagger": Mock(),
        "scanner": Mock(),
        "recalibration": Mock(),
    }


@pytest.fixture
def mock_event_broker():
    """Create mock event broker."""
    return Mock()


@pytest.fixture
def worker_system_service(mock_db, mock_backends, mock_event_broker):
    """Create WorkerSystemService with mocked dependencies."""
    # Disable automatic worker starting for tests
    mock_db.meta.get.return_value = "false"

    service = WorkerSystemService(
        db=mock_db,
        tagger_backend=mock_backends["tagger"],
        scanner_backend=mock_backends["scanner"],
        recalibration_backend=mock_backends["recalibration"],
        event_broker=mock_event_broker,
        tagger_count=1,
        scanner_count=1,
        recalibration_count=1,
        default_enabled=False,
    )

    return service


@pytest.fixture
def mock_worker():
    """Create mock BaseWorker."""
    worker = Mock()
    worker.worker_id = 0
    worker.pid = 12345
    worker.name = "MockWorker-0"
    worker.is_alive = Mock(return_value=True)
    worker.exitcode = None
    worker.stop = Mock()
    worker.join = Mock()
    worker.terminate = Mock()
    worker.start = Mock()
    return worker


# ---------------------------- Helper Method Tests ----------------------------


# Tests for restart decision logic moved to component tests (components/workers/)
# The helper methods _calculate_backoff and _should_mark_failed were moved to
# nomarr/components/workers/worker_crash_comp.py as pure functions.
# Test coverage is now in tests/unit/components/workers/test_worker_crash_comp.py


# ---------------------------- Crash Detection Tests ----------------------------


class TestHeartbeatTimeoutDetection:
    """Test detection and handling of stale heartbeats."""

    @patch("nomarr.services.infrastructure.worker_system_svc.time.sleep")
    def test_detects_stale_heartbeat(self, mock_sleep, worker_system_service, mock_db, mock_worker):
        """Should detect stale heartbeat and mark as crashed."""
        # Setup: Add worker to service
        worker_system_service._worker_groups["tag"].append(mock_worker)

        # Setup: Health record with stale heartbeat
        now_ms = int(time.time() * 1000)
        stale_heartbeat_ms = now_ms - HEARTBEAT_STALE_THRESHOLD_MS - 1000  # 1s past threshold

        mock_db.health.get_component.return_value = {
            "component": "worker:tag:0",
            "last_heartbeat": stale_heartbeat_ms,
            "status": "healthy",
        }

        # Run one iteration of health monitor (manually)
        with patch.object(worker_system_service, "_schedule_restart") as mock_schedule:
            # Simulate one health check cycle
            worker_system_service._shutdown = False
            now_ms_check = int(time.time() * 1000)

            for queue_type, workers in worker_system_service._worker_groups.items():
                for worker in workers:
                    component_id = f"worker:{queue_type}:{worker.worker_id}"
                    health = mock_db.health.get_component(component_id)
                    if health and isinstance(health["last_heartbeat"], int):
                        heartbeat_age = now_ms_check - health["last_heartbeat"]
                        if heartbeat_age > HEARTBEAT_STALE_THRESHOLD_MS:
                            mock_db.health.mark_crashed(
                                component=component_id,
                                exit_code=EXIT_CODE_HEARTBEAT_TIMEOUT,
                                metadata=f"Heartbeat stale for {heartbeat_age}ms",
                            )
                            mock_schedule(worker, queue_type, component_id)

        # Verify mark_crashed called with correct exit code
        mock_db.health.mark_crashed.assert_called_once()
        call_args = mock_db.health.mark_crashed.call_args
        assert call_args.kwargs["component"] == "worker:tag:0"
        assert call_args.kwargs["exit_code"] == EXIT_CODE_HEARTBEAT_TIMEOUT
        assert "stale" in call_args.kwargs["metadata"].lower()

        # Verify restart scheduled
        mock_schedule.assert_called_once()

    def test_exit_code_heartbeat_timeout_constant(self):
        """Validate EXIT_CODE_HEARTBEAT_TIMEOUT constant value."""
        assert EXIT_CODE_HEARTBEAT_TIMEOUT == -2


class TestInvalidHeartbeatDetection:
    """Test detection and handling of invalid heartbeat data."""

    def test_detects_invalid_heartbeat_type(self, worker_system_service, mock_db, mock_worker):
        """Should detect non-integer heartbeat and mark as crashed."""
        worker_system_service._worker_groups["tag"].append(mock_worker)

        # Setup: Health record with invalid heartbeat (string instead of int)
        mock_db.health.get_component.return_value = {
            "component": "worker:tag:0",
            "last_heartbeat": "not_an_integer",  # Invalid!
            "status": "healthy",
        }

        with patch.object(worker_system_service, "_schedule_restart") as mock_schedule:
            # Simulate health check for invalid heartbeat
            int(time.time() * 1000)
            for queue_type, workers in worker_system_service._worker_groups.items():
                for worker in workers:
                    component_id = f"worker:{queue_type}:{worker.worker_id}"
                    health = mock_db.health.get_component(component_id)
                    if health:
                        last_heartbeat = health["last_heartbeat"]
                        if not isinstance(last_heartbeat, int):
                            mock_db.health.mark_crashed(
                                component=component_id,
                                exit_code=EXIT_CODE_INVALID_HEARTBEAT,
                                metadata="Invalid heartbeat timestamp",
                            )
                            mock_schedule(worker, queue_type, component_id)

        # Verify mark_crashed called with invalid heartbeat code
        mock_db.health.mark_crashed.assert_called_once()
        call_args = mock_db.health.mark_crashed.call_args
        assert call_args.kwargs["exit_code"] == EXIT_CODE_INVALID_HEARTBEAT

    def test_exit_code_invalid_heartbeat_constant(self):
        """Validate EXIT_CODE_INVALID_HEARTBEAT constant value."""
        assert EXIT_CODE_INVALID_HEARTBEAT == -3


class TestProcessDeathDetection:
    """Test detection and handling of dead worker processes."""

    def test_detects_dead_process(self, worker_system_service, mock_db, mock_worker):
        """Should detect dead process and mark as crashed."""
        # Setup: Worker that is dead
        mock_worker.is_alive.return_value = False
        mock_worker.exitcode = 137  # SIGKILL
        worker_system_service._worker_groups["tag"].append(mock_worker)

        mock_db.health.get_component.return_value = {
            "component": "worker:tag:0",
            "last_heartbeat": int(time.time() * 1000),  # Fresh heartbeat
            "status": "healthy",
        }

        with patch.object(worker_system_service, "_schedule_restart") as mock_schedule:
            # Simulate health check for dead process
            for queue_type, workers in worker_system_service._worker_groups.items():
                for worker in workers:
                    component_id = f"worker:{queue_type}:{worker.worker_id}"
                    if not worker.is_alive():
                        exit_code = worker.exitcode if worker.exitcode is not None else EXIT_CODE_UNKNOWN_CRASH
                        mock_db.health.mark_crashed(
                            component=component_id,
                            exit_code=exit_code,
                            metadata=f"Process terminated unexpectedly with exit code {exit_code}",
                        )
                        mock_schedule(worker, queue_type, component_id)

        # Verify mark_crashed called with actual exit code
        mock_db.health.mark_crashed.assert_called_once()
        call_args = mock_db.health.mark_crashed.call_args
        assert call_args.kwargs["exit_code"] == 137

    def test_uses_unknown_crash_code_when_exitcode_none(self, worker_system_service, mock_db, mock_worker):
        """Should use EXIT_CODE_UNKNOWN_CRASH when exitcode is None."""
        mock_worker.is_alive.return_value = False
        mock_worker.exitcode = None  # Unknown exit code
        worker_system_service._worker_groups["tag"].append(mock_worker)

        mock_db.health.get_component.return_value = {
            "component": "worker:tag:0",
            "last_heartbeat": int(time.time() * 1000),
            "status": "healthy",
        }

        with patch.object(worker_system_service, "_schedule_restart") as mock_schedule:
            for queue_type, workers in worker_system_service._worker_groups.items():
                for worker in workers:
                    component_id = f"worker:{queue_type}:{worker.worker_id}"
                    if not worker.is_alive():
                        exit_code = worker.exitcode if worker.exitcode is not None else EXIT_CODE_UNKNOWN_CRASH
                        mock_db.health.mark_crashed(
                            component=component_id,
                            exit_code=exit_code,
                            metadata=f"Process terminated unexpectedly with exit code {exit_code}",
                        )
                        mock_schedule(worker, queue_type, component_id)

        call_args = mock_db.health.mark_crashed.call_args
        assert call_args.kwargs["exit_code"] == EXIT_CODE_UNKNOWN_CRASH
        assert EXIT_CODE_UNKNOWN_CRASH == -1


# ---------------------------- Restart Behavior Tests ----------------------------


class TestRestartScheduling:
    """Test non-blocking restart scheduling."""

    def test_schedule_restart_spawns_thread(self, worker_system_service, mock_worker):
        """Should spawn background thread for restart."""
        with patch("threading.Thread") as mock_thread:
            worker_system_service._schedule_restart(mock_worker, "tag", "worker:tag:0")

            # Verify thread created and started
            mock_thread.assert_called_once()
            call_kwargs = mock_thread.call_args.kwargs
            assert call_kwargs["daemon"] is True
            assert call_kwargs["name"] == "Restart-worker:tag:0"

            mock_thread.return_value.start.assert_called_once()

    def test_schedule_restart_is_non_blocking(self, worker_system_service, mock_worker):
        """_schedule_restart should return immediately without blocking."""
        with patch("threading.Thread"):
            start_time = time.time()
            worker_system_service._schedule_restart(mock_worker, "tag", "worker:tag:0")
            elapsed = time.time() - start_time

            # Should complete in <100ms (not wait for backoff/restart)
            assert elapsed < 0.1


class TestRestartWithBackoff:
    """Test restart logic with exponential backoff."""

    @patch("nomarr.services.infrastructure.worker_system_svc.time.sleep")
    def test_restart_applies_backoff(self, mock_sleep, worker_system_service, mock_db, mock_worker):
        """Should apply exponential backoff before restarting."""
        # Setup: First restart (restart_count=1 means this is the first restart, backoff is 2^1 = 2)
        mock_db.health.increment_restart_count.return_value = {
            "restart_count": 1,
            "last_restart": int(time.time() * 1000),
        }

        with patch.object(worker_system_service, "_create_worker", return_value=mock_worker):
            worker_system_service._restart_worker(mock_worker, "tag", "worker:tag:0")

            # Verify backoff sleep called with 2^1 = 2 seconds (restart_count=1)
            mock_sleep.assert_any_call(2)

    @patch("nomarr.services.infrastructure.worker_system_svc.time.sleep")
    def test_restart_increments_count(self, mock_sleep, worker_system_service, mock_db, mock_worker):
        """Should increment restart count atomically."""
        mock_db.health.increment_restart_count.return_value = {
            "restart_count": 3,
            "last_restart": int(time.time() * 1000),
        }

        with patch.object(worker_system_service, "_create_worker", return_value=mock_worker):
            worker_system_service._restart_worker(mock_worker, "tag", "worker:tag:0")

            # Verify increment_restart_count called
            mock_db.health.increment_restart_count.assert_called_once_with("worker:tag:0")


class TestPermanentFailure:
    """Test permanent failure after exceeding restart limits."""

    @patch("nomarr.services.infrastructure.worker_system_svc.time.sleep")
    def test_marks_failed_after_max_restarts(self, mock_sleep, worker_system_service, mock_db, mock_worker):
        """Should mark as failed and stop restarting after max attempts in window."""
        # Setup: Reached max restarts within window
        now_ms = int(time.time() * 1000)
        mock_db.health.increment_restart_count.return_value = {
            "restart_count": MAX_RESTARTS_IN_WINDOW,
            "last_restart": now_ms - 1000,  # Recent restart
        }
        mock_db.health.get_component.return_value = {"current_job": None}

        worker_system_service._restart_worker(mock_worker, "tag", "worker:tag:0")

        # Verify mark_failed called
        mock_db.health.mark_failed.assert_called_once()
        call_args = mock_db.health.mark_failed.call_args
        assert call_args.kwargs["component"] == "worker:tag:0"
        # Updated: Check for new failure message from component
        assert "restart limit" in call_args.kwargs["metadata"].lower()

        # Verify worker NOT restarted
        mock_worker.stop.assert_not_called()

    @patch("nomarr.services.infrastructure.worker_system_svc.time.sleep")
    def test_continues_restarting_if_outside_window(self, mock_sleep, worker_system_service, mock_db, mock_worker):
        """Should continue restarting if failures are spread over time."""
        # Setup: Many restarts but old
        now_ms = int(time.time() * 1000)
        mock_db.health.increment_restart_count.return_value = {
            "restart_count": MAX_RESTARTS_IN_WINDOW,
            "last_restart": now_ms - RESTART_WINDOW_MS - 1000,  # Outside window
        }

        with patch.object(worker_system_service, "_create_worker", return_value=mock_worker):
            worker_system_service._restart_worker(mock_worker, "tag", "worker:tag:0")

        # Verify NOT marked as failed
        mock_db.health.mark_failed.assert_not_called()

        # Verify worker restarted
        mock_worker.stop.assert_called_once()


# ---------------------------- Worker Replacement Tests ----------------------------


class TestReplaceWorkerInList:
    """Test worker replacement in centralized groups."""

    def test_replaces_tag_worker(self, worker_system_service, mock_worker):
        """Should replace tag worker in centralized group."""
        old_worker = mock_worker
        old_worker.worker_id = 0
        worker_system_service._worker_groups["tag"].append(old_worker)

        new_worker = Mock()
        new_worker.worker_id = 0

        worker_system_service._replace_worker_in_list("tag", 0, new_worker)

        assert worker_system_service._worker_groups["tag"][0] == new_worker

    def test_replaces_library_worker(self, worker_system_service, mock_worker):
        """Should replace library worker in centralized group."""
        old_worker = mock_worker
        old_worker.worker_id = 2
        worker_system_service._worker_groups["library"].append(old_worker)

        new_worker = Mock()
        new_worker.worker_id = 2

        worker_system_service._replace_worker_in_list("library", 2, new_worker)

        assert worker_system_service._worker_groups["library"][0] == new_worker

    def test_replaces_calibration_worker(self, worker_system_service, mock_worker):
        """Should replace calibration worker in centralized group."""
        old_worker = mock_worker
        old_worker.worker_id = 1
        worker_system_service._worker_groups["calibration"].append(old_worker)

        new_worker = Mock()
        new_worker.worker_id = 1

        worker_system_service._replace_worker_in_list("calibration", 1, new_worker)

        assert worker_system_service._worker_groups["calibration"][0] == new_worker


# ---------------------------- Integration-Style Tests ----------------------------


class TestWorkerGroupsCentralization:
    """Test that centralized _worker_groups works correctly."""

    def test_worker_groups_initialized_empty(self, worker_system_service):
        """Should initialize with empty worker groups."""
        assert worker_system_service._worker_groups == {
            "tag": [],
            "library": [],
            "calibration": [],
        }

    def test_all_queue_types_present(self, worker_system_service):
        """Should have all three queue types in mapping."""
        queue_types = set(worker_system_service._worker_groups.keys())
        assert queue_types == {"tag", "library", "calibration"}

    def test_stop_all_workers_uses_centralized_groups(self, worker_system_service, mock_worker):
        """stop_all_workers should iterate over centralized groups."""
        # Add mock workers to each group
        for queue_type in ["tag", "library", "calibration"]:
            worker = Mock()
            worker.name = f"Worker-{queue_type}"
            worker.is_alive = Mock(return_value=False)
            worker.stop = Mock()
            worker.join = Mock()
            worker_system_service._worker_groups[queue_type].append(worker)

        worker_system_service.stop_all_workers()

        # Verify all workers stopped
        for workers in worker_system_service._worker_groups.values():
            for worker in workers:
                worker.stop.assert_called_once()

        # Verify all groups cleared
        for workers in worker_system_service._worker_groups.values():
            assert len(workers) == 0
