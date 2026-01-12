"""
Worker System Service - Process Pool Management with Health Monitoring.

Manages all worker processes (taggers, scanners, recalibration) with:
- Automatic health monitoring and restart
- Exponential backoff for failed workers
- Per-worker process isolation
- Graceful shutdown handling

Architecture:
- WorkerSystemService owns all worker process lifecycles
- Each worker is a multiprocessing.Process (not Thread)
- Health monitoring via DB health table (Phase 3)
- Restart logic with exponential backoff (1s → 60s max)
- After 5 rapid restarts, worker marked "failed" and stopped
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any, Literal

from nomarr.components.workers import requeue_crashed_job, should_restart_worker
from nomarr.helpers.dto.admin_dto import WorkerOperationResult
from nomarr.persistence.db import Database
from nomarr.services.infrastructure.workers.base import BaseWorker
from nomarr.services.infrastructure.workers.recalibration import RecalibrationWorker
from nomarr.services.infrastructure.workers.scanner import LibraryScanWorker
from nomarr.services.infrastructure.workers.tagger import TaggerWorker

# Queue type literal (matches queue_svc.py)
QueueType = Literal["tag", "library", "calibration"]

# Restart and health monitoring constants
MAX_RESTARTS_IN_WINDOW = 5  # Maximum restarts before marking as failed
RESTART_WINDOW_MS = 5 * 60 * 1000  # 5 minutes in milliseconds
MAX_BACKOFF_SECONDS = 60  # Maximum exponential backoff delay
HEARTBEAT_STALE_THRESHOLD_MS = 30 * 1000  # 30 seconds (for healthy workers)
STARTING_HEARTBEAT_GRACE_MS = 5 * 60 * 1000  # 5 minutes (for starting workers doing TF init)
HEALTH_CHECK_INTERVAL_SECONDS = 10  # How often to check worker health
WORKER_STOP_TIMEOUT_SECONDS = 10  # Timeout for graceful worker shutdown
WORKER_TERMINATE_TIMEOUT_SECONDS = 2  # Timeout after terminate
PID_WAIT_MAX_MS = 500  # Maximum time to wait for worker PID assignment
PID_WAIT_POLL_MS = 10  # Poll interval for PID assignment

# Exit codes for crash reporting
EXIT_CODE_UNKNOWN_CRASH = -1
EXIT_CODE_HEARTBEAT_TIMEOUT = -2
EXIT_CODE_INVALID_HEARTBEAT = -3


def _get_stale_threshold_for_cache_state(cache_loaded: bool) -> int:
    """
    Get appropriate stale heartbeat threshold based on cache state.

    Workers with unloaded cache get a longer grace period (5 minutes) to complete
    TensorFlow model initialization on first job. Workers with loaded cache use
    the normal 30-second threshold.

    Args:
        cache_loaded: True if worker's expensive cache (TF models) is loaded

    Returns:
        Stale threshold in milliseconds
    """
    if not cache_loaded:
        return STARTING_HEARTBEAT_GRACE_MS
    return HEARTBEAT_STALE_THRESHOLD_MS


class WorkerSystemService:
    """
    Manages all worker processes with health monitoring and automatic restart.

    Features:
    - Creates and manages N worker processes per queue type (configurable)
    - Monitors worker health via DB health table heartbeats
    - Automatically restarts crashed or hung workers
    - Exponential backoff prevents restart loops
    - Global enable/disable control via DB meta worker_enabled flag

    Health Monitoring:
    - Background thread checks worker heartbeats every 10 seconds
    - Heartbeat stale (>30s) → restart worker
    - Process died (not is_alive()) → restart worker
    - Restart backoff: 1s, 2s, 4s, 8s, 16s, 32s, max 60s
    - After 5 restarts within 5 minutes → mark failed, stop restarting
    """

    def __init__(
        self,
        db: Database,
        tagger_backend: Callable[[Database, str, bool], Any],
        scanner_backend: Callable[[Database, str, bool], Any] | None,
        recalibration_backend: Callable[[Database, str, bool], Any],
        event_broker: Any,
        tagger_count: int = 2,
        scanner_count: int = 10,
        recalibration_count: int = 5,
        default_enabled: bool = True,
    ):
        """
        Initialize worker system service.

        Args:
            db: Database instance (for health monitoring and meta flags)
            tagger_backend: Processing backend for tagger workers
            scanner_backend: Processing backend for scanner workers (None if no library_root)
            recalibration_backend: Processing backend for recalibration workers
            event_broker: Event broker for SSE updates
            tagger_count: Number of tagger worker processes (default: 2, ML heavy)
            scanner_count: Number of scanner worker processes (default: 10, I/O bound)
            recalibration_count: Number of recalibration worker processes (default: 5, CPU light)
            default_enabled: Default worker_enabled flag if not in DB (default: True)
        """
        self.db = db
        self.tagger_backend = tagger_backend
        self.scanner_backend = scanner_backend
        self.recalibration_backend = recalibration_backend
        self.event_broker = event_broker
        self.tagger_count = tagger_count
        self.scanner_count = scanner_count
        self.recalibration_count = recalibration_count
        self.default_enabled = default_enabled

        # Centralized worker collections by queue type
        self._worker_groups: dict[QueueType, list[BaseWorker]] = {
            "tag": [],
            "library": [],
            "calibration": [],
        }

        # GPU health monitor process (independent of workers)
        self._gpu_monitor: Any = None  # GPUHealthMonitor process

        # Health monitor control
        self._monitor_thread: threading.Thread | None = None
        self._shutdown = False

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
        logging.info("[WorkerSystemService] Worker system globally enabled")

    def disable_worker_system(self) -> None:
        """
        Disable worker system globally (sets worker_enabled=false in DB meta).

        Note: This prevents new workers from starting but does not stop running workers.
        Use stop_all_workers() to actually stop running workers.
        """
        self.db.meta.set("worker_enabled", "false")
        logging.info("[WorkerSystemService] Worker system globally disabled")

    # ---------------------------- Worker Lifecycle ----------------------------

    def start_all_workers(self) -> None:
        """
        Start all worker processes and health monitor.

        Only starts workers if worker_enabled=true in DB meta.
        Idempotent - only starts workers that aren't already running.
        """
        if not self.is_worker_system_enabled():
            logging.info("[WorkerSystemService] Worker system disabled, not starting workers")
            return

        logging.info("[WorkerSystemService] Starting worker processes...")

        # Start tagger workers (only starts missing workers)
        self._start_tagger_workers()

        # Start scanner workers (if backend configured)
        if self.scanner_backend:
            self._start_scanner_workers()

        # Start recalibration workers
        self._start_recalibration_workers()

        # Start GPU health monitor (independent process)
        self._start_gpu_monitor()

        # Start health monitor thread
        self._start_health_monitor()

        logging.info("[WorkerSystemService] Worker startup complete")

    def stop_all_workers(self) -> None:
        """
        Stop all worker processes and health monitor.

        Gracefully signals workers to stop, waits for them to finish,
        then terminates any that don't stop within timeout.
        """
        logging.info("[WorkerSystemService] Stopping all worker processes...")

        # Stop GPU monitor first (independent process)
        self._stop_gpu_monitor()

        # Stop health monitor
        self._shutdown = True
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)

        # Collect all workers from centralized groups
        all_workers: list[BaseWorker] = []
        for workers in self._worker_groups.values():
            all_workers.extend(workers)

        # Signal all workers to stop
        for worker in all_workers:
            try:
                worker.stop()
            except Exception as e:
                logging.error(f"[WorkerSystemService] Error stopping {worker.name}: {e}")

        # Wait for graceful shutdown with timeout
        for worker in all_workers:
            try:
                worker.join(timeout=WORKER_STOP_TIMEOUT_SECONDS)
                if worker.is_alive():
                    logging.warning(f"[WorkerSystemService] {worker.name} did not stop gracefully, terminating...")
                    worker.terminate()
                    worker.join(timeout=WORKER_TERMINATE_TIMEOUT_SECONDS)
            except Exception as e:
                logging.error(f"[WorkerSystemService] Error joining {worker.name}: {e}")

        # Clear all worker groups
        for workers in self._worker_groups.values():
            workers.clear()

        logging.info("[WorkerSystemService] All worker processes stopped")

    def _start_tagger_workers(self) -> None:
        """Start N tagger worker processes (only starts missing workers)."""
        existing_workers = self._worker_groups["tag"]

        # Remove dead workers from list
        existing_workers[:] = [w for w in existing_workers if w.is_alive()]

        # Start missing workers
        for i in range(self.tagger_count):
            # Check if worker with this ID already exists and is alive
            if any(w.worker_id == i and w.is_alive() for w in existing_workers):
                continue

            worker = TaggerWorker(
                db_path=str(self.db.path),
                processing_backend=self.tagger_backend,
                worker_id=i,
                interval=2,
            )
            worker.start()
            existing_workers.append(worker)
            logging.info(f"[WorkerSystemService] Started TaggerWorker-{i} (PID: {worker.pid})")

    def _start_scanner_workers(self) -> None:
        """Start N scanner worker processes (only starts missing workers)."""
        if not self.scanner_backend:
            return

        existing_workers = self._worker_groups["library"]

        # Remove dead workers from list
        existing_workers[:] = [w for w in existing_workers if w.is_alive()]

        # Start missing workers
        for i in range(self.scanner_count):
            # Check if worker with this ID already exists and is alive
            if any(w.worker_id == i and w.is_alive() for w in existing_workers):
                continue

            worker = LibraryScanWorker(
                db_path=str(self.db.path),
                processing_backend=self.scanner_backend,
                worker_id=i,
                interval=5,
            )
            worker.start()
            existing_workers.append(worker)
            logging.info(f"[WorkerSystemService] Started LibraryScanWorker-{i} (PID: {worker.pid})")

    def _start_recalibration_workers(self) -> None:
        """Start N recalibration worker processes (only starts missing workers)."""
        existing_workers = self._worker_groups["calibration"]

        # Remove dead workers from list
        existing_workers[:] = [w for w in existing_workers if w.is_alive()]

        # Start missing workers
        for i in range(self.recalibration_count):
            # Check if worker with this ID already exists and is alive
            if any(w.worker_id == i and w.is_alive() for w in existing_workers):
                continue

            worker = RecalibrationWorker(
                db_path=str(self.db.path),
                processing_backend=self.recalibration_backend,
                worker_id=i,
                interval=2,
            )
            worker.start()
            existing_workers.append(worker)
            logging.info(f"[WorkerSystemService] Started RecalibrationWorker-{i} (PID: {worker.pid})")

    def _start_gpu_monitor(self) -> None:
        """
        Start GPU health monitor process (independent of workers).

        This process runs nvidia-smi probes in complete isolation.
        If nvidia-smi hangs, the monitor process may become stuck,
        but StateBroker will detect stale data and mark GPU as UNKNOWN.
        """
        from nomarr.components.platform import GPUHealthMonitor

        # Don't restart if already running
        if self._gpu_monitor and self._gpu_monitor.is_alive():
            logging.debug("[WorkerSystemService] GPU monitor already running")
            return

        try:
            logging.info("[WorkerSystemService] Starting GPU health monitor process")
            self._gpu_monitor = GPUHealthMonitor(db_path=self.db.path)
            self._gpu_monitor.start()
            logging.info("[WorkerSystemService] GPU health monitor started")
        except Exception as e:
            logging.error(f"[WorkerSystemService] Failed to start GPU health monitor: {e}")
            self._gpu_monitor = None

    def _stop_gpu_monitor(self) -> None:
        """Stop GPU health monitor process."""
        if not self._gpu_monitor:
            return

        try:
            logging.info("[WorkerSystemService] Stopping GPU health monitor...")
            self._gpu_monitor.stop()
            self._gpu_monitor.join(timeout=5)

            if self._gpu_monitor.is_alive():
                logging.warning("[WorkerSystemService] GPU monitor did not stop gracefully, terminating...")
                self._gpu_monitor.terminate()
                self._gpu_monitor.join(timeout=2)

            self._gpu_monitor = None
            logging.info("[WorkerSystemService] GPU health monitor stopped")
        except Exception as e:
            logging.error(f"[WorkerSystemService] Error stopping GPU health monitor: {e}")

    # ---------------------------- Health Monitoring ----------------------------

    def _start_health_monitor(self) -> None:
        """Start background thread for health monitoring."""
        self._shutdown = False
        self._monitor_thread = threading.Thread(
            target=self._monitor_worker_health,
            daemon=True,
            name="WorkerHealthMonitor",
        )
        self._monitor_thread.start()
        logging.info("[WorkerSystemService] Health monitor started")

    def _monitor_worker_health(self) -> None:
        """
        Monitor worker heartbeats and restart if needed.

        Checks every HEALTH_CHECK_INTERVAL_SECONDS:
        - Heartbeat age > threshold → stale, restart worker
          - "starting" workers: 5-minute grace period (TF cold start)
          - "healthy" workers: 30-second threshold (normal operation)
        - Process not alive → restart worker
        - Restart with exponential backoff
        """
        while not self._shutdown:
            try:
                now_ms = int(time.time() * 1000)

                # Check all worker types from centralized groups
                for queue_type, workers in self._worker_groups.items():
                    for worker in workers:
                        component_id = f"worker:{queue_type}:{worker.worker_id}"

                        # Get health record
                        health = self.db.health.get_component(component_id)
                        if not health:
                            # Worker hasn't written heartbeat yet (just started)
                            continue

                        # Check if heartbeat is stale
                        last_heartbeat = health["last_heartbeat"]
                        if not isinstance(last_heartbeat, int):
                            logging.warning(
                                f"[WorkerSystemService] {component_id} has invalid heartbeat, marking as crashed..."
                            )
                            self.db.health.mark_crashed(
                                component=component_id,
                                exit_code=EXIT_CODE_INVALID_HEARTBEAT,
                                metadata="Invalid heartbeat timestamp",
                            )
                            self._schedule_restart(worker, queue_type, component_id)
                            continue

                        heartbeat_age = now_ms - last_heartbeat

                        # Choose threshold based on cache_loaded metadata
                        # Workers with unloaded cache get 5 minutes for TF initialization
                        # Workers with loaded cache use normal 30-second threshold
                        cache_loaded = True  # Default: assume cache is loaded
                        metadata_str = health.get("metadata")
                        if isinstance(metadata_str, str):
                            try:
                                import json

                                metadata = json.loads(metadata_str)
                                cache_loaded = metadata.get("cache_loaded", True)
                            except (json.JSONDecodeError, AttributeError):
                                pass  # Use default if metadata invalid

                        stale_threshold = _get_stale_threshold_for_cache_state(cache_loaded)

                        if heartbeat_age > stale_threshold:
                            logging.warning(
                                f"[WorkerSystemService] {component_id} heartbeat stale "
                                f"({heartbeat_age}ms old, threshold={stale_threshold}ms, cache_loaded={cache_loaded}), "
                                f"marking as crashed and restarting..."
                            )
                            # Mark as crashed due to stale heartbeat
                            self.db.health.mark_crashed(
                                component=component_id,
                                exit_code=EXIT_CODE_HEARTBEAT_TIMEOUT,
                                metadata=f"Heartbeat stale for {heartbeat_age}ms (threshold={stale_threshold}ms, cache_loaded={cache_loaded})",
                            )
                            self._schedule_restart(worker, queue_type, component_id)
                            continue

                        # Check if process died
                        if not worker.is_alive():
                            # Check if already marked as failed - don't restart if so
                            if health["status"] == "failed":
                                logging.debug(
                                    f"[WorkerSystemService] {component_id} already marked as failed, skipping restart"
                                )
                                continue

                            exit_code = worker.exitcode if worker.exitcode is not None else EXIT_CODE_UNKNOWN_CRASH
                            logging.warning(
                                f"[WorkerSystemService] {component_id} process died (exit_code={exit_code}), "
                                f"marking as crashed and restarting..."
                            )
                            # Mark as crashed before restarting
                            self.db.health.mark_crashed(
                                component=component_id,
                                exit_code=exit_code,
                                metadata=f"Process terminated unexpectedly with exit code {exit_code}",
                            )
                            self._schedule_restart(worker, queue_type, component_id)
                            continue

            except Exception as e:
                logging.error(f"[WorkerSystemService] Health monitor error: {e}")

            # Check every HEALTH_CHECK_INTERVAL_SECONDS
            time.sleep(HEALTH_CHECK_INTERVAL_SECONDS)

    def _schedule_restart(self, worker: BaseWorker, queue_type: str, component_id: str) -> None:
        """Schedule a worker restart in a background thread (non-blocking)."""

        def restart_in_background():
            try:
                from typing import Literal, cast

                queue_type_literal = cast(Literal["tag", "library", "calibration"], queue_type)
                self._restart_worker(worker, queue_type_literal, component_id)
            except Exception as e:
                logging.error(f"[WorkerSystemService] Background restart failed for {component_id}: {e}")

        restart_thread = threading.Thread(
            target=restart_in_background,
            name=f"Restart-{component_id}",
            daemon=True,
        )
        restart_thread.start()

    def _restart_worker(self, worker: BaseWorker, queue_type: QueueType, component_id: str) -> None:
        """
        Restart a worker with exponential backoff.

        Handles job recovery for interrupted jobs before restarting the worker.
        Uses two-tier restart limits to detect both rapid crashes and slow thrashing.

        Args:
            worker: Worker process to restart
            queue_type: Queue type ("tag", "library", "calibration")
            component_id: Component ID for health tracking
        """
        try:
            # Get current health record to check for interrupted job
            health = self.db.health.get_component(component_id)

            # Double-check: if already marked as failed, don't restart
            if health and health.get("status") == "failed":
                logging.info(f"[WorkerSystemService] {component_id} already marked as failed, aborting restart")
                return
            current_job_raw = health.get("current_job") if health else None

            # Ensure current_job is int or None for type safety
            current_job: int | None = None
            if current_job_raw is not None and isinstance(current_job_raw, int):
                current_job = current_job_raw

            # Attempt to requeue interrupted job (if any) before restart
            if current_job is not None:
                requeued = requeue_crashed_job(self.db, queue_type, current_job)
                if requeued:
                    logging.info(
                        f"[WorkerSystemService] Requeued interrupted job {current_job} "
                        f"from crashed worker {component_id}"
                    )
                else:
                    logging.warning(
                        f"[WorkerSystemService] Job {current_job} not requeued "
                        f"(already completed, marked toxic, or invalid)"
                    )

            # Increment restart count and get updated values atomically
            restart_info = self.db.health.increment_restart_count(component_id)
            restart_count = restart_info["restart_count"]
            last_restart = restart_info["last_restart"]

            # Check restart limits using component logic
            decision = should_restart_worker(restart_count, last_restart)

            if decision.action == "mark_failed":
                logging.error(f"[WorkerSystemService] {component_id} exceeded restart limits: {decision.reason}")
                self.db.health.mark_failed(
                    component=component_id,
                    metadata=decision.failure_reason or f"Failed after {restart_count} restart attempts",
                )
                return

            # Apply exponential backoff before restarting
            logging.info(
                f"[WorkerSystemService] Waiting {decision.backoff_seconds}s before restarting {component_id}..."
            )
            time.sleep(decision.backoff_seconds)

            # Stop old worker
            try:
                worker.stop()
                worker.join(timeout=5)
                if worker.is_alive():
                    worker.terminate()
                    worker.join(timeout=2)
            except Exception as e:
                logging.error(f"[WorkerSystemService] Error stopping {component_id}: {e}")

            # Create new worker based on queue type
            new_worker = self._create_worker(queue_type, worker.worker_id)
            new_worker.start()

            # Update worker list
            self._replace_worker_in_list(queue_type, worker.worker_id, new_worker)

            # Wait briefly for PID to be assigned by OS
            max_wait = PID_WAIT_MAX_MS / 1000.0
            wait_start = time.time()
            while new_worker.pid is None and (time.time() - wait_start) < max_wait:
                time.sleep(PID_WAIT_POLL_MS / 1000.0)

            # Mark new worker as starting with actual PID
            worker_pid = new_worker.pid if new_worker.pid is not None else os.getpid()
            self.db.health.mark_starting(component=component_id, pid=worker_pid)

            logging.info(
                f"[WorkerSystemService] Restarted {component_id} (PID: {new_worker.pid}, restart #{restart_count})"
            )

        except Exception as e:
            logging.error(f"[WorkerSystemService] Failed to restart {component_id}: {e}")

    def _create_worker(self, queue_type: str, worker_id: int) -> BaseWorker:
        """
        Create a new worker process.

        Args:
            queue_type: Queue type ("tag", "library", "calibration")
            worker_id: Worker ID

        Returns:
            New worker process instance
        """
        if queue_type == "tag":
            return TaggerWorker(
                db_path=str(self.db.path),
                processing_backend=self.tagger_backend,
                worker_id=worker_id,
                interval=2,
            )
        elif queue_type == "library":
            if not self.scanner_backend:
                raise ValueError("Scanner backend not configured")
            return LibraryScanWorker(
                db_path=str(self.db.path),
                processing_backend=self.scanner_backend,
                worker_id=worker_id,
                interval=5,
            )
        elif queue_type == "calibration":
            return RecalibrationWorker(
                db_path=str(self.db.path),
                processing_backend=self.recalibration_backend,
                worker_id=worker_id,
                interval=2,
            )
        else:
            raise ValueError(f"Unknown queue type: {queue_type}")

    def _replace_worker_in_list(self, queue_type: QueueType, worker_id: int, new_worker: BaseWorker) -> None:
        """
        Replace a worker in the appropriate list.

        Args:
            queue_type: Queue type ("tag", "library", "calibration")
            worker_id: Worker ID to replace
            new_worker: New worker process instance
        """
        workers = self._worker_groups[queue_type]
        for i, w in enumerate(workers):
            if w.worker_id == worker_id:
                workers[i] = new_worker
                return

    # ---------------------------- Admin Operations ----------------------------

    def pause_all_workers(self, event_broker: Any | None = None) -> WorkerOperationResult:
        """
        Pause all workers.

        Sets worker_enabled=false, then stops all worker processes.

        Args:
            event_broker: Optional event broker for SSE updates

        Returns:
            WorkerOperationResult with status message
        """
        logging.info("[WorkerSystemService] Pause all workers requested")

        # Disable worker system
        self.disable_worker_system()

        # Stop all workers
        self.stop_all_workers()

        # Individual worker state changes are broadcast via normal worker updates

        return WorkerOperationResult(status="success", message="All workers paused")

    def resume_all_workers(self, event_broker: Any | None = None) -> WorkerOperationResult:
        """
        Resume all workers.

        Sets worker_enabled=true and starts all worker processes.

        Args:
            event_broker: Optional event broker for SSE updates

        Returns:
            WorkerOperationResult with status message
        """
        logging.info("[WorkerSystemService] Resume all workers requested")

        # Enable worker system
        self.enable_worker_system()

        # Start all workers
        self.start_all_workers()

        # Individual worker state changes are broadcast via normal worker updates

        return WorkerOperationResult(status="success", message="All workers resumed")

    def reset_restart_count(self, component_id: str) -> None:
        """
        Reset restart count for a worker (admin operation).

        Allows manually recovering a worker marked as permanently failed.

        Args:
            component_id: Component ID (e.g., "worker:tag:0")
        """
        health = self.db.health.get_component(component_id)
        if not health:
            logging.warning(f"[WorkerSystemService] No health record for {component_id}")
            return

        self.db.health.reset_restart_count(component_id)
        logging.info(f"[WorkerSystemService] Reset restart count for {component_id}")

    # ---------------------------- Status Reporting ----------------------------

    def get_workers_status(self) -> dict[str, Any]:
        """
        Get unified status across all worker processes.

        Returns:
            Dict with:
                - enabled: Global worker_enabled flag
                - workers: Dict of worker statuses by queue type
                    - Each worker: worker_id, pid, status, last_heartbeat, current_job, restart_count
        """
        status: dict[str, Any] = {
            "enabled": self.is_worker_system_enabled(),
            "workers": {
                "tag": [],
                "library": [],
                "calibration": [],
            },
        }

        # Get health records for all workers
        all_health = self.db.health.get_all_workers()

        # Organize by queue type
        for health in all_health:
            component = health["component"]
            if not isinstance(component, str) or not component.startswith("worker:"):
                continue

            # Parse component_id: "worker:tag:0" → ("tag", 0)
            parts = component.split(":")
            if len(parts) != 3:
                continue

            queue_type = parts[1]
            if queue_type in status["workers"]:
                status["workers"][queue_type].append(
                    {
                        "worker_id": int(parts[2]),
                        "pid": health.get("pid"),
                        "status": health.get("status"),
                        "last_heartbeat": health.get("last_heartbeat"),
                        "current_job": health.get("current_job"),
                        "restart_count": health.get("restart_count", 0),
                    }
                )

        return status
