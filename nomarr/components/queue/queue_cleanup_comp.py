"""Queue cleanup operations - remove, reset, and clear jobs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

QueueType = Literal["tag", "library", "calibration"]

logger = logging.getLogger(__name__)


def remove_job(db: Database, job_id: int, queue_type: QueueType) -> int:
    """
    Remove a single job by ID.

    Does not check if job is running - caller should validate.

    Args:
        db: Database instance
        job_id: Job ID to remove
        queue_type: Which queue the job belongs to

    Returns:
        Number of jobs removed (0 or 1)

    Raises:
        ValueError: If queue_type is invalid
    """
    logger.debug(f"Removing job {job_id} from {queue_type} queue")

    if queue_type == "tag":
        return db.tag_queue.delete_job(job_id)
    elif queue_type == "library":
        # Library queue doesn't have delete by ID, use status-based removal
        # This is a limitation - for now we can't remove individual library jobs
        logger.warning("Cannot remove individual library queue jobs - unsupported by persistence layer")
        return 0
    elif queue_type == "calibration":
        # Calibration queue doesn't have delete by ID either
        logger.warning("Cannot remove individual calibration queue jobs - unsupported by persistence layer")
        return 0
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")


def clear_jobs_by_status(db: Database, statuses: list[str], queue_type: QueueType) -> int:
    """
    Remove all jobs with specified statuses.

    Args:
        db: Database instance
        statuses: List of statuses to clear (e.g., ["done", "error"])
        queue_type: Which queue to clear from

    Returns:
        Number of jobs removed

    Raises:
        ValueError: If queue_type is invalid or statuses include "running"
    """
    if "running" in statuses:
        raise ValueError("Cannot remove running jobs")

    logger.info(f"Clearing {queue_type} queue jobs with statuses: {statuses}")

    if queue_type == "tag":
        return db.tag_queue.delete_jobs_by_status(statuses)
    elif queue_type == "library":
        # Library queue has clear_scan_queue which clears all
        if set(statuses) == {"pending", "done", "error"}:
            return db.library_queue.clear_scan_queue()
        else:
            logger.warning("Library queue only supports full clear, not selective by status")
            return 0
    elif queue_type == "calibration":
        # Calibration queue has clear_calibration_queue which clears all
        if set(statuses) == {"pending", "done", "error"}:
            return db.calibration_queue.clear_calibration_queue()
        else:
            logger.warning("Calibration queue only supports full clear, not selective by status")
            return 0
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")


def clear_completed_jobs(db: Database, queue_type: QueueType) -> int:
    """
    Remove all completed (done) jobs.

    Args:
        db: Database instance
        queue_type: Which queue to clear from

    Returns:
        Number of jobs removed

    Raises:
        ValueError: If queue_type is invalid
    """
    return clear_jobs_by_status(db, ["done"], queue_type)


def clear_error_jobs(db: Database, queue_type: QueueType) -> int:
    """
    Remove all error jobs.

    Args:
        db: Database instance
        queue_type: Which queue to clear from

    Returns:
        Number of jobs removed

    Raises:
        ValueError: If queue_type is invalid
    """
    return clear_jobs_by_status(db, ["error"], queue_type)


def clear_all_jobs(db: Database, queue_type: QueueType) -> int:
    """
    Remove all jobs (pending, done, error - not running).

    Args:
        db: Database instance
        queue_type: Which queue to clear

    Returns:
        Number of jobs removed

    Raises:
        ValueError: If queue_type is invalid
    """
    return clear_jobs_by_status(db, ["pending", "done", "error"], queue_type)


def reset_stuck_jobs(db: Database, queue_type: QueueType) -> int:
    """
    Reset jobs stuck in 'running' state back to 'pending'.

    Args:
        db: Database instance
        queue_type: Which queue to reset

    Returns:
        Number of jobs reset

    Raises:
        ValueError: If queue_type is invalid
    """
    logger.info(f"Resetting stuck jobs in {queue_type} queue")

    if queue_type == "tag":
        return db.tag_queue.reset_stuck_jobs()
    elif queue_type == "library":
        return db.library_queue.reset_running_library_scans()
    elif queue_type == "calibration":
        # Calibration queue doesn't have reset method
        logger.warning("Calibration queue does not support resetting stuck jobs")
        return 0
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")


def reset_error_jobs(db: Database, queue_type: QueueType) -> int:
    """
    Reset error jobs back to pending status.

    Args:
        db: Database instance
        queue_type: Which queue to reset

    Returns:
        Number of jobs reset

    Raises:
        ValueError: If queue_type is invalid
    """
    logger.info(f"Resetting error jobs in {queue_type} queue")

    if queue_type == "tag":
        return db.tag_queue.reset_error_jobs()
    elif queue_type == "library":
        # Library queue doesn't have reset_error method
        logger.warning("Library queue does not support resetting error jobs")
        return 0
    elif queue_type == "calibration":
        # Calibration queue doesn't have reset_error method
        logger.warning("Calibration queue does not support resetting error jobs")
        return 0
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")


def cleanup_old_jobs(db: Database, max_age_hours: int, queue_type: QueueType) -> int:
    """
    Remove old completed/error jobs from queue.

    Args:
        db: Database instance
        max_age_hours: Remove jobs older than this many hours
        queue_type: Which queue to clean

    Returns:
        Number of jobs removed

    Raises:
        ValueError: If queue_type is invalid
    """
    logger.info(f"Cleaning up {queue_type} queue jobs older than {max_age_hours} hours")

    if queue_type == "tag":
        db.tag_queue.clear_old_jobs(max_age_hours=max_age_hours)
        # clear_old_jobs returns None, so we can't count
        return 0
    elif queue_type == "library":
        # Library queue doesn't have age-based cleanup
        logger.warning("Library queue does not support age-based cleanup")
        return 0
    elif queue_type == "calibration":
        # Calibration queue doesn't have age-based cleanup
        logger.warning("Calibration queue does not support age-based cleanup")
        return 0
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")
