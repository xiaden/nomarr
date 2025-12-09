"""
Job recovery component - automatic requeue for jobs interrupted by worker crashes.

Handles jobs that were left in "running" state due to worker crash (OS kill, OOM, etc.).
Implements safeguards to prevent infinite requeue loops on toxic jobs.

Architecture:
- No imports from services layer
- Uses persistence and helpers only
- Pure decision logic with clear inputs/outputs
- WorkerSystemService delegates crash recovery to this component

Distinction from file-level failures:
- File-level failures: process_fn raises exception → BaseWorker marks job as error
  → No automatic requeue (job is legitimately bad)
- Worker crashes: Worker process dies before marking job complete/error
  → Job stuck in "running" → This component requeues it (with limits)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

# Job recovery policy constants
MAX_JOB_CRASH_RETRIES = 2  # Allow job to be requeued this many times after worker crashes
CRASH_COUNTER_KEY_PREFIX = "job_crash_count"  # Meta key prefix for tracking per-job crashes

QueueType = Literal["tag", "library", "calibration"]


def requeue_crashed_job(
    db: Database,
    queue_type: QueueType,
    job_id: int | None,
    *,
    max_retries: int = MAX_JOB_CRASH_RETRIES,
) -> bool:
    """
    Requeue a job that was interrupted by worker crash.

    Only requeues jobs that are currently in "running" state and haven't
    exceeded the crash retry limit. Toxic jobs (repeatedly crashing workers)
    are marked as failed instead of requeued.

    Args:
        db: Database instance
        queue_type: Queue type ("tag", "library", "calibration")
        job_id: Job ID from worker's current_job field (None if worker was idle)
        max_retries: Maximum number of times to requeue after crashes (default: 2)

    Returns:
        True if job was requeued, False if no action taken

    Side effects:
        - Updates job status (running → pending OR running → error)
        - Increments crash counter in meta table
        - Logs actions taken

    Examples:
        # Worker crashed while processing job 123
        >>> requeue_crashed_job(db, "tag", job_id=123)
        True  # Job requeued to pending

        # Worker was idle (no current_job)
        >>> requeue_crashed_job(db, "tag", job_id=None)
        False  # No action needed

        # Job already crashed 3 times
        >>> requeue_crashed_job(db, "tag", job_id=456, max_retries=2)
        False  # Job marked as toxic, not requeued
    """
    if job_id is None:
        logger.debug("Worker had no current_job - no recovery needed")
        return False

    logger.info(f"Attempting to recover job {job_id} from {queue_type} queue after worker crash")

    # Get job details to verify it needs recovery
    job = _get_job_if_running(db, queue_type, job_id)
    if job is None:
        # Job is not in running state (maybe already completed/errored by another process)
        logger.debug(f"Job {job_id} not in running state - no recovery needed")
        return False

    # Check crash counter - have we tried this job too many times?
    crash_count = _get_job_crash_count(db, queue_type, job_id)

    if crash_count >= max_retries:
        # Toxic job - mark as failed permanently
        error_msg = (
            f"Job failed after {crash_count + 1} worker crashes. "
            f"This job appears to cause workers to crash (OOM, GPU errors, etc.). "
            f"Manual intervention required."
        )
        _mark_job_toxic(db, queue_type, job_id, crash_count, error_msg)
        logger.warning(
            f"Job {job_id} exceeded crash retry limit ({crash_count} >= {max_retries}). Marked as toxic/failed."
        )
        return False

    # Increment crash counter and requeue job
    _increment_job_crash_count(db, queue_type, job_id, crash_count)
    _reset_job_to_pending(db, queue_type, job_id)

    logger.info(f"Requeued job {job_id} from {queue_type} queue (crash #{crash_count + 1}, limit={max_retries})")
    return True


def _get_job_if_running(
    db: Database,
    queue_type: QueueType,
    job_id: int,
) -> dict[str, Any] | None:
    """
    Get job details if it's currently in running state.

    Returns:
        Job dict if status is "running", None otherwise
    """
    if queue_type == "tag":
        job = db.tag_queue.job_status(job_id)
        if job is None:
            logger.warning(f"Job {job_id} not found in tag queue during crash recovery")
            return None

        status = job.get("status")
        logger.debug(f"Job {job_id} current status: {status}")

        if status == "running":
            return {"id": job_id, "status": "running", "path": job.get("path")}
        else:
            logger.debug(f"Job {job_id} not in running state (status={status}), skipping recovery")
            return None
    elif queue_type == "library":
        # Library queue uses different schema - check if scan is in progress
        # For now, we assume library jobs don't need crash recovery (idempotent scans)
        logger.debug(f"Library queue job {job_id} - skipping crash recovery (not implemented)")
        return None
    elif queue_type == "calibration":
        # Calibration queue - check if job is running
        # Note: Calibration may not support per-job tracking
        logger.debug(f"Calibration queue job {job_id} - skipping crash recovery (not implemented)")
        return None

    return None


def _get_job_crash_count(db: Database, queue_type: QueueType, job_id: int) -> int:
    """
    Get current crash count for a job from meta table.

    Returns:
        Crash count (0 if key doesn't exist)
    """
    key = f"{CRASH_COUNTER_KEY_PREFIX}:{queue_type}:{job_id}"
    value = db.meta.get(key)
    if value is None:
        return 0

    try:
        return int(value)
    except ValueError:
        logger.warning(f"Invalid crash count value for {key}: {value!r}. Treating as 0.")
        return 0


def _increment_job_crash_count(
    db: Database,
    queue_type: QueueType,
    job_id: int,
    current_count: int,
) -> None:
    """
    Increment crash counter for a job in meta table.
    """
    key = f"{CRASH_COUNTER_KEY_PREFIX}:{queue_type}:{job_id}"
    new_count = current_count + 1
    db.meta.set(key, str(new_count))
    logger.debug(f"Incremented crash count for job {job_id}: {current_count} → {new_count}")


def _reset_job_to_pending(db: Database, queue_type: QueueType, job_id: int) -> None:
    """
    Reset job from running → pending status.

    Uses existing queue operations to perform the reset.
    """
    if queue_type == "tag":
        # Tag queue has direct status update capability
        db.tag_queue.update_job(job_id, status="pending")
        logger.debug(f"Reset tag queue job {job_id} to pending")
    elif queue_type == "library":
        # Library queue reset via reset_running_library_scans
        db.library_queue.reset_running_library_scans()
        logger.debug(f"Reset library queue job {job_id} via reset_running_library_scans")
    elif queue_type == "calibration":
        logger.warning(f"Calibration queue job {job_id} reset not implemented")


def _mark_job_toxic(
    db: Database,
    queue_type: QueueType,
    job_id: int,
    crash_count: int,
    error_msg: str,
) -> None:
    """
    Mark job as permanently failed (toxic job).

    Args:
        db: Database instance
        queue_type: Queue type
        job_id: Job ID
        crash_count: Final crash count
        error_msg: Error message explaining why job is toxic
    """
    if queue_type == "tag":
        # Mark job as error with toxic job message
        db.tag_queue.update_job(job_id, status="error", error_message=error_msg)
        logger.info(f"Marked tag queue job {job_id} as toxic (error status)")
    elif queue_type == "library":
        logger.warning(f"Library queue job {job_id} toxic marking not implemented")
    elif queue_type == "calibration":
        logger.warning(f"Calibration queue job {job_id} toxic marking not implemented")

    # Clean up crash counter from meta table
    key = f"{CRASH_COUNTER_KEY_PREFIX}:{queue_type}:{job_id}"
    db.meta.delete(key)
    logger.debug(f"Deleted crash counter for toxic job {job_id}")
