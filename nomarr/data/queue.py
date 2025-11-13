#!/usr/bin/env python3
# ======================================================================
#  Essentia Autotag - Processing Queue Data Access
"""
queue.py
─────────────
#  Thin data access layer for the ML processing queue
"""
# ======================================================================

from __future__ import annotations

import logging
import threading
from typing import Any

from nomarr.data.db import Database


# ----------------------------------------------------------------------
#  ProcessingQueue - Data Access Layer
# ----------------------------------------------------------------------
class ProcessingQueue:
    """
    Thin data access layer for the ML processing queue table.

    Provides thread-safe CRUD operations for queue jobs.
    Business logic should live in QueueService, not here.
    """

    def __init__(self, db: Database):
        """Initialize queue with database connection and lock."""
        self.db = db
        self.lock = threading.Lock()

    # ---------------------------- Basic CRUD Operations ----------------------------

    def add(self, path: str, force: bool = False) -> int:
        """Add a file to the processing queue."""
        with self.lock:
            job_id = self.db.enqueue(path, force)
            logging.debug(f"[ProcessingQueue] Added job {job_id} for {path}")
            return job_id

    def get(self, job_id: int) -> Job | None:
        """Get job by ID."""
        row = self.db.job_status(job_id)
        if not row:
            return None
        return Job(**row)

    def delete(self, job_id: int) -> int:
        """Delete a job by ID. Returns 1 if deleted, 0 if not found."""
        with self.lock:
            cursor = self.db.conn.execute("DELETE FROM tag_queue WHERE id=?", (job_id,))
            self.db.conn.commit()
            return cursor.rowcount

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
            query = "SELECT * FROM tag_queue WHERE status = ? ORDER BY id DESC LIMIT ? OFFSET ?"
            count_query = "SELECT COUNT(*) FROM tag_queue WHERE status = ?"
            params = (status, limit, offset)
            count_params = (status,)
        else:
            query = "SELECT * FROM tag_queue ORDER BY id DESC LIMIT ? OFFSET ?"
            count_query = "SELECT COUNT(*) FROM tag_queue"
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

    def update_status(self, job_id: int, status: str, **kwargs) -> None:
        """Update job status and optional fields."""
        with self.lock:
            self.db.update_job(job_id, status, **kwargs)

    def start(self, job_id: int) -> None:
        """Mark a job as running."""
        self.update_status(job_id, "running")

    def mark_done(self, job_id: int, results: dict[str, Any] | None = None) -> None:
        """Mark a job as complete with optional results."""
        self.update_status(job_id, "done", results=results)

    def mark_error(self, job_id: int, error_message: str) -> None:
        """Mark a job as failed."""
        self.update_status(job_id, "error", error_message=error_message)

    def depth(self) -> int:
        """Return number of pending/running jobs."""
        return self.db.queue_depth()

    def delete_by_status(self, statuses: list[str]) -> int:
        """
        Delete jobs by status.

        Args:
            statuses: List of statuses to delete

        Returns:
            Number of jobs deleted
        """
        with self.lock:
            placeholders = ",".join("?" * len(statuses))
            query = f"DELETE FROM tag_queue WHERE status IN ({placeholders})"
            cursor = self.db.conn.execute(query, tuple(statuses))
            count = cursor.rowcount
            self.db.conn.commit()
            return count

    def reset_stuck_jobs(self) -> int:
        """
        Reset jobs stuck in 'running' state back to 'pending'.

        Clears all state fields (started_at, error_message, finished_at).

        Returns:
            Number of jobs reset
        """
        with self.lock:
            cursor = self.db.conn.execute(
                """UPDATE tag_queue
                   SET status='pending', started_at=NULL, error_message=NULL, finished_at=NULL
                   WHERE status='running'"""
            )
            count = cursor.rowcount
            self.db.conn.commit()
            return count

    def reset_error_jobs(self) -> int:
        """
        Reset jobs in 'error' state back to 'pending'.

        Clears error state fields (error_message, finished_at).

        Returns:
            Number of jobs reset
        """
        with self.lock:
            cursor = self.db.conn.execute(
                """UPDATE tag_queue
                   SET status='pending', error_message=NULL, finished_at=NULL
                   WHERE status='error'"""
            )
            count = cursor.rowcount
            self.db.conn.commit()
            return count


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
#  Backwards Compatibility Import
# ----------------------------------------------------------------------
# TaggerWorker moved to services/workers/tagger.py
# Import here for backwards compatibility with existing code
try:
    from nomarr.services.workers.base import BaseWorker as TaggerWorker  # noqa: F401
except ImportError:
    # If BaseWorker not available yet (during migration), skip
    pass
