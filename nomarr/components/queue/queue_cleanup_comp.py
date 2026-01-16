"""Queue cleanup operations - remove, reset, and clear jobs.

IMPORTANT: Queue type support matrix:

Operation              | Tag | Library
----------------------|-----|----------
remove_job            | ✓   | ✗
clear_jobs_by_status  | ✓   | ✗ (1)
clear_completed_jobs  | ✓   | ✗ (1)
clear_error_jobs      | ✓   | ✗ (1)
clear_all_jobs        | ✓   | ✓ (2)
reset_stuck_jobs      | ✓   | ✓
reset_error_jobs      | ✓   | ✗
cleanup_old_jobs      | ✓   | ✗

Notes:
(1) Library only supports clearing ALL jobs (pending+done+error)
(2) Library clear_all_jobs clears everything (no status filtering)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

QueueType = Literal["tag", "library"]

logger = logging.getLogger(__name__)


class UnsupportedQueueOperationError(Exception):
    """Raised when attempting an unsupported operation on a queue type."""

    pass


def remove_job(db: Database, job_id: str, queue_type: QueueType) -> int:
    """
    Remove a single job by ID.

    Does not check if job is running - caller should validate.

    Support:
    - Tag: ✓ Full support
    - Library: ✗ Not supported (no individual job deletion)
    - Calibration: ✗ Not supported (no individual job deletion)

    Args:
        db: Database instance
        job_id: Job ID to remove
        queue_type: Which queue the job belongs to

    Returns:
        Number of jobs removed (0 or 1)

    Raises:
        ValueError: If queue_type is invalid
        UnsupportedQueueOperationError: If queue type doesn't support this operation
    """
    logger.debug(f"Removing job {job_id} from {queue_type} queue")

    if queue_type == "tag":
        return db.tag_queue.delete_job(job_id)
    elif queue_type == "library":
        raise UnsupportedQueueOperationError(
            "Library queue does not support removing individual jobs by ID. Use clear_all_jobs() to clear entire queue."
        )
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")


def clear_jobs_by_status(db: Database, statuses: list[str], queue_type: QueueType) -> int:
    """
    Remove all jobs with specified statuses.

    Support:
    - Tag: ✓ Full support for selective status filtering
    - Library: ✗ Only supports clearing ALL jobs (use clear_all_jobs)
    - Calibration: ✗ Only supports clearing ALL jobs (use clear_all_jobs)

    Args:
        db: Database instance
        statuses: List of statuses to clear (e.g., ["done", "error"])
        queue_type: Which queue to clear from

    Returns:
        Number of jobs removed

    Raises:
        ValueError: If queue_type is invalid or statuses include "running"
        UnsupportedQueueOperationError: If queue type doesn't support selective clearing
    """
    if "running" in statuses:
        raise ValueError("Cannot remove running jobs. Use reset_stuck_jobs() to reset them first.")

    logger.info(f"Clearing {queue_type} queue jobs with statuses: {statuses}")

    if queue_type == "tag":
        # Delete jobs for each status separately
        total_deleted = 0
        for status in statuses:
            total_deleted += db.tag_queue.delete_jobs_by_status(status)
        return total_deleted
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")


def clear_completed_jobs(db: Database, queue_type: QueueType) -> int:
    """
    Remove all completed (done) jobs.

    Support:
    - Tag: ✓ Full support
    - Library: ✗ Not supported (use clear_all_jobs)
    - Calibration: ✗ Not supported (use clear_all_jobs)

    Args:
        db: Database instance
        queue_type: Which queue to clear from

    Returns:
        Number of jobs removed

    Raises:
        ValueError: If queue_type is invalid
        UnsupportedQueueOperationError: If queue type doesn't support this operation
    """
    if queue_type != "tag":
        raise UnsupportedQueueOperationError(
            f"{queue_type.title()} queue does not support clearing only completed jobs. "
            f"Use clear_all_jobs() to clear entire queue."
        )
    return clear_jobs_by_status(db, ["done"], queue_type)


def clear_error_jobs(db: Database, queue_type: QueueType) -> int:
    """
    Remove all error jobs.

    Support:
    - Tag: ✓ Full support
    - Library: ✗ Not supported (use clear_all_jobs)
    - Calibration: ✗ Not supported (use clear_all_jobs)

    Args:
        db: Database instance
        queue_type: Which queue to clear from

    Returns:
        Number of jobs removed

    Raises:
        ValueError: If queue_type is invalid
        UnsupportedQueueOperationError: If queue type doesn't support this operation
    """
    if queue_type != "tag":
        raise UnsupportedQueueOperationError(
            f"{queue_type.title()} queue does not support clearing only error jobs. "
            f"Use clear_all_jobs() to clear entire queue."
        )
    return clear_jobs_by_status(db, ["error"], queue_type)


def clear_all_jobs(db: Database, queue_type: QueueType) -> int:
    """
    Remove all jobs (pending, done, error - not running).

    Support:
    - Tag: ✓ Clears pending+done+error (not running)
    - Library: ✓ Clears ALL jobs including running
    - Calibration: ✓ Clears ALL jobs including running

    NOTE: For library and calibration queues, this also clears running jobs.
    For tag queue, running jobs are not affected. Use reset_stuck_jobs() first if needed.

    Args:
        db: Database instance
        queue_type: Which queue to clear

    Returns:
        Number of jobs removed

    Raises:
        ValueError: If queue_type is invalid
    """
    logger.info(f"Clearing all jobs from {queue_type} queue")

    if queue_type == "tag":
        # Tag queue: selective clear (preserves running jobs)
        return clear_jobs_by_status(db, ["pending", "done", "error"], queue_type)
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")


def reset_stuck_jobs(db: Database, queue_type: QueueType) -> int:
    """
    Reset jobs stuck in 'running' state back to 'pending'.

    Support:
    - Tag: ✓ Full support
    - Library: ✓ Full support
    - Calibration: ✗ Not supported

    Args:
        db: Database instance
        queue_type: Which queue to reset

    Returns:
        Number of jobs reset

    Raises:
        ValueError: If queue_type is invalid
        UnsupportedQueueOperationError: If queue type doesn't support this operation
    """
    logger.info(f"Resetting stuck jobs in {queue_type} queue")

    if queue_type == "tag":
        return db.tag_queue.reset_stale_jobs()
    elif queue_type == "calibration":
        raise UnsupportedQueueOperationError(
            "Calibration queue does not support resetting stuck jobs. Use clear_all_jobs() to clear queue."
        )
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")


def reset_error_jobs(db: Database, queue_type: QueueType) -> int:
    """
    Reset error jobs back to pending status.

    Support:
    - Tag: ✓ Full support
    - Library: ✗ Not supported
    - Calibration: ✗ Not supported

    Args:
        db: Database instance
        queue_type: Which queue to reset

    Returns:
        Number of jobs reset

    Raises:
        ValueError: If queue_type is invalid
        UnsupportedQueueOperationError: If queue type doesn't support this operation
    """
    logger.info(f"Resetting error jobs in {queue_type} queue")

    if queue_type == "tag":
        return db.tag_queue.reset_error_jobs()
    elif queue_type == "library":
        raise UnsupportedQueueOperationError("Library queue does not support resetting error jobs.")
    elif queue_type == "calibration":
        raise UnsupportedQueueOperationError("Calibration queue does not support resetting error jobs.")
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")


def cleanup_old_jobs(db: Database, max_age_hours: int, queue_type: QueueType) -> int:
    """
    Remove old completed/error jobs from queue.

    Support:
    - Tag: ✓ Full support (deletes done/error jobs older than max_age_hours)
    - Library: ✗ Not supported (no age-based cleanup)
    - Calibration: ✗ Not supported (no age-based cleanup)

    NOTE: Tag queue's clear_old_jobs() returns None from persistence layer,
    so we cannot return an accurate count. Returns -1 to indicate "operation
    completed but count unavailable".

    Args:
        db: Database instance
        max_age_hours: Remove jobs older than this many hours
        queue_type: Which queue to clean

    Returns:
        Number of jobs removed, or -1 if operation succeeded but count unavailable

    Raises:
        ValueError: If queue_type is invalid
        UnsupportedQueueOperationError: If queue type doesn't support this operation
    """
    logger.info(f"Cleaning up {queue_type} queue jobs older than {max_age_hours} hours")

    if queue_type == "tag":
        # Convert hours to days for clear_completed_jobs
        max_age_days = int(max_age_hours / 24) if max_age_hours >= 24 else 1
        return db.tag_queue.clear_completed_jobs(max_age_days=max_age_days)
    elif queue_type == "library":
        raise UnsupportedQueueOperationError("Library queue does not support age-based cleanup.")
    elif queue_type == "calibration":
        raise UnsupportedQueueOperationError("Calibration queue does not support age-based cleanup.")
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")
