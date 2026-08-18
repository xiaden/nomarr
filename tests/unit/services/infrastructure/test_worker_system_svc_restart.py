"""Unit tests for WorkerSystemService restart integration."""

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.workers import RestartDecision
from nomarr.helpers.dto.health_dto import StatusChangeContext
from nomarr.services.infrastructure.worker_system_svc import WorkerSystemService


@pytest.fixture
def mock_db():
    """Provide mock Database."""
    db = MagicMock()
    db.app = MagicMock()
    db.app.get_meta.return_value = None
    db.app.get_worker_restart_policy.return_value = None
    return db


@pytest.fixture
def mock_health_monitor():
    """Provide mock HealthMonitorService."""
    return MagicMock()


@pytest.fixture
def mock_pipeline_svc() -> MagicMock:
    """Provide mock LibraryPipelineService."""
    return MagicMock()


@pytest.fixture
def worker_service(mock_db, mock_health_monitor, mock_pipeline_svc):
    """Provide WorkerSystemService instance with mocked dependencies."""
    from nomarr.helpers.dto.processing_dto import ProcessorConfig

    processor_config = ProcessorConfig(
        models_dir="/mock/models",
        min_duration_s=30,
        allow_short=False,
        batch_size=11,
        namespace="nom",
        version_tag_key="nom_version",
        tagger_version="test",
    )
    return WorkerSystemService(
        db=mock_db,
        processor_config=processor_config,
        pipeline_svc=mock_pipeline_svc,
        health_monitor=mock_health_monitor,
        default_enabled=True,
        worker_count=2,
    )


