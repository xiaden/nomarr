"""
Queue management service.
Shared business logic for queue operations across all interfaces (CLI, API, Web).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from nomarr.persistence.db import Database
from nomarr.workflows.enqueue_files import enqueue_files_workflow


# ----------------------------------------------------------------------
#  Job Dataclass
# ----------------------------------------------------------------------
class Job:
    """Represents a single job in the processing queue."""

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
        """Convert job to dictionary representation."""
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
#  ProcessingQueue - Data Access Layer
# ----------------------------------------------------------------------
class ProcessingQueue:
    """
    Thread-safe data access layer for the ML processing queue table.

    Provides CRUD operations for queue jobs using QueueOperations.
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
            job_id = self.db.queue.enqueue(path, force)
            logging.debug(f"[ProcessingQueue] Added job {job_id} for {path}")
            return job_id

    def get(self, job_id: int) -> Job | None:
        """Get job by ID."""
        row = self.db.queue.job_status(job_id)
        if not row:
            return None
        return Job(**row)

    def delete(self, job_id: int) -> int:
        """Delete a job by ID. Returns 1 if deleted, 0 if not found."""
        with self.lock:
            return self.db.queue.delete_job(job_id)

    def list_jobs(self, limit: int = 25, offset: int = 0, status: str | None = None) -> tuple[list[Job], int]:
        """
        List jobs with pagination and optional status filter.

        Args:
            limit: Maximum number of jobs to return
            offset: Number of jobs to skip (for pagination)
            status: Filter by status (pending/running/done/error), or None for all

        Returns:
            Tuple of (jobs list, total count matching filter)
        """
        rows, total = self.db.queue.list_jobs(limit=limit, offset=offset, status=status)
        jobs = [Job(**row) for row in rows]
        return jobs, total

    def update_status(self, job_id: int, status: str, **kwargs) -> None:
        """Update job status and optional fields."""
        with self.lock:
            self.db.queue.update_job(job_id, status, **kwargs)

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
        return self.db.queue.queue_depth()

    def delete_by_status(self, statuses: list[str]) -> int:
        """
        Delete jobs by status.

        Args:
            statuses: List of statuses to delete

        Returns:
            Number of jobs deleted
        """
        with self.lock:
            return self.db.queue.delete_jobs_by_status(statuses)

    def reset_stuck_jobs(self) -> int:
        """
        Reset jobs stuck in 'running' state back to 'pending'.

        Clears all state fields (started_at, error_message, finished_at).

        Returns:
            Number of jobs reset
        """
        with self.lock:
            return self.db.queue.reset_stuck_jobs()

    def reset_error_jobs(self) -> int:
        """
        Reset jobs in 'error' state back to 'pending'.

        Clears error state fields (error_message, finished_at).

        Returns:
            Number of jobs reset
        """
        with self.lock:
            return self.db.queue.reset_error_jobs()


