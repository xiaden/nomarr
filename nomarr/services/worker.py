"""
Worker service.
Shared business logic for worker management across all interfaces.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.data.db import Database
    from nomarr.data.queue import JobQueue, TaggerWorker
    from nomarr.interfaces.api.coordinator import ProcessingCoordinator


class WorkerService:
    """
    Worker management operations - shared by all interfaces.

    This service encapsulates worker lifecycle management, ensuring CLI, API,
    and Web interfaces coordinate properly when starting/stopping workers.
    """

    def __init__(
        self,
        db: Database,
        queue: JobQueue,
        processor_coord: ProcessingCoordinator | None = None,
        default_enabled: bool = True,
        worker_count: int = 1,
        poll_interval: int = 2,
    ):
        """
        Initialize worker service.

        Args:
            db: Database instance
            queue: Job queue instance
            processor_coord: ProcessingCoordinator for parallel processing
            default_enabled: Default worker enabled state
            worker_count: Maximum number of workers to run
            poll_interval: Worker poll interval in seconds
        """
        self.db = db
        self.queue = queue
        self.processor_coord = processor_coord
        self.default_enabled = default_enabled
        self.worker_count = worker_count
        self.poll_interval = poll_interval
        self.worker_pool: list[TaggerWorker] = []

    def is_enabled(self) -> bool:
        """
        Check if workers are enabled.

        Returns:
            True if workers are enabled in DB meta or default config
        """
        meta = self.db.get_meta("worker_enabled")
        if meta is None:
            return self.default_enabled
        return meta == "true"

    def enable(self) -> None:
        """
        Enable workers (sets DB meta flag).
        """
        self.db.set_meta("worker_enabled", "true")
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
        self.db.set_meta("worker_enabled", "false")
        logging.info("[WorkerService] Workers disabled, waiting for active jobs to complete...")

        # Wait for all running jobs to finish before stopping threads
        if not self.wait_until_idle(timeout=60):
            logging.warning("[WorkerService] Timeout waiting for jobs to complete - forcing shutdown")

        self.stop_all_workers()
        logging.info("[WorkerService] All workers stopped")

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
            cur = self.db.conn.execute("SELECT COUNT(*) FROM queue WHERE status='running'")
            row = cur.fetchone()
            running_count = row[0] if row else 0

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
            cur = self.db.conn.execute("SELECT id FROM queue WHERE status='running'")
            running_job_ids = [row[0] for row in cur.fetchall()]

            for job_id in running_job_ids:
                self.db.update_job(job_id, "pending")
                jobs_reset += 1

        if jobs_reset > 0:
            logging.warning(f"[WorkerService] Reset {jobs_reset} orphaned job(s) to pending")

        return jobs_reset

    def start_workers(self, event_broker: Any | None = None) -> list[TaggerWorker]:
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
        if current_count >= self.worker_count:
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
            from nomarr.core.processor import process_file

            if self.processor_coord is None:
                # Fallback: direct processing (shouldn't happen after startup)
                return process_file(path, force)
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
        for i in range(current_count, self.worker_count):
            worker = TaggerWorker(
                db=self.db,
                queue=self.queue,
                interval=self.poll_interval,
                process_fn=process_via_pool,  # Route through process pool
                worker_id=i,
                event_broker=event_broker,  # Pass event broker for SSE updates
            )
            worker.start()
            self.worker_pool.append(worker)
            logging.info(f"[WorkerService] Started worker {i + 1}/{self.worker_count}")

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

    def get_status(self) -> dict[str, Any]:
        """
        Get worker status information.

        Returns:
            Dict with:
                - enabled: bool (from DB meta)
                - worker_count: int (configured max)
                - running: int (currently active)
                - workers: list of worker states
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
                    "name": worker.thread.name if hasattr(worker, "thread") else f"Worker-{i}",
                }
            )

        return {
            "enabled": enabled,
            "worker_count": self.worker_count,
            "running": running,
            "workers": workers,
        }

    def pause(self) -> dict[str, Any]:
        """
        Pause workers (disable and stop).

        Returns:
            Status dict after pausing
        """
        self.disable()
        return self.get_status()

    def resume(self, event_broker: Any | None = None) -> dict[str, Any]:
        """
        Resume workers (enable and start).

        Args:
            event_broker: Optional event broker for SSE updates

        Returns:
            Status dict after resuming
        """
        self.enable()
        self.start_workers(event_broker=event_broker)
        return self.get_status()
