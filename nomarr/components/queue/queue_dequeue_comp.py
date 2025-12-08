"""Queue dequeue operations - poll for jobs and update job status."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

QueueType = Literal["tag", "library", "calibration"]

logger = logging.getLogger(__name__)


def get_next_job(db: Database, queue_type: QueueType) -> dict | None:
    """
    Get next pending job from specified queue.

    Returns the next job in pending status and marks it as running.

    Args:
        db: Database instance
        queue_type: Which queue to poll ("tag", "library", "calibration")

    Returns:
        Job dict with keys: id, path, force (if applicable)
        Returns None if no pending jobs available

    Raises:
        ValueError: If queue_type is invalid
    """
    if queue_type == "tag":
        job = db.tag_queue.get_next_pending_job()
        if job:
            return {
                "id": job["id"],
                "path": job["path"],
                "force": job.get("force", False),
            }
        return None

    elif queue_type == "library":
        # library_queue.dequeue_scan() returns tuple[int, str, bool] | None
        lib_result = db.library_queue.dequeue_scan()
        if lib_result:
            job_id, path, force = lib_result
            return {
                "id": job_id,
                "path": path,
                "force": force,
                "status": "running",
            }
        return None

    elif queue_type == "calibration":
        # calibration_queue.get_next_calibration_job() returns tuple[int, str] | None
        cal_result = db.calibration_queue.get_next_calibration_job()
        if cal_result:
            job_id, path = cal_result
            return {
                "id": job_id,
                "path": path,
                "force": False,  # Calibration doesn't use force flag
                "status": "running",
            }
        return None

    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")


def mark_job_complete(db: Database, job_id: int, queue_type: QueueType) -> None:
    """
    Mark a job as completed.

    Args:
        db: Database instance
        job_id: ID of job to mark complete
        queue_type: Which queue the job belongs to

    Raises:
        ValueError: If queue_type is invalid
    """
    logger.debug(f"Marking job {job_id} complete in {queue_type} queue")

    if queue_type == "tag":
        db.tag_queue.update_job(job_id, status="done")
    elif queue_type == "library":
        db.library_queue.mark_scan_complete(job_id)
    elif queue_type == "calibration":
        db.calibration_queue.complete_calibration_job(job_id)
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")


def mark_job_error(db: Database, job_id: int, error_message: str, queue_type: QueueType) -> None:
    """
    Mark a job as failed with error message.

    Args:
        db: Database instance
        job_id: ID of job to mark as error
        error_message: Error description
        queue_type: Which queue the job belongs to

    Raises:
        ValueError: If queue_type is invalid
    """
    logger.debug(f"Marking job {job_id} as error in {queue_type} queue: {error_message}")

    if queue_type == "tag":
        db.tag_queue.update_job(job_id, status="error", error_message=error_message)
    elif queue_type == "library":
        db.library_queue.mark_scan_error(job_id, error_message)
    elif queue_type == "calibration":
        db.calibration_queue.fail_calibration_job(job_id, error_message)
    else:
        raise ValueError(f"Invalid queue_type: {queue_type}")
