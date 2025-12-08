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
import multiprocessing
import os
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar

from nomarr.components.queue import (
    get_active_jobs,
    get_next_job,
    get_queue_stats,
    mark_job_complete,
    mark_job_error,
)
from nomarr.helpers.dto.queue_dto import DequeueResult
from nomarr.persistence.db import Database

if TYPE_CHECKING:
    pass


# Type variable for worker result types (covariant for return types)
TResult = TypeVar("TResult", covariant=True)

# Queue type literal for type safety
QueueType = Literal["tag", "library", "calibration"]


# ----------------------------------------------------------------------
#  BaseWorker - Generic Background Worker
# ----------------------------------------------------------------------
class BaseWorker(multiprocessing.Process, Generic[TResult]):
    """
    Generic background worker for queue processing (multiprocessing-based).

    Features:
    - Polls database for pending jobs
    - Respects runtime pause/resume via DB meta `worker_enabled`
    - Process-safe job state transitions via DB
    - Graceful shutdown with job reset
    - Heartbeat tracking via health table (Phase 3: DB-based IPC)
    - Event publishing (optional)
    - Idle cache eviction
    - Rolling average processing time

    Type Parameters:
        TResult: The result type returned by process_fn (e.g., ProcessFileResult, dict[str, Any])

    Usage:
        worker = BaseWorker(
            name="TaggerWorker",
            queue_type="tag",
            process_fn=process_file,  # Your processing logic here
            db_path="/path/to/db.sqlite",
            event_broker=broker,
            worker_id=0
        )
        worker.start()  # Spawns a new process
    """

    def __init__(
        self,
        name: str,
        queue_type: QueueType,
        process_fn: Callable[[Database, str, bool], TResult],
        db_path: str,
        worker_id: int = 0,
        interval: int = 2,
    ):
        """
        Initialize generic worker process.

        Args:
            name: Worker process name (e.g., "TaggerWorker")
            queue_type: Queue type - "tag", "library", or "calibration"
            process_fn: Function to process jobs, signature: (db: Database, path: str, force: bool) -> TResult
            db_path: Path to database file (worker creates its own connection for multiprocessing safety)
            worker_id: Unique worker ID (for multi-worker setups)
            interval: Polling interval in seconds (default: 2)
        """
        super().__init__(daemon=True, name=f"{name}-{worker_id}")
        self.queue_type: QueueType = queue_type
        self.db_path = db_path
        self.db: Database | None = None  # Created in run() for process safety
        self.process_fn = process_fn
        self.worker_id = worker_id
        self.interval = max(1, int(interval))
        self.worker_name = name

        # Component ID for health tracking (e.g., "worker:tag:0")
        self.component_id = f"worker:{queue_type}:{worker_id}"

        # Worker state
        self._stop_event = multiprocessing.Event()
        self._shutdown = False
        self._is_busy = False
        self._last_heartbeat = 0.0
        self._heartbeat_interval = 5  # seconds
        self._cancel_requested = False
        self._current_job_id: int | None = None
        self._heartbeat_thread: threading.Thread | None = None

    # ---------------------------- Queue Operations (use components) ----------------------------

    def _dequeue(self) -> DequeueResult | None:
        """Dequeue next pending job using queue component."""
        if not self.db:
            return None
        job = get_next_job(self.db, self.queue_type)
        if not job:
            return None
        return DequeueResult(job_id=job["id"], file_path=job["path"], force=job["force"])

    def _mark_complete(self, job_id: int) -> None:
        """Mark job as complete using queue component."""
        if not self.db:
            return
        mark_job_complete(self.db, job_id, self.queue_type)

    def _mark_error(self, job_id: int, error: str) -> None:
        """Mark job as failed using queue component."""
        if not self.db:
            return
        mark_job_error(self.db, job_id, error, self.queue_type)

    def _queue_stats(self) -> dict[str, int]:
        """Get queue statistics using queue component."""
        if not self.db:
            return {"pending": 0, "running": 0, "complete": 0, "error": 0}
        return get_queue_stats(self.db, self.queue_type)

    def _get_active_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get active jobs using queue component."""
        if not self.db:
            return []
        return get_active_jobs(self.db, self.queue_type, limit=limit)

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

    def _heartbeat_loop(self) -> None:
        """Background thread that continuously updates heartbeat (prevents blocking during heavy processing)."""
        logging.info(f"[{self.name}] Heartbeat thread started")

        # Create dedicated DB connection for heartbeat thread (SQLite connections are NOT thread-safe)
        from nomarr.persistence.db import Database

        heartbeat_db = Database(self.db_path)

        try:
            while not self._shutdown:
                try:
                    heartbeat_db.health.update_heartbeat(
                        component=self.component_id,
                        status="healthy",
                        current_job=self._current_job_id,
                    )
                    self._last_heartbeat = time.time()
                except Exception as e:
                    logging.warning(f"[{self.name}] Heartbeat update failed: {e}")
                time.sleep(self._heartbeat_interval)
        finally:
            heartbeat_db.close()
            logging.info(f"[{self.name}] Heartbeat thread stopped")

    def _clear_current_job(self) -> None:
        """Clear current job and update health table (single source of truth)."""
        self._current_job_id = None
        if self.db:
            try:
                self.db.health.update_heartbeat(
                    component=self.component_id,
                    status="healthy",
                    current_job=None,
                )
            except Exception as e:
                logging.warning(f"[{self.name}] Failed to clear current_job in health: {e}")

    # ---------------------------- Worker Loop ----------------------------

    def run(self) -> None:
        """
        Main worker loop - polls and processes jobs.

        CRITICAL: Creates database connection in child process (required for multiprocessing).
        Each process must have its own sqlite3 connection - never share connections across processes.
        """
        # Create database connection in worker process (critical for multiprocessing safety)
        self.db = Database(self.db_path)

        # Mark worker as starting
        self.db.health.mark_starting(
            component=self.component_id,
            pid=os.getpid(),
        )

        # Start heartbeat thread (prevents blocking during heavy ML processing)
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name=f"{self.name}-Heartbeat"
        )
        self._heartbeat_thread.start()

        logging.info(f"[{self.name}] Background worker started")
        try:
            while not self._stop_event.is_set():
                try:
                    self._tick()
                except Exception:
                    logging.exception(f"[{self.name}] Worker loop error")
                time.sleep(self.interval)
        finally:
            # Stop heartbeat thread
            self._shutdown = True
            if self._heartbeat_thread and self._heartbeat_thread.is_alive():
                self._heartbeat_thread.join(timeout=2)

            # Mark worker as stopping
            if self.db:
                self.db.health.mark_stopping(
                    component=self.component_id,
                    exit_code=0,
                )
                self.db.close()

        logging.info(f"[{self.name}] Stopped")

    def _tick(self) -> None:
        """Single worker iteration - check for work and process if available."""
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

    def _get_next_job(self) -> DequeueResult | None:
        """
        Get next pending job from queue.

        Returns:
            DequeueResult or None if no jobs available
        """
        result = self._dequeue()
        if not result:
            return None

        logging.info(f"[{self.name}] Processing job {result.job_id}: {result.file_path} (force={result.force})")

        # Track current job for heartbeat (Phase 3: DB-based IPC)
        self._current_job_id = result.job_id

        # Publish job start event
        self._publish_job_state(result.job_id, result.file_path, "running")
        self._publish_queue_stats()

        return result

    def _process_job(self, job: DequeueResult) -> None:
        """
        Process a single job using the injected process_fn.

        Handles success, failure, and shutdown scenarios.
        """
        job_id = job.job_id
        path = job.file_path
        force = job.force

        try:
            self._is_busy = True
            t0 = time.time()

            # Call injected processing function with worker's DB connection (can return DTO or dict)
            result = self.process_fn(self.db, path, force)  # type: ignore[arg-type]

            elapsed = round(time.time() - t0, 2)

            # Mark job as done
            self._mark_complete(job_id)
            self._update_avg_time(elapsed)

            # Convert result to dict for event publishing
            # Support both ProcessFileResult DTOs and plain dicts
            if hasattr(result, "__dataclass_fields__"):
                # It's a dataclass DTO - convert to dict
                results_dict = {
                    field: getattr(result, field)
                    for field in result.__dataclass_fields__  # type: ignore[attr-defined]
                }
            elif isinstance(result, dict):
                # It's already a dict
                results_dict = result
            else:
                # Unknown type - convert to string representation
                results_dict = {"result": str(result)}

            # Publish completion event
            self._publish_job_state(job_id, path, "done", results=results_dict)
            self._publish_queue_stats()

            # Clear current job (single source of truth: health table)
            self._clear_current_job()

            logging.info(f"[{self.name}] ✅ Job {job_id} done in {elapsed}s")

        except KeyboardInterrupt:
            # Job was cancelled via cancel() - mark as error with cancellation message
            self._mark_error(job_id, "Cancelled by user")

            self._publish_job_state(job_id, path, "error", error="Cancelled by user")
            self._publish_queue_stats()

            # Clear current job (single source of truth: health table)
            self._clear_current_job()

            logging.info(f"[{self.name}] 🔄 Job {job_id} cancelled")
            self._cancel_requested = False  # Reset flag

        except RuntimeError as e:
            # RuntimeError during shutdown - mark as error
            if self._shutdown or "shutting down" in str(e).lower():
                self._mark_error(job_id, "Shutdown requested")

                self._publish_job_state(job_id, path, "error", error="Shutdown requested")
                self._publish_queue_stats()

                # Clear current job (single source of truth: health table)
                self._clear_current_job()

                logging.info(f"[{self.name}] 🔄 Job {job_id} marked error (shutdown)")
            else:
                # Other RuntimeError - mark as error
                self._mark_job_error(job_id, path, str(e))

        except Exception as e:
            # General error - mark job as failed
            self._mark_job_error(job_id, path, str(e))

        finally:
            self._is_busy = False
            # Ensure current job is cleared (Phase 3: DB-based IPC)
            self._current_job_id = None

    def _mark_job_error(self, job_id: int, path: str, error_message: str) -> None:
        """Mark job as failed and publish error event."""
        self._mark_error(job_id, error_message)

        self._publish_job_state(job_id, path, "error", error=error_message)
        self._publish_queue_stats()

        logging.error(f"[{self.name}] ❌ Job {job_id} failed: {error_message}")

    # ---------------------------- Helper Methods ----------------------------

    def _is_paused(self) -> bool:
        """Check if worker is paused via DB meta."""
        if not self.db:
            return True  # Paused if no DB connection
        meta = self.db.meta.get("worker_enabled")
        return bool(meta == "false")

    def _check_cache_eviction(self) -> None:
        """Periodically check and evict idle ML model cache."""
        try:
            from nomarr.components.ml.ml_cache_comp import check_and_evict_idle_cache

            check_and_evict_idle_cache()
        except Exception as e:
            logging.debug(f"[{self.name}] Cache check error: {e}")

    def _update_avg_time(self, job_elapsed: float) -> None:
        """Update rolling average processing time."""
        if not self.db:
            return

        current_avg_str = self.db.meta.get("avg_processing_time")
        current_avg: float
        if current_avg_str:
            current_avg = float(current_avg_str)
        else:
            # No stored average yet - use current job time as initial estimate
            current_avg = job_elapsed

        # Weighted average: 80% old, 20% new
        new_avg = (current_avg * 0.8) + (job_elapsed * 0.2)
        self.db.meta.set("avg_processing_time", str(new_avg))

    # ---------------------------- Event Publishing ----------------------------

    def _publish_job_state(
        self, job_id: int, path: str, status: str, results: dict[str, Any] | None = None, error: str | None = None
    ) -> None:
        """Publish job state to DB meta table (Phase 3.6: IPC for multiprocessing)."""
        if not self.db:
            return

        try:
            # Ensure we're in a clean transaction state
            if self.db.conn.in_transaction:
                self.db.conn.commit()

            # Write to DB meta table - StateBroker will poll and broadcast to SSE
            self.db.meta.set(f"job:{job_id}:status", status)
            self.db.meta.set(f"job:{job_id}:path", path)
            self.db.meta.set(f"worker:{self.queue_type}:{self.worker_id}:current_job", str(job_id))

            if results:
                import json

                self.db.meta.set(f"job:{job_id}:results", json.dumps(results))
            if error:
                self.db.meta.set(f"job:{job_id}:error", error)
        except Exception as e:
            logging.error(f"[{self.name}] Failed to publish job state: {e}")

    def _publish_queue_stats(self) -> None:
        """Publish queue statistics to DB meta table (Phase 3.6: IPC for multiprocessing)."""
        if not self.db:
            return

        try:
            # Get current queue stats
            stats = self._queue_stats()

            # Write to DB meta table - StateBroker will poll and broadcast to SSE
            import json

            self.db.meta.set(f"queue:{self.queue_type}:stats", json.dumps(stats))

            # Store timestamp for freshness tracking
            import time

            self.db.meta.set(f"queue:{self.queue_type}:last_update", str(int(time.time() * 1000)))
        except Exception as e:
            logging.error(f"[{self.name}] Failed to publish queue stats: {e}")