class TestOnStatusChangeRestartLogic:
    """Test on_status_change() restart decision integration."""

    @patch(
        "nomarr.services.infrastructure.worker_system_svc.worker_death_ops.release_worker_promises",
    )
    @patch(
        "nomarr.services.infrastructure.worker_system_svc.worker_death_ops.release_claims_for_worker",
    )
    def test_graceful_shutdown_prevents_restart(self, mock_release_claims, mock_release_promises, worker_service):
        """When stop_event is set, no restart attempted."""
        worker_service._shutting_down = True

        worker_service.on_status_change("worker_0", "healthy", "dead", StatusChangeContext())

        # Verify no restart-related DB calls since _shutting_down returns early
        assert worker_service.db.app.get_worker_restart_policy.call_count == 0
        assert worker_service.db.app.update_worker_restart_policy.call_count == 0

    @patch(
        "nomarr.services.infrastructure.worker_system_svc.worker_death_ops.release_worker_promises",
    )
    @patch(
        "nomarr.services.infrastructure.worker_system_svc.worker_death_ops.release_claims_for_worker",
    )
    @patch("nomarr.services.infrastructure.worker_system_svc.worker_death_ops.should_restart_worker")
    def test_restart_decision_schedules_timer(
        self, mock_should_restart, mock_release_claims, mock_release_promises, worker_service, mock_db
    ):
        """When decision is 'restart', schedules timer with backoff."""
        mock_should_restart.return_value = RestartDecision(
            action="restart",
            backoff_seconds=2,
            reason="Under restart limit",
        )
        mock_db.app.get_worker_restart_policy = MagicMock(
            return_value={
                "component_id": "worker_1",
                "restart_count": 2,
                "last_restart_wall_ms": 1234567890,
            }
        )
        mock_db.app.update_worker_restart_policy = MagicMock()

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
            mock_db.app.update_worker_restart_policy.assert_called_once()
            update_args, _ = mock_db.app.update_worker_restart_policy.call_args
            assert update_args[0] == "worker_1"
            assert update_args[1]["restart_count"] == 3

    @patch(
        "nomarr.services.infrastructure.worker_system_svc.worker_death_ops.release_worker_promises",
    )
    @patch(
        "nomarr.services.infrastructure.worker_system_svc.worker_death_ops.release_claims_for_worker",
    )
    @patch("nomarr.services.infrastructure.worker_system_svc.worker_death_ops.should_restart_worker")
    def test_mark_failed_decision(
        self, mock_should_restart, mock_release_claims, mock_release_promises, worker_service, mock_db
    ):
        """When decision is 'mark_failed', marks worker as permanently failed."""
        mock_should_restart.return_value = RestartDecision(
            action="mark_failed",
            backoff_seconds=0,
            failure_reason="Restart limit exceeded",
            reason="Too many restarts",
        )
        mock_db.app.get_worker_restart_policy = MagicMock(
            return_value={
                "component_id": "worker_2",
                "restart_count": 5,
                "last_restart_wall_ms": 1234567890,
            }
        )
        mock_db.app.update_worker_restart_policy = MagicMock()

        worker_service.on_status_change("worker_2", "healthy", "dead", StatusChangeContext())

        # Verify health monitor called
        worker_service.health_monitor.set_failed.assert_called_once_with("worker_2")

        # Verify DB persistence
        mock_db.app.update_worker_restart_policy.assert_called_once()
        update_args, _ = mock_db.app.update_worker_restart_policy.call_args
        assert update_args[0] == "worker_2"
        assert update_args[1]["failure_reason"] == "Restart limit exceeded"

        # Verify no timer scheduled
        assert "worker_2" not in worker_service._pending_restart_timers

    @patch(
        "nomarr.services.infrastructure.worker_system_svc.worker_death_ops.release_worker_promises",
    )
    @patch(
        "nomarr.services.infrastructure.worker_system_svc.worker_death_ops.release_claims_for_worker",
    )
    @patch("nomarr.services.infrastructure.worker_system_svc.worker_death_ops.should_restart_worker")
    def test_idempotent_restart_cancels_existing_timer(
        self, mock_should_restart, mock_release_claims, mock_release_promises, worker_service, mock_db
    ):
        """When worker crashes again during backoff, cancels old timer."""
        mock_should_restart.return_value = RestartDecision(
            action="restart",
            backoff_seconds=2,
            reason="Under restart limit",
        )
        mock_db.app.get_worker_restart_policy = MagicMock(
            return_value={
                "component_id": "worker_3",
                "restart_count": 1,
                "last_restart_wall_ms": 1234567890,
            }
        )
        mock_db.app.upsert_worker_restart_policy = MagicMock()
        mock_db.app.update_worker_restart_policy = MagicMock()

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
        mock_db.app.get_meta.return_value = {"key": "worker_enabled", "value": "false"}  # disabled

        worker_service._restart_worker("worker_0")

        # Verify no worker created
        assert len(worker_service._workers) == 0

    @patch("nomarr.services.infrastructure.workers.discovery_worker.create_discovery_worker")
    def test_restart_worker_spawns_replacement(self, mock_create_worker, worker_service, mock_db):
        """When enabled, spawns replacement worker and registers with health monitor."""
        mock_db.app.get_config_option.return_value = {"key": "worker_enabled", "value": "true"}  # enabled
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

    @patch("nomarr.services.infrastructure.workers.discovery_worker.DiscoveryWorker")
    def test_restart_worker_serializes_dataclass_processor_config(self, mock_worker_cls, worker_service):
        """Canonical path: ProcessorConfig dataclass is serialized via asdict().

        Runs the real create_discovery_worker (only the process class is patched)
        and verifies the worker receives the asdict() output.
        """
        from dataclasses import asdict

        mock_worker = MagicMock()
        mock_worker.worker_id = "worker:tag:0"
        mock_worker_cls.return_value = mock_worker

        worker_service._restart_worker("discovery_worker:0")

        mock_worker_cls.assert_called_once()
        call_kwargs = mock_worker_cls.call_args[1]
        assert call_kwargs["processor_config_dict"] == asdict(worker_service.processor_config)
        mock_worker.start.assert_called_once()

    @patch("nomarr.services.infrastructure.workers.discovery_worker.DiscoveryWorker")
    def test_restart_worker_accepts_dict_processor_config(self, mock_worker_cls, mock_db):
        """Regression: dict processor_config must not raise asdict() TypeError.

        Previously, create_discovery_worker called asdict() on a non-dataclass,
        raising "asdict() should be called on dataclass instances". The exception
        was caught and logged as "Failed to restart worker", silently leaving the
        worker dead. A pre-serialized dict must pass through unchanged.
        """
        config_dict = {
            "models_dir": "/mock/models",
            "min_duration_s": 30,
            "allow_short": False,
            "batch_size": 11,
            "namespace": "nom",
            "version_tag_key": "nom_version",
            "tagger_version": "test",
        }
        service = WorkerSystemService(
            db=mock_db,
            processor_config=config_dict,  # type: ignore[arg-type]  # Intentional: exercises the dict-form contract the restart path must tolerate
            pipeline_svc=MagicMock(),
            health_monitor=MagicMock(),
            default_enabled=True,
            worker_count=1,
        )
        mock_worker = MagicMock()
        mock_worker.worker_id = "worker:tag:0"
        mock_worker_cls.return_value = mock_worker

        service._restart_worker("discovery_worker:0")

        mock_worker_cls.assert_called_once()
        call_kwargs = mock_worker_cls.call_args[1]
        assert call_kwargs["processor_config_dict"] == config_dict
        mock_worker.start.assert_called_once()


