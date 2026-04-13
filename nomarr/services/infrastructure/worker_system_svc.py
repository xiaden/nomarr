"""Discovery-worker system service with admission control and restart handling."""

from __future__ import annotations

import logging
import threading
import time
from multiprocessing import Event, Pipe
from typing import TYPE_CHECKING, Any, cast

from nomarr.components.ml.resources.ml_capacity_probe_comp import CapacityEstimate, get_or_run_capacity_probe
from nomarr.components.ml.resources.ml_tier_selection_comp import (
    TIER_CONFIGS,
    ExecutionTier,
    TierSelection,
    select_execution_tier,
)
from nomarr.components.ml.resources.ml_vram_coordinator_comp import release_worker_promises
from nomarr.components.platform.resource_monitor_comp import check_nvidia_gpu_capability
from nomarr.components.workers import should_restart_worker
from nomarr.components.workers.worker_discovery_comp import cleanup_stale_claims, release_claims_for_worker
from nomarr.helpers.dto.health_dto import (
    ComponentLifecycleHandler,
    ComponentPolicy,
    ComponentStatus,
    StatusChangeContext,
)
from nomarr.helpers.time_helper import now_ms
from nomarr.services.infrastructure.pipeline_svc import LibraryPipelineService
from nomarr.services.infrastructure.workers.discovery_worker import DiscoveryWorker, create_discovery_worker

if TYPE_CHECKING:
    from nomarr.helpers.dto.processing_dto import ProcessorConfig
    from nomarr.persistence.db import Database
    from nomarr.services.infrastructure.health_monitor_svc import HealthMonitorService

logger = logging.getLogger(__name__)
DEFAULT_HEARTBEAT_TIMEOUT_MS = 30_000
DEFAULT_WORKER_POLICY = ComponentPolicy(
    startup_timeout_s=60.0,
    staleness_interval_s=9.0,
    max_consecutive_misses=3,
    min_recovery_s=5.0,
    max_recovery_s=120.0,
)
WORKER_STAGGER_DELAY_S = 2.0


