"""Clear queue workflow - remove jobs from queue with business rules."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from nomarr.components.queue import clear_all_jobs, clear_completed_jobs, clear_error_jobs, clear_jobs_by_status

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

QueueType = Literal["tag", "library", "calibration"]

logger = logging.getLogger(__name__)


def clear_queue_workflow(
    db: Database,
    queue_type: QueueType,
    clear_pending: bool = False,
    clear_done: bool = True,
    clear_errors: bool = True,
) -> int:
    """
    Clear jobs from queue based on status.

    Business rules:
    - Cannot clear running jobs (safety)
    - By default clears done + error jobs
    - Can optionally clear pending jobs
    - Returns count of removed jobs

    Args:
        db: Database instance
        queue_type: Which queue to clear ("tag", "library", "calibration")
        clear_pending: If True, also clear pending jobs (default False)
        clear_done: If True, clear completed jobs (default True)
        clear_errors: If True, clear error jobs (default True)

    Returns:
        Total number of jobs removed

    Raises:
        ValueError: If no clear options specified
    """
    if not (clear_pending or clear_done or clear_errors):
        raise ValueError("Must specify at least one status to clear")

    logger.info(
        f"[clear_queue_wf] Clearing {queue_type} queue: "
        f"pending={clear_pending}, done={clear_done}, errors={clear_errors}"
    )

    # Build list of statuses to clear
    statuses = []
    if clear_pending:
        statuses.append("pending")
    if clear_done:
        statuses.append("done")
    if clear_errors:
        statuses.append("error")

    # Call component to clear by status
    removed = clear_jobs_by_status(db, statuses, queue_type)

    logger.info(f"[clear_queue_wf] Cleared {removed} jobs from {queue_type} queue")
    return removed


def clear_completed_workflow(db: Database, queue_type: QueueType) -> int:
    """
    Clear only completed (done) jobs from queue.

    Convenience workflow for common operation.

    Args:
        db: Database instance
        queue_type: Which queue to clear

    Returns:
        Number of jobs removed
    """
    removed = clear_completed_jobs(db, queue_type)
    logger.info(f"[clear_queue_wf] Cleared {removed} completed jobs from {queue_type} queue")
    return removed


def clear_errors_workflow(db: Database, queue_type: QueueType) -> int:
    """
    Clear only error jobs from queue.

    Convenience workflow for common operation.

    Args:
        db: Database instance
        queue_type: Which queue to clear

    Returns:
        Number of jobs removed
    """
    removed = clear_error_jobs(db, queue_type)
    logger.info(f"[clear_queue_wf] Cleared {removed} error jobs from {queue_type} queue")
    return removed


def clear_all_workflow(db: Database, queue_type: QueueType) -> int:
    """
    Clear all jobs (pending, done, error) from queue.

    Does not clear running jobs (safety).

    Args:
        db: Database instance
        queue_type: Which queue to clear

    Returns:
        Number of jobs removed
    """
    removed = clear_all_jobs(db, queue_type)
    logger.info(f"[clear_queue_wf] Cleared all {removed} jobs from {queue_type} queue")
    return removed
