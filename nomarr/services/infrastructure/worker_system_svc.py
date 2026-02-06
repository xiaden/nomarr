"""Worker System Service - Discovery-based worker management.

Manages discovery workers that query library_files directly instead of
polling a queue. Workers claim files via worker_claims collection.

Implements ComponentLifecycleHandler protocol for HealthMonitor callbacks.
Receives status change events and decides on restart/recovery actions.

Per GPU_REFACTOR_PLAN.md:
- Implements admission control (Section 10)
- Uses tier selection for graceful degradation (Section 9)
- GPU capability gating at startup (Section 5)
"""

from __future__ import annotations

import logging
import threading
import time
from multiprocessing import Event, Pipe
from typing import TYPE_CHECKING, Any

from nomarr.components.ml.ml_capacity_probe_comp import (
    CapacityEstimate,
    get_or_run_capacity_probe,
)
from nomarr.components.ml.ml_tier_selection_comp import (
    TIER_CONFIGS,
    ExecutionTier,
    TierSelection,
    select_execution_tier,
)
from nomarr.components.platform.resource_monitor_comp import check_nvidia_gpu_capability
from nomarr.components.workers import should_restart_worker
from nomarr.components.workers.worker_discovery_comp import cleanup_stale_claims
from nomarr.helpers.dto.admin_dto import WorkerOperationResult
from nomarr.helpers.dto.health_dto import (
    ComponentLifecycleHandler,
    ComponentPolicy,
    ComponentStatus,
    StatusChangeContext,
)
from nomarr.services.infrastructure.workers.discovery_worker import (
    DiscoveryWorker,
    create_discovery_worker,
)

if TYPE_CHECKING:
    from nomarr.helpers.dto.processing_dto import ProcessorConfig
    from nomarr.persistence.db import Database
    from nomarr.services.infrastructure.health_monitor_svc import HealthMonitorService

logger = logging.getLogger(__name__)

# Default heartbeat timeout for claim cleanup (30 seconds)
DEFAULT_HEARTBEAT_TIMEOUT_MS = 30_000

# Default worker health monitoring policy
# NOTE: Worker sends heartbeats every 3s, monitor checks every 5s
# This 3s < 5s relationship provides buffer for timing jitter and prevents false unhealthy states
DEFAULT_WORKER_POLICY = ComponentPolicy(
    startup_timeout_s=60.0,  # Workers may take time to load models
    staleness_interval_s=5.0,  # Expect health frame every 5s
    max_consecutive_misses=3,  # 3 misses = 15s before dead
    min_recovery_s=5.0,
    max_recovery_s=120.0,  # Allow up to 2 min recovery for heavy operations
)

# Worker startup stagger delay (seconds between starting workers)
WORKER_STAGGER_DELAY_S = 2.0


