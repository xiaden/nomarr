"""
Admin API endpoints for queue management and system control.
Routes: /v1/admin/queue/*, /v1/admin/cache/*, /v1/admin/worker/*

These routes will be mounted under /api/v1/admin via the integration router.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from nomarr.interfaces.api.auth import verify_key
from nomarr.interfaces.api.types.admin_types import (
    CacheRefreshResponse,
    CalibrationHistoryResponse,
    JobRemovalResponse,
    RetagAllResponse,
    RunCalibrationResponse,
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
from nomarr.services.calibration_svc import CalibrationService
from nomarr.services.ml_svc import MLService
from nomarr.services.queue_svc import QueueService
from nomarr.services.workers_coordinator_svc import WorkersCoordinator

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
        result = queue_service.remove_job_for_admin(job_id=int(payload.job_id))
        return JobRemovalResponse.from_dto(result)
    except ValueError as e:
        status_code = 404 if "not found" in str(e).lower() else 409
        raise HTTPException(status_code=status_code, detail=str(e)) from e


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
        raise HTTPException(status_code=status_code, detail=str(e)) from e


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
        raise HTTPException(status_code=500, detail=str(e)) from e


# ----------------------------------------------------------------------
#  POST /admin/worker/pause
# ----------------------------------------------------------------------
@router.post("/worker/pause", dependencies=[Depends(verify_key)])
async def admin_pause_worker(
    workers_coordinator: WorkersCoordinator = Depends(get_workers_coordinator),
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
    workers_coordinator: WorkersCoordinator = Depends(get_workers_coordinator),
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
) -> RunCalibrationResponse:
    """
    Generate calibrations with drift tracking (requires calibrate_heads=true).

    Analyzes library tags, calculates drift metrics, saves versioned files,
    and updates reference files for unstable heads.

    Returns:
        Calibration summary with drift metrics per head
    """
    try:
        result = calibration_service.run_calibration_for_admin()
        return RunCalibrationResponse.from_dto(result)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Calibration generation failed: {e!s}") from e


# ----------------------------------------------------------------------
#  GET /admin/calibration/history
# ----------------------------------------------------------------------
@router.get("/calibration/history", dependencies=[Depends(verify_key)])
async def admin_calibration_history(
    calibration_service: CalibrationService = Depends(get_calibration_service),
    model: str | None = None,
    head: str | None = None,
    limit: int = 100,
) -> CalibrationHistoryResponse:
    """
    Get calibration history with drift metrics.

    Query params:
        model: Filter by model name (optional)
        head: Filter by head name (optional)
        limit: Maximum number of results (default 100)

    Returns:
        List of calibration runs with drift metrics
    """
    try:
        result = calibration_service.get_calibration_history_for_admin(model_name=model, head_name=head, limit=limit)
        return CalibrationHistoryResponse.from_dto(result)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve calibration history: {e!s}") from e


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
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to enqueue files: {e!s}") from e
