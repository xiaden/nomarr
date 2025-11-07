#!/usr/bin/env python3
# ======================================================================
#  Essentia Autotag - Job Queue Manager
"""
queue.py
─────────────
#  Simple persistent queue built on Database
"""
# ======================================================================

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from nomarr.core.processor import process_file
from nomarr.data.db import Database


# ----------------------------------------------------------------------
#  JobQueue
# ----------------------------------------------------------------------
class JobQueue:
    def __init__(self, db: Database):
        """
        Wraps Database queue operations and provides thread-safe control
        for job submission and tracking.
        """
        self.db = db
        self.lock = threading.Lock()

    # ---------------------------- Job Lifecycle ----------------------------
    def add(self, path: str, force: bool = False) -> int:
        """
        Enqueue a new file processing job.
        """
        with self.lock:
            job_id = self.db.enqueue(path, force)
            logging.info(f"[Queue] Added job {job_id} for {path}")
            return job_id

    def start(self, job_id: int):
        """
        Mark a job as running.
        """
        with self.lock:
            self.db.update_job(job_id, "running")

    def mark_done(self, job_id: int, results: dict[str, Any] | None = None):
        """
        Mark a job as complete with optional results.
        """
        with self.lock:
            self.db.update_job(job_id, "done", results=results)

    def mark_error(self, job_id: int, error_message: str):
        """
        Mark a job as failed.
        """
        with self.lock:
            self.db.update_job(job_id, "error", error_message=error_message)

    # ---------------------------- Status ----------------------------
    def get(self, job_id: int) -> Job | None:
        """
        Fetch job info by ID.
        """
        row = self.db.job_status(job_id)
        if not row:
            return None
        return Job(**row)

    def depth(self) -> int:
        """
        Return number of pending/running jobs.
        """
        return self.db.queue_depth()

    def list(self, limit: int = 25, offset: int = 0, status: str | None = None) -> tuple[list[Job], int]:
        """
        List jobs with pagination and optional status filter.

        Args:
            limit: Maximum number of jobs to return
            offset: Number of jobs to skip (for pagination)
            status: Filter by status (pending/running/done/error), or None for all

        Returns:
            Tuple of (jobs list, total count matching filter)
        """
        # Build query with optional status filter
        if status:
            query = "SELECT * FROM queue WHERE status = ? ORDER BY id DESC LIMIT ? OFFSET ?"
            count_query = "SELECT COUNT(*) FROM queue WHERE status = ?"
            params = (status, limit, offset)
            count_params = (status,)
        else:
            query = "SELECT * FROM queue ORDER BY id DESC LIMIT ? OFFSET ?"
            count_query = "SELECT COUNT(*) FROM queue"
            params = (limit, offset)
            count_params = ()

        # Get total count
        cur = self.db.conn.execute(count_query, count_params)
        total = cur.fetchone()[0]

        # Get jobs
        cur = self.db.conn.execute(query, params)
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]
        jobs = [Job(**dict(zip(columns, r, strict=False))) for r in rows]

        return jobs, total

    def flush(self, statuses: list[str] | None = None) -> int:
        """
        Remove jobs by status from the queue.

        Args:
            statuses: List of statuses to remove (e.g., ["done", "error"]).
                     If None, defaults to ["done", "error"] (finished jobs).
                     Valid: "pending", "done", "error".
                     Cannot flush "running" jobs.

        Returns:
            Number of jobs removed.

        Raises:
            ValueError: If invalid status or attempting to flush "running" jobs.
        """
        # Default to finished jobs
        statuses_to_flush = statuses if statuses is not None else ["done", "error"]

        # Check for running status first (explicit error message)
        if "running" in statuses_to_flush:
            raise ValueError("Cannot flush 'running' jobs")

        # Validate remaining statuses
        valid_statuses = {"pending", "done", "error"}
        invalid = [s for s in statuses_to_flush if s not in valid_statuses]
        if invalid:
            raise ValueError(f"Invalid statuses: {invalid}")

        with self.lock:
            query = f"DELETE FROM queue WHERE status IN ({','.join('?' * len(statuses_to_flush))})"
            cursor = self.db.conn.execute(query, tuple(statuses_to_flush))
            count = cursor.rowcount
            self.db.conn.commit()
            return count

    def reset_running_to_pending(self) -> int:
        """
        Reset any jobs stuck in 'running' state back to 'pending'.
        Used during startup to recover from crashes/restarts.
        Returns the number of jobs reset.
        """
        with self.lock:
            return self.db.reset_running_to_pending()


