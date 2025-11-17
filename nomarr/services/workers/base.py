#!/usr/bin/env python3
# ======================================================================
#  Essentia Autotag - Generic Worker Base Class
"""
base.py
────────
Generic background worker that polls a queue and processes jobs.

Supports dependency injection of processing logic, making it reusable
for different job types (tagging, library scanning, etc.).
"""
# ======================================================================

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from nomarr.persistence.db import Database
from nomarr.services.queue import ProcessingQueue


# ----------------------------------------------------------------------
#  BaseWorker - Generic Background Worker
# ----------------------------------------------------------------------
class BaseWorker(threading.Thread):
    """
    Generic background worker for queue processing.

    Features:
    - Polls database for pending jobs
    - Respects runtime pause/resume via DB meta `worker_enabled`
    - Thread-safe job state transitions
    - Graceful shutdown with job reset
    - Heartbeat tracking
    - Event publishing (optional)
    - Idle cache eviction
    - Rolling average processing time

    Usage:
        worker = BaseWorker(
            name="TaggerWorker",
            queue=queue,
            process_fn=process_file,  # Your processing logic here
            db=db,
            worker_id=0,
            event_broker=None
        )
        worker.start()
    """

    def __init__(
        self,
        name: str,
        queue: ProcessingQueue,
        process_fn: Callable[[str, bool], dict[str, Any]],
        db: Database,
        event_broker: Any,
        worker_id: int = 0,
        interval: int = 2,
    ):
        """
        Initialize generic worker.

        Args:
            name: Worker thread name (e.g., "TaggerWorker")
            queue: ProcessingQueue instance for job operations
            process_fn: Function to process jobs, signature: (path: str, force: bool) -> dict
            db: Database instance for meta operations
            event_broker: Event broker for SSE state updates (required)
            worker_id: Unique worker ID (for multi-worker setups)
            interval: Polling interval in seconds (default: 2)
        """
        super().__init__(daemon=True, name=f"{name}-{worker_id}")
        self.queue = queue
        self.db = db
        self.process_fn = process_fn
        self.worker_id = worker_id
        self.interval = max(1, int(interval))
        self.worker_name = name

        # Worker state
        self._stop_event = threading.Event()
        self._shutdown = False
        self._is_busy = False
        self._last_heartbeat = 0
        self._event_broker = event_broker
        self._cancel_requested = False

    # ---------------------------- Control Methods ----------------------------

    def stop(self) -> None:
        """Signal worker to stop gracefully."""
        self._shutdown = True
        self._stop_event.set()

    def cancel(self) -> None:
        """Request cancellation of current job."""
        self._cancel_requested = True
        logging.info(f"[{self.name}] Job cancellation requested")

    def is_busy(self) -> bool:
        """Check if worker is currently processing a job."""
        return self._is_busy

    def last_heartbeat(self) -> int:
        """Get timestamp of last heartbeat."""
        return int(self._last_heartbeat)

    # ---------------------------- Worker Loop ----------------------------

    def run(self) -> None:
        """Main worker loop - polls and processes jobs."""
        logging.info(f"[{self.name}] Background worker started")
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception:
                logging.exception(f"[{self.name}] Worker loop error")
            time.sleep(self.interval)
        logging.info(f"[{self.name}] Stopped")

    def _tick(self) -> None:
        """Single worker iteration - check for work and process if available."""
        self._last_heartbeat = int(time.time())

        # Periodic cache eviction
        self._check_cache_eviction()

        # Don't pick up new work during shutdown
        if self._shutdown:
            return

        # Check if worker is paused at runtime
        if self._is_paused():
            return

        # Check if cancellation was requested
        if self._cancel_requested:
            logging.debug(f"[{self.name}] Skipping new work due to cancel request")
            self._cancel_requested = False  # Reset for next job
            return

        # Get next pending job
        job = self._get_next_job()
        if not job:
            return

        # Process job (outside lock)
        self._process_job(job)

    # ---------------------------- Job Processing ----------------------------

    def _get_next_job(self) -> dict[str, Any] | None:
        """
        Get next pending job from tag queue.

        Returns:
            Job dict with keys: id, path, force, or None if no jobs available
        """
        with self.queue.lock:
            job = self.db.queue.get_next_pending_job()
            if not job:
                return None

            job_id = job["id"]
            path = job["path"]
            force = job["force"]

            # Mark job as running
            self.db.queue.update_job(job_id, "running")
            logging.info(f"[{self.name}] Processing job {job_id}: {path} (force={force})")

            # Publish job start event
            self._publish_job_state(job_id, path, "running")
            self._publish_queue_stats()

            return {"id": job_id, "path": path, "force": force}

    def _process_job(self, job: dict[str, Any]) -> None:
        """
        Process a single job using the injected process_fn.

        Handles success, failure, and shutdown scenarios.
        """
        job_id = job["id"]
        path = job["path"]
        force = job["force"]

        try:
            self._is_busy = True
            t0 = time.time()

            # Call injected processing function
            summary = self.process_fn(path, force)

            elapsed = round(time.time() - t0, 2)

            # Mark job as done
            with self.queue.lock:
                self.db.queue.update_job(job_id, "done", results=summary)
                self._update_avg_time(elapsed)

            # Publish completion event
            self._publish_job_state(job_id, path, "done", results=summary)
            self._publish_queue_stats()

            logging.info(f"[{self.name}] ✅ Job {job_id} done in {elapsed}s")

        except KeyboardInterrupt:
            # Job was cancelled via cancel() - reset to pending
            with self.queue.lock:
                self.db.queue.update_job(job_id, "pending")

            self._publish_job_state(job_id, path, "pending")
            self._publish_queue_stats()

            logging.info(f"[{self.name}] 🔄 Job {job_id} cancelled, reset to pending")
            self._cancel_requested = False  # Reset flag

        except RuntimeError as e:
            # RuntimeError during shutdown - reset job to pending
            if self._shutdown or "shutting down" in str(e).lower():
                with self.queue.lock:
                    self.db.queue.update_job(job_id, "pending")

                self._publish_job_state(job_id, path, "pending")
                self._publish_queue_stats()

                logging.info(f"[{self.name}] 🔄 Job {job_id} reset to pending (shutdown)")
            else:
                # Other RuntimeError - mark as error
                self._mark_job_error(job_id, path, str(e))

        except Exception as e:
            # General error - mark job as failed
            self._mark_job_error(job_id, path, str(e))

        finally:
            self._is_busy = False

    def _mark_job_error(self, job_id: int, path: str, error_message: str) -> None:
        """Mark job as failed and publish error event."""
        with self.queue.lock:
            self.db.queue.update_job(job_id, "error", error_message=error_message)

        self._publish_job_state(job_id, path, "error", error=error_message)
        self._publish_queue_stats()

        logging.error(f"[{self.name}] ❌ Job {job_id} failed: {error_message}")

    # ---------------------------- Helper Methods ----------------------------

    def _is_paused(self) -> bool:
        """Check if worker is paused via DB meta."""
        meta = self.db.meta.get("worker_enabled")
        return meta == "false"

    def _check_cache_eviction(self) -> None:
        """Periodically check and evict idle ML model cache."""
        try:
            from nomarr.ml.cache import check_and_evict_idle_cache

            check_and_evict_idle_cache()
        except Exception as e:
            logging.debug(f"[{self.name}] Cache check error: {e}")

    def _update_avg_time(self, job_elapsed: float) -> None:
        """Update rolling average processing time."""
        current_avg_str = self.db.meta.get("avg_processing_time")
        current_avg: float
        if current_avg_str:
            current_avg = float(current_avg_str)
        else:
            # Calculate from last 5 jobs if no stored average
            rows = self.db.queue.get_recent_done_jobs_timing(limit=5)
            if rows:
                times = [(finished - started) / 1000.0 for finished, started in rows]
                current_avg = sum(times) / len(times)
            else:
                current_avg = 100.0  # Default estimate

        # Weighted average: 80% old, 20% new
        new_avg = (current_avg * 0.8) + (job_elapsed * 0.2)
        self.db.meta.set("avg_processing_time", str(new_avg))

    # ---------------------------- Event Publishing ----------------------------

    def _publish_job_state(
        self, job_id: int, path: str, status: str, results: dict[str, Any] | None = None, error: str | None = None
    ) -> None:
        """Publish job state update to event broker."""
        job_state = {
            "id": job_id,
            "path": path,
            "status": status,
        }

        if results:
            job_state["results"] = results
        if error:
            job_state["error"] = error

        try:
            self._event_broker.update_job_state(job_id, **job_state)
        except Exception as e:
            logging.error(f"[{self.name}] Failed to publish job state: {e}")

    def _publish_queue_stats(self) -> None:
        """Publish queue statistics to event broker."""
        try:
            # Get current queue stats from persistence layer
            stats = self.db.queue.queue_stats()

            # Get active jobs (pending + running) from persistence layer
            jobs = self.db.queue.get_active_jobs(limit=50)

            queue_state = {"stats": stats, "jobs": jobs}
            self._event_broker.update_queue_state(**queue_state)
        except Exception as e:
            logging.error(f"[{self.name}] Failed to publish queue stats: {e}")