class TestStopAllWorkersTimerCleanup:
    """Test stop_all_workers() cancels pending restart timers."""

    def test_stop_all_workers_cancels_pending_timers(self, worker_service):
        """When stopping, cancels all pending restart timers BEFORE setting _shutting_down."""
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

        worker_service.stop_all_workers(timeout_sec=1.0)

        # Verify both timers cancelled
        mock_timer_1.cancel.assert_called_once()
        mock_timer_2.cancel.assert_called_once()

        # Verify dict cleared
        assert len(worker_service._pending_restart_timers) == 0

        # Verify _shutting_down was set (after timer cancellation)
        assert worker_service._shutting_down


class TestDrainOldWorker:
    """Test WorkerSystemService._drain_old_worker drain/terminate/kill escalation."""

    def test_drain_exits_cleanly_when_worker_stops_within_timeout(self, worker_service):
        """When worker stops before timeout, terminate() and kill() are never called."""
        mock_worker = MagicMock()
        mock_worker.worker_id = "worker_0"
        mock_worker.is_alive.return_value = False  # already stopped after join

        worker_service._drain_old_worker(mock_worker, timeout=2.0)

        mock_worker.join.assert_called_once_with(timeout=2.0)
        mock_worker.terminate.assert_not_called()
        mock_worker.kill.assert_not_called()

    def test_drain_terminates_when_still_alive_after_first_join(self, worker_service):
        """When worker is alive after join but stops after terminate(), kill() is skipped."""
        mock_worker = MagicMock()
        mock_worker.worker_id = "worker_0"
        # First is_alive → True (trigger terminate), second → False (no kill needed)
        mock_worker.is_alive.side_effect = [True, False]

        worker_service._drain_old_worker(mock_worker, timeout=2.0)

        mock_worker.terminate.assert_called_once()
        mock_worker.kill.assert_not_called()
        assert mock_worker.join.call_count == 2

    def test_drain_kills_when_still_alive_after_terminate(self, worker_service):
        """When worker survives both join and terminate(), kill() is called."""
        mock_worker = MagicMock()
        mock_worker.worker_id = "worker_0"
        mock_worker.pid = 9999
        # All is_alive checks return True → escalates to kill
        mock_worker.is_alive.return_value = True

        worker_service._drain_old_worker(mock_worker, timeout=2.0)

        mock_worker.terminate.assert_called_once()
        mock_worker.kill.assert_called_once()
        assert mock_worker.join.call_count == 3