class WorkerSystemService(ComponentLifecycleHandler):
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
        if not db.hosts or not db.password:
            msg = "Database hosts and password required for worker system"
            raise ValueError(msg)
        self._db_hosts: str = db.hosts
        self._db_password: str = db.password
        self._workers: list[DiscoveryWorker] = []
        self._stop_event = Event()
        self._started = False
        self._pending_restart_timers: dict[str, threading.Timer] = {}
        self._gpu_capable: bool | None = None
        self._capacity_estimate: CapacityEstimate | None = None
        self._tier_selection: TierSelection | None = None

    # ------------------- Resource Management ------------------

    def _check_gpu_capability(self) -> bool:
        if self._gpu_capable is None:
            self._gpu_capable = check_nvidia_gpu_capability()
            if self._gpu_capable:
                logger.info("[WorkerSystemService] GPU capability confirmed")
            else:
                logger.info("[WorkerSystemService] GPU not available, running CPU-only")
        return self._gpu_capable

    def _run_admission_control(self) -> TierSelection:
        """Determine execution tier and worker count."""
        rm_config = self.processor_config.resource_management
        if rm_config is None or not rm_config.enabled:
            logger.debug("[WorkerSystemService] Resource management disabled, using configured worker count")
            return TierSelection(
                tier=ExecutionTier.FAST_PATH,
                config=TIER_CONFIGS[ExecutionTier.FAST_PATH],
                calculated_workers=self.worker_count,
                reason="Resource management disabled",
            )
        self._check_gpu_capability()
        logger.info("[WorkerSystemService] Running capacity probe...")
        capacity_estimate = get_or_run_capacity_probe(
            db=self.db,
            models_dir=self.processor_config.models_dir,
            worker_id="worker_system_service",
            ram_detection_mode=rm_config.ram_detection_mode,
        )
        self._capacity_estimate = capacity_estimate
        if capacity_estimate.is_conservative:
            logger.warning("[WorkerSystemService] Using conservative capacity estimates (probe failed or timed out)")
        tier_selection = select_execution_tier(
            capacity_estimate=capacity_estimate,
            vram_budget_mb=rm_config.vram_budget_mb,
            ram_budget_mb=rm_config.ram_budget_mb,
            config_max_workers=self.worker_count,
        )
        self._tier_selection = tier_selection
        logger.info(
            "[WorkerSystemService] Tier selection: %s (workers=%d)",
            tier_selection.reason,
            tier_selection.calculated_workers,
        )
        return tier_selection

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
            logger.debug(
                "[WorkerSystemService] Failed to release VRAM promises for dead worker %s", component_id, exc_info=True
            )
        if self._stop_event.is_set():
            logger.info("[WorkerSystemService] Worker %s stopped gracefully, not restarting", component_id)
            return
        existing_timer = self._pending_restart_timers.pop(component_id, None)
        if existing_timer:
            existing_timer.cancel()
            logger.debug("[WorkerSystemService] Cancelled existing restart timer for %s", component_id)
        restart_state = cast(
            "dict[str, Any] | None",
            self.db.worker_restart_policy.component_id.get(component_id),
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
                self.db.worker_restart_policy.component_id.upsert(
                    [
                        {
                            "component_id": component_id,
                            "restart_count": 1,
                            "last_restart_wall_ms": timestamp,
                            "failed_at_wall_ms": None,
                            "failure_reason": None,
                            "updated_at_wall_ms": timestamp,
                        }
                    ],
                    match_field="component_id",
                )
            else:
                self.db.worker_restart_policy.component_id.update(
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
            self.db.worker_restart_policy.component_id.upsert(
                [
                    {
                        "component_id": component_id,
                        "restart_count": 0,
                        "last_restart_wall_ms": None,
                        "failed_at_wall_ms": timestamp,
                        "failure_reason": failure_reason,
                        "updated_at_wall_ms": timestamp,
                    }
                ],
                match_field="component_id",
            )
        else:
            self.db.worker_restart_policy.component_id.update(
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
        self._pending_restart_timers.pop(component_id, None)
        if self._stop_event.is_set():
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
                stop_event=self._stop_event,
                health_pipe=child_conn,
                execution_tier=self._tier_selection.tier if self._tier_selection else 0,
                prefer_gpu=self._tier_selection.config.prefer_gpu if self._tier_selection else True,
            )
            new_worker.start()
            child_conn.close()
            if self.health_monitor:
                self.health_monitor.register_component(new_worker.worker_id, self, parent_conn)
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

    # ---------------------------- Control Methods ----------------------------

    def is_worker_system_enabled(self) -> bool:
        """Return whether the worker system is globally enabled."""
        meta = cast("dict[str, Any] | None", self.db.meta.key.get("worker_enabled"))
        if meta is None:
            return self.default_enabled
        return cast("str | None", meta.get("value")) == "true"

    def enable_worker_system(self) -> None:
        """Enable worker system globally (sets worker_enabled=true in DB meta)."""
        self.db.meta.key.upsert([{"key": "worker_enabled", "value": "true"}], match_field="key")
        logger.info("[WorkerSystemService] Worker system globally enabled")

    def disable_worker_system(self) -> None:
        """Disable worker system globally (sets worker_enabled=false in DB meta)."""
        self.db.meta.key.upsert([{"key": "worker_enabled", "value": "false"}], match_field="key")
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
        self._stop_event.clear()
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
            stop_event=self._stop_event,
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
        logger.info("[WorkerSystemService] Stopping %d worker(s)", len(self._workers))
        for component_id, timer in list(self._pending_restart_timers.items()):
            timer.cancel()
            logger.debug("[WorkerSystemService] Cancelled pending restart timer for %s", component_id)
        self._pending_restart_timers.clear()
        self._stop_event.set()
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
                logger.debug(
                    "[WorkerSystemService] Failed to release VRAM promises for worker %s",
                    worker.worker_id,
                    exc_info=True,
                )
        self._workers.clear()
        self._started = False
        logger.info("[WorkerSystemService] All workers stopped")

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
