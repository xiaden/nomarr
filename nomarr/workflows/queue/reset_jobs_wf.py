"""Reset jobs workflow - reset job status with business rules."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from nomarr.components.queue import reset_error_jobs, reset_stuck_jobs

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

QueueType = Literal["tag", "library"]

logger = logging.getLogger(__name__)


def reset_jobs_workflow(
    db: Database,
    queue_type: QueueType,
    reset_stuck: bool = False,
    reset_errors: bool = False,
) -> int:
    """
    Reset jobs back to pending status.

    Business rules:
    - Stuck jobs: jobs in 'running' state that are likely orphaned
    - Error jobs: jobs in 'error' state that should be retried
    - Must specify at least one reset option

    Args:
        db: Database instance
        queue_type: Which queue to reset ("tag", "library", "calibration")
        reset_stuck: If True, reset stuck running jobs to pending
        reset_errors: If True, reset error jobs to pending

    Returns:
        Total number of jobs reset

    Raises:
        ValueError: If no reset options specified
    """
    if not (reset_stuck or reset_errors):
        raise ValueError("Must specify --stuck or --errors")

    logger.info(f"[reset_jobs_wf] Resetting {queue_type} queue jobs: stuck={reset_stuck}, errors={reset_errors}")

    total_reset = 0

    if reset_stuck:
        stuck_count = reset_stuck_jobs(db, queue_type)
        total_reset += stuck_count
        logger.info(f"[reset_jobs_wf] Reset {stuck_count} stuck jobs to pending")

    if reset_errors:
        error_count = reset_error_jobs(db, queue_type)
        total_reset += error_count
        logger.info(f"[reset_jobs_wf] Reset {error_count} error jobs to pending")

    logger.info(f"[reset_jobs_wf] Total jobs reset: {total_reset}")
    return total_reset


def reset_stuck_workflow(db: Database, queue_type: QueueType) -> int:
    """
    Reset only stuck (running) jobs to pending.

    Convenience workflow for common operation.

    Args:
        db: Database instance
        queue_type: Which queue to reset

    Returns:
        Number of jobs reset
    """
    reset_count = reset_stuck_jobs(db, queue_type)
    logger.info(f"[reset_jobs_wf] Reset {reset_count} stuck jobs to pending")
    return reset_count


def reset_errors_workflow(db: Database, queue_type: QueueType) -> int:
    """
    Reset only error jobs to pending.

    Convenience workflow for common operation.

    Args:
        db: Database instance
        queue_type: Which queue to reset

    Returns:
        Number of jobs reset
    """
    reset_count = reset_error_jobs(db, queue_type)
    logger.info(f"[reset_jobs_wf] Reset {reset_count} error jobs to pending")
    return reset_count
