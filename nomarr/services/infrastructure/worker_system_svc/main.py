"""Main WorkerSystemService class — assembles mixins into the public interface."""

from __future__ import annotations

import logging
import threading
import time
from multiprocessing import Event, Pipe
from typing import TYPE_CHECKING, Any, cast

from nomarr.components.ml.resources.ml_capacity_probe_comp import CapacityEstimate
from nomarr.components.ml.resources.ml_tier_selection_comp import (
    ExecutionTier,
    TierSelection,
)
from nomarr.components.ml.resources.ml_vram_coordinator_comp import release_worker_promises
from nomarr.components.workers.worker_discovery_comp import cleanup_stale_claims
from nomarr.helpers.dto.health_dto import (
    ComponentLifecycleHandler,
    ComponentStatus,
    StatusChangeContext,
)
from nomarr.services.infrastructure.workers.discovery_worker import (
    DiscoveryWorker,
    create_discovery_worker,
)

from ._helpers import DEFAULT_HEARTBEAT_TIMEOUT_MS, DEFAULT_WORKER_POLICY, WORKER_STAGGER_DELAY_S
from .gpu_admission_ops import GpuAdmissionOpsMixin
from .worker_death_ops import WorkerDeathOpsMixin

if TYPE_CHECKING:
    from nomarr.helpers.dto.processing_dto import ProcessorConfig
    from nomarr.persistence.db import Database
    from nomarr.services.infrastructure.health_monitor_svc import HealthMonitorService
    from nomarr.services.infrastructure.pipeline_svc import LibraryPipelineService

logger = logging.getLogger(__name__)


