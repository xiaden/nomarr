"""Mixin for deadline checking: startup timeouts, staleness, and recovery deadlines."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import threading

    from nomarr.helpers.dto.health_dto import (
        ComponentLifecycleHandler,
        ComponentStatus,
    )
    from nomarr.helpers.time_helper import InternalSeconds

    from ._helpers import _ComponentState

logger = logging.getLogger(__name__)


class DeadlineOpsMixin:
    """Mixin for deadline-based health checks.

    Requires the host class to provide:
    - ``self._lock`` (threading.Lock)
    - ``self._components`` (dict[str, _ComponentState])
    - ``self._emit_status_change(...)`` (method from StateTransitionOpsMixin)
    """

    _lock: threading.Lock
    _components: dict[str, _ComponentState]

    def _emit_status_change(
        self,
        component_id: str,
        old_status: ComponentStatus,
        new_status: ComponentStatus,
        handler: ComponentLifecycleHandler,
        state: _ComponentState,
    ) -> None:
        """Stub — overridden by StateTransitionOpsMixin via MRO."""
        raise NotImplementedError

    def _check_all_deadlines(self, now: InternalSeconds) -> None:
        """Check startup timeouts, staleness, and recovery deadlines."""
        # Collect state changes to emit outside lock
        changes: list[tuple[str, ComponentStatus, ComponentStatus, ComponentLifecycleHandler, _ComponentState]] = []

        with self._lock:
            for component_id, state in self._components.items():
                if state.status in {"failed", "dead"}:
                    continue  # Don't check failed/dead

                change = self._check_component_deadline(component_id, state, now)
                if change:
                    changes.append(change)

        # Emit callbacks outside lock
        for component_id, old_status, new_status, handler, state in changes:
            self._emit_status_change(component_id, old_status, new_status, handler, state)

    def _check_component_deadline(
        self,
        component_id: str,
        state: _ComponentState,
        now: InternalSeconds,
    ) -> tuple[str, ComponentStatus, ComponentStatus, ComponentLifecycleHandler, _ComponentState] | None:
        """Check deadlines for a single component. Returns state change if any."""
        policy = state.policy

        # Pending: check startup timeout
        if state.status == "pending":
            if state.startup_deadline and now.value >= state.startup_deadline.value:
                old_status: ComponentStatus = state.status
                state.status = "dead"
                logger.warning(
                    "[HealthMonitor] %s: pending -> dead (startup timeout)",
                    component_id,
                )
                return (component_id, old_status, "dead", state.handler, state)
            return None

        # Recovering: check recovery deadline
        if state.status == "recovering":
            if state.recovery_deadline and now.value >= state.recovery_deadline.value:
                old_status = state.status
                state.status = "dead"
                logger.warning(
                    "[HealthMonitor] %s: recovering -> dead (recovery timeout)",
                    component_id,
                )
                return (component_id, old_status, "dead", state.handler, state)
            return None

        # Healthy/Unhealthy: check staleness
        if state.status in ("healthy", "unhealthy"):
            time_since_frame = now.value - state.last_frame_time.value
            if time_since_frame >= policy.staleness_interval_s:
                state.consecutive_misses += 1
                state.last_frame_time = now  # Reset for next interval

                if state.consecutive_misses >= policy.max_consecutive_misses:
                    prev_status: ComponentStatus = state.status
                    state.status = "dead"
                    logger.warning(
                        "[HealthMonitor] %s: %s -> dead (%d consecutive misses)",
                        component_id,
                        prev_status,
                        state.consecutive_misses,
                    )
                    return (component_id, prev_status, "dead", state.handler, state)
                if state.status == "healthy":
                    prev_healthy: ComponentStatus = state.status
                    state.status = "unhealthy"
                    logger.debug(
                        "[HealthMonitor] %s: healthy -> unhealthy (miss %d/%d)",
                        component_id,
                        state.consecutive_misses,
                        policy.max_consecutive_misses,
                    )
                    return (component_id, prev_healthy, "unhealthy", state.handler, state)
                # Already unhealthy, just increment miss count (no callback)
            return None

        return None
