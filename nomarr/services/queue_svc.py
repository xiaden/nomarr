"""
Queue management service.
Shared business logic for queue operations across all interfaces (CLI, API, Web).
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Any

from nomarr.helpers.dto.admin_dto import JobRemovalResult, RetagAllResult, WorkerOperationResult
from nomarr.helpers.dto.queue_dto import (
    BatchEnqueueResult,
    DequeueResult,
    EnqueueFilesResult,
    FlushResult,
    Job,
    ListJobsResult,
    QueueStatus,
)
from nomarr.persistence.db import Database
from nomarr.workflows.queue.enqueue_files_wf import enqueue_files_workflow


# ----------------------------------------------------------------------
#  BaseQueue - Abstract Queue Interface
# ----------------------------------------------------------------------
class BaseQueue(ABC):
    """
    Abstract base class for all queue implementations.

    Defines the common interface expected by BaseWorker for queue polling
    and job state management. Each concrete queue wraps a specific DB table.
    """

    def __init__(self, db: Database):
        """Initialize queue with database connection."""
        self.db = db
        self.lock = threading.Lock()

    @abstractmethod
    def dequeue(self) -> DequeueResult | None:
        """
        Dequeue next pending job.

        Returns:
            DequeueResult with (job_id, file_path, force) or None if no jobs available
        """
        ...

    @abstractmethod
    def mark_complete(self, job_id: int) -> None:
        """Mark job as complete."""
        ...

    @abstractmethod
    def mark_error(self, job_id: int, error: str) -> None:
        """Mark job as failed."""
        ...

    @abstractmethod
    def enqueue(self, path: str, force: bool = False) -> int:
        """
        Enqueue a new job.

        Args:
            path: File path or identifier
            force: Whether to force reprocessing

        Returns:
            job_id of created job
        """
        ...


# ----------------------------------------------------------------------
#  QueueJob Dataclass (DB row wrapper)
# ----------------------------------------------------------------------
class QueueJob:
    """Internal wrapper for a single job row from the database."""

    def __init__(self, **row):
        self.id = row.get("id")
        self.path = row.get("path")
        self.status = row.get("status", "pending")
        self.started_at = row.get("started_at")
        self.finished_at = row.get("finished_at")
        self.error_message = row.get("error_message")
        self.force = bool(row.get("force", 0))

    def to_dto(self) -> Job:
        """Convert DB row wrapper to Job DTO."""
        # Ensure required fields have values (should always be true from DB)
        if self.id is None or self.path is None:
            raise ValueError("Job missing required fields")

        return Job(
            id=self.id,
            path=self.path,
            status=self.status,
            started_at=self.started_at,
            finished_at=self.finished_at,
            error_message=self.error_message,
            force=self.force,
        )


# ----------------------------------------------------------------------
#  ProcessingQueue - Data Access Layer for tag_queue table
# ----------------------------------------------------------------------
class ProcessingQueue(BaseQueue):
    """
    Thread-safe data access layer for the ML processing queue (tag_queue table).

    Provides CRUD operations for tagging jobs using QueueOperations.
    Business logic should live in QueueService, not here.
    """

    def dequeue(self) -> DequeueResult | None:
        """
        Dequeue next pending tagging job.

        Returns:
            DequeueResult with (job_id, file_path, force) or None if no jobs available
        """
        with self.lock:
            job = self.db.tag_queue.get_next_pending_job()
            if not job:
                return None

            job_id = job["id"]
            path = job["path"]
            force = job["force"]

            # Mark job as running
            self.db.tag_queue.update_job(job_id, "running")
            logging.debug(f"[ProcessingQueue] Dequeued job {job_id}: {path}")

            return DequeueResult(job_id=job_id, file_path=path, force=force)

    def mark_complete(self, job_id: int) -> None:
        """Mark tagging job as complete."""
        with self.lock:
            self.db.tag_queue.update_job(job_id, "done")

    def mark_error(self, job_id: int, error: str) -> None:
        """Mark tagging job as failed."""
        with self.lock:
            self.db.tag_queue.update_job(job_id, "error", error_message=error)

    def enqueue(self, path: str, force: bool = False) -> int:
        """
        Enqueue a file for ML tagging.

        Args:
            path: File path to tag
            force: Whether to force reprocessing

        Returns:
            job_id of created job
        """
        with self.lock:
            job_id = self.db.tag_queue.enqueue(path, force)
            logging.debug(f"[ProcessingQueue] Enqueued job {job_id} for {path}")
            return job_id

    # ---------------------------- Legacy Methods (keep for compatibility) ----------------------------

    def add(self, path: str, force: bool = False) -> int:
        """Add a file to the processing queue."""
        with self.lock:
            job_id = self.db.tag_queue.enqueue(path, force)
            logging.debug(f"[ProcessingQueue] Added job {job_id} for {path}")
            return job_id

    def get(self, job_id: int) -> QueueJob | None:
        """Get job by ID (returns internal QueueJob wrapper)."""
        row = self.db.tag_queue.job_status(job_id)
        if not row:
            return None
        return QueueJob(**row)

    def delete(self, job_id: int) -> int:
        """Delete a job by ID. Returns 1 if deleted, 0 if not found."""
        with self.lock:
            return self.db.tag_queue.delete_job(job_id)

    def list_jobs(self, limit: int = 25, offset: int = 0, status: str | None = None) -> ListJobsResult:
        """
        List jobs with pagination and optional status filter.

        Args:
            limit: Maximum number of jobs to return
            offset: Number of jobs to skip (for pagination)
            status: Filter by status (pending/running/done/error), or None for all

        Returns:
            ListJobsResult with jobs list and total count
        """
        rows, total = self.db.tag_queue.list_jobs(limit=limit, offset=offset, status=status)
        jobs = [QueueJob(**row) for row in rows]
        return ListJobsResult(
            jobs=[job.to_dto() for job in jobs],
            total=total,
            limit=limit,
            offset=offset,
        )

    def update_status(self, job_id: int, status: str, **kwargs) -> None:
        """Update job status and optional fields."""
        with self.lock:
            self.db.tag_queue.update_job(job_id, status, **kwargs)

    def start(self, job_id: int) -> None:
        """Mark a job as running."""
        self.update_status(job_id, "running")

    def mark_done(self, job_id: int, results: dict[str, Any] | None = None) -> None:
        """Mark a job as complete with optional results."""
        self.update_status(job_id, "done", results=results)

    def depth(self) -> int:
        """Return number of pending/running jobs."""
        return self.db.tag_queue.queue_depth()

    def delete_by_status(self, statuses: list[str]) -> int:
        """
        Delete jobs by status.

        Args:
            statuses: List of statuses to delete

        Returns:
            Number of jobs deleted
        """
        with self.lock:
            return self.db.tag_queue.delete_jobs_by_status(statuses)

    def reset_stuck_jobs(self) -> int:
        """
        Reset jobs stuck in 'running' state back to 'pending'.

        Clears all state fields (started_at, error_message, finished_at).

        Returns:
            Number of jobs reset
        """
        with self.lock:
            return self.db.tag_queue.reset_stuck_jobs()

    def reset_error_jobs(self) -> int:
        """
        Reset jobs in 'error' state back to 'pending'.

        Clears error state fields (error_message, finished_at).

        Returns:
            Number of jobs reset
        """
        with self.lock:
            return self.db.tag_queue.reset_error_jobs()


class RecalibrationQueue(BaseQueue):
    """
    Queue interface for calibration_queue table.

    Wraps calibration queue operations to match BaseQueue interface
    expected by BaseWorker.
    """

    def dequeue(self) -> DequeueResult | None:
        """
        Dequeue next pending recalibration job.

        Returns:
            DequeueResult with (job_id, file_path, force=False) or None if no jobs available
        """
        job = self.db.calibration_queue.get_next_calibration_job()
        if not job:
            return None
        job_id, path = job
        return DequeueResult(job_id=job_id, file_path=path, force=False)

    def mark_complete(self, job_id: int) -> None:
        """Mark recalibration job as complete."""
        self.db.calibration_queue.complete_calibration_job(job_id)

    def mark_error(self, job_id: int, error: str) -> None:
        """Mark recalibration job as failed."""
        self.db.calibration_queue.fail_calibration_job(job_id, error)

    def enqueue(self, path: str, force: bool = False) -> int:
        """
        Enqueue a file for recalibration.

        Args:
            path: File path to recalibrate
            force: Ignored (recalibration always runs)

        Returns:
            job_id of created job
        """
        return self.db.calibration_queue.enqueue_calibration(path)


class ScanQueue(BaseQueue):
    """
    Queue interface for library_queue table.

    Wraps library_queue operations to match BaseQueue interface
    expected by BaseWorker. Each job represents ONE file to scan.
    """

    def dequeue(self) -> DequeueResult | None:
        """
        Dequeue next pending scan job.

        Returns:
            DequeueResult with (job_id, file_path, force) or None if no pending jobs
        """
        result = self.db.library_queue.dequeue_scan()
        if not result:
            return None
        job_id, path, force = result
        return DequeueResult(job_id=job_id, file_path=path, force=force)

    def mark_complete(self, job_id: int) -> None:
        """Mark scan job as complete."""
        self.db.library_queue.mark_scan_complete(job_id)

    def mark_error(self, job_id: int, error: str) -> None:
        """Mark scan job as failed."""
        self.db.library_queue.mark_scan_error(job_id, error)

    def enqueue(self, path: str, force: bool = False) -> int:
        """
        Enqueue a file for library scanning.

        Args:
            path: File path to scan
            force: Whether to force rescan even if file hasn't changed

        Returns:
            Job ID of enqueued scan
        """
        return self.db.library_queue.enqueue_scan(path, force)


class QueueService:
    """
    Queue management operations - shared by all interfaces.

    This service encapsulates all business logic for queue operations,
    allowing CLI, API, and Web interfaces to be thin presentation layers.
    """

    def __init__(self, queue: ProcessingQueue, config: dict[str, Any], event_broker: Any | None = None):
        """
        Initialize queue service.

        Args:
            queue: ProcessingQueue instance (data access layer)
            config: Application configuration dict
            event_broker: Optional StateBroker for SSE events
        """
        self.queue = queue
        self.config = config
        self.event_broker = event_broker

    def add_files(self, paths: str | list[str], force: bool = False, recursive: bool = True) -> EnqueueFilesResult:
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
            EnqueueFilesResult with:
                - job_ids: List of created job IDs
                - files_queued: Number of files added
                - queue_depth: Total pending jobs after adding
                - paths: Input paths (normalized to list)

        Raises:
            ValueError: If no audio files found at given paths
        """
        return enqueue_files_workflow(
            queue=self.queue,  # Pass the ProcessingQueue instance
            paths=paths,
            force=force,
            recursive=recursive,
        )

    def batch_add_files(self, paths: list[str], force: bool = False) -> BatchEnqueueResult:
        """
        Add multiple paths to queue, returning detailed per-path results.

        Each path is processed independently - failures don't stop processing
        of remaining paths.

        Args:
            paths: List of file or directory paths
            force: If True, reprocess files even if already tagged

        Returns:
            BatchEnqueueResult with per-path results and totals
        """
        from nomarr.helpers.dto.queue_dto import BatchEnqueuePathResult, BatchEnqueueResult

        results = []
        total_queued = 0
        total_errors = 0

        for path in paths:
            try:
                result = self.add_files(
                    paths=[path],
                    force=force,
                    recursive=True,
                )

                files_count = result.files_queued
                job_ids = result.job_ids

                if files_count > 1:
                    message = f"Added {files_count} files to queue (jobs {job_ids[0]}-{job_ids[-1]})"
                else:
                    message = f"Added to queue as job {job_ids[0]}"

                results.append(
                    BatchEnqueuePathResult(
                        path=path,
                        status="queued",
                        message=message,
                        files_queued=files_count,
                        job_ids=job_ids,
                    )
                )
                total_queued += files_count

            except Exception as e:
                results.append(
                    BatchEnqueuePathResult(
                        path=path,
                        status="error",
                        message=str(e),
                        files_queued=0,
                        job_ids=None,
                    )
                )
                total_errors += 1

        return BatchEnqueueResult(
            total_queued=total_queued,
            total_errors=total_errors,
            results=results,
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
            ValueError: If no removal criteria specified, invalid combination, job not found, or attempting to remove running job
        """
        if job_id is not None:
            # Remove single job by ID - validate first
            job = self.get_job(job_id)
            if not job:
                raise ValueError(f"Job {job_id} not found")
            if job.status == "running":
                raise ValueError("Cannot remove running job")

            removed = self.queue.delete(job_id)
            logging.info(f"[QueueService] Removed job {job_id}")
            self.publish_queue_update(self.event_broker)
            return removed

        elif all:
            # Remove all jobs (including pending, done, error - not running)
            # Business logic: don't remove running jobs
            removed = self.queue.delete_by_status(["pending", "done", "error"])
            logging.info(f"[QueueService] Removed all {removed} jobs from queue")
            self.publish_queue_update(self.event_broker)
            return removed

        elif status:
            # Remove jobs by status
            # Business logic: validate status
            valid_statuses = {"pending", "running", "done", "error"}
            if status not in valid_statuses:
                raise ValueError(f"Invalid status: {status}")
            if status == "running":
                raise ValueError("Cannot remove running jobs")

            removed = self.queue.delete_by_status([status])
            logging.info(f"[QueueService] Removed {removed} job(s) with status '{status}'")
            self.publish_queue_update(self.event_broker)
            return removed

        else:
            raise ValueError("Must specify job_id, status, or all=True")

    def flush_completed_and_errors(self) -> tuple[int, int]:
        """
        Remove all completed and error jobs in a single operation.

        Returns:
            Tuple of (done_count, error_count)
        """
        done_count = self.queue.delete_by_status(["done"])
        error_count = self.queue.delete_by_status(["error"])
        logging.info(f"[QueueService] Flushed {done_count} done and {error_count} error jobs")
        self.publish_queue_update(self.event_broker)
        return (done_count, error_count)

    def flush_by_statuses(self, statuses: list[str]) -> FlushResult:
        """
        Remove jobs for multiple statuses at once.

        Args:
            statuses: List of statuses to flush

        Returns:
            FlushResult with flushed_statuses list and total removed count

        Raises:
            ValueError: If invalid status or attempting to flush running jobs
        """
        # Validate all statuses first
        valid = {"pending", "running", "done", "error"}
        invalid = [s for s in statuses if s not in valid]
        if invalid:
            raise ValueError(f"Invalid statuses: {invalid}")
        if "running" in statuses:
            raise ValueError("Cannot flush running jobs")

        # Remove jobs by each status
        total_removed = 0
        for status in statuses:
            removed = self.remove_jobs(status=status)
            total_removed += removed

        logging.info(f"[QueueService] Flushed {total_removed} jobs with statuses {statuses}")
        return FlushResult(flushed_statuses=statuses, removed=total_removed)

    def get_status(self) -> QueueStatus:
        """
        Get queue statistics including depth and counts.

        Returns:
            QueueStatus with depth and job counts by status
        """
        from nomarr.persistence.db import get_queue_stats

        counts = get_queue_stats(self.queue.db)
        depth = self.queue.depth()

        return QueueStatus(depth=depth, counts=counts)

    def get_job(self, job_id: int) -> Job | None:
        """
        Get job details by ID.

        Args:
            job_id: Job ID to retrieve

        Returns:
            Job DTO or None if not found
        """
        job = self.queue.get(job_id)
        if job:
            return job.to_dto()
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

        self.publish_queue_update(self.event_broker)
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
        self.publish_queue_update(self.event_broker)
        return removed

    def remove_job_for_admin(self, job_id: int) -> JobRemovalResult:
        """
        Remove a single job by ID for admin operations.

        Args:
            job_id: Job ID to remove

        Returns:
            JobRemovalResult with removal count and message

        Raises:
            ValueError: If job not found or is running
        """
        removed_count = self.remove_jobs(job_id=job_id)
        return JobRemovalResult(
            removed=removed_count,
            message=f"Removed job {job_id}",
        )

    def cleanup_old_jobs_for_admin(self, max_age_hours: int = 168) -> JobRemovalResult:
        """
        Remove old finished jobs with result message for admin operations.

        Args:
            max_age_hours: Remove jobs older than this many hours (default 7 days)

        Returns:
            JobRemovalResult with removal count and message
        """
        removed = self.cleanup_old_jobs(max_age_hours)
        return JobRemovalResult(
            removed=removed,
            message=f"Cleaned up {removed} job(s) older than {max_age_hours} hours",
        )

    def list_jobs(self, limit: int = 50, offset: int = 0, status: str | None = None) -> ListJobsResult:
        """
        List jobs with pagination and filtering.

        Args:
            limit: Maximum number of jobs to return
            offset: Number of jobs to skip
            status: Filter by status (e.g., 'pending', 'running', 'done', 'error')

        Returns:
            ListJobsResult with:
                - jobs: List of job dicts
                - total: Total count of jobs matching filter
                - limit: Limit used
                - offset: Offset used
        """
        result = self.queue.list_jobs(limit=limit, offset=offset, status=status)
        return result

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

    def enqueue_all_tagged_files(self, force: bool = True) -> int:
        """
        Enqueue all library files that have been tagged for re-processing.

        This is typically used after calibration updates to re-tag the entire
        library with new thresholds.

        Args:
            force: If True, reprocess files even if already tagged (default: True)

        Returns:
            Number of files enqueued
        """
        # Get all tagged file paths from persistence layer
        tagged_paths = self.queue.db.library_files.get_tagged_file_paths()

        if not tagged_paths:
            logging.info("[QueueService] No tagged files found to enqueue")
            return 0

        # Enqueue all tagged files using the database queue operations
        count = 0
        for path in tagged_paths:
            try:
                self.queue.db.tag_queue.enqueue(path, force=force)
                count += 1
            except Exception as e:
                logging.error(f"[QueueService] Failed to enqueue {path}: {e}")

        logging.info(f"[QueueService] Enqueued {count} tagged files for re-processing")
        return count

    def retag_all_for_admin(self) -> RetagAllResult:
        """
        Enqueue all tagged files for re-tagging with admin-friendly error handling.

        Checks if calibrate_heads is enabled in config before proceeding.

        Returns:
            RetagAllResult with status, message, and enqueued count

        Raises:
            ValueError: If calibrate_heads is disabled in config
        """
        # Read calibrate_heads from config internally
        calibrate_heads = self.config.get("general", {}).get("calibrate_heads", False)

        if not calibrate_heads:
            raise ValueError("Bulk re-tagging not available. Set calibrate_heads: true in config to enable.")

        count = self.enqueue_all_tagged_files()

        if count == 0:
            return RetagAllResult(status="ok", message="No tagged files found", enqueued=0)

        return RetagAllResult(status="ok", message=f"Enqueued {count} files for re-tagging", enqueued=count)

    def remove_jobs_for_admin(
        self, job_id: int | None = None, status: str | None = None, all: bool = False
    ) -> JobRemovalResult:
        """
        Remove jobs with admin-friendly messaging.

        Args:
            job_id: Optional job ID to remove
            status: Optional status filter
            all: Remove all jobs

        Returns:
            JobRemovalResult with count and message
        """
        removed = self.remove_jobs(job_id=job_id, status=status, all=all)

        if removed == 0:
            message = "No jobs removed"
        else:
            message = f"Removed {removed} job(s)"

        return JobRemovalResult(removed=removed, message=message)

    def flush_completed_and_errors_for_admin(self) -> JobRemovalResult:
        """
        Flush completed and error jobs with admin-friendly messaging.

        Returns:
            JobRemovalResult with count and message
        """
        done_count, error_count = self.flush_completed_and_errors()
        total_removed = done_count + error_count

        return JobRemovalResult(
            removed=total_removed,
            message=f"Removed {done_count} completed and {error_count} error jobs",
        )

    def clear_all_for_admin(self) -> JobRemovalResult:
        """
        Clear all jobs with admin-friendly messaging.

        Returns:
            JobRemovalResult with count and message
        """
        removed = self.remove_jobs(all=True)
        return JobRemovalResult(
            removed=removed,
            message=f"Cleared all jobs ({removed} removed)",
        )

    def clear_completed_for_admin(self) -> JobRemovalResult:
        """
        Clear completed jobs with admin-friendly messaging.

        Returns:
            JobRemovalResult with count and message
        """
        removed = self.remove_jobs(status="done")
        return JobRemovalResult(
            removed=removed,
            message=f"Cleared {removed} completed job(s)",
        )

    def clear_errors_for_admin(self) -> JobRemovalResult:
        """
        Clear error jobs with admin-friendly messaging.

        Returns:
            JobRemovalResult with count and message
        """
        removed = self.remove_jobs(status="error")
        return JobRemovalResult(
            removed=removed,
            message=f"Cleared {removed} error job(s)",
        )

    def reset_jobs_for_admin(self, stuck: bool = False, errors: bool = False) -> WorkerOperationResult:
        """
        Reset jobs with admin-friendly messaging and validation.

        Args:
            stuck: Reset stuck running jobs
            errors: Reset error jobs

        Returns:
            WorkerOperationResult with status and message

        Raises:
            ValueError: If neither stuck nor errors is True
        """
        if not stuck and not errors:
            raise ValueError("Must specify --stuck or --errors")

        reset_count = self.reset_jobs(stuck=stuck, errors=errors)
        return WorkerOperationResult(
            status="success",
            message=f"Reset {reset_count} job(s) to pending",
        )
