"""
Worker System Service - Discovery-based worker management.

Manages discovery workers that query library_files directly instead of
polling a queue. Workers claim files via worker_claims collection.

Implements ComponentLifecycleHandler protocol for HealthMonitor callbacks.
Receives status change events and decides on restart/recovery actions.
"""

from __future__ import annotations

import logging
from multiprocessing import Event, Pipe
from typing import TYPE_CHECKING, Any

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
DEFAULT_WORKER_POLICY = ComponentPolicy(
    startup_timeout_s=60.0,  # Workers may take time to load models
    staleness_interval_s=5.0,  # Expect health frame every 5s
    max_consecutive_misses=3,  # 3 misses = 15s before dead
    min_recovery_s=5.0,
    max_recovery_s=120.0,  # Allow up to 2 min recovery for heavy operations
)


class WorkerSystemService(ComponentLifecycleHandler):
    """
    Discovery-based worker system service.

    Manages worker processes that:
    1. Query library_files for files with needs_tagging=1
    2. Claim files via worker_claims collection
    3. Process files using process_file_workflow
    4. Update library_files.tagged=1 before releasing claims

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
    ):
        """
        Initialize worker system service.

        Args:
            db: Database instance
            processor_config: Configuration for the processing workflow
            health_monitor: HealthMonitor to register workers with
            worker_count: Number of worker processes to spawn
            default_enabled: Default worker_enabled flag if not in DB
        """
        self.db = db
        self.processor_config = processor_config
        self.health_monitor = health_monitor
        self.worker_count = worker_count
        self.default_enabled = default_enabled

        # Get DB connection info for workers (required for subprocess connections)
        if not db.hosts or not db.password:
            raise ValueError("Database hosts and password required for worker system")
        self._db_hosts: str = db.hosts
        self._db_password: str = db.password

        # Worker process management
        self._workers: list[DiscoveryWorker] = []
        self._stop_event = Event()
        self._started = False

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
            # Worker needs intervention - could restart here
            logger.warning("[WorkerSystemService] Worker %s is dead, may need restart", component_id)
            # TODO: Implement restart logic with backoff if needed

        elif new_status == "unhealthy":
            # Worker is missing health checks but not dead yet
            logger.warning(
                "[WorkerSystemService] Worker %s unhealthy (%d misses)",
                component_id,
                context.consecutive_misses,
            )

    # ---------------------------- Control Methods ----------------------------

    def is_worker_system_enabled(self) -> bool:
        """
        Check if worker system is globally enabled.

        Returns:
            True if worker_enabled=true in DB meta, or default if not set
        """
        meta = self.db.meta.get("worker_enabled")
        if meta is None:
            return self.default_enabled
        return bool(meta == "true")

    def enable_worker_system(self) -> None:
        """Enable worker system globally (sets worker_enabled=true in DB meta)."""
        self.db.meta.set("worker_enabled", "true")
        logger.info("[WorkerSystemService] Worker system globally enabled")

    def disable_worker_system(self) -> None:
        """Disable worker system globally (sets worker_enabled=false in DB meta)."""
        self.db.meta.set("worker_enabled", "false")
        logger.info("[WorkerSystemService] Worker system globally disabled")

    def pause_worker_system(self) -> WorkerOperationResult:
        """
        Pause worker system - disables processing and stops workers.

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
        """
        Resume worker system - enables processing and starts workers.

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
        """Start all worker processes and register with HealthMonitor."""
        if self._started:
            logger.debug("[WorkerSystemService] Workers already started")
            return

        if not self.is_worker_system_enabled():
            logger.info("[WorkerSystemService] Worker system disabled, not starting")
            return

        logger.info("[WorkerSystemService] Starting %d discovery worker(s)", self.worker_count)

        # Clear stop event for new workers
        self._stop_event.clear()

        # Create and start workers, registering each with HealthMonitor
        for i in range(self.worker_count):
            # Create dedicated pipe for this worker's health telemetry
            parent_conn, child_conn = Pipe(duplex=False)  # One-way: child writes, parent reads

            worker = create_discovery_worker(
                worker_index=i,
                db_hosts=self._db_hosts,
                db_password=self._db_password,
                processor_config=self.processor_config,
                stop_event=self._stop_event,
                health_pipe=child_conn,  # Pass write-end to worker
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
        """
        Get worker system status.

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

    # ---------------------------- Claim Cleanup ----------------------------

    def cleanup_stale_claims(self) -> int:
        """
        Run claim cleanup to remove stale/orphaned claims.

        This should be called periodically (e.g., in health monitor cycle).

        Returns:
            Number of claims removed
        """
        from nomarr.components.workers.worker_discovery_comp import cleanup_stale_claims

        return cleanup_stale_claims(self.db, DEFAULT_HEARTBEAT_TIMEOUT_MS)
