"""
Admin API endpoints for queue management and system control.
Routes: /v1/admin/queue/*, /v1/admin/cache/*, /v1/admin/worker/*

These routes will be mounted under /api/v1/admin via the integration router.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_key
from nomarr.interfaces.api.types.admin_types import (
    CacheRefreshResponse,
    JobRemovalResponse,
    RetagAllResponse,
    WorkerOperationResponse,
)
from nomarr.interfaces.api.types.queue_types import FlushRequest, FlushResponse, RemoveJobRequest
from nomarr.interfaces.api.web.dependencies import (
    get_calibration_service,
    get_event_broker,
    get_ml_service,
    get_queue_service,
    get_workers_coordinator,
)
from nomarr.services.domain.calibration_svc import CalibrationService
from nomarr.services.infrastructure.ml_svc import MLService
from nomarr.services.infrastructure.queue_svc import QueueService
from nomarr.services.infrastructure.worker_system_svc import WorkerSystemService

# Router instance (will be included under /api/v1/admin)
router = APIRouter(tags=["admin"], prefix="/v1/admin")


# ----------------------------------------------------------------------
#  POST /admin/queue/remove
# ----------------------------------------------------------------------
@router.post("/queue/remove", dependencies=[Depends(verify_key)])
async def admin_remove_job(
    payload: RemoveJobRequest,
    queue_service: QueueService = Depends(get_queue_service),
) -> JobRemovalResponse:
    """Remove a single job by ID (cannot remove if running)."""
    try:
        result = queue_service.remove_job_for_admin(job_id=payload.job_id)
        return JobRemovalResponse.from_dto(result)
    except ValueError as e:
        status_code = 404 if "not found" in str(e).lower() else 409
        detail = "Job not found" if status_code == 404 else "Cannot remove job"
        raise HTTPException(status_code=status_code, detail=detail) from None


# ----------------------------------------------------------------------
#  POST /admin/queue/flush
# ----------------------------------------------------------------------
@router.post("/queue/flush", dependencies=[Depends(verify_key)])
async def admin_flush_queue(
    payload: FlushRequest = Body(default=None),
    queue_service: QueueService = Depends(get_queue_service),
) -> FlushResponse:
    """Flush jobs by status (default: pending + error). Cannot flush running jobs."""
    statuses = payload.statuses if payload and payload.statuses else ["pending", "error"]

    try:
        result = queue_service.flush_by_statuses(statuses)
        # Transform DTO to Pydantic response
        return FlushResponse.from_dto(result)
    except ValueError as e:
        status_code = 400 if "Invalid" in str(e) else 409
        detail = "Invalid flush request" if status_code == 400 else "Cannot flush queue"
        raise HTTPException(status_code=status_code, detail=detail) from None


# ----------------------------------------------------------------------
#  POST /admin/queue/cleanup
# ----------------------------------------------------------------------
@router.post("/queue/cleanup", dependencies=[Depends(verify_key)])
async def admin_cleanup_queue(
    max_age_hours: int = 168,
    queue_service: QueueService = Depends(get_queue_service),
) -> JobRemovalResponse:
    """
    Remove old finished jobs from the queue (done/error status).
    Matches CLI cleanup command behavior.
    Default: 168 hours (7 days).
    """
    result = queue_service.cleanup_old_jobs_for_admin(max_age_hours)
    return JobRemovalResponse.from_dto(result)


# ----------------------------------------------------------------------
#  POST /admin/cache/refresh
# ----------------------------------------------------------------------
@router.post("/cache/refresh", dependencies=[Depends(verify_key)])
async def admin_cache_refresh(
    ml_service: MLService = Depends(get_ml_service),
) -> CacheRefreshResponse:
    """Force rebuild of the predictor cache (discover heads and load missing)."""
    try:
        result = ml_service.warmup_cache_for_admin()
        return CacheRefreshResponse.from_dto(result)
    except Exception as e:
        logging.exception("[Admin API] Cache refresh failed")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Cache refresh failed")) from e


# ----------------------------------------------------------------------
#  POST /admin/worker/pause
# ----------------------------------------------------------------------
@router.post("/worker/pause", dependencies=[Depends(verify_key)])
async def admin_pause_worker(
    workers_coordinator: WorkerSystemService = Depends(get_workers_coordinator),
    event_broker=Depends(get_event_broker),
) -> WorkerOperationResponse:
    """Pause all background workers (stops processing new jobs)."""
    result = workers_coordinator.pause_all_workers(event_broker)
    return WorkerOperationResponse.from_dto(result)


# ----------------------------------------------------------------------
#  POST /admin/worker/resume
# ----------------------------------------------------------------------
@router.post("/worker/resume", dependencies=[Depends(verify_key)])
async def admin_resume_worker(
    workers_coordinator: WorkerSystemService = Depends(get_workers_coordinator),
    event_broker=Depends(get_event_broker),
) -> WorkerOperationResponse:
    """Resume all background workers (starts processing again)."""
    result = workers_coordinator.resume_all_workers(event_broker)
    return WorkerOperationResponse.from_dto(result)


# ----------------------------------------------------------------------
#  POST /admin/calibration/run
# ----------------------------------------------------------------------
@router.post("/calibration/run", dependencies=[Depends(verify_key)])
async def admin_run_calibration(
    calibration_service: CalibrationService = Depends(get_calibration_service),
):
    """
    Generate calibrations using histogram-based approach.

    Analyzes library tags using DB histogram queries (memory-bounded).
    Computes p5/p95 percentiles for each head.

    Returns:
        Calibration summary with per-head results
    """
    try:
        if not calibration_service.cfg.calibrate_heads:
            raise HTTPException(
                status_code=403,
                detail="Calibration generation disabled. Set calibrate_heads: true in config to enable.",
            )

        result = calibration_service.generate_histogram_calibration()
        return result
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("[Admin API] Calibration generation failed")
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Calibration generation failed")
        ) from e


# NOTE: /admin/calibration/history endpoint removed - was part of old drift tracking system


# ----------------------------------------------------------------------
#  POST /admin/calibration/backfill
# ----------------------------------------------------------------------
@router.post("/calibration/backfill", dependencies=[Depends(verify_key)])
async def admin_backfill_calibration_hashes(
    set_to_current: bool = False,
    calibration_service: CalibrationService = Depends(get_calibration_service),
):
    """
    Backfill calibration_hash for files currently showing as NULL.

    Two strategies:
    - set_to_current=False (default): Leave as NULL, users must recalibrate
    - set_to_current=True: Set to current global hash (assumes files are current)

    Returns:
        Summary of backfill operation
    """
    try:
        from nomarr.workflows.calibration.backfill_calibration_hash_wf import backfill_calibration_hashes_wf

        result = backfill_calibration_hashes_wf(db=calibration_service._db, set_to_current=set_to_current)
        return result
    except Exception as e:
        logging.exception("[Admin API] Backfill failed")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Backfill failed")) from e


# ----------------------------------------------------------------------
#  POST /admin/calibration/retag-all
# ----------------------------------------------------------------------
@router.post("/calibration/retag-all", dependencies=[Depends(verify_key)])
async def admin_retag_all(
    queue_service: QueueService = Depends(get_queue_service),
) -> RetagAllResponse:
    """
    Mark all tagged files for re-tagging (requires calibrate_heads=true).

    This enqueues all library_files with tagged=1 for ML re-tagging.
    Use after deciding final calibration is stable and want to apply it
    to entire library.

    Returns:
        Number of files enqueued
    """
    try:
        result = queue_service.retag_all_for_admin()
        return RetagAllResponse.from_dto(result)
    except ValueError:
        raise HTTPException(status_code=403, detail="Retag operation not allowed") from None
    except Exception as e:
        logging.exception("[Admin API] Failed to enqueue files")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to enqueue files")) from e
