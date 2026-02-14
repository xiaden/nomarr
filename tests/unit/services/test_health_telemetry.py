"""Unit tests for pipe-based health telemetry.

Tests cover:
- Frame parsing logic
- HealthMonitor status registry and state machine
- ComponentLifecycleHandler callback protocol
- Worker health frame emission
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dto.health_dto import ComponentPolicy, StatusChangeContext
from nomarr.helpers.time_helper import now_s

# Test the frame prefix and parsing logic
HEALTH_FRAME_PREFIX = "HEALTH|"


class TestHealthFrameParsing:
    """Tests for health frame format and parsing."""

    def test_valid_healthy_frame(self) -> None:
        """Valid healthy frame should parse correctly."""
        frame = HEALTH_FRAME_PREFIX + json.dumps(
            {
                "component_id": "worker:tag:0",
                "status": "healthy",
            },
        )

        assert frame.startswith(HEALTH_FRAME_PREFIX)
        json_str = frame[len(HEALTH_FRAME_PREFIX) :]
        data = json.loads(json_str)
        assert data["component_id"] == "worker:tag:0"
        assert data["status"] == "healthy"

    def test_recovering_frame_with_duration(self) -> None:
        """Recovering frame with recover_for_s should parse correctly."""
        frame = HEALTH_FRAME_PREFIX + json.dumps(
            {
                "component_id": "worker:tag:0",
                "status": "recovering",
                "recover_for_s": 15.0,
            },
        )

        json_str = frame[len(HEALTH_FRAME_PREFIX) :]
        data = json.loads(json_str)
        assert data["status"] == "recovering"
        assert data["recover_for_s"] == 15.0

    def test_invalid_json_frame(self) -> None:
        """Invalid JSON should raise JSONDecodeError."""
        frame = HEALTH_FRAME_PREFIX + "not valid json"

        with pytest.raises(json.JSONDecodeError):
            json_str = frame[len(HEALTH_FRAME_PREFIX) :]
            json.loads(json_str)

    def test_frame_without_prefix_not_parsed(self) -> None:
        """Frame without HEALTH| prefix should not be parsed."""
        frame = json.dumps({"component_id": "worker:tag:0", "status": "healthy"})
        assert not frame.startswith(HEALTH_FRAME_PREFIX)


class TestHealthMonitorStatusRegistry:
    """Tests for HealthMonitorService status registry."""

    def test_register_component_creates_pending_status(self) -> None:
        """register_component should create registry entry with pending status."""
        from nomarr.services.infrastructure.health_monitor_svc import (
            HealthMonitorConfig,
            HealthMonitorService,
        )

        monitor = HealthMonitorService(cfg=HealthMonitorConfig(), db=None)
        mock_handler = MagicMock()
        mock_pipe = MagicMock()

        monitor.register_component(
            component_id="worker:tag:0",
            handler=mock_handler,
            pipe_conn=mock_pipe,
            policy=ComponentPolicy(),
        )

        assert monitor.get_status("worker:tag:0") == "pending"

    def test_transition_to_healthy_resets_misses(self) -> None:
        """Healthy frame should reset consecutive misses."""
        from nomarr.services.infrastructure.health_monitor_svc import (
            HealthMonitorConfig,
            HealthMonitorService,
            _ComponentState,
        )

        monitor = HealthMonitorService(cfg=HealthMonitorConfig(), db=None)
        mock_handler = MagicMock()

        # Set up component state directly
        state = _ComponentState(
            handler=mock_handler,
            pipe_conn=MagicMock(),
            policy=ComponentPolicy(),
            status="unhealthy",
            consecutive_misses=2,
        )
        monitor._components["worker:tag:0"] = state

        # Trigger healthy transition
        monitor._transition_to_healthy("worker:tag:0")

        assert monitor.get_status("worker:tag:0") == "healthy"
        assert state.consecutive_misses == 0
        mock_handler.on_status_change.assert_called_once()

    def test_transition_to_recovering_sets_deadline(self) -> None:
        """Recovering transition should set recovery deadline."""
        from nomarr.services.infrastructure.health_monitor_svc import (
            HealthMonitorConfig,
            HealthMonitorService,
            _ComponentState,
        )

        monitor = HealthMonitorService(cfg=HealthMonitorConfig(), db=None)
        mock_handler = MagicMock()

        state = _ComponentState(
            handler=mock_handler,
            pipe_conn=MagicMock(),
            policy=ComponentPolicy(min_recovery_s=5.0, max_recovery_s=60.0),
            status="healthy",
        )
        monitor._components["worker:tag:0"] = state

        # Trigger recovering transition with requested duration
        monitor._transition_to_recovering("worker:tag:0", reported_recover_for_s=15.0)

        assert monitor.get_status("worker:tag:0") == "recovering"
        assert state.recovery_deadline is not None
        assert state.reported_recover_for_s == 15.0

    def test_recovery_duration_clamped_to_max(self) -> None:
        """Recovery duration should be clamped to max_recovery_s."""
        from nomarr.services.infrastructure.health_monitor_svc import (
            HealthMonitorConfig,
            HealthMonitorService,
            _ComponentState,
        )

        monitor = HealthMonitorService(cfg=HealthMonitorConfig(), db=None)
        mock_handler = MagicMock()

        state = _ComponentState(
            handler=mock_handler,
            pipe_conn=MagicMock(),
            policy=ComponentPolicy(min_recovery_s=5.0, max_recovery_s=30.0),
            status="healthy",
        )
        monitor._components["worker:tag:0"] = state

        monitor._transition_to_recovering("worker:tag:0", reported_recover_for_s=120.0)
        after = now_s()

        # Deadline should be clamped to max_recovery_s (30s)
        assert state.recovery_deadline is not None
        # Convert InternalSeconds to float for comparison
        deadline_value = state.recovery_deadline.value
        after_value = after.value
        assert deadline_value <= after_value + 30 + 1  # Allow 1s tolerance

    def test_set_failed_is_terminal(self) -> None:
        """set_failed should permanently mark component as failed."""
        from nomarr.services.infrastructure.health_monitor_svc import (
            HealthMonitorConfig,
            HealthMonitorService,
            _ComponentState,
        )

        monitor = HealthMonitorService(cfg=HealthMonitorConfig(), db=None)
        mock_handler = MagicMock()

        state = _ComponentState(
            handler=mock_handler,
            pipe_conn=MagicMock(),
            policy=ComponentPolicy(),
            status="healthy",
        )
        monitor._components["worker:tag:0"] = state

        monitor.set_failed("worker:tag:0")

        assert monitor.get_status("worker:tag:0") == "failed"
        mock_handler.on_status_change.assert_called_once()

    def test_set_failed_is_idempotent(self) -> None:
        """set_failed should be idempotent (no callback on second call)."""
        from nomarr.services.infrastructure.health_monitor_svc import (
            HealthMonitorConfig,
            HealthMonitorService,
            _ComponentState,
        )

        monitor = HealthMonitorService(cfg=HealthMonitorConfig(), db=None)
        mock_handler = MagicMock()

        state = _ComponentState(
            handler=mock_handler,
            pipe_conn=MagicMock(),
            policy=ComponentPolicy(),
            status="healthy",
        )
        monitor._components["worker:tag:0"] = state

        monitor.set_failed("worker:tag:0")
        monitor.set_failed("worker:tag:0")  # Second call

        # Should only callback once
        assert mock_handler.on_status_change.call_count == 1

    def test_cannot_reregister_failed_component(self) -> None:
        """Cannot re-register a component that is marked failed."""
        from nomarr.services.infrastructure.health_monitor_svc import (
            HealthMonitorConfig,
            HealthMonitorService,
            _ComponentState,
        )

        monitor = HealthMonitorService(cfg=HealthMonitorConfig(), db=None)
        mock_handler = MagicMock()

        state = _ComponentState(
            handler=mock_handler,
            pipe_conn=MagicMock(),
            policy=ComponentPolicy(),
            status="failed",
        )
        monitor._components["worker:tag:0"] = state

        # Try to re-register
        new_handler = MagicMock()
        monitor.register_component(
            component_id="worker:tag:0",
            handler=new_handler,
            pipe_conn=MagicMock(),
            policy=ComponentPolicy(),
        )

        # Should still be failed with old handler
        assert monitor.get_status("worker:tag:0") == "failed"
        assert monitor._components["worker:tag:0"].handler is mock_handler

    def test_pipe_closed_transitions_to_dead(self) -> None:
        """Pipe EOF should transition component to dead."""
        from nomarr.services.infrastructure.health_monitor_svc import (
            HealthMonitorConfig,
            HealthMonitorService,
            _ComponentState,
        )

        monitor = HealthMonitorService(cfg=HealthMonitorConfig(), db=None)
        mock_handler = MagicMock()

        state = _ComponentState(
            handler=mock_handler,
            pipe_conn=MagicMock(),
            policy=ComponentPolicy(),
            status="healthy",
        )
        monitor._components["worker:tag:0"] = state

        monitor._handle_pipe_closed("worker:tag:0")

        assert monitor.get_status("worker:tag:0") == "dead"
        mock_handler.on_status_change.assert_called_once()

    def test_get_all_statuses_returns_all(self) -> None:
        """get_all_statuses should return all component statuses."""
        from nomarr.services.infrastructure.health_monitor_svc import (
            HealthMonitorConfig,
            HealthMonitorService,
            _ComponentState,
        )

        monitor = HealthMonitorService(cfg=HealthMonitorConfig(), db=None)

        monitor._components["worker:tag:0"] = _ComponentState(
            handler=MagicMock(),
            pipe_conn=MagicMock(),
            policy=ComponentPolicy(),
            status="healthy",
        )
        monitor._components["worker:tag:1"] = _ComponentState(
            handler=MagicMock(),
            pipe_conn=MagicMock(),
            policy=ComponentPolicy(),
            status="unhealthy",
        )

        result = monitor.get_all_statuses()
        assert result == {"worker:tag:0": "healthy", "worker:tag:1": "unhealthy"}


class TestComponentLifecycleHandler:
    """Tests for ComponentLifecycleHandler protocol implementation."""

    def test_worker_system_implements_lifecycle_handler(self) -> None:
        """WorkerSystemService should implement ComponentLifecycleHandler."""
        from nomarr.helpers.dto.health_dto import ComponentLifecycleHandler
        from nomarr.services.infrastructure.worker_system_svc import WorkerSystemService

        mock_db = MagicMock()
        mock_db.hosts = "http://localhost:8529"
        mock_db.password = "test"

        mock_config = MagicMock()
        mock_config.tagger_version = "test"
        mock_config.enabled_heads = []
        mock_config.models_base_path = "/models"
        mock_config.model_map = {}
        mock_config.min_duration_s = 3
        mock_config.allow_short = False

        service = WorkerSystemService(
            db=mock_db,
            processor_config=mock_config,
            worker_count=1,
        )

        # Verify it has the required method
        assert hasattr(service, "on_status_change")
        assert isinstance(service, ComponentLifecycleHandler)

    def test_on_status_change_does_not_raise(self) -> None:
        """on_status_change should not raise."""
        from nomarr.services.infrastructure.worker_system_svc import WorkerSystemService

        mock_db = MagicMock()
        mock_db.hosts = "http://localhost:8529"
        mock_db.password = "test"
        # Add worker_restart_policy mock for new restart logic
        mock_db.worker_restart_policy = MagicMock()
        mock_db.worker_restart_policy.get_restart_state.return_value = (0, None)

        mock_config = MagicMock()
        mock_config.tagger_version = "test"
        mock_config.enabled_heads = []
        mock_config.models_base_path = "/models"
        mock_config.model_map = {}
        mock_config.min_duration_s = 3
        mock_config.allow_short = False

        service = WorkerSystemService(
            db=mock_db,
            processor_config=mock_config,
            worker_count=1,
        )

        context = StatusChangeContext(consecutive_misses=0)

        # Should not raise
        service.on_status_change("worker:tag:0", "pending", "healthy", context)
        service.on_status_change("worker:tag:0", "healthy", "dead", context)


class TestHealthFrameEmission:
    """Tests for health frame emission from worker."""

    def test_send_health_frame_format(self) -> None:
        """_send_health_frame should emit correctly formatted frame."""
        from nomarr.services.infrastructure.workers.discovery_worker import (
            HEALTH_FRAME_PREFIX,
            DiscoveryWorker,
        )

        # Create worker without starting
        worker = DiscoveryWorker(
            worker_id="worker:tag:0",
            db_hosts="http://localhost:8529",
            db_password="test",
            processor_config_dict={
                "tagger_version": "test",
                "enabled_heads": [],
                "models_base_path": "/models",
                "model_map": {},
                "min_duration_s": 3,
                "allow_short": False,
            },
            health_pipe=MagicMock(),
        )

        # Call _send_health_frame
        worker._send_health_frame("healthy")

        # Verify frame was sent
        worker._health_pipe.send.assert_called_once()
        frame = worker._health_pipe.send.call_args[0][0]

        # Verify format
        assert frame.startswith(HEALTH_FRAME_PREFIX)
        data = json.loads(frame[len(HEALTH_FRAME_PREFIX) :])
        assert data["component_id"] == "worker:tag:0"
        assert data["status"] == "healthy"

    def test_send_health_frame_handles_pipe_error(self) -> None:
        """_send_health_frame should handle pipe errors gracefully."""
        from nomarr.services.infrastructure.workers.discovery_worker import DiscoveryWorker

        mock_pipe = MagicMock()
        mock_pipe.send.side_effect = BrokenPipeError("Pipe closed")

        worker = DiscoveryWorker(
            worker_id="worker:tag:0",
            db_hosts="http://localhost:8529",
            db_password="test",
            processor_config_dict={
                "tagger_version": "test",
                "enabled_heads": [],
                "models_base_path": "/models",
                "model_map": {},
                "min_duration_s": 3,
                "allow_short": False,
            },
            health_pipe=mock_pipe,
        )

        # Should not raise
        worker._send_health_frame("healthy")

    def test_send_health_frame_with_no_pipe(self) -> None:
        """_send_health_frame should do nothing if no pipe."""
        from nomarr.services.infrastructure.workers.discovery_worker import DiscoveryWorker

        worker = DiscoveryWorker(
            worker_id="worker:tag:0",
            db_hosts="http://localhost:8529",
            db_password="test",
            processor_config_dict={
                "tagger_version": "test",
                "enabled_heads": [],
                "models_base_path": "/models",
                "model_map": {},
                "min_duration_s": 3,
                "allow_short": False,
            },
            health_pipe=None,
        )

        # Should not raise
        worker._send_health_frame("healthy")