class TestAddRemoveWorkers:
    """Tests for add_workers() and remove_workers() dynamic scaling methods."""

    def test_add_workers_normal(self, worker_service):
        """Normal path spawns workers and adds to pool."""
        worker_service._tier_selection = MagicMock()
        worker_service._tier_selection.tier = 1
        worker_service._tier_selection.config.prefer_gpu = True

        with patch.object(worker_service, "_spawn_worker") as mock_spawn:
            workers = []

            def side_effect(index, tier):
                w = MagicMock()
                w.worker_id = f"worker:{index}"
                workers.append(w)
                worker_service._workers.append(w)
                return w

            mock_spawn.side_effect = side_effect

            worker_service.add_workers(3)

            assert mock_spawn.call_count == 3
            assert len(worker_service._workers) == 3

    def test_add_workers_zero(self, worker_service, caplog):
        """add_workers(0) is a no-op with warning logged."""
        caplog.set_level("WARNING")
        worker_service.add_workers(0)
        assert len(worker_service._workers) == 0
        assert "add_workers called with count=0" in caplog.text

    def test_add_workers_no_tier_selection(self, worker_service, caplog):
        """When _tier_selection is None, no-op with warning logged."""
        caplog.set_level("WARNING")
        worker_service._tier_selection = None
        worker_service.add_workers(2)
        assert len(worker_service._workers) == 0
        assert "No tier selection exists" in caplog.text

    def test_add_workers_empty_pool(self, worker_service):
        """When pool is empty, spawns workers without re-running admission control."""
        worker_service._tier_selection = MagicMock()
        worker_service._tier_selection.tier = 1
        worker_service._tier_selection.config.prefer_gpu = True

        with patch.object(worker_service, "_spawn_worker") as mock_spawn:
            workers = []

            def side_effect(index, tier):
                w = MagicMock()
                w.worker_id = f"worker:{index}"
                workers.append(w)
                worker_service._workers.append(w)
                return w

            mock_spawn.side_effect = side_effect

            worker_service.add_workers(2)

            # Should spawn directly without re-running admission control
            assert mock_spawn.call_count == 2
            assert len(worker_service._workers) == 2

    def test_remove_workers_normal(self, worker_service):
        """Normal path stops workers, joins, unregisters, removes from pool."""
        mock_workers = [MagicMock() for _ in range(3)]
        for i, mw in enumerate(mock_workers):
            mw.worker_id = f"worker_{i}"
            mw.is_alive.return_value = False
        worker_service._workers = list(mock_workers)

        worker_service.remove_workers(2)

        # Last two workers should have been stopped
        mock_workers[1].stop.assert_called_once()
        mock_workers[2].stop.assert_called_once()
        mock_workers[0].stop.assert_not_called()

        # Should unregister from health monitor
        assert worker_service.health_monitor.unregister_component.call_count == 2

        # Should remove from pool
        assert len(worker_service._workers) == 1
        assert worker_service._workers[0] == mock_workers[0]

    @patch("nomarr.services.infrastructure.worker_system_svc.main.release_worker_promises")
    @patch("nomarr.services.infrastructure.worker_system_svc.main.release_claims_for_worker")
    def test_remove_workers_keeps_worker_tracked_if_force_stop_fails(
        self, mock_release_claims, mock_release_promises, worker_service
    ):
        """A worker still alive after terminate/kill remains tracked with resources intact."""
        mock_workers = [MagicMock() for _ in range(2)]
        for i, worker in enumerate(mock_workers):
            worker.worker_id = f"worker_{i}"
            worker.is_alive.return_value = i == 1
        worker_service._workers = list(mock_workers)

        worker_service.remove_workers(1)

        worker = mock_workers[1]
        worker.stop.assert_called_once()
        worker.terminate.assert_called_once()
        worker.kill.assert_called_once()
        assert worker in worker_service._workers
        mock_release_claims.assert_not_called()
        mock_release_promises.assert_not_called()
        worker_service.health_monitor.unregister_component.assert_not_called()

    def test_remove_workers_zero(self, worker_service, caplog):
        """remove_workers(0) is a no-op with warning logged."""
        caplog.set_level("WARNING")
        worker_service.remove_workers(0)
        assert "remove_workers called with count=0" in caplog.text

    def test_remove_workers_all_when_count_ge_pool(self, worker_service):
        """When n >= len(pool), calls stop_all_workers."""
        mock_workers = [MagicMock() for _ in range(2)]
        for i, mw in enumerate(mock_workers):
            mw.worker_id = f"worker_{i}"
        worker_service._workers = list(mock_workers)

        with patch.object(worker_service, "stop_all_workers") as mock_stop_all:
            worker_service.remove_workers(3)

            mock_stop_all.assert_called_once()

    @patch(
        "nomarr.services.infrastructure.worker_system_svc.worker_death_ops.release_worker_promises",
    )
    @patch(
        "nomarr.services.infrastructure.worker_system_svc.worker_death_ops.release_claims_for_worker",
    )
    def test_shutting_down_gates_restart_in_handle_worker_death(
        self, mock_release_claims, mock_release_promises, worker_service
    ):
        """When _shutting_down is True, _handle_worker_death returns without restart."""
        worker_service._shutting_down = True
        worker_service.on_status_change("worker_0", "healthy", "dead", StatusChangeContext())
        # Verify no restart-related DB calls since we return early
        assert worker_service.db.app.get_worker_restart_policy.call_count == 0

    def test_shutting_down_gates_restart_in_restart_worker(self, worker_service):
        """When _shutting_down is True, _restart_worker skips restart."""
        worker_service._shutting_down = True
        worker_service._restart_worker("discovery_worker:0")
        # Verify no worker was created
        assert len(worker_service._workers) == 0


class TestGetWorkerCount:
    """Tests for ``WorkerSystemService.get_worker_count()``."""

    def test_returns_zero_initially(self, worker_service: WorkerSystemService) -> None:
        """get_worker_count() returns 0 before any workers are spawned."""
        assert worker_service.get_worker_count() == 0

    def test_returns_correct_count_after_manual_append(self, worker_service: WorkerSystemService) -> None:
        """get_worker_count() returns actual worker list length."""
        worker_service._workers.extend([MagicMock(), MagicMock(), MagicMock()])
        assert worker_service.get_worker_count() == 3

    def test_reflects_worker_removal(self, worker_service: WorkerSystemService) -> None:
        """get_worker_count() decreases after workers are removed."""
        w1, w2 = MagicMock(), MagicMock()
        worker_service._workers.extend([w1, w2])
        assert worker_service.get_worker_count() == 2

        worker_service._workers.remove(w1)
        assert worker_service.get_worker_count() == 1