# ----------------------------------------------------------------------
#  Job Dataclass
# ----------------------------------------------------------------------
class Job:
    def __init__(self, **row):
        self.id = row.get("id")
        self.path = row.get("path")
        self.status = row.get("status", "pending")
        self.created_at = row.get("created_at")
        self.started_at = row.get("started_at")
        self.finished_at = row.get("finished_at")
        self.error_message = row.get("error_message")
        self.force = bool(row.get("force", 0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error_message": self.error_message,
            "force": self.force,
        }


# ----------------------------------------------------------------------
#  Optional: Background Worker
# ----------------------------------------------------------------------
class TaggerWorker(threading.Thread):
    """
    Reusable background worker for the tagger.

    - Polls the DB for pending jobs
    - Respects DB meta key `worker_enabled` (if set to 'false', the worker idles)
    - Uses the provided JobQueue.lock when mutating DB state
    - Calls `process_file()` outside the lock to avoid holding DB lock during long work
    - Publishes state updates to event_broker if provided
    """

    def __init__(
        self,
        db: Database,
        queue: JobQueue,
        interval: int = 2,
        process_fn: Callable[[str, bool], dict[str, Any]] | None = None,
        worker_id: int = 0,
        event_broker: Any | None = None,
    ):
        super().__init__(daemon=True, name=f"TaggerWorker-{worker_id}")
        self.db = db
        self.queue = queue
        self.interval = max(1, int(interval))
        self.worker_id = worker_id
        self._stop_event = threading.Event()
        self._shutdown = False  # Track if we're in shutdown mode
        self._is_busy = False  # Track if currently processing a job
        self._last_heartbeat = 0
        self._event_broker = event_broker  # Optional SSE state broker
        # Allow injecting a process function (e.g., via API's ProcessingThread)
        self._process_fn: Callable[[str, bool], dict[str, Any]] = process_fn or (lambda p, f: process_file(p, f))

    def stop(self) -> None:
        self._shutdown = True  # Signal shutdown before stopping
        self._stop_event.set()

    def is_busy(self) -> bool:
        """Check if worker is currently processing a job."""
        return self._is_busy

    def last_heartbeat(self) -> int:
        return int(self._last_heartbeat)

    def run(self) -> None:
        logging.info(f"[TaggerWorker-{self.worker_id}] Background worker started")
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception:
                logging.exception(f"[TaggerWorker-{self.worker_id}] Worker loop error")
            time.sleep(self.interval)
        logging.info(f"[TaggerWorker-{self.worker_id}] Stopped")

    def _tick(self) -> None:
        self._last_heartbeat = int(time.time())

        # Check for idle cache eviction periodically
        try:
            from nomarr.ml.cache import check_and_evict_idle_cache

            check_and_evict_idle_cache()
        except Exception as e:
            logging.debug(f"[TaggerWorker-{self.worker_id}] Cache check error: {e}")

        # If shutting down, don't pick up new work
        if self._shutdown:
            return

        # If paused at runtime, idle
        meta = self.db.get_meta("worker_enabled")
        if meta == "false":
            return

        # Select next pending job under the queue lock
        with self.queue.lock:
            cur = self.db.conn.execute(
                "SELECT id, path, force FROM queue WHERE status='pending' ORDER BY id ASC LIMIT 1"
            )
            row = cur.fetchone()
            if not row:
                return
            job_id, path, force_int = row
            force = bool(force_int)
            self.db.update_job(job_id, "running")
            logging.info(f"[TaggerWorker-{self.worker_id}] Processing job {job_id}: {path} (force={force})")

            # Publish job start event
            if self._event_broker:
                self._publish_job_state(job_id, path, "running")
                self._publish_queue_stats()

        # Do not hold lock during processing
        try:
            self._is_busy = True  # Mark worker as busy
            t0 = time.time()
            summary = self._process_fn(path, force)
            elapsed = round(time.time() - t0, 2)
            with self.queue.lock:
                self.db.update_job(job_id, "done", results=summary)
                # Update rolling average processing time
                self._update_avg_time(elapsed)

            # Publish job completion event
            if self._event_broker:
                self._publish_job_state(job_id, path, "done", results=summary)
                self._publish_queue_stats()

            logging.info(f"[TaggerWorker-{self.worker_id}] ✅ Job {job_id} done in {elapsed}s")
        except RuntimeError as e:
            # RuntimeError during shutdown - reset job to pending for next startup
            if self._shutdown or "shutting down" in str(e).lower():
                with self.queue.lock:
                    self.db.update_job(job_id, "pending")

                # Publish job reset event
                if self._event_broker:
                    self._publish_job_state(job_id, path, "pending")
                    self._publish_queue_stats()

                logging.info(f"[TaggerWorker-{self.worker_id}] 🔄 Job {job_id} reset to pending (shutdown)")
            else:
                # Other RuntimeError - mark as error
                with self.queue.lock:
                    self.db.update_job(job_id, "error", error_message=str(e))

                # Publish job error event
                if self._event_broker:
                    self._publish_job_state(job_id, path, "error", error=str(e))
                    self._publish_queue_stats()

                logging.error(f"[TaggerWorker-{self.worker_id}] ❌ Job {job_id} failed: {e}")
        except Exception as e:
            with self.queue.lock:
                self.db.update_job(job_id, "error", error_message=str(e))

            # Publish job error event
            if self._event_broker:
                self._publish_job_state(job_id, path, "error", error=str(e))
                self._publish_queue_stats()

            logging.error(f"[TaggerWorker-{self.worker_id}] ❌ Job {job_id} failed: {e}")
        finally:
            self._is_busy = False  # Mark worker as idle

    def _update_avg_time(self, job_elapsed: float):
        """Update rolling average processing time."""
        current_avg = self.db.get_meta("avg_processing_time")
        if current_avg:
            current_avg = float(current_avg)
        else:
            # Calculate from last 5 jobs if no stored average
            cur = self.db.conn.execute(
                """
                SELECT finished_at, started_at
                FROM queue
                WHERE status='done' AND finished_at IS NOT NULL AND started_at IS NOT NULL
                ORDER BY finished_at DESC
                LIMIT 5
                """
            )
            rows = cur.fetchall()
            if rows:
                times = [(finished - started) / 1000.0 for finished, started in rows]
                current_avg = sum(times) / len(times)
            else:
                current_avg = 100.0  # Default estimate

        # Weighted average: 80% old, 20% new
        new_avg = (current_avg * 0.8) + (job_elapsed * 0.2)
        self.db.set_meta("avg_processing_time", str(new_avg))

    def _publish_job_state(
        self, job_id: int, path: str, status: str, results: dict[str, Any] | None = None, error: str | None = None
    ):
        """Publish job state update to event broker."""
        if not self._event_broker:
            return

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
            logging.error(f"[TaggerWorker-{self.worker_id}] Failed to publish job state: {e}")

    def _publish_queue_stats(self):
        """Publish queue statistics to event broker."""
        if not self._event_broker:
            return

        try:
            # Get current queue stats
            cur = self.db.conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) as running,
                    SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as completed
                FROM queue
                """
            )
            row = cur.fetchone()
            stats = {"pending": row[0] or 0, "running": row[1] or 0, "completed": row[2] or 0}

            # Get active jobs (pending + running)
            cur = self.db.conn.execute(
                """
                SELECT id, path, status, created_at, started_at
                FROM queue
                WHERE status IN ('pending', 'running')
                ORDER BY id ASC
                LIMIT 50
                """
            )
            jobs = []
            for row in cur.fetchall():
                jobs.append(
                    {
                        "id": row[0],
                        "path": row[1],
                        "status": row[2],
                        "created_at": row[3],
                        "started_at": row[4],
                    }
                )

            queue_state = {"stats": stats, "jobs": jobs}
            self._event_broker.update_queue_state(**queue_state)
        except Exception as e:
            logging.error(f"[TaggerWorker-{self.worker_id}] Failed to publish queue stats: {e}")
