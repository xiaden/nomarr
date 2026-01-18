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
QueueType = Literal["tag", "library"]


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
        worker_id: int = 0,
        interval: int = 2,
        db_config_override: dict[str, str] | None = None,
    ):
        """
        Initialize generic worker process.

        Args:
            name: Worker process name (e.g., "TaggerWorker")
            queue_type: Queue type - "tag", "library", or "calibration"
            process_fn: Function to process jobs, signature: (db: Database, path: str, force: bool) -> TResult
            worker_id: Unique worker ID (for multi-worker setups)
            interval: Polling interval in seconds (default: 2)
            db_config_override: Database config override for tests ONLY.
                Do NOT use in production - workers read from environment.
                Only for single-process test harness or non-fork contexts.

        Note:
            Database connection is created in run() method.
            Requires ARANGO_HOST env var. Password is read from config file.
            App startup validates environment before spawning workers.
        """
        super().__init__(daemon=True, name=f"{name}-{worker_id}")
        self.queue_type: QueueType = queue_type
        self.db: Database | None = None  # Created in run() for process safety
        self.db_config_override = db_config_override  # Test-only override
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
        self._current_job_id: str | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._cache_loaded = True  # True for workers without expensive cache (scanner, recalibration)

    # ---------------------------- Queue Operations (use components) ----------------------------

    def _dequeue(self) -> DequeueResult | None:
        """Dequeue next pending job using queue component."""
        if not self.db:
            return None
        job = get_next_job(self.db, self.queue_type)
        if not job:
            return None
        return DequeueResult(_id=job["_id"], file_path=job["path"], force=job["force"])

    def _mark_complete(self, job_id: str) -> None:
        """Mark job as complete using queue component."""
        if not self.db:
            return
        mark_job_complete(self.db, job_id, self.queue_type)

    def _mark_error(self, job_id: str, error: str) -> None:
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

    def _check_gpu_available(self) -> tuple[bool, str]:
        """
        Check GPU availability via DB meta table (cached state from GPUHealthMonitor).

        Returns:
            Tuple of (is_available, status_message)
            - (True, "available") if GPU is ready
            - (False, "unavailable: <reason>") if probe ran but GPU not accessible
            - (False, "unknown: <reason>") if health data stale/missing

        Note:
            This reads cached GPU health state written by GPUHealthMonitor.
            Does NOT run nvidia-smi inline (non-blocking preflight check).
        """
        import json

        from nomarr.components.platform import check_gpu_health_staleness

        if not self.db:
            # No DB - cannot check GPU
            return False, "unknown: Database not available"

        try:
            # Read atomic GPU health JSON from DB meta table
            health_json = self.db.meta.get("gpu:health")
            if not health_json:
                # GPU health not yet initialized
                return False, "unknown: GPU health not yet initialized (monitor may not be running)"

            # Parse JSON blob
            health_data = json.loads(health_json)
            last_check_at = health_data.get("probe_time")

            # Check for staleness
            is_stale = check_gpu_health_staleness(last_check_at)

            if is_stale:
                # Data too old - monitor may be stuck
                return False, "unknown: GPU health data stale (monitor may be stuck)"

            # Fresh data - check actual status
            status = health_data.get("status", "unknown")
            if status == "available":
                return True, "available"
            elif status == "unavailable":
                error = health_data.get("error_summary", "GPU not accessible")
                return False, f"unavailable: {error}"
            else:
                return False, f"unknown: {health_data.get('error_summary', 'Status unknown')}"

        except Exception as e:
            logging.error(f"[{self.name}] Error checking GPU availability: {e}")
            return False, f"unknown: {e!s}"

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

        # Create dedicated DB connection for heartbeat thread
        from nomarr.persistence.db import Database

        if self.db_config_override:
            heartbeat_db = Database(**self.db_config_override)
        else:
            heartbeat_db = Database()

        try:
            while not self._shutdown:
                try:
                    # Update heartbeat with cache_loaded metadata
                    import json

                    heartbeat_db.health.upsert_component(
                        component_id=self.component_id,
                        component_type="worker",
                        data={
                            "status": "healthy",
                            "current_job": self._current_job_id,
                            "metadata": json.dumps({"cache_loaded": self._cache_loaded}),
                        },
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
                import json

                self.db.health.upsert_component(
                    component_id=self.component_id,
                    component_type="worker",
                    data={
                        "status": "healthy",
                        "current_job": None,
                        "metadata": json.dumps({"cache_loaded": self._cache_loaded}),
                    },
                )
            except Exception as e:
                logging.warning(f"[{self.name}] Failed to clear current_job in health: {e}")

    # ---------------------------- Worker Loop ----------------------------

    def run(self) -> None:
        """
        Main worker loop - polls and processes jobs.

        CRITICAL: Creates database connection in child process from environment variables.
        This is required for multiprocessing safety - each process must have its own connection.
        Environment variables are validated at app startup, so if we get here, they exist.
        """
        # Create database connection from environment (or test override)
        if self.db_config_override:
            # Test mode: explicit config
            self.db = Database(**self.db_config_override)
        else:
            # Production mode: environment variables (validated at startup)
            self.db = Database()

        # Mark worker as starting with cache_loaded metadata
        import json

        self.db.health.upsert_component(
            component_id=self.component_id,
            component_type="worker",
            data={
                "status": "starting",
                "pid": os.getpid(),
                "metadata": json.dumps({"cache_loaded": self._cache_loaded}),
            },
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
                    component_id=self.component_id,
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

        logging.debug(f"[{self.name}] Processing job {result._id}: {result.file_path} (force={result.force})")

        # Track current job for heartbeat (Phase 3: DB-based IPC)
        self._current_job_id = result._id

        # CRITICAL: Update health record IMMEDIATELY with current_job
        # Don't wait for heartbeat thread (5s delay) - worker might crash before then
        if self.db:
            try:
                self.db.health.update_heartbeat(
                    component_id=self.component_id,
                    status="healthy",
                    current_job=self._current_job_id,
                )
            except Exception as e:
                logging.warning(f"[{self.name}] Failed to set current_job in health immediately: {e}")

        # Publish job start event
        self._publish_job_state(result._id, result.file_path, "running")
        self._publish_queue_stats()

        return result

    def _process_job(self, job: DequeueResult) -> None:
        """
        Process a single job using the injected process_fn.

        Handles success, failure, and shutdown scenarios.
        """
        job_id = job._id
        path = job.file_path
        force = job.force

        try:
            self._is_busy = True
            t0 = time.time()

            # GPU preflight check for ML tagging workers (tag queue only)
            if self.queue_type == "tag":
                gpu_available, gpu_status = self._check_gpu_available()
                if not gpu_available:
                    # GPU unavailable - fail fast without attempting ML inference
                    error_msg = f"GPU unavailable: {gpu_status} (check /health/gpu endpoint)"
                    logging.error(f"[{self.name}] GPU preflight failed for job {job_id}: {error_msg}")
                    self._mark_error(job_id, error_msg)
                    self._publish_job_state(job_id, path, "error", error=error_msg)
                    self._publish_queue_stats()
                    self._clear_current_job()
                    self._cleanup_job_metadata(job_id)
                    return

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

            # Clean up job metadata from meta table after a short delay
            # (gives StateBroker time to poll and broadcast before cleanup)
            time.sleep(0.5)
            self._cleanup_job_metadata(job_id)

            # Mark cache as loaded after first successful job (for workers with expensive ML cache)
            if not self._cache_loaded:
                self._cache_loaded = True
                logging.info(f"[{self.name}] Cache loaded (TF models initialized)")

            logging.debug(f"[{self.name}] ✅ Job {job_id} done in {elapsed}s")

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

    def _mark_job_error(self, job_id: str, path: str, error_message: str) -> None:
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
        self, job_id: str, path: str, status: str, results: dict[str, Any] | None = None, error: str | None = None
    ) -> None:
        """Publish job state to DB meta table (Phase 3.6: IPC for multiprocessing)."""
        if not self.db:
            return

        try:
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

    def _cleanup_job_metadata(self, job_id: str) -> None:
        """Clean up job metadata from meta table after job completion."""
        if not self.db:
            return

        try:
            # Remove job metadata keys to prevent stale data in SSE stream
            self.db.meta.delete(f"job:{job_id}:status")
            self.db.meta.delete(f"job:{job_id}:path")
            self.db.meta.delete(f"job:{job_id}:results")
            self.db.meta.delete(f"job:{job_id}:error")
        except Exception as e:
            logging.error(f"[{self.name}] Failed to cleanup job metadata: {e}")