class QueueService:
    """
    Queue management operations - shared by all interfaces.

    This service encapsulates all business logic for queue operations,
    allowing CLI, API, and Web interfaces to be thin presentation layers.
    """

    def __init__(self, queue: ProcessingQueue):
        """
        Initialize queue service.

        Args:
            queue: ProcessingQueue instance (data access layer)
        """
        self.queue = queue

    def add_files(self, paths: str | list[str], force: bool = False, recursive: bool = True) -> dict[str, Any]:
        """
        Add audio files to the queue for processing.

        Handles both single files and directories. Automatically discovers
        audio files in directories when recursive=True.

        Delegates to workflows.queue_operations.enqueue_files_workflow for
        the actual file discovery and enqueueing logic.

        Args:
            paths: Single path string or list of paths (files or directories)
            force: If True, reprocess files even if already tagged
            recursive: If True, recursively scan directories for audio files

        Returns:
            Dict with:
                - job_ids: List of created job IDs
                - files_queued: Number of files added
                - queue_depth: Total pending jobs after adding
                - paths: Input paths (normalized to list)

        Raises:
            ValueError: If no audio files found at given paths
        """
        return enqueue_files_workflow(
            db=self.queue.db,  # Service orchestrates: pass db to workflow
            paths=paths,
            force=force,
            recursive=recursive,
        )

    def remove_jobs(self, job_id: int | None = None, status: str | None = None, all: bool = False) -> int:
        """
        Remove jobs from the queue.

        Args:
            job_id: Remove specific job by ID
            status: Remove all jobs with this status (e.g., 'error', 'done')
            all: Remove all jobs regardless of status

        Returns:
            Number of jobs removed

        Raises:
            ValueError: If no removal criteria specified or invalid combination
        """
        if job_id is not None:
            # Remove single job by ID
            removed = self.queue.delete(job_id)
            logging.info(f"[QueueService] Removed job {job_id}")
            return removed

        elif all:
            # Remove all jobs (including pending, done, error - not running)
            # Business logic: don't remove running jobs
            removed = self.queue.delete_by_status(["pending", "done", "error"])
            logging.info(f"[QueueService] Removed all {removed} jobs from queue")
            return removed

        elif status:
            # Remove jobs by status
            # Business logic: validate status
            valid_statuses = {"pending", "done", "error"}
            if status not in valid_statuses:
                raise ValueError(f"Invalid status: {status}")
            if status == "running":
                raise ValueError("Cannot remove running jobs")

            removed = self.queue.delete_by_status([status])
            logging.info(f"[QueueService] Removed {removed} job(s) with status '{status}'")
            return removed

        else:
            raise ValueError("Must specify job_id, status, or all=True")

    def get_status(self) -> dict[str, int]:
        """
        Get queue statistics.

        Returns:
            Dict with job counts by status:
                - pending: Jobs waiting to be processed
                - running: Jobs currently being processed
                - completed: Successfully completed jobs
                - errors: Jobs that failed with errors
        """
        from nomarr.persistence.db import get_queue_stats

        return get_queue_stats(self.queue.db)

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        """
        Get job details by ID.

        Args:
            job_id: Job ID to retrieve

        Returns:
            Job details dict or None if not found
        """
        job = self.queue.get(job_id)
        if job:
            return job.to_dict()
        return None

    def reset_jobs(self, stuck: bool = False, errors: bool = False) -> int:
        """
        Reset jobs back to pending status.

        Args:
            stuck: Reset jobs stuck in 'running' state
            errors: Reset jobs in 'error' state

        Returns:
            Total number of jobs reset

        Raises:
            ValueError: If no reset criteria specified
        """
        if not stuck and not errors:
            raise ValueError("Must specify stuck=True and/or errors=True")

        reset_count = 0

        if stuck:
            count = self.queue.reset_stuck_jobs()
            reset_count += count
            if count > 0:
                logging.info(f"[QueueService] Reset {count} stuck job(s) from 'running' to 'pending'")

        if errors:
            count = self.queue.reset_error_jobs()
            reset_count += count
            if count > 0:
                logging.info(f"[QueueService] Reset {count} error job(s) to 'pending'")

        return reset_count

    def cleanup_old_jobs(self, max_age_hours: int = 24) -> int:
        """
        Remove old completed/error jobs from tag queue.

        Args:
            max_age_hours: Remove jobs older than this many hours

        Returns:
            Number of jobs removed
        """
        from nomarr.persistence.db import count_and_delete

        # Calculate cutoff timestamp (milliseconds since epoch)
        cutoff_ms = int((time.time() - (max_age_hours * 3600)) * 1000)

        # Remove old done/error jobs
        removed = count_and_delete(
            self.queue.db,
            "tag_queue",
            where_clause="status IN ('done', 'error') AND finished_at < ?",
            params=(cutoff_ms,),
        )

        logging.info(f"[QueueService] Cleaned up {removed} old job(s) (>{max_age_hours}h)")
        return removed

    def get_depth(self) -> int:
        """
        Get number of pending jobs in queue.

        Returns:
            Count of jobs with status='pending'
        """
        return self.queue.depth()

    def list_jobs(self, limit: int = 50, offset: int = 0, status: str | None = None) -> dict[str, Any]:
        """
        List jobs with pagination and filtering.

        Args:
            limit: Maximum number of jobs to return
            offset: Number of jobs to skip
            status: Filter by status (e.g., 'pending', 'running', 'done', 'error')

        Returns:
            Dict with:
                - jobs: List of job dicts
                - total: Total count of jobs matching filter
                - limit: Limit used
                - offset: Offset used
        """
        jobs_list, total = self.queue.list_jobs(limit=limit, offset=offset, status=status)

        return {
            "jobs": [job.to_dict() for job in jobs_list],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def publish_queue_update(self, event_broker: Any | None) -> None:
        """
        Update queue state in event broker with current statistics.

        Retrieves current queue stats from database and broadcasts to SSE clients.

        Args:
            event_broker: StateBroker instance (or None if not available)
        """
        if not event_broker:
            return

        from nomarr.persistence.db import get_queue_stats

        stats = get_queue_stats(self.queue.db)
        event_broker.update_queue_state(**stats)
        logging.debug(f"[QueueService] Published queue update: {stats}")

    async def wait_for_job_completion(self, job_id: int, timeout: int) -> dict[str, Any]:
        """
        Wait for job to complete (async polling with timeout).

        Polls job status until it reaches terminal state (done/error) or timeout.

        Args:
            job_id: Job ID to wait for
            timeout: Maximum seconds to wait

        Returns:
            Final job details dict

        Raises:
            HTTPException: If job not found or timeout exceeded
        """
        import asyncio
        import time

        from fastapi import HTTPException

        start = time.time()
        poll_interval = 0.5  # seconds

        while (time.time() - start) < timeout:
            job = self.queue.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

            if job.status in ("done", "error"):
                return job.to_dict()

            await asyncio.sleep(poll_interval)

        # Timeout - return current state
        job = self.queue.get(job_id)
        if job:
            job_dict = job.to_dict()
            job_dict["timeout"] = True
            return job_dict

        raise HTTPException(status_code=404, detail=f"Job {job_id} disappeared during wait")
