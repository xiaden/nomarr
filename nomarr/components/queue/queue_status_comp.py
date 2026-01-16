"""Queue status operations - query queue state and job information.

IMPORTANT: Standardized queue stats and job listing.

All queue types now return consistent stats dictionaries with these fields:
- pending: int (count of pending jobs)
- running: int (count of running jobs)
- done: int (count of completed jobs, or 0 if not tracked)
- error: int (count of error jobs, or 0 if not tracked)
- total: int (sum of all statuses)
- completed: int (alias for 'done' for backward compatibility)
- failed: int (alias for 'error' for backward compatibility)

Job listing support:
- Tag: Full support for limit, offset, status filtering
- Library: Limited support (offset and status filtering not fully implemented)
- Calibration: Limited support (only returns active jobs)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

QueueType = Literal["tag", "library"]

logger = logging.getLogger(__name__)


def get_queue_stats(db: Database, queue_type: QueueType) -> dict[str, int]:
    """
    Get standardized statistics for a queue (counts by status).

    Returns consistent structure across all queue types with fields:
    - pending: Count of pending jobs
    - running: Count of running jobs
    - done: Count of completed jobs (or 0 if not tracked)
    - error: Count of error jobs (or 0 if not tracked)
    - total: Sum of all job counts
    - completed: Alias for 'done' (backward compatibility)
    - failed: Alias for 'error' (backward compatibility)

    Args:
        db: Database instance
        queue_type: Which queue to get stats for

    Returns:
        Dict with standardized status counts

    Raises:
        ValueError: If queue_type is invalid
    """
    if queue_type == "tag":
        stats = db.tag_queue.queue_stats()
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")

    # Ensure all fields are present with defaults
    normalized = {
        "pending": stats.get("pending", 0),
        "running": stats.get("running", 0),
        "done": stats.get("done", 0),
        "error": stats.get("error", 0),
    }

    # Add computed fields
    normalized["total"] = sum(normalized.values())
    normalized["completed"] = normalized["done"]  # Alias
    normalized["failed"] = normalized["error"]  # Alias

    return normalized


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
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")


def get_job(db: Database, job_id: str, queue_type: QueueType) -> dict[str, Any] | None:
    """
    Get details for a specific job.

    Support matrix:
    - Tag: ✓ Direct lookup by job_id via job_status()
    - Library: ✓ Direct lookup by job_id via get_library_scan()
    - Calibration: ⚠️ Must search through active jobs list (inefficient, no direct lookup)

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

    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")


def list_jobs(
    db: Database, queue_type: QueueType, limit: int = 50, offset: int = 0, status: str | None = None
) -> tuple[list[dict[str, Any]], int]:
    """
    List jobs from a queue with pagination and filtering.

    Support matrix:
    - Tag: ✓ Full support (limit, offset, status filtering all work)
    - Library: ⚠️ Partial (limit works, offset/status not supported in persistence layer)
    - Calibration: ⚠️ Partial (only returns active jobs, offset/status ignored)

    NOTE: Library and calibration queues have limitations. This function does its
    best to honor parameters, but offset and status filtering are not available
    for non-tag queues due to persistence layer constraints.

    Args:
        db: Database instance
        queue_type: Which queue to list from
        limit: Maximum number of jobs to return
        offset: Number of jobs to skip (tag queue only)
        status: Optional status filter "pending", "running", "done", "error" (tag queue only)

    Returns:
        Tuple of (job list, total count)

    Raises:
        ValueError: If queue_type is invalid
    """
    if queue_type == "tag":
        # Tag queue doesn't support offset, only limit and status
        if offset != 0:
            logger.debug(f"Tag queue list_jobs: offset={offset} ignored (not supported)")
        jobs, total = db.tag_queue.list_jobs(limit=limit, status=status)
        return (jobs, total)
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")


def get_active_jobs(db: Database, queue_type: QueueType, limit: int = 50) -> list[dict[str, Any]]:
    """
    Get active (pending or running) jobs from queue.

    Args:
        db: Database instance
        queue_type: Which queue to check
        limit: Maximum number of jobs to return (NOTE: ignored by persistence layer)

    Returns:
        List of active job dicts

    Raises:
        ValueError: If queue_type is invalid
    """
    # NOTE: Persistence layer get_active_jobs() doesn't support limit parameter yet
    # We return all jobs and let the caller slice if needed
    if queue_type == "tag":
        return db.tag_queue.get_active_jobs()
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")