class WorkerSystemService(ComponentLifecycleHandler):
    """Discovery-based worker system service with admission control.

    Manages worker processes that:
    1. Query library_files for files with needs_tagging=1
    2. Claim files via worker_claims collection
    3. Process files using process_file_workflow
    4. Update library_files.tagged=1 before releasing claims

    Implements GPU/CPU adaptive resource management:
    - GPU capability gating at startup
    - Capacity probe to measure resource usage
    - Tier selection for graceful degradation
    - Admission control for worker count

    Implements ComponentLifecycleHandler:
    - Registers workers with HealthMonitor (pipes + policy + callback handler)
    - Receives status change callbacks
    - Decides on restart/recovery based on status transitions
    """

    def __init__(
        self,
        db: Database,
        processor_config: ProcessorConfig,
        health_monitor: HealthMonitorService | None = None,
        worker_count: int = 1,
        default_enabled: bool = True,
    ) -> None:
        """Initialize worker system service.

        Args:
            db: Database instance
            processor_config: Configuration for the processing workflow
            health_monitor: HealthMonitor to register workers with
            worker_count: Number of worker processes to spawn (max)
            default_enabled: Default worker_enabled flag if not in DB

        """
        self.db = db
        self.processor_config = processor_config
        self.health_monitor = health_monitor
        self.worker_count = worker_count
        self.default_enabled = default_enabled

        # Get DB connection info for workers (required for subprocess connections)
        if not db.hosts or not db.password:
            msg = "Database hosts and password required for worker system"
            raise ValueError(msg)
        self._db_hosts: str = db.hosts
        self._db_password: str = db.password

        # Worker process management
        self._workers: list[DiscoveryWorker] = []
        self._stop_event = Event()
        self._started = False

        # Restart timer tracking (idempotent scheduling)
        self._pending_restart_timers: dict[str, threading.Timer] = {}  # component_id -> Timer

        # GPU/CPU adaptive resource management state
        self._gpu_capable: bool | None = None
        self._capacity_estimate: CapacityEstimate | None = None
        self._tier_selection: TierSelection | None = None

    # ------------------- Resource Management ------------------

    def _check_gpu_capability(self) -> bool:
        """Check NVIDIA GPU capability once at startup.

        Per GPU_REFACTOR_PLAN.md Section 5:
        - A container is GPU-capable iff nvidia-smi succeeds
        - Checked once at startup and cached

        Returns:
            True if GPU is available, False otherwise

        """
        if self._gpu_capable is None:
            self._gpu_capable = check_nvidia_gpu_capability()
            if self._gpu_capable:
                logger.info("[WorkerSystemService] GPU capability confirmed")
            else:
                logger.info("[WorkerSystemService] GPU not available, running CPU-only")
        return self._gpu_capable

    def _run_admission_control(self) -> TierSelection:
        """Run admission control to determine execution tier and worker count.

        Per GPU_REFACTOR_PLAN.md Section 10:
        1. Check GPU capability
        2. Wait for capacity estimate
        3. Select execution tier
        4. Calculate worker count based on tier

        Returns:
            TierSelection with tier and calculated worker count

        """
        # Get resource management config
        rm_config = self.processor_config.resource_management
        if rm_config is None or not rm_config.enabled:
            # Resource management disabled - use configured worker count
            logger.info("[WorkerSystemService] Resource management disabled, using configured worker count")

            # Return Tier 0 with configured workers
            return TierSelection(
                tier=ExecutionTier.FAST_PATH,
                config=TIER_CONFIGS[ExecutionTier.FAST_PATH],
                calculated_workers=self.worker_count,
                reason="Resource management disabled",
            )

        # Check GPU capability (result is cached in check_nvidia_gpu_capability)
        # This pre-warms the GPU capability cache for the capacity probe
        self._check_gpu_capability()

        # Run or wait for capacity probe
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

        # Select execution tier
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
        """Handle component status change (from HealthMonitor callback).

        Args:
            component_id: Worker component ID
            old_status: Previous status
            new_status: New status
            context: Additional context (consecutive_misses, recovery_deadline, etc.)

        """
        logger.info(
            "[WorkerSystemService] %s: %s -> %s (misses=%d)",
            component_id,
            old_status,
            new_status,
            context.consecutive_misses,
        )

        if new_status == "dead":
            # Check if shutdown was requested (graceful stop)
            if self._stop_event.is_set():
                logger.info("[WorkerSystemService] Worker %s stopped gracefully, not restarting", component_id)
                return

            # Cancel any existing pending restart for this component (idempotent scheduling)
            existing_timer = self._pending_restart_timers.pop(component_id, None)
            if existing_timer:
                existing_timer.cancel()
                logger.debug("[WorkerSystemService] Cancelled existing restart timer for %s", component_id)

            # Worker died unexpectedly - consult restart policy
            restart_count, last_restart_wall_ms = self.db.worker_restart_policy.get_restart_state(component_id)
            decision = should_restart_worker(restart_count, last_restart_wall_ms)

            logger.info(
                "[WorkerSystemService] Restart decision for %s: %s (reason: %s)",
                component_id,
                decision.action,
                decision.reason,
            )

            if decision.action == "restart":
                self.db.worker_restart_policy.increment_restart_count(component_id)
                # Schedule restart with backoff (non-blocking)
                timer = threading.Timer(
                    decision.backoff_seconds,
                    self._restart_worker,
                    args=(component_id,),
                )
                self._pending_restart_timers[component_id] = timer  # Track for idempotency
                timer.start()
            else:  # mark_failed
                if self.health_monitor:
                    self.health_monitor.set_failed(component_id)
                self.db.worker_restart_policy.mark_failed_permanent(
                    component_id,
                    decision.failure_reason or "Restart limit exceeded",
                )
                logger.error(
                    "[WorkerSystemService] Worker %s marked as permanently failed: %s",
                    component_id,
                    decision.failure_reason,
                )

        elif new_status == "unhealthy":
            # Worker is missing health checks but not dead yet
            logger.warning(
                "[WorkerSystemService] Worker %s unhealthy (%d misses)",
                component_id,
                context.consecutive_misses,
            )

    def _restart_worker(self, component_id: str) -> None:
        """Spawn replacement worker after backoff delay.

        This is called by threading.Timer after backoff seconds.
        Only replaces worker if system is still enabled.

        Args:
            component_id: Worker component ID (e.g., "discovery_worker_0")

        """
        # Remove timer from pending dict (already executed)
        self._pending_restart_timers.pop(component_id, None)

        # Re-check worker_enabled (user may have disabled during backoff)
        if not self.is_worker_system_enabled():
            logger.info(
                "[WorkerSystemService] Skipping restart for %s (worker system disabled)",
                component_id,
            )
            return

        # Extract worker index from component_id
        try:
            worker_index = int(component_id.split("_")[-1])
        except (ValueError, IndexError):
            logger.exception("[WorkerSystemService] Invalid component_id format: %s", component_id)
            return

        # Spawn replacement worker
        logger.info("[WorkerSystemService] Restarting worker %d", worker_index)
        try:
            # Create dedicated pipe for this worker's health telemetry
            parent_conn, child_conn = Pipe(duplex=False)

            new_worker = create_discovery_worker(
                worker_index=worker_index,
                db_hosts=self._db_hosts,
                db_password=self._db_password,
                processor_config=self.processor_config,
                stop_event=self._stop_event,
                health_pipe=child_conn,  # Pass write-end to worker
                execution_tier=self._tier_selection.tier if self._tier_selection else 0,
                prefer_gpu=self._tier_selection.config.prefer_gpu if self._tier_selection else True,
            )
            new_worker.start()

            # Close child end in parent - only the worker should have it
            child_conn.close()

            # Register with HealthMonitor
            if self.health_monitor:
                self.health_monitor.register_component(new_worker.worker_id, self, parent_conn)

            # Replace worker in list
            if worker_index < len(self._workers):
                self._workers[worker_index] = new_worker
            else:
                # Worker list shrunk? Append instead
                self._workers.append(new_worker)

            logger.info("[WorkerSystemService] Worker %d restarted successfully", worker_index)

        except Exception as e:
            logger.error(
                "[WorkerSystemService] Failed to restart worker %d: %s",
                worker_index,
                e,
                exc_info=True,
            )

    # ---------------------------- Control Methods ----------------------------

    def is_worker_system_enabled(self) -> bool:
        """Check if worker system is globally enabled.

        Returns:
            True if worker_enabled=true in DB meta, or default if not set

        """
        meta = self.db.meta.get("worker_enabled")
        if meta is None:
            return self.default_enabled
        return meta == "true"

    def enable_worker_system(self) -> None:
        """Enable worker system globally (sets worker_enabled=true in DB meta)."""
        self.db.meta.set("worker_enabled", "true")
        logger.info("[WorkerSystemService] Worker system globally enabled")

    def disable_worker_system(self) -> None:
        """Disable worker system globally (sets worker_enabled=false in DB meta)."""
        self.db.meta.set("worker_enabled", "false")
        logger.info("[WorkerSystemService] Worker system globally disabled")

    def pause_worker_system(self) -> WorkerOperationResult:
        """Pause worker system - disables processing and stops workers.

        Returns:
            WorkerOperationResult with success status

        """
        self.disable_worker_system()
        self.stop_all_workers()
        return WorkerOperationResult(
            success=True,
            message="Worker system paused",
            worker_enabled=False,
        )

    def resume_worker_system(self) -> WorkerOperationResult:
        """Resume worker system - enables processing and starts workers.

        Returns:
            WorkerOperationResult with success status

        """
        self.enable_worker_system()
        self.start_all_workers()
        return WorkerOperationResult(
            success=True,
            message="Worker system resumed",
            worker_enabled=True,
        )

    # ---------------------------- Worker Lifecycle ----------------------------

    def start_all_workers(self) -> None:
        """Start worker processes based on admission control and tier selection.

        Per GPU_REFACTOR_PLAN.md Section 10:
        - Runs admission control to determine tier and worker count
        - Tier 4 means refusal (no workers started)
        - Workers are started with stagger delays
        """
        if self._started:
            logger.debug("[WorkerSystemService] Workers already started")
            return

        if not self.is_worker_system_enabled():
            logger.info("[WorkerSystemService] Worker system disabled, not starting")
            return

        # Run admission control to determine tier and worker count
        tier_selection = self._run_admission_control()

        # Check for Tier 4 (refuse)
        if tier_selection.tier == ExecutionTier.REFUSE:
            logger.error(
                "[WorkerSystemService] Tier 4 (Refuse): %s. No workers will be started.",
                tier_selection.reason,
            )
            # Mark as started but with 0 workers
            self._started = True
            return

        actual_worker_count = tier_selection.calculated_workers
        logger.info(
            "[WorkerSystemService] Starting %d discovery worker(s) at %s",
            actual_worker_count,
            tier_selection.config.description,
        )

        # Clean up stale claims from previous runs before starting workers
        removed_claims = self.cleanup_stale_claims()
        if removed_claims > 0:
            logger.info(
                "[WorkerSystemService] Cleaned up %d stale claim(s) from previous session",
                removed_claims,
            )

        # Clear stop event for new workers
        self._stop_event.clear()

        # Create and start workers with stagger delay, registering each with HealthMonitor
        for i in range(actual_worker_count):
            # Stagger worker starts to avoid resource contention
            if i > 0:
                time.sleep(WORKER_STAGGER_DELAY_S)

            # Create dedicated pipe for this worker's health telemetry
            parent_conn, child_conn = Pipe(duplex=False)  # One-way: child writes, parent reads

            worker = create_discovery_worker(
                worker_index=i,
                db_hosts=self._db_hosts,
                db_password=self._db_password,
                processor_config=self.processor_config,
                stop_event=self._stop_event,
                health_pipe=child_conn,  # Pass write-end to worker
                execution_tier=tier_selection.tier,  # Pass tier to worker
                prefer_gpu=tier_selection.config.prefer_gpu,  # GPU preference from tier
            )

            worker.start()
            self._workers.append(worker)

            # Close child end in parent - only the worker should have it
            child_conn.close()

            # Register with HealthMonitor (it owns the pipe reader)
            if self.health_monitor:
                self.health_monitor.register_component(
                    component_id=worker.worker_id,
                    handler=self,  # WorkerSystemService implements ComponentLifecycleHandler
                    pipe_conn=parent_conn,
                    policy=DEFAULT_WORKER_POLICY,
                )

            logger.info("[WorkerSystemService] Started worker:tag:%d (pid=%s)", i, worker.pid)

        self._started = True

    def stop_all_workers(self, timeout: float = 10.0) -> None:
        """Stop all worker processes gracefully.

        Args:
            timeout: Seconds to wait for graceful shutdown before force kill

        """
        if not self._workers:
            logger.debug("[WorkerSystemService] No workers to stop")
            return

        logger.info("[WorkerSystemService] Stopping %d worker(s)", len(self._workers))

        # Cancel all pending restart timers FIRST (before setting stop event)
        for component_id, timer in list(self._pending_restart_timers.items()):
            timer.cancel()
            logger.debug("[WorkerSystemService] Cancelled pending restart timer for %s", component_id)
        self._pending_restart_timers.clear()

        # Signal all workers to stop
        self._stop_event.set()

        # Unregister workers from HealthMonitor
        if self.health_monitor:
            for worker in self._workers:
                self.health_monitor.unregister_component(worker.worker_id)

        # Wait for graceful shutdown
        for worker in self._workers:
            worker.join(timeout=timeout)
            if worker.is_alive():
                logger.warning(
                    "[WorkerSystemService] Worker %s did not stop gracefully, terminating",
                    worker.worker_id,
                )
                worker.terminate()
                worker.join(timeout=1.0)

        self._workers.clear()
        self._started = False
        logger.info("[WorkerSystemService] All workers stopped")

    def is_running(self) -> bool:
        """Check if any workers are running."""
        return self._started and any(w.is_alive() for w in self._workers)

    # ---------------------------- Status Methods ----------------------------

    def get_workers_status(self) -> dict[str, Any]:
        """Get worker system status.

        Returns:
            Dict with worker pool status

        """
        alive_workers = [w for w in self._workers if w.is_alive()]

        # Get status from HealthMonitor if available
        statuses = {}
        if self.health_monitor:
            statuses = self.health_monitor.get_all_statuses()

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
                    "id": w.worker_id,
                    "pid": w.pid,
                    "alive": w.is_alive(),
                    "status": statuses.get(w.worker_id, "pending"),
                }
                for w in self._workers
            ],
        }

    def get_resource_status(self) -> dict[str, Any]:
        """Get GPU/CPU resource management status.

        Returns:
            Dict with resource management status including tier, capacity, and GPU capability

        """
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
        """Run claim cleanup to remove stale/orphaned claims.

        This should be called periodically (e.g., in health monitor cycle).

        Returns:
            Number of claims removed

        """
        return cleanup_stale_claims(self.db, DEFAULT_HEARTBEAT_TIMEOUT_MS)
