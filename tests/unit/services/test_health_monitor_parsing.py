"""Unit tests for HealthMonitorService frame parsing.

Tests verify that `_handle_frame` correctly:
- Accepts HEALTH| prefixed JSON frames
- Rejects non-HEALTH| prefixed data
- Does not crash on malformed JSON
- Transitions component status based on frame content
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dto.health_dto import ComponentPolicy

HEALTH_FRAME_PREFIX = "HEALTH|"


class TestHandleFrameParsing:
    """Tests for HealthMonitorService._handle_frame parsing behavior."""

    @pytest.fixture
    def monitor_with_component(self) -> tuple:
        """Create HealthMonitorService with one registered component."""
        from nomarr.services.infrastructure.health_monitor_svc import (
            HealthMonitorConfig,
            HealthMonitorService,
        )

        monitor = HealthMonitorService(cfg=HealthMonitorConfig(), db=None)
        mock_handler = MagicMock()
        mock_pipe = MagicMock()

        monitor.register_component(
            component_id="test:component:0",
            handler=mock_handler,
            pipe_conn=mock_pipe,
            policy=ComponentPolicy(),
        )

        return monitor, mock_handler

    @pytest.mark.unit
    def test_accepts_valid_healthy_frame(self, monitor_with_component: tuple) -> None:
        """Valid HEALTH| JSON frame with status=healthy should transition to healthy."""
        monitor, mock_handler = monitor_with_component

        frame = HEALTH_FRAME_PREFIX + json.dumps(
            {
                "component_id": "test:component:0",
                "status": "healthy",
            },
        )

        # Initial status is pending
        assert monitor.get_status("test:component:0") == "pending"

        # Process frame
        monitor._handle_frame("test:component:0", frame)

        # Should transition to healthy
        assert monitor.get_status("test:component:0") == "healthy"
        mock_handler.on_status_change.assert_called_once()

    @pytest.mark.unit
    def test_accepts_valid_recovering_frame(self, monitor_with_component: tuple) -> None:
        """Valid HEALTH| JSON frame with status=recovering should set recovery deadline."""
        monitor, _mock_handler = monitor_with_component

        frame = HEALTH_FRAME_PREFIX + json.dumps(
            {
                "component_id": "test:component:0",
                "status": "recovering",
                "recover_for_s": 10.0,
            },
        )

        monitor._handle_frame("test:component:0", frame)

        assert monitor.get_status("test:component:0") == "recovering"

    @pytest.mark.unit
    def test_rejects_frame_without_health_prefix(self, monitor_with_component: tuple) -> None:
        """Frame without HEALTH| prefix should be silently ignored."""
        monitor, mock_handler = monitor_with_component

        # Valid JSON but no HEALTH| prefix
        frame = json.dumps(
            {
                "component_id": "test:component:0",
                "status": "healthy",
            },
        )

        # Process frame
        monitor._handle_frame("test:component:0", frame)

        # Status should remain pending (no transition)
        assert monitor.get_status("test:component:0") == "pending"
        mock_handler.on_status_change.assert_not_called()

    @pytest.mark.unit
    def test_rejects_non_string_data(self, monitor_with_component: tuple) -> None:
        """Non-string data should be silently ignored."""
        monitor, mock_handler = monitor_with_component

        # Pass non-string data
        monitor._handle_frame("test:component:0", {"status": "healthy"})
        monitor._handle_frame("test:component:0", 12345)
        monitor._handle_frame("test:component:0", None)

        # Status should remain pending
        assert monitor.get_status("test:component:0") == "pending"
        mock_handler.on_status_change.assert_not_called()

    @pytest.mark.unit
    def test_does_not_crash_on_malformed_json(self, monitor_with_component: tuple) -> None:
        """Malformed JSON after HEALTH| prefix should not crash, just ignore."""
        monitor, mock_handler = monitor_with_component

        # HEALTH| prefix but invalid JSON payload
        frame = HEALTH_FRAME_PREFIX + "not valid json {"

        # Should not raise
        monitor._handle_frame("test:component:0", frame)

        # Status should remain pending
        assert monitor.get_status("test:component:0") == "pending"
        mock_handler.on_status_change.assert_not_called()

    @pytest.mark.unit
    def test_does_not_crash_on_empty_json(self, monitor_with_component: tuple) -> None:
        """Empty JSON object after HEALTH| should not crash."""
        monitor, _mock_handler = monitor_with_component

        frame = HEALTH_FRAME_PREFIX + "{}"

        # Should not raise
        monitor._handle_frame("test:component:0", frame)

        # Status should remain pending (no status field = no transition)
        assert monitor.get_status("test:component:0") == "pending"

    @pytest.mark.unit
    def test_ignores_unknown_status_values(self, monitor_with_component: tuple) -> None:
        """Unknown status values should be silently ignored."""
        monitor, _mock_handler = monitor_with_component

        frame = HEALTH_FRAME_PREFIX + json.dumps(
            {
                "component_id": "test:component:0",
                "status": "unknown_status_value",
            },
        )

        monitor._handle_frame("test:component:0", frame)

        # Status should remain pending
        assert monitor.get_status("test:component:0") == "pending"

    @pytest.mark.unit
    def test_gpu_monitor_frame_format(self, monitor_with_component: tuple) -> None:
        """GPU monitor frame format should be accepted (regression test)."""
        monitor, _mock_handler = monitor_with_component

        # This is the exact format GPUHealthMonitor._send_heartbeat emits
        frame = HEALTH_FRAME_PREFIX + json.dumps(
            {
                "component_id": "gpu_monitor",
                "status": "healthy",
            },
        )

        # Register gpu_monitor component
        monitor.register_component(
            component_id="gpu_monitor",
            handler=MagicMock(),
            pipe_conn=MagicMock(),
            policy=ComponentPolicy(),
        )

        monitor._handle_frame("gpu_monitor", frame)

        assert monitor.get_status("gpu_monitor") == "healthy"
