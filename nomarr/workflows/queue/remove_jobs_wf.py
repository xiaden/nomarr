"""Remove jobs workflow - delete specific jobs with validation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from nomarr.components.queue import get_job, remove_job

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

QueueType = Literal["tag", "library", "calibration"]

logger = logging.getLogger(__name__)


def remove_job_workflow(db: Database, job_id: str, queue_type: QueueType) -> bool:
    """
    Remove a specific job by ID with validation.

    Business rules:
    - Cannot remove running jobs (safety)
    - Job must exist
    - Returns success status

    Args:
        db: Database instance
        job_id: Job ID to remove
        queue_type: Which queue the job belongs to

    Returns:
        True if job was removed, False if not found or couldn't be removed

    Raises:
        ValueError: If job is running (cannot remove)
    """
    logger.info(f"[remove_job_wf] Attempting to remove job {job_id} from {queue_type} queue")

    # Check if job exists and get its status
    job = get_job(db, job_id, queue_type)
    if not job:
        logger.warning(f"[remove_job_wf] Job {job_id} not found in {queue_type} queue")
        return False

    # Business rule: cannot remove running jobs
    if job.get("status") == "running":
        raise ValueError(f"Cannot remove running job {job_id}. Wait for it to complete or reset it first.")

    # Remove the job
    removed_count = remove_job(db, job_id, queue_type)

    if removed_count > 0:
        logger.info(f"[remove_job_wf] Successfully removed job {job_id}")
        return True
    else:
        logger.warning(f"[remove_job_wf] Failed to remove job {job_id}")
        return False
