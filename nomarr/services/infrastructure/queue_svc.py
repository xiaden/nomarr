"""
Queue management service - orchestrates queue operations.

This service wraps queue components and workflows, adding:
- Business rules and validation
- Event broadcasting (SSE updates)
- DTO transformation (components use dicts, service uses DTOs)
- Admin-friendly error handling and messaging
- Config-based feature checks

All heavy lifting is done by components (nomarr.components.queue) and
workflows (nomarr.workflows.queue). This service provides orchestration,
validation, and presentation logic.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from nomarr.components.queue.queue_cleanup_comp import (
    cleanup_old_jobs,
    clear_jobs_by_status,
    remove_job,
    reset_error_jobs,
    reset_stuck_jobs,
)
from nomarr.components.queue.queue_enqueue_comp import enqueue_file
from nomarr.components.queue.queue_status_comp import get_job, get_queue_stats
from nomarr.components.queue.queue_status_comp import list_jobs as list_jobs_comp
from nomarr.helpers.dto.admin_dto import JobRemovalResult, RetagAllResult, WorkerOperationResult
from nomarr.helpers.dto.queue_dto import (
    BatchEnqueuePathResult,
    BatchEnqueueResult,
    EnqueueFilesResult,
    FlushResult,
    Job,
    ListJobsResult,
    QueueStatus,
)
from nomarr.workflows.queue.enqueue_files_wf import enqueue_files_workflow

if TYPE_CHECKING:
    from nomarr.components.events.event_broker_comp import StateBroker
    from nomarr.persistence.db import Database

# Queue type literal (consistent with components/workflows)
QueueType = Literal["tag", "library"]


class QueueService:
    """
    Queue management operations - shared by all interfaces.

    This service orchestrates queue operations using components and workflows,
    adding validation, event broadcasting, and DTO transformation.
    """

    def __init__(
        self,
        db: Database,
        config: dict[str, Any],
        event_broker: StateBroker | None = None,
        queue_type: QueueType = "tag",
    ):
        """
        Initialize queue service.

        Args:
            db: Database instance (passed to components)
            config: Application configuration dict
            event_broker: Optional StateBroker for SSE events
            queue_type: Which queue to operate on ("tag", "library", "calibration")
        """
        self.db = db
        self.config = config
        self.event_broker = event_broker
        self.queue_type = queue_type

    def enqueue_files_for_tagging(
        self, paths: str | list[str], force: bool = False, recursive: bool = True
    ) -> EnqueueFilesResult:
        """
        Enqueue audio files for ML tagging.

        Handles both single files and directories. Automatically discovers
        audio files in directories when recursive=True.

        Args:
            paths: Single path string or list of paths (files or directories)
            force: If True, reprocess files even if already tagged
            recursive: If True, recursively scan directories for audio files

        Returns:
            EnqueueFilesResult DTO with job_ids, files_queued, queue_depth, paths

        Raises:
            ValueError: If no audio files found at given paths
        """
        result = enqueue_files_workflow(
            db=self.db,
            queue_type=self.queue_type,
            paths=paths,
            force=force,
            recursive=recursive,
        )
        self._publish_queue_update()
        return result

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
        from nomarr.helpers.dto.queue_dto import BatchEnqueueResult

        results = []
        total_queued = 0
        total_errors = 0
        for path in paths:
            try:
                result = self.enqueue_files_for_tagging(paths=[path], force=force, recursive=True)
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

    def remove_jobs(self, job_id: str | None = None, status: str | None = None, all: bool = False) -> int:
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
            job = self.get_job(job_id)
            if not job:
                raise ValueError(f"Job {job_id} not found")
            if job.status == "running":
                raise ValueError("Cannot remove running job")
            removed = remove_job(self.db, job_id, self.queue_type)
            logging.info(f"[QueueService] Removed job {job_id}")
            self._publish_queue_update()
            return removed
        elif all:
            removed = clear_jobs_by_status(self.db, ["pending", "done", "error"], self.queue_type)
            logging.info(f"[QueueService] Removed all {removed} jobs from queue")
            self._publish_queue_update()
            return removed
        elif status:
            valid_statuses = {"pending", "running", "done", "error"}
            if status not in valid_statuses:
                raise ValueError(f"Invalid status: {status}")
            if status == "running":
                raise ValueError("Cannot remove running jobs")
            removed = clear_jobs_by_status(self.db, [status], self.queue_type)
            logging.info(f"[QueueService] Removed {removed} job(s) with status '{status}'")
            self._publish_queue_update()
            return removed
        else:
            raise ValueError("Must specify job_id, status, or all=True")

    def flush_completed_and_errors(self) -> tuple[int, int]:
        """
        Remove all completed and error jobs in a single operation.

        Returns:
            Tuple of (done_count, error_count)
        """
        done_count = clear_jobs_by_status(self.db, ["done"], self.queue_type)
        error_count = clear_jobs_by_status(self.db, ["error"], self.queue_type)
        logging.info(f"[QueueService] Flushed {done_count} done and {error_count} error jobs")
        self._publish_queue_update()
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
        valid = {"pending", "running", "done", "error"}
        invalid = [s for s in statuses if s not in valid]
        if invalid:
            raise ValueError(f"Invalid statuses: {invalid}")
        if "running" in statuses:
            raise ValueError("Cannot flush running jobs")
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

        counts = get_queue_stats(self.db, self.queue_type)
        depth = get_queue_stats(self.db, self.queue_type).get("pending", 0)
        return QueueStatus(depth=depth, counts=counts)

    def get_job(self, job_id: str) -> Job | None:
        """
        Get job details by ID.

        Args:
            job_id: Job ID to retrieve

        Returns:
            Job DTO or None if not found
        """
        job = get_job(self.db, job_id, self.queue_type)
        if job:
            return Job(
                id=job["id"],
                path=job["path"],
                status=job["status"],
                created_at=job.get("created_at", 0),
                started_at=job.get("started_at"),
                finished_at=job.get("finished_at"),
                error_message=job.get("error_message"),
                force=job.get("force", False),
            )
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
        if not stuck and (not errors):
            raise ValueError("Must specify stuck=True and/or errors=True")
        reset_count = 0
        if stuck:
            count = reset_stuck_jobs(self.db, self.queue_type)
            reset_count += count
            if count > 0:
                logging.info(f"[QueueService] Reset {count} stuck job(s) from 'running' to 'pending'")
        if errors:
            count = reset_error_jobs(self.db, self.queue_type)
            reset_count += count
            if count > 0:
                logging.info(f"[QueueService] Reset {count} error job(s) to 'pending'")
        self._publish_queue_update()
        return reset_count

    def cleanup_old_jobs(self, max_age_hours: int = 24) -> int:
        """
        Remove old completed/error jobs from tag queue.

        Args:
            max_age_hours: Remove jobs older than this many hours

        Returns:
            Number of jobs removed
        """

        removed = cleanup_old_jobs(self.db, max_age_hours, self.queue_type)
        logging.info(f"[QueueService] Cleaned up {removed} old job(s) (>{max_age_hours}h)")
        self._publish_queue_update()
        return removed

    def remove_job_for_admin(self, job_id: str) -> JobRemovalResult:
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
        return JobRemovalResult(removed=removed_count, message=f"Removed job {job_id}")

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
            removed=removed, message=f"Cleaned up {removed} job(s) older than {max_age_hours} hours"
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
        jobs_data, total = list_jobs_comp(self.db, self.queue_type, limit=limit, offset=offset, status=status)  # type: ignore[arg-type]
        jobs = [
            Job(
                id=j["id"],
                path=j.get("file_path", j.get("path", "")),
                status=j["status"],
                created_at=j.get("created_at", 0),
                started_at=j.get("started_at"),
                finished_at=j.get("finished_at"),
                error_message=j.get("error_message"),
                force=j.get("force", False),
            )
            for j in jobs_data
        ]
        return ListJobsResult(jobs=jobs, total=total, limit=limit, offset=offset)

    def _publish_queue_update(self) -> None:
        """
        Update queue state in event broker with current statistics.

        Retrieves current queue stats from database and broadcasts to SSE clients.
        """
        if not self.event_broker:
            return
        stats = get_queue_stats(self.db, self.queue_type)  # type: ignore[arg-type]
        self.event_broker.update_queue_state(**stats)
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
        tagged_paths = self.db.library_files.get_tagged_file_paths()
        if not tagged_paths:
            logging.info("[QueueService] No tagged files found to enqueue")
            return 0
        count = 0
        for path in tagged_paths:
            try:
                enqueue_file(self.db, path, force=force, queue_type=self.queue_type)  # type: ignore[arg-type]
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
        calibrate_heads = self.config.get("general", {}).get("calibrate_heads", False)
        if not calibrate_heads:
            raise ValueError("Bulk re-tagging not available. Set calibrate_heads: true in config to enable.")
        count = self.enqueue_all_tagged_files()
        if count == 0:
            return RetagAllResult(status="ok", message="No tagged files found", enqueued=0)
        return RetagAllResult(status="ok", message=f"Enqueued {count} files for re-tagging", enqueued=count)

    def remove_jobs_for_admin(
        self, job_id: str | None = None, status: str | None = None, all: bool = False
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
        (done_count, error_count) = self.flush_completed_and_errors()
        total_removed = done_count + error_count
        return JobRemovalResult(
            removed=total_removed, message=f"Removed {done_count} completed and {error_count} error jobs"
        )

    def clear_all_for_admin(self) -> JobRemovalResult:
        """
        Clear all jobs with admin-friendly messaging.

        Returns:
            JobRemovalResult with count and message
        """
        removed = self.remove_jobs(all=True)
        return JobRemovalResult(removed=removed, message=f"Cleared all jobs ({removed} removed)")

    def clear_completed_for_admin(self) -> JobRemovalResult:
        """
        Clear completed jobs with admin-friendly messaging.

        Returns:
            JobRemovalResult with count and message
        """
        removed = self.remove_jobs(status="done")
        return JobRemovalResult(removed=removed, message=f"Cleared {removed} completed job(s)")

    def clear_errors_for_admin(self) -> JobRemovalResult:
        """
        Clear error jobs with admin-friendly messaging.

        Returns:
            JobRemovalResult with count and message
        """
        removed = self.remove_jobs(status="error")
        return JobRemovalResult(removed=removed, message=f"Cleared {removed} error job(s)")

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
        if not stuck and (not errors):
            raise ValueError("Must specify --stuck or --errors")
        reset_count = self.reset_jobs(stuck=stuck, errors=errors)
        return WorkerOperationResult(status="success", message=f"Reset {reset_count} job(s) to pending")
