"""
Health monitoring service.

## Health Monitoring Contract

HealthMonitor OWNS:
- Single consolidated monitor thread (polls all pipes + checks staleness)
- In-memory status registry
- Per-component policies and deadlines

HealthMonitor EMITS:
- Status change callbacks to handlers (domain decides actions)

### Status Model

| Status      | Set by        | Meaning                                      |
|-------------|---------------|----------------------------------------------|
| pending     | HealthMonitor | Waiting for first frame after registration   |
| healthy     | HealthMonitor | Receiving healthy frames                     |
| unhealthy   | HealthMonitor | Missed 1+ staleness checks                   |
| recovering  | HealthMonitor | Component requested recovery window          |
| dead        | HealthMonitor | Intervention needed (timeout/misses/EOF)     |
| failed      | Domain        | Permanent, not restarting                    |

### Key Rules

1. A frame with status="healthy" resets consecutive misses and transitions to healthy;
   any other frame does not.

2. Calling set_failed permanently transitions the component to failed; no further
   health checks, callbacks, or state transitions occur.

3. EOF on pipe → dead (from any state except failed).
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from multiprocessing.connection import wait
from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.health_dto import (
    ComponentLifecycleHandler,
    ComponentPolicy,
    ComponentStatus,
    StatusChangeContext,
)
from nomarr.helpers.time_helper import InternalSeconds, internal_s, internal_s_to_ms, to_wall_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

# Health frame prefix for parsing
HEALTH_FRAME_PREFIX = "HEALTH|"


@dataclass
class HealthMonitorConfig:
    """Configuration for HealthMonitorService."""

    monitor_poll_timeout_s: float = 1.0  # Timeout for pipe polling
    history_snapshot_interval_s: int = 30  # Seconds between DB history writes


@dataclass
class _ComponentState:
    """Internal state tracking for a monitored component."""

    handler: ComponentLifecycleHandler
    pipe_conn: Any
    policy: ComponentPolicy
    status: ComponentStatus = "pending"
    last_frame_time: InternalSeconds = field(default_factory=internal_s)
    consecutive_misses: int = 0
    startup_deadline: InternalSeconds | None = None
    recovery_deadline: InternalSeconds | None = None
    reported_recover_for_s: float | None = None


class HealthMonitorService:
    """
    Health monitor that owns component status registry.

    Uses a single consolidated monitor thread to:
    - Poll all pipes for health frames using multiprocessing.connection.wait()
    - Check startup timeouts, staleness, and recovery deadlines
    - Emit status change callbacks to handlers

    Key design:
    - Owns status registry; domain owns restart/backoff/failure decisions
    - Never calls Process/Thread lifecycle methods
    - Never holds Process/Thread references (tracks by component_id string)
    - DB writes are history-only and best-effort
    - Calling set_failed permanently transitions the component to failed;
      no further health checks, callbacks, or state transitions occur.
    """

    def __init__(self, cfg: HealthMonitorConfig, db: Database | None = None):
        """
        Initialize health monitor.

        Args:
            cfg: Health monitor configuration
            db: Optional database for history snapshots (can be None to disable)
        """
        self.cfg = cfg
        self.db = db

        # Component state: component_id -> _ComponentState
        self._components: dict[str, _ComponentState] = {}

        # Threading
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._history_thread: threading.Thread | None = None

    # ----------------------------- Registration ------------------------------

    def register_component(
        self,
        component_id: str,
        handler: ComponentLifecycleHandler,
        pipe_conn: Any,
        policy: ComponentPolicy | None = None,
    ) -> None:
        """
        Register a component to monitor.

        Args:
            component_id: Unique component identifier (e.g., "worker:tag:0")
            handler: Lifecycle handler to receive callbacks
            pipe_conn: Parent end of the pipe (read-only)
            policy: Monitoring policy (uses defaults if None)
        """
        if policy is None:
            policy = ComponentPolicy()

        now = internal_s()
        state = _ComponentState(
            handler=handler,
            pipe_conn=pipe_conn,
            policy=policy,
            status="pending",
            last_frame_time=now,
            consecutive_misses=0,
            startup_deadline=InternalSeconds(now.value + int(policy.startup_timeout_s)),
            recovery_deadline=None,
            reported_recover_for_s=None,
        )

        with self._lock:
            # Reject re-registration of failed components
            existing = self._components.get(component_id)
            if existing and existing.status == "failed":
                logger.warning(
                    "[HealthMonitor] Cannot re-register failed component: %s",
                    component_id,
                )
                return

            self._components[component_id] = state

        logger.debug("[HealthMonitor] Registered component: %s", component_id)

    def unregister_component(self, component_id: str) -> None:
        """
        Unregister a component.

        Closes pipe and removes from monitoring.

        Args:
            component_id: Component to unregister
        """
        with self._lock:
            state = self._components.pop(component_id, None)
            if state:
                with contextlib.suppress(Exception):
                    state.pipe_conn.close()

        logger.debug("[HealthMonitor] Unregistered component: %s", component_id)

    def set_failed(self, component_id: str) -> None:
        """
        Mark a component as permanently failed.

        Calling set_failed permanently transitions the component to failed;
        no further health checks, callbacks, or state transitions occur.

        This is terminal and idempotent.

        Args:
            component_id: Component to mark as failed
        """
        with self._lock:
            state = self._components.get(component_id)
            if not state:
                return
            if state.status == "failed":
                return  # Already failed, idempotent

            old_status = state.status
            state.status = "failed"
            state.recovery_deadline = None  # Clear any recovery
            handler = state.handler

        # Callback outside lock
        if old_status != "failed":
            logger.info("[HealthMonitor] %s: %s -> failed (domain set)", component_id, old_status)
            self._emit_status_change(component_id, old_status, "failed", handler, state)

    def get_component_ids(self) -> list[str]:
        """Get list of all registered component IDs."""
        with self._lock:
            return list(self._components.keys())

    # ------------------------------ Status API -------------------------------

    def get_status(self, component_id: str) -> ComponentStatus | None:
        """
        Get current status for a component.

        Args:
            component_id: Component identifier

        Returns:
            Status if known, None if component not registered
        """
        with self._lock:
            state = self._components.get(component_id)
            return state.status if state else None

    def get_all_statuses(self) -> dict[str, ComponentStatus]:
        """Get all component statuses."""
        with self._lock:
            return {cid: state.status for cid, state in self._components.items()}

    # ---------------------------- Lifecycle ----------------------------------

    def start(self) -> None:
        """Start health monitoring background threads."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            logger.warning("[HealthMonitor] Already running")
            return

        self._stop_event.clear()

        # Start consolidated monitor thread
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="HealthMonitor",
        )
        self._monitor_thread.start()

        # Start history writer
        self._history_thread = threading.Thread(
            target=self._history_write_loop,
            daemon=True,
            name="HealthHistoryWriter",
        )
        self._history_thread.start()

        logger.info("[HealthMonitor] Started")

    def stop(self) -> None:
        """Stop health monitoring background threads."""
        if not self._monitor_thread:
            return

        logger.info("[HealthMonitor] Stopping...")
        self._stop_event.set()

        # Close all pipes
        with self._lock:
            for state in self._components.values():
                with contextlib.suppress(Exception):
                    state.pipe_conn.close()

        if self._monitor_thread:
            self._monitor_thread.join(timeout=2)
        if self._history_thread:
            self._history_thread.join(timeout=2)

        logger.info("[HealthMonitor] Stopped")

    # ------------------------- Monitor Loop ----------------------------------

    def _monitor_loop(self) -> None:
        """
        Consolidated monitoring loop.

        Polls all pipes and checks deadlines/staleness in a single thread.
        """
        last_staleness_check = internal_s()

        while not self._stop_event.is_set():
            now = internal_s()

            # Get current pipes snapshot
            with self._lock:
                pipe_map = {
                    state.pipe_conn: cid
                    for cid, state in self._components.items()
                    if state.status != "failed"  # Don't monitor failed
                }
                pipes = list(pipe_map.keys())

            if not pipes:
                time.sleep(self.cfg.monitor_poll_timeout_s)
                continue

            # Wait for any pipe to have data
            try:
                ready = wait(pipes, timeout=self.cfg.monitor_poll_timeout_s)
            except (OSError, ValueError):
                # Pipe closed or invalid during wait
                ready = []

            # Process ready pipes
            for conn in ready:
                component_id = pipe_map.get(conn)
                if not component_id:
                    continue
                self._read_pipe(component_id, conn)

            # Periodic staleness check (every ~1s based on poll timeout)
            now = internal_s()
            if now.value - last_staleness_check.value >= 1:
                self._check_all_deadlines(now)
                last_staleness_check = now

    def _read_pipe(self, component_id: str, conn: Any) -> None:
        """Read and process data from a pipe."""
        try:
            data = conn.recv()
            self._handle_frame(component_id, data)
        except EOFError:
            self._handle_pipe_closed(component_id)
        except OSError:
            self._handle_pipe_closed(component_id)

    def _handle_frame(self, component_id: str, data: Any) -> None:
        """Process a received health frame."""
        if not isinstance(data, str) or not data.startswith(HEALTH_FRAME_PREFIX):
            return

        try:
            json_str = data[len(HEALTH_FRAME_PREFIX) :]
            frame = json.loads(json_str)
            reported_status = frame.get("status")
            recover_for_s = frame.get("recover_for_s")

            if reported_status == "healthy":
                self._transition_to_healthy(component_id)
            elif reported_status == "recovering":
                self._transition_to_recovering(component_id, recover_for_s)
            # Other statuses in frame are ignored (only healthy resets misses)

        except json.JSONDecodeError:
            logger.warning("Dropped malformed HEALTH frame from %s", component_id)

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
            if not state or state.status == "failed":
                return

            old_status = state.status
            state.status = "dead"
            state.recovery_deadline = None
            handler = state.handler

        logger.debug("[HealthMonitor] %s: %s -> dead (pipe closed)", component_id, old_status)
        self._emit_status_change(component_id, old_status, "dead", handler, state)

    def _check_all_deadlines(self, now: InternalSeconds) -> None:
        """Check startup timeouts, staleness, and recovery deadlines."""
        # Collect state changes to emit outside lock
        changes: list[tuple[str, ComponentStatus, ComponentStatus, ComponentLifecycleHandler, _ComponentState]] = []

        with self._lock:
            for component_id, state in self._components.items():
                if state.status == "failed" or state.status == "dead":
                    continue  # Don't check failed/dead

                change = self._check_component_deadline(component_id, state, now)
                if change:
                    changes.append(change)

        # Emit callbacks outside lock
        for component_id, old_status, new_status, handler, state in changes:
            self._emit_status_change(component_id, old_status, new_status, handler, state)

    def _check_component_deadline(
        self, component_id: str, state: _ComponentState, now: InternalSeconds
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
                elif state.status == "healthy":
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
            logger.error("[HealthMonitor] Handler error on status change: %s", e)

    # ------------------------- History Writer --------------------------------

    def _history_write_loop(self) -> None:
        """Periodically write status snapshots to DB for history."""
        while not self._stop_event.is_set():
            if self.db:
                self._write_history_snapshot()

            # Sleep in small intervals for faster shutdown
            for _ in range(self.cfg.history_snapshot_interval_s):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def _write_history_snapshot(self) -> None:
        """Write current statuses to DB for history/diagnostics.

        This is write-only and best-effort. Failures do not affect health decisions.
        """
        if not self.db:
            return

        try:
            with self._lock:
                snapshot = [(cid, state.status, state.last_frame_time) for cid, state in self._components.items()]

            for component_id, status, last_time in snapshot:
                try:
                    # Convert monotonic time to wall-clock for DB storage
                    wall_ms = to_wall_ms(internal_s_to_ms(last_time))
                    self.db.health.update_health_snapshot(
                        component_id=component_id,
                        status=status,
                        timestamp=wall_ms.value,
                    )
                except Exception as e:
                    logger.debug("[HealthMonitor] History write failed for %s: %s", component_id, e)

        except Exception as e:
            logger.debug("[HealthMonitor] History snapshot failed: %s", e)
