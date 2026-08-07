"""Mixin for worker death handling, restart policy, and drain logic."""

from __future__ import annotations

import logging
import threading
from multiprocessing import Event, Pipe
from typing import TYPE_CHECKING, Any, cast

from nomarr.components.ml.resources.ml_vram_coordinator_comp import release_worker_promises
from nomarr.components.workers import should_restart_worker
from nomarr.components.workers.worker_discovery_comp import release_claims_for_worker
from nomarr.helpers.time_helper import now_ms

from ._helpers import DEFAULT_WORKER_POLICY

if TYPE_CHECKING:
    from nomarr.components.ml.resources.ml_tier_selection_comp import TierSelection
    from nomarr.helpers.dto.health_dto import ComponentLifecycleHandler
    from nomarr.helpers.dto.processing_dto import ProcessorConfig
    from nomarr.persistence.db import Database
    from nomarr.services.infrastructure.health_monitor_svc import HealthMonitorService
    from nomarr.services.infrastructure.workers.discovery_worker import DiscoveryWorker

logger = logging.getLogger(__name__)


class WorkerDeathOpsMixin:
    """Mixin for worker death handling, restart decisions, and drain/restart logic.

    Requires the host class to provide:
    - ``self.db`` (Database)
    - ``self.processor_config`` (ProcessorConfig)
    - ``self.health_monitor`` (HealthMonitorService | None)
    - ``self._workers`` (list[DiscoveryWorker])
    - ``self._shutting_down`` (bool)
    - ``self._pending_restart_timers`` (dict[str, threading.Timer])
    - ``self._db_hosts`` (str)
    - ``self._db_password`` (str)
    - ``self._tier_selection`` (TierSelection | None)
    - ``self.is_worker_system_enabled()`` (bool)
    """

    db: Database
    processor_config: ProcessorConfig
    health_monitor: HealthMonitorService | None
    _workers: list[DiscoveryWorker]
    _shutting_down: bool
    _pending_restart_timers: dict[str, threading.Timer]
    _db_hosts: str
    _db_password: str
    _tier_selection: TierSelection | None

    def is_worker_system_enabled(self) -> bool:
        """Stub — implemented by the main class."""
        raise NotImplementedError

    def _reset_restart_count(self, component_id: str) -> None:
        """Reset the restart counter once a worker has confirmed healthy after starting.

        A worker that starts and runs successfully should not carry forward crash
        counts from earlier sessions or restart cycles.
        """
        try:
            restart_state = self.db.app.get_worker_restart_policy(component_id)
            if isinstance(restart_state, dict) and int(restart_state.get("restart_count", 0)) > 0:
                timestamp = now_ms().value
                with self.db.app.transaction():
                    self.db.app.update_worker_restart_policy(
                        component_id,
                        {
                            "restart_count": 0,
                            "last_restart_wall_ms": None,
                            "updated_at_wall_ms": timestamp,
                        },
                    )
                logger.info("[WorkerSystemService] Reset restart count for %s (worker confirmed healthy)", component_id)
        except Exception:
            logger.warning("[WorkerSystemService] Failed to reset restart count for %s", component_id, exc_info=True)

    def _handle_worker_death(self, component_id: str) -> None:
        released_file_ids = release_claims_for_worker(self.db, component_id)
        if released_file_ids:
            logger.info(
                "[WorkerSystemService] Released %d claim(s) for dead worker %s - files will be reprocessed",
                len(released_file_ids),
                component_id,
            )
        try:
            release_worker_promises(self.db, component_id)
        except Exception:
            logger.warning(
                "[WorkerSystemService] Failed to release VRAM promises for dead worker %s", component_id, exc_info=True
            )
        if self._shutting_down:
            logger.info("[WorkerSystemService] Worker %s stopped gracefully, not restarting", component_id)
            return
        existing_timer = self._pending_restart_timers.pop(component_id, None)
        if existing_timer:
            existing_timer.cancel()
            logger.debug("[WorkerSystemService] Cancelled existing restart timer for %s", component_id)
        restart_state = cast(
            "dict[str, Any] | None",
            self.db.app.get_worker_restart_policy(component_id),
        )
        restart_count = int(restart_state.get("restart_count", 0)) if restart_state is not None else 0
        last_restart_wall_ms = (
            cast("int | None", restart_state.get("last_restart_wall_ms")) if restart_state is not None else None
        )
        decision = should_restart_worker(restart_count, last_restart_wall_ms)
        logger.info(
            "[WorkerSystemService] Restart decision for %s: %s (reason: %s)",
            component_id,
            decision.action,
            decision.reason,
        )
        if decision.action == "restart":
            timestamp = now_ms().value
            if restart_state is None:
                with self.db.app.transaction():
                    self.db.app.upsert_worker_restart_policy(
                        component_id,
                        {
                            "restart_count": 1,
                            "last_restart_wall_ms": timestamp,
                            "failed_at_wall_ms": None,
                            "failure_reason": None,
                            "updated_at_wall_ms": timestamp,
                        },
                    )
            else:
                with self.db.app.transaction():
                    self.db.app.update_worker_restart_policy(
                        component_id,
                        {
                            "restart_count": restart_count + 1,
                            "last_restart_wall_ms": timestamp,
                            "updated_at_wall_ms": timestamp,
                        },
                    )
            timer = threading.Timer(decision.backoff_seconds, self._restart_worker, args=(component_id,))
            self._pending_restart_timers[component_id] = timer
            timer.start()
            return
        if self.health_monitor:
            self.health_monitor.set_failed(component_id)
        failure_reason = decision.failure_reason or "Restart limit exceeded"
        timestamp = now_ms().value
        if restart_state is None:
            with self.db.app.transaction():
                self.db.app.upsert_worker_restart_policy(
                    component_id,
                    {
                        "restart_count": 0,
                        "last_restart_wall_ms": None,
                        "failed_at_wall_ms": timestamp,
                        "failure_reason": failure_reason,
                        "updated_at_wall_ms": timestamp,
                    },
                )
        else:
            with self.db.app.transaction():
                self.db.app.update_worker_restart_policy(
                    component_id,
                    {
                        "failed_at_wall_ms": timestamp,
                        "failure_reason": failure_reason,
                        "updated_at_wall_ms": timestamp,
                    },
                )
        logger.error(
            "[WorkerSystemService] Worker %s marked as permanently failed: %s", component_id, decision.failure_reason
        )

    def _drain_old_worker(self, worker: DiscoveryWorker, timeout: float) -> None:
        worker.join(timeout=timeout)
        if worker.is_alive():
            logger.warning(
                "[WorkerSystemService] Old worker %s (pid=%s) still alive before restart, terminating",
                worker.worker_id,
                worker.pid,
            )
            worker.terminate()
            worker.join(timeout=1.0)
            if worker.is_alive():
                logger.error(
                    "[WorkerSystemService] Worker %s (pid=%s) still alive after terminate(), force killing",
                    worker.worker_id,
                    worker.pid,
                )
                worker.kill()
                worker.join(timeout=0.5)

    def _restart_worker(self, component_id: str) -> None:
        from nomarr.services.infrastructure.workers.discovery_worker import create_discovery_worker

        self._pending_restart_timers.pop(component_id, None)
        if self._shutting_down:
            logger.info("[WorkerSystemService] Skipping restart for %s (shutdown in progress)", component_id)
            return
        if not self.is_worker_system_enabled():
            logger.info("[WorkerSystemService] Skipping restart for %s (worker system disabled)", component_id)
            return
        try:
            worker_index = int(component_id.split(":")[-1])
        except (ValueError, IndexError):
            logger.exception("[WorkerSystemService] Invalid component_id format: %s", component_id)
            return

        logger.info("[WorkerSystemService] Restarting worker %d", worker_index)
        try:
            old_worker: DiscoveryWorker | None = (
                self._workers[worker_index] if worker_index < len(self._workers) else None
            )
            if old_worker is not None:
                self._drain_old_worker(old_worker, timeout=2.0)
            parent_conn, child_conn = Pipe(duplex=False)
            new_worker = create_discovery_worker(
                worker_index=worker_index,
                db_hosts=self._db_hosts,
                db_password=self._db_password,
                processor_config=self.processor_config,
                stop_event=Event(),
                health_pipe=child_conn,
                execution_tier=self._tier_selection.tier if self._tier_selection else 0,
                prefer_gpu=self._tier_selection.config.prefer_gpu if self._tier_selection else True,
            )
            new_worker.start()
            child_conn.close()
            if self.health_monitor:
                self.health_monitor.register_component(
                    new_worker.worker_id,
                    cast("ComponentLifecycleHandler", self),
                    parent_conn,
                    policy=DEFAULT_WORKER_POLICY,
                )
            if worker_index < len(self._workers):
                self._workers[worker_index] = new_worker
            else:
                self._workers.append(new_worker)
            logger.info(
                "[WorkerSystemService] Worker %d restarted successfully (new_pid=%s, old_pid=%s)",
                worker_index,
                new_worker.pid,
                old_worker.pid if old_worker else None,
            )
        except Exception as exc:
            logger.error("[WorkerSystemService] Failed to restart worker %d: %s", worker_index, exc, exc_info=True)
