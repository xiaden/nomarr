"""Main HealthMonitorService class — assembles mixins into the public interface."""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
from collections.abc import Callable
from multiprocessing.connection import Connection, wait
from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.health_dto import (
    HEALTH_FRAME_PREFIX,
    PIPELINE_FRAME_PREFIX,
    ComponentLifecycleHandler,
    ComponentPolicy,
    ComponentStatus,
)
from nomarr.helpers.time_helper import InternalSeconds, internal_s, internal_s_to_ms, to_wall_ms
from nomarr.services.infrastructure.workers.discovery_worker import IDLE_FRAME_PREFIX

from ._helpers import HealthMonitorConfig, _ComponentState
from .deadline_ops import DeadlineOpsMixin
from .state_transition_ops import StateTransitionOpsMixin

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


class HealthMonitorService(StateTransitionOpsMixin, DeadlineOpsMixin):
    """Health monitor that owns component status registry.

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

    def __init__(self, cfg: HealthMonitorConfig, db: Database | None = None) -> None:
        """Initialize health monitor.

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
        self._pipeline_callback: Callable[[], None] | None = None
        self._idle_callback: Callable[[str, bool], None] | None = None

    # ----------------------------- Registration ------------------------------

    def register_component(
        self,
        component_id: str,
        handler: ComponentLifecycleHandler,
        pipe_conn: Connection,
        policy: ComponentPolicy | None = None,
    ) -> None:
        """Register a component to monitor.

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
        """Unregister a component.

        Closes pipe and removes from monitoring.

        Args:
            component_id: Component to unregister

        """
        with self._lock:
            state = self._components.pop(component_id, None)
            if state:
                with contextlib.suppress(OSError):  # Pipe may already be closed
                    state.pipe_conn.close()

        logger.debug("[HealthMonitor] Unregistered component: %s", component_id)

    def set_failed(self, component_id: str) -> None:
        """Mark a component as permanently failed.

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
        """Get current status for a component.

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

    def set_pipeline_callback(self, callback: Callable[[], None] | None) -> None:
        """Register a callback for PIPELINE pipe frames."""
        self._pipeline_callback = callback

    def set_idle_callback(self, callback: Callable[[str, bool], None] | None) -> None:
        """Register a callback for IDLE pipe frames.

        Callback receives (worker_id, is_idle).
        """
        self._idle_callback = callback

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

        logger.debug("[HealthMonitor] Started")

    def stop(self) -> None:
        """Stop health monitoring background threads."""
        if not self._monitor_thread:
            return

        logger.info("[HealthMonitor] Stopping...")
        self._stop_event.set()

        # Close all pipes
        with self._lock:
            for state in self._components.values():
                with contextlib.suppress(OSError):  # Pipe may already be closed during shutdown
                    state.pipe_conn.close()

        if self._monitor_thread:
            self._monitor_thread.join(timeout=2)
        if self._history_thread:
            self._history_thread.join(timeout=2)

        logger.info("[HealthMonitor] Stopped")

    # ------------------------- Monitor Loop ----------------------------------

    def _monitor_loop(self) -> None:
        """Consolidated monitoring loop.

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
                    if state.status not in ("failed", "dead")  # Don't monitor terminal states
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
                if not isinstance(conn, Connection):
                    continue
                component_id = pipe_map.get(conn)
                if not component_id:
                    continue
                self._read_pipe(component_id, conn)

            # Periodic staleness check (every ~1s based on poll timeout)
            now = internal_s()
            if now.value - last_staleness_check.value >= 1:
                self._check_all_deadlines(now)
                last_staleness_check = now

    def _read_pipe(self, component_id: str, conn: Connection) -> None:
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
        if not isinstance(data, str):
            return

        if data.startswith(PIPELINE_FRAME_PREFIX):
            if self._pipeline_callback is not None:
                try:
                    self._pipeline_callback()
                except Exception as exc:
                    logger.exception(
                        "[HealthMonitor] Pipeline callback error for %s: %s",
                        component_id,
                        exc,
                    )
            return

        if data.startswith(IDLE_FRAME_PREFIX):
            if self._idle_callback is not None:
                try:
                    payload = json.loads(data[len(IDLE_FRAME_PREFIX) :])
                    self._idle_callback(payload.get("worker_id", component_id), payload.get("idle", False))
                except Exception as exc:
                    logger.exception(
                        "[HealthMonitor] Idle callback error for %s: %s",
                        component_id,
                        exc,
                    )
            return

        if not data.startswith(HEALTH_FRAME_PREFIX):
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
                    self.db.app.update_health(
                        component_id,
                        {
                            "status": status,
                            "last_snapshot": wall_ms.value,
                            "created_at": wall_ms.value,
                            "snapshot_type": "history",
                        },
                    )
                except Exception as e:
                    logger.warning("[HealthMonitor] History write failed for %s: %s", component_id, e, exc_info=True)

        except Exception as e:
            logger.warning("[HealthMonitor] History snapshot failed: %s", e, exc_info=True)