class WorkerSystemService(WorkerDeathOpsMixin, GpuAdmissionOpsMixin, ComponentLifecycleHandler):
    """Manage discovery workers, admission control, and restart policy."""

    def __init__(
        self,
        db: Database,
        processor_config: ProcessorConfig,
        pipeline_svc: LibraryPipelineService,
        health_monitor: HealthMonitorService | None = None,
        worker_count: int = 1,
        default_enabled: bool = True,
    ) -> None:
        """Initialize worker system service."""
        self.db = db
        self.processor_config = processor_config
        self.pipeline_svc = pipeline_svc
        self.health_monitor = health_monitor
        self.worker_count = worker_count
        self.default_enabled = default_enabled
        if self.health_monitor is not None:
            self.health_monitor.set_pipeline_callback(self.pipeline_svc.trigger_calibration)
            self.health_monitor.set_idle_callback(self._on_worker_idle)
        if not db.hosts or not db.password:
            msg = "Database hosts and password required for worker system"
            raise ValueError(msg)
        self._db_hosts: str = db.hosts
        self._db_password: str = db.password
        self._workers: list[DiscoveryWorker] = []
        self._shutting_down: bool = False
        self._started = False
        self._pending_restart_timers: dict[str, threading.Timer] = {}
        self._gpu_capable: bool | None = None
        self._capacity_estimate: CapacityEstimate | None = None
        self._tier_selection: TierSelection | None = None
        self._idle_workers: set[str] = set()
        self._promotion_suppressed: bool = False

    # ------------------- ComponentLifecycleHandler Protocol ------------------

    def on_status_change(
        self,
        component_id: str,
        old_status: ComponentStatus,
        new_status: ComponentStatus,
        context: StatusChangeContext,
    ) -> None:
        """Handle a health-monitor status transition for a worker."""
        logger.debug(
            "[WorkerSystemService] %s: %s -> %s (misses=%d)",
            component_id,
            old_status,
            new_status,
            context.consecutive_misses,
        )
        if new_status == "dead":
            self._handle_worker_death(component_id)
        elif new_status == "unhealthy":
            logger.warning(
                "[WorkerSystemService] Worker %s unhealthy (%d misses)", component_id, context.consecutive_misses
            )
        elif new_status == "healthy" and old_status == "pending":
            self._reset_restart_count(component_id)

    def _on_worker_idle(self, worker_id: str, is_idle: bool) -> None:
        """Handle idle/active state transitions from worker processes.

        When all workers report idle and promotion hasn't been suppressed,
        dispatches a single idle vector promotion task in a daemon thread.
        """
        if is_idle:
            self._idle_workers.add(worker_id)
        else:
            self._idle_workers.discard(worker_id)
            self._promotion_suppressed = False

        total_workers = len(self._workers)
        if total_workers == 0:
            return

        all_idle = len(self._idle_workers) >= total_workers
        if all_idle and not self._promotion_suppressed:
            self._promotion_suppressed = True
            self._dispatch_idle_promotion()

    def _dispatch_idle_promotion(self) -> None:
        """Dispatch a single idle vector promotion task."""
        from nomarr.workflows.platform.idle_promotion_vectors_wf import (
            idle_promotion_vectors_workflow as run_idle_promotion,
        )

        def _promotion_wrapper() -> None:
            try:
                promoted = run_idle_promotion(self.db, "worker_system", str(self.processor_config.models_dir))
                logger.info("[WorkerSystemService] Idle promotion complete: %d promoted", promoted)
            except Exception:
                logger.exception("[WorkerSystemService] Idle promotion failed")

        thread = threading.Thread(target=_promotion_wrapper, daemon=True, name="VecPromo-System")
        thread.start()
        logger.info("[WorkerSystemService] All workers idle — dispatching vector promotion")

    # ---------------------------- Control Methods ----------------------------

    def is_worker_system_enabled(self) -> bool:
        """Return whether the worker system is globally enabled."""
        meta = cast("dict[str, Any] | None", self.db.app.get_config_option("worker_enabled"))
        if meta is None:
            return self.default_enabled
        return cast("str | None", meta.get("value")) == "true"

    def enable_worker_system(self) -> None:
        """Enable worker system globally (sets worker_enabled=true in DB meta)."""
        self.db.app.update_config_option("worker_enabled", {"value": "true"})
        logger.info("[WorkerSystemService] Worker system globally enabled")

    def disable_worker_system(self) -> None:
        """Disable worker system globally (sets worker_enabled=false in DB meta)."""
        self.db.app.update_config_option("worker_enabled", {"value": "false"})
        logger.info("[WorkerSystemService] Worker system globally disabled")

    # ---------------------------- Worker Lifecycle ----------------------------

    def start_all_workers(self) -> None:
        """Start worker processes based on admission control and tier selection."""
        if self._started:
            logger.debug("[WorkerSystemService] Workers already started")
            return
        if not self.is_worker_system_enabled():
            logger.info("[WorkerSystemService] Worker system disabled, not starting")
            return
        tier_selection = self._run_admission_control()
        if tier_selection.tier == ExecutionTier.REFUSE:
            logger.error(
                "[WorkerSystemService] Tier 4 (Refuse): %s. No workers will be started.", tier_selection.reason
            )
            self._started = True
            return
        actual_worker_count = tier_selection.calculated_workers
        logger.debug(
            "[WorkerSystemService] Starting %d discovery worker(s) at %s",
            actual_worker_count,
            tier_selection.config.description,
        )
        removed_claims = self.cleanup_stale_claims()
        if removed_claims > 0:
            logger.info("[WorkerSystemService] Cleaned up %d stale claim(s) from previous session", removed_claims)
        started_workers: list[str] = []
        for i in range(actual_worker_count):
            if i > 0:
                time.sleep(WORKER_STAGGER_DELAY_S)
            worker = self._spawn_worker(i, tier_selection)
            started_workers.append(f"worker:tag:{i} (pid={worker.pid})")
        logger.info("[WorkerSystemService] Started %d worker(s): %s", actual_worker_count, ", ".join(started_workers))
        self._started = True

    def _spawn_worker(self, index: int, tier_selection: TierSelection) -> DiscoveryWorker:
        parent_conn, child_conn = Pipe(duplex=False)
        worker = create_discovery_worker(
            worker_index=index,
            db_hosts=self._db_hosts,
            db_password=self._db_password,
            processor_config=self.processor_config,
            stop_event=Event(),
            health_pipe=child_conn,
            execution_tier=tier_selection.tier,
            prefer_gpu=tier_selection.config.prefer_gpu,
        )
        worker.start()
        self._workers.append(worker)
        child_conn.close()
        if self.health_monitor:
            self.health_monitor.register_component(
                component_id=worker.worker_id,
                handler=self,
                pipe_conn=parent_conn,
                policy=DEFAULT_WORKER_POLICY,
            )
        return worker

    def stop_all_workers(self, timeout: float = 10.0) -> None:
        """Stop all worker processes gracefully."""
        if not self._workers:
            logger.debug("[WorkerSystemService] No workers to stop")
            return
        self._shutting_down = True
        logger.info("[WorkerSystemService] Stopping %d worker(s)", len(self._workers))
        for component_id, timer in list(self._pending_restart_timers.items()):
            timer.cancel()
            logger.debug("[WorkerSystemService] Cancelled pending restart timer for %s", component_id)
        self._pending_restart_timers.clear()
        for worker in self._workers:
            worker.stop()
        if self.health_monitor:
            for worker in self._workers:
                self.health_monitor.unregister_component(worker.worker_id)
        for worker in self._workers:
            worker.join(timeout=timeout)
            if worker.is_alive():
                logger.warning(
                    "[WorkerSystemService] Worker %s (pid=%s) did not stop gracefully, terminating",
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
        for worker in self._workers:
            try:
                release_worker_promises(self.db, worker.worker_id)
            except Exception:
                logger.warning(
                    "[WorkerSystemService] Failed to release VRAM promises for worker %s",
                    worker.worker_id,
                    exc_info=True,
                )
        self._workers.clear()
        self._started = False
        logger.info("[WorkerSystemService] All workers stopped")

    def add_workers(self, count: int) -> None:
        """Add worker processes to the pool dynamically.

        Args:
            count: Number of workers to add. Must be > 0.

        Edge cases handled:
            - count <= 0: warning, no-op
            - No tier selection exists: warning, recommends start_all_workers()
            - Pool is empty: spawns workers without re-running admission control
        """
        if count <= 0:
            logger.warning("[WorkerSystemService] add_workers called with count=%d (must be > 0)", count)
            return
        if self._tier_selection is None:
            logger.warning(
                "[WorkerSystemService] No tier selection exists yet - start_all_workers must be used instead"
            )
            return
        if not self._workers:
            logger.info("[WorkerSystemService] Pool empty, spawning %d worker(s) with existing tier selection", count)
        else:
            logger.info("[WorkerSystemService] Adding %d worker(s) to pool of %d", count, len(self._workers))
        start_index = len(self._workers)
        for i in range(count):
            worker = self._spawn_worker(start_index + i, self._tier_selection)
            logger.info(
                "[WorkerSystemService] Added worker %s (pid=%s, index=%d)",
                worker.worker_id,
                worker.pid,
                start_index + i,
            )
        logger.info("[WorkerSystemService] Added %d worker(s), total=%d", count, len(self._workers))

    def remove_workers(self, count: int) -> None:
        """Remove worker processes from the pool dynamically.

        Args:
            count: Number of workers to remove from the end of the pool. Must be > 0.

        Edge cases handled:
            - count <= 0: warning, no-op
            - count >= len(self._workers): stops all workers via stop_all_workers()
        """
        if count <= 0:
            logger.warning("[WorkerSystemService] remove_workers called with count=%d (must be > 0)", count)
            return
        if count >= len(self._workers):
            logger.warning(
                "[WorkerSystemService] remove_workers(%d) >= current pool size (%d) - stopping all workers",
                count,
                len(self._workers),
            )
            self.stop_all_workers()
            return
        logger.info("[WorkerSystemService] Removing %d worker(s) from pool of %d", count, len(self._workers))
        workers_to_remove = self._workers[-count:]
        for worker in workers_to_remove:
            worker.stop()
        for worker in workers_to_remove:
            worker.join(timeout=2.0)
            if worker.is_alive():
                logger.warning(
                    "[WorkerSystemService] Worker %s (pid=%s) did not stop gracefully during scale-down",
                    worker.worker_id,
                    worker.pid,
                )
        if self.health_monitor:
            for worker in workers_to_remove:
                try:
                    self.health_monitor.unregister_component(worker.worker_id)
                except Exception:
                    logger.warning(
                        "[WorkerSystemService] Failed to unregister worker %s from health monitor",
                        worker.worker_id,
                        exc_info=True,
                    )
        for worker in workers_to_remove:
            self._workers.remove(worker)
        logger.info("[WorkerSystemService] Removed %d worker(s), remaining=%d", count, len(self._workers))

    def get_worker_count(self) -> int:
        """Return the current number of workers in the pool."""
        return len(self._workers)

    def is_running(self) -> bool:
        """Check if any workers are running."""
        return self._started and any(worker.is_alive() for worker in self._workers)

    # ---------------------------- Status Methods ----------------------------

    def get_workers_status(self) -> dict[str, Any]:
        """Get worker-system status."""
        alive_workers = [worker for worker in self._workers if worker.is_alive()]
        statuses = self.health_monitor.get_all_statuses() if self.health_monitor else {}
        return {
            "enabled": self.is_worker_system_enabled(),
            "started": self._started,
            "worker_count": self.worker_count,
            "running": len(alive_workers),
            "tier": self._tier_selection.tier.name if self._tier_selection else None,
            "tier_reason": self._tier_selection.reason if self._tier_selection else None,
            "gpu_capable": self._gpu_capable,
            "workers": [
                {
                    "id": worker.worker_id,
                    "pid": worker.pid,
                    "alive": worker.is_alive(),
                    "status": statuses.get(worker.worker_id, "pending"),
                }
                for worker in self._workers
            ],
        }

    def get_resource_status(self) -> dict[str, Any]:
        """Get resource-management status."""
        return {
            "gpu_capable": self._gpu_capable,
            "tier": self._tier_selection.tier.name if self._tier_selection else None,
            "tier_description": self._tier_selection.config.description if self._tier_selection else None,
            "calculated_workers": self._tier_selection.calculated_workers if self._tier_selection else None,
            "reason": self._tier_selection.reason if self._tier_selection else None,
            "capacity_estimate": {
                "model_set_hash": self._capacity_estimate.model_set_hash,
                "backbone_vram_mb": self._capacity_estimate.measured_backbone_vram_mb,
                "worker_ram_mb": self._capacity_estimate.estimated_worker_ram_mb,
                "is_conservative": self._capacity_estimate.is_conservative,
            }
            if self._capacity_estimate
            else None,
        }

    # ---------------------------- Claim Cleanup ----------------------------

    def cleanup_stale_claims(self) -> int:
        """Remove stale or orphaned worker claims."""
        return cleanup_stale_claims(self.db, DEFAULT_HEARTBEAT_TIMEOUT_MS)
