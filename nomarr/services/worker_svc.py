"""
Worker service.
Shared business logic for worker management across all interfaces.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.admin_dto import WorkerOperationResult
from nomarr.helpers.dto.processing_dto import WorkerEnabledResult, WorkerStatusResult

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.coordinator_svc import CoordinatorService
    from nomarr.services.queue_svc import ProcessingQueue
    from nomarr.services.workers.base import BaseWorker


# ----------------------------------------------------------------------
#  Service-Local Config (used only by WorkerService)
# ----------------------------------------------------------------------


@dataclass
class WorkerConfig:
    """Configuration for WorkerService."""

    default_enabled: bool
    worker_count: int
    poll_interval: int


class WorkerService:
    """
    Worker management operations - shared by all interfaces.

    This service encapsulates worker lifecycle management, ensuring CLI, API,
    and Web interfaces coordinate properly when starting/stopping workers.
    """

    def __init__(
        self,
        db: Database,
        queue: ProcessingQueue,
        cfg: WorkerConfig,
        processor_coord: CoordinatorService | None = None,
    ):
        """
        Initialize worker service.

        Args:
            db: Database instance
            queue: Job queue instance
            cfg: Worker configuration
            processor_coord: CoordinatorService for parallel processing
        """
        self.db = db
        self.queue = queue
        self.cfg = cfg
        self.processor_coord = processor_coord
        self.worker_pool: list[BaseWorker] = []

    def is_enabled(self) -> bool:
        """
        Check if workers are enabled.

        Returns:
            True if workers are enabled in DB meta or default config
        """
        meta = self.db.meta.get("worker_enabled")
        if meta is None:
            return self.cfg.default_enabled
        return bool(meta == "true")

    def enable(self) -> None:
        """
        Enable workers (sets DB meta flag).
        """
        self.db.meta.set("worker_enabled", "true")
        logging.info("[WorkerService] Workers enabled")

    def disable(self) -> None:
        """
        Disable workers (sets DB meta flag, waits for idle, then stops workers).

        This method ensures safe shutdown by:
        1. Setting worker_enabled=false (stops accepting NEW jobs)
        2. Waiting for all running jobs to complete (prevents orphaned state)
        3. Stopping worker threads

        Blocks until all jobs complete or timeout (60s default).
        """
        self.db.meta.set("worker_enabled", "false")
        logging.info("[WorkerService] Workers disabled, waiting for active jobs to complete...")

        # Wait for all running jobs to finish before stopping threads
        if not self.wait_until_idle(timeout=60):
            logging.warning("[WorkerService] Timeout waiting for jobs to complete - forcing shutdown")

        self.stop_all_workers()
        logging.info("[WorkerService] All workers stopped")

    def pause_workers(self, event_broker: Any | None = None) -> WorkerEnabledResult:
        """
        Pause workers (disable new job processing).

        Args:
            event_broker: Optional event broker for SSE updates

        Returns:
            WorkerEnabledResult with worker_enabled status
        """
        self.disable()

        if event_broker:
            event_broker.update_worker_state({"enabled": False})

        return WorkerEnabledResult(worker_enabled=False)

    def resume_workers(self, worker_pool: list, event_broker: Any | None = None) -> WorkerEnabledResult:
        """
        Resume workers (enable job processing and start workers).

        Args:
            worker_pool: Worker pool list to update
            event_broker: Optional event broker for SSE updates

        Returns:
            WorkerEnabledResult with worker_enabled status
        """
        self.enable()
        updated_pool = self.start_workers(event_broker=event_broker)
        worker_pool.clear()
        worker_pool.extend(updated_pool)

        if event_broker:
            event_broker.update_worker_state({"enabled": True})

        return WorkerEnabledResult(worker_enabled=True)

    # -------------------------------------------------------------------------
    #  Admin Wrappers (for interfaces/api)
    # -------------------------------------------------------------------------

    def pause_workers_for_admin(self, event_broker: Any | None = None) -> WorkerOperationResult:
        """
        Pause workers with admin-friendly messaging.

        Args:
            event_broker: Optional event broker for SSE updates

        Returns:
            WorkerOperationResult with status message
        """
        result = self.pause_workers(event_broker)
        message = "Worker paused" if not result.worker_enabled else "Worker already paused"
        return WorkerOperationResult(status="success", message=message)

    def resume_workers_for_admin(self, worker_pool: list, event_broker: Any | None = None) -> WorkerOperationResult:
        """
        Resume workers with admin-friendly messaging.

        Args:
            worker_pool: Worker pool list to update
            event_broker: Optional event broker for SSE updates

        Returns:
            WorkerOperationResult with status message
        """
        result = self.resume_workers(worker_pool, event_broker)
        message = "Worker resumed" if result.worker_enabled else "Worker failed to resume"
        return WorkerOperationResult(status="success", message=message)

    def wait_until_idle(self, timeout: int = 60, poll_interval: float = 0.5) -> bool:
        """
        Wait for all running jobs to complete (workers to become idle).

        This is useful when you need to ensure no jobs are actively being processed
        before performing queue operations (like removal or cleanup).

        Checks both:
        - Worker busy state (any worker currently processing a job)
        - Database running count (jobs marked as running in DB)

        This dual-check prevents waiting forever if workers crash mid-job.

        Args:
            timeout: Maximum seconds to wait (default: 60)
            poll_interval: Seconds between status checks (default: 0.5)

        Returns:
            True if all jobs completed within timeout, False if timeout exceeded

        Raises:
            None - returns False on timeout instead of raising
        """
        import time

        start = time.time()
        while (time.time() - start) < timeout:
            # Check if any worker is actively processing
            any_busy = any(w.is_busy() for w in self.worker_pool if w.is_alive())

            # Check if any jobs are currently running in DB
            running_count = self.db.tag_queue.queue_stats().get("running", 0)

            # Both checks must be idle
            if not any_busy and running_count == 0:
                logging.debug("[WorkerService] All workers idle (no busy workers, no running jobs)")
                return True

            # Log what we're waiting for
            status_parts = []
            if any_busy:
                busy_workers = [w.worker_id for w in self.worker_pool if w.is_alive() and w.is_busy()]
                status_parts.append(f"workers {busy_workers} busy")
            if running_count > 0:
                status_parts.append(f"{running_count} job(s) running in DB")

            logging.debug(f"[WorkerService] Waiting: {', '.join(status_parts)}")
            time.sleep(poll_interval)

        # Timeout exceeded
        logging.warning(f"[WorkerService] Timeout waiting for workers to become idle after {timeout}s")
        return False

    def cleanup_orphaned_jobs(self) -> int:
        """
        Reset orphaned jobs to pending.

        Called when workers crash - finds jobs stuck in "running" status
        and resets them to "pending" so they can be processed again.

        Returns:
            Number of jobs reset
        """
        jobs_reset = 0
        with self.queue.lock:
            running_job_ids = self.db.tag_queue.get_running_job_ids()

            for job_id in running_job_ids:
                self.db.tag_queue.update_job(job_id, "pending")
                jobs_reset += 1

        if jobs_reset > 0:
            logging.warning(f"[WorkerService] Reset {jobs_reset} orphaned job(s) to pending")

        return jobs_reset

    def start_workers(self, event_broker: Any | None = None) -> list[BaseWorker]:
        """
        Start worker threads up to configured count.

        Args:
            event_broker: Optional event broker for SSE updates

        Returns:
            Updated worker pool list
        """
        if not self.is_enabled():
            logging.info("[WorkerService] Workers disabled, not starting")
            return self.worker_pool

        # Check if we already have enough workers
        current_count = len([w for w in self.worker_pool if w.is_alive()])
        if current_count >= self.cfg.worker_count:
            return self.worker_pool

        self._start_new_workers(current_count, event_broker)
        return self.worker_pool

    def _start_new_workers(self, current_count: int, event_broker: Any | None = None) -> None:
        """
        Internal method to start new worker threads.

        Args:
            current_count: Number of currently alive workers
            event_broker: Optional event broker for SSE updates
        """

        # Create wrapper that uses the process pool
        def process_via_pool(path: str, force: bool) -> dict[str, Any]:
            from nomarr.helpers.file_validation_helper import (
                make_skip_result,
                should_skip_processing,
                validate_file_exists,
            )
            from nomarr.services.config_svc import ConfigService
            from nomarr.workflows.processing.process_file_wf import process_file_workflow

            if self.processor_coord is None:
                # Fallback: direct processing (shouldn't happen after startup)
                # Create typed config
                config_service = ConfigService()
                processor_config = config_service.make_processor_config()

                # Validate file
                validate_file_exists(path)

                # Check skip conditions
                should_skip, skip_reason = should_skip_processing(
                    path,
                    force,
                    processor_config.namespace,
                    processor_config.version_tag_key,
                    processor_config.tagger_version,
                )

                if should_skip:
                    return make_skip_result(path, skip_reason or "unknown")

                # Process with DB
                return process_file_workflow(path, config=processor_config, db=self.db)
            try:
                return self.processor_coord.submit(path, force)
            except Exception as e:
                # Check for worker crash vs shutdown
                error_message = str(e).lower()
                if "abruptly" in error_message or "process pool" in error_message:
                    # Worker process crashed - don't confuse with shutdown
                    logging.error(f"[WorkerService] Process pool broken (worker crash): {e}")
                    raise
                elif "shutting down" in error_message:
                    # Pool unavailable or shutting down
                    logging.warning(f"[WorkerService] Cannot process job during shutdown: {e}")
                    raise
                else:
                    logging.error(f"[WorkerService] Process pool error: {e}")
                    raise

        # Start new workers up to worker_count
        for i in range(current_count, self.cfg.worker_count):
            from nomarr.services.workers.tagger import TaggerWorker

            # Ensure event_broker is provided (required for BaseWorker)
            if not event_broker:
                raise RuntimeError("event_broker is required for workers")

            worker = TaggerWorker(
                db=self.db,
                queue=self.queue,
                event_broker=event_broker,
                interval=self.cfg.poll_interval,
                worker_id=i,
            )
            # Override process_fn to use process pool
            worker.process_fn = process_via_pool
            worker.start()
            self.worker_pool.append(worker)
            logging.info(f"[WorkerService] Started worker {i + 1}/{self.cfg.worker_count}")

        running_count = len([w for w in self.worker_pool if w.is_alive()])
        logging.info(f"[WorkerService] {running_count} worker(s) running")

    def stop_all_workers(self) -> None:
        """
        Stop all running workers gracefully.
        """
        if not self.worker_pool:
            return

        logging.info(f"[WorkerService] Stopping {len(self.worker_pool)} worker(s)...")
        for worker in self.worker_pool:
            worker.stop()

        for worker in self.worker_pool:
            if worker.is_alive():
                worker.join(timeout=10)

        self.worker_pool = []
        logging.info("[WorkerService] All workers stopped")

    def get_status(self) -> WorkerStatusResult:
        """
        Get worker status information.

        Returns:
            WorkerStatusResult with enabled status, counts, and worker details
        """
        enabled = self.is_enabled()

        # Clean up dead workers
        self.worker_pool = [w for w in self.worker_pool if w.is_alive()]
        running = len(self.worker_pool)

        workers = []
        for i, worker in enumerate(self.worker_pool):
            workers.append(
                {
                    "id": i,
                    "alive": worker.is_alive(),
                    "name": worker.name,
                }
            )

        return WorkerStatusResult(
            enabled=enabled,
            worker_count=self.cfg.worker_count,
            running=running,
            workers=workers,
        )
