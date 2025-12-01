"""Queue status operations - query queue state and job information."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

QueueType = Literal["tag", "library", "calibration"]

logger = logging.getLogger(__name__)


def get_queue_stats(db: Database, queue_type: QueueType) -> dict[str, int]:
    """
    Get statistics for a queue (counts by status).

    Args:
        db: Database instance
        queue_type: Which queue to get stats for

    Returns:
        Dict with keys: pending, running, done, error (counts)

    Raises:
        ValueError: If queue_type is invalid
    """
    if queue_type == "tag":
        return db.tag_queue.queue_stats()
    elif queue_type == "library":
        return db.library_queue.queue_stats()
    elif queue_type == "calibration":
        return db.calibration_queue.queue_stats()
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")


def get_queue_depth(db: Database, queue_type: QueueType) -> int:
    """
    Get count of pending jobs in queue.

    Args:
        db: Database instance
        queue_type: Which queue to check

    Returns:
        Number of pending jobs

    Raises:
        ValueError: If queue_type is invalid
    """
    if queue_type == "tag":
        return db.tag_queue.queue_depth()
    elif queue_type == "library":
        return db.library_queue.count_pending_scans()
    elif queue_type == "calibration":
        stats = db.calibration_queue.queue_stats()
        return stats.get("pending", 0)
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")


def get_job(db: Database, job_id: int, queue_type: QueueType) -> dict[str, Any] | None:
    """
    Get details for a specific job.

    Args:
        db: Database instance
        job_id: Job ID to retrieve
        queue_type: Which queue to check

    Returns:
        Job dict with id, path, status, timestamps, etc. or None if not found

    Raises:
        ValueError: If queue_type is invalid
    """
    if queue_type == "tag":
        return db.tag_queue.job_status(job_id)
    elif queue_type == "library":
        return db.library_queue.get_library_scan(job_id)
    elif queue_type == "calibration":
        # Calibration queue doesn't have a get_job method, use list with filter
        jobs = db.calibration_queue.get_active_jobs(limit=1000)
        for job in jobs:
            if job.get("id") == job_id:
                return job
        return None
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")


def list_jobs(
    db: Database, queue_type: QueueType, limit: int = 50, offset: int = 0, status: str | None = None
) -> tuple[list[dict[str, Any]], int]:
    """
    List jobs from a queue with pagination and filtering.

    Args:
        db: Database instance
        queue_type: Which queue to list from
        limit: Maximum number of jobs to return
        offset: Number of jobs to skip
        status: Optional status filter ("pending", "running", "done", "error")

    Returns:
        Tuple of (job list, total count)

    Raises:
        ValueError: If queue_type is invalid
    """
    if queue_type == "tag":
        return db.tag_queue.list_jobs(limit=limit, offset=offset, status=status)
    elif queue_type == "library":
        # Library queue list_scan_jobs doesn't support offset/status filtering
        jobs = db.library_queue.list_scan_jobs(limit=limit)
        total = len(jobs)
        return (jobs, total)
    elif queue_type == "calibration":
        # Calibration queue only has get_active_jobs
        jobs = db.calibration_queue.get_active_jobs(limit=limit)
        total = len(jobs)
        return (jobs, total)
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")


def get_active_jobs(db: Database, queue_type: QueueType, limit: int = 50) -> list[dict[str, Any]]:
    """
    Get active (pending or running) jobs from queue.

    Args:
        db: Database instance
        queue_type: Which queue to check
        limit: Maximum number of jobs to return

    Returns:
        List of active job dicts

    Raises:
        ValueError: If queue_type is invalid
    """
    if queue_type == "tag":
        return db.tag_queue.get_active_jobs(limit=limit)
    elif queue_type == "library":
        return db.library_queue.get_active_jobs(limit=limit)
    elif queue_type == "calibration":
        return db.calibration_queue.get_active_jobs(limit=limit)
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")
