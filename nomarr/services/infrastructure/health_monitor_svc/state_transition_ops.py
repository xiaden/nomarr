"""Mixin for state transitions and status change emission."""

from __future__ import annotations

import logging
import threading

from nomarr.helpers.dto.health_dto import (
    ComponentLifecycleHandler,
    ComponentStatus,
    StatusChangeContext,
)
from nomarr.helpers.time_helper import InternalSeconds, internal_s

from ._helpers import _ComponentState

logger = logging.getLogger(__name__)


class StateTransitionOpsMixin:
    """Mixin for state transitions and status change callbacks.

    Requires the host class to provide:
    - ``self._lock`` (threading.Lock)
    - ``self._components`` (dict[str, _ComponentState])
    """

    _lock: threading.Lock
    _components: dict[str, _ComponentState]

    def _transition_to_healthy(self, component_id: str) -> None:
        """Transition component to healthy status."""
        with self._lock:
            state = self._components.get(component_id)
            if not state or state.status == "failed":
                return

            old_status = state.status
            state.status = "healthy"
            state.last_frame_time = internal_s()
            state.consecutive_misses = 0
            state.recovery_deadline = None
            state.reported_recover_for_s = None
            handler = state.handler

        if old_status != "healthy":
            logger.debug("[HealthMonitor] %s: %s -> healthy", component_id, old_status)
            self._emit_status_change(component_id, old_status, "healthy", handler, state)

    def _transition_to_recovering(self, component_id: str, reported_recover_for_s: float | None) -> None:
        """Transition component to recovering status with deadline."""
        with self._lock:
            state = self._components.get(component_id)
            if not state or state.status == "failed":
                return

            # Clamp recovery duration to [min, max]
            policy = state.policy
            if reported_recover_for_s is None:
                recover_s = policy.max_recovery_s
            else:
                recover_s = max(policy.min_recovery_s, min(reported_recover_for_s, policy.max_recovery_s))

            old_status = state.status
            state.status = "recovering"
            state.last_frame_time = internal_s()
            state.recovery_deadline = InternalSeconds(internal_s().value + int(recover_s))
            state.reported_recover_for_s = reported_recover_for_s
            handler = state.handler

        if old_status != "recovering":
            logger.debug(
                "[HealthMonitor] %s: %s -> recovering (%.1fs)",
                component_id,
                old_status,
                recover_s,
            )
            self._emit_status_change(component_id, old_status, "recovering", handler, state)

    def _handle_pipe_closed(self, component_id: str) -> None:
        """Handle pipe EOF - component exited."""
        with self._lock:
            state = self._components.get(component_id)
            if not state or state.status in ("failed", "dead"):
                return  # Idempotent: only emit dead transition once

            old_status = state.status
            state.status = "dead"
            state.recovery_deadline = None
            handler = state.handler

        logger.debug("[HealthMonitor] %s: %s -> dead (pipe closed)", component_id, old_status)
        self._emit_status_change(component_id, old_status, "dead", handler, state)

    def _emit_status_change(
        self,
        component_id: str,
        old_status: ComponentStatus,
        new_status: ComponentStatus,
        handler: ComponentLifecycleHandler,
        state: _ComponentState,
    ) -> None:
        """Emit status change callback to handler."""
        context = StatusChangeContext(
            consecutive_misses=state.consecutive_misses,
            recovery_deadline=state.recovery_deadline.value if state.recovery_deadline else None,
            reported_recover_for_s=state.reported_recover_for_s,
        )

        try:
            handler.on_status_change(component_id, old_status, new_status, context)
        except Exception as e:
            logger.exception("[HealthMonitor] Handler error on status change: %s", e)
