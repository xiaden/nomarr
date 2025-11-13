"""
Queue management service.
Shared business logic for queue operations across all interfaces (CLI, API, Web).
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Any

from nomarr.helpers.files import collect_audio_files

if TYPE_CHECKING:
    from nomarr.data.queue import ProcessingQueue


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
        # Normalize paths to list
        if isinstance(paths, str):
            paths = [paths]

        # Validate paths exist
        for path in paths:
            if not os.path.exists(path):
                raise FileNotFoundError(f"Path not found: {path}")

        # Collect audio files from all paths
        audio_files = collect_audio_files(paths, recursive=recursive)

        if not audio_files:
            # Determine error message based on input type
            if len(paths) == 1 and os.path.isdir(paths[0]):
                raise ValueError(f"No audio files found in directory: {paths[0]}")
            elif len(paths) == 1:
                raise ValueError(f"Not an audio file: {paths[0]}")
            else:
                raise ValueError(f"No audio files found in provided paths: {paths}")

        # Queue all files
        job_ids = []
        for file_path in audio_files:
            job_id = self.queue.add(file_path, force)
            job_ids.append(job_id)
            logging.debug(f"[QueueService] Queued job {job_id} for {file_path}")

        queue_depth = self.queue.depth()
        logging.info(
            f"[QueueService] Queued {len(job_ids)} files from {len(paths)} path(s) (queue depth={queue_depth})"
        )

        return {
            "job_ids": job_ids,
            "files_queued": len(job_ids),
            "queue_depth": queue_depth,
            "paths": paths,
        }

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
        from nomarr.helpers.db import get_queue_stats

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
        from nomarr.helpers.db import count_and_delete

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

    def publish_queue_update(self, event_broker: Any | None) -> None:
        """
        Update queue state in event broker with current statistics.

        Retrieves current queue stats from database and broadcasts to SSE clients.

        Args:
            event_broker: StateBroker instance (or None if not available)
        """
        if not event_broker:
            return

        from nomarr.helpers.db import get_queue_stats

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
