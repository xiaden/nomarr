"""
Admin API endpoints for queue management and system control.
Routes: /v1/admin/queue/*, /v1/admin/cache/*, /v1/admin/worker/*

These routes will be mounted under /api/v1/admin via the integration router.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from nomarr.interfaces.api.auth import verify_key
from nomarr.interfaces.api.types.queue_request_types import FlushRequest, RemoveJobRequest
from nomarr.interfaces.api.web.dependencies_if import (
    get_calibration_service,
    get_config,
    get_event_broker,
    get_ml_service,
    get_queue_service,
    get_worker_pool,
    get_worker_service,
)
from nomarr.services.calibration_svc import CalibrationService
from nomarr.services.ml_svc import MLService
from nomarr.services.queue_svc import QueueService
from nomarr.services.worker_svc import WorkerService

# Router instance (will be included under /api/v1/admin)
router = APIRouter(tags=["admin"], prefix="/v1/admin")


# ----------------------------------------------------------------------
#  POST /admin/queue/remove
# ----------------------------------------------------------------------
@router.post("/queue/remove", dependencies=[Depends(verify_key)])
async def admin_remove_job(
    payload: RemoveJobRequest,
    queue_service: QueueService = Depends(get_queue_service),
):
    """Remove a single job by ID (cannot remove if running)."""
    try:
        queue_service.remove_jobs(job_id=int(payload.job_id))
        return {"status": "ok", "removed": int(payload.job_id)}
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
):
    """Flush jobs by status (default: pending + error). Cannot flush running jobs."""
    statuses = payload.statuses if payload and payload.statuses else ["pending", "error"]

    try:
        result = queue_service.flush_by_statuses(statuses)
        # Return DTO fields inline rather than unpacking
        return {"status": "ok", "flushed_statuses": result.flushed_statuses, "removed": result.removed}
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
):
    """
    Remove old finished jobs from the queue (done/error status).
    Matches CLI cleanup command behavior.
    Default: 168 hours (7 days).
    """
    removed = queue_service.cleanup_old_jobs(max_age_hours)
    return {"status": "ok", "max_age_hours": max_age_hours, "jobs_removed": removed}


# ----------------------------------------------------------------------
#  POST /admin/cache/refresh
# ----------------------------------------------------------------------
@router.post("/cache/refresh", dependencies=[Depends(verify_key)])
async def admin_cache_refresh(
    ml_service: MLService = Depends(get_ml_service),
):
    """Force rebuild of the predictor cache (discover heads and load missing)."""
    try:
        num = ml_service.warmup_cache()
        return {"status": "ok", "predictors": num}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


# ----------------------------------------------------------------------
#  POST /admin/worker/pause
# ----------------------------------------------------------------------
@router.post("/worker/pause", dependencies=[Depends(verify_key)])
async def admin_pause_worker(
    worker_service: WorkerService = Depends(get_worker_service),
    event_broker=Depends(get_event_broker),
):
    """Pause the background worker (stops processing new jobs)."""
    result = worker_service.pause_workers(event_broker)
    return {"status": "ok", "worker_enabled": result.worker_enabled}


# ----------------------------------------------------------------------
#  POST /admin/worker/resume
# ----------------------------------------------------------------------
@router.post("/worker/resume", dependencies=[Depends(verify_key)])
async def admin_resume_worker(
    worker_service: WorkerService = Depends(get_worker_service),
    worker_pool: list = Depends(get_worker_pool),
    event_broker=Depends(get_event_broker),
):
    """Resume the background worker (starts processing again)."""
    result = worker_service.resume_workers(worker_pool, event_broker)
    return {"status": "ok", "worker_enabled": result.worker_enabled}


# ----------------------------------------------------------------------
#  POST /admin/calibration/run
# ----------------------------------------------------------------------
@router.post("/calibration/run", dependencies=[Depends(verify_key)])
async def admin_run_calibration(
    calibration_service: CalibrationService = Depends(get_calibration_service),
    config: dict = Depends(get_config),
):
    """
    Generate calibrations with drift tracking (requires calibrate_heads=true).

    Analyzes library tags, calculates drift metrics, saves versioned files,
    and updates reference files for unstable heads.

    Returns:
        Calibration summary with drift metrics per head
    """
    # Check if calibrate_heads mode is enabled
    calibrate_heads = config.get("general", {}).get("calibrate_heads", False)

    if not calibrate_heads:
        raise HTTPException(
            status_code=403,
            detail="Calibration generation disabled. Set calibrate_heads: true in config to enable.",
        )

    try:
        result = calibration_service.generate_calibration_with_tracking()
        return {"status": "ok", "calibration": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Calibration generation failed: {e!s}") from e


# ----------------------------------------------------------------------
#  GET /admin/calibration/history
# ----------------------------------------------------------------------
@router.get("/calibration/history", dependencies=[Depends(verify_key)])
async def admin_calibration_history(
    calibration_service: CalibrationService = Depends(get_calibration_service),
    config: dict = Depends(get_config),
    model: str | None = None,
    head: str | None = None,
    limit: int = 100,
):
    """
    Get calibration history with drift metrics.

    Query params:
        model: Filter by model name (optional)
        head: Filter by head name (optional)
        limit: Maximum number of results (default 100)

    Returns:
        List of calibration runs with drift metrics
    """
    # Check if calibrate_heads mode is enabled
    calibrate_heads = config.get("general", {}).get("calibrate_heads", False)

    if not calibrate_heads:
        raise HTTPException(
            status_code=403,
            detail="Calibration history not available. Set calibrate_heads: true in config to enable.",
        )

    try:
        runs = calibration_service.get_calibration_history(model_name=model, head_name=head, limit=limit)
        return {"status": "ok", "runs": runs, "count": len(runs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve calibration history: {e!s}") from e


# ----------------------------------------------------------------------
#  POST /admin/calibration/retag-all
# ----------------------------------------------------------------------
@router.post("/calibration/retag-all", dependencies=[Depends(verify_key)])
async def admin_retag_all(
    queue_service: QueueService = Depends(get_queue_service),
    config: dict = Depends(get_config),
):
    """
    Mark all tagged files for re-tagging (requires calibrate_heads=true).

    This enqueues all library_files with tagged=1 for ML re-tagging.
    Use after deciding final calibration is stable and want to apply it
    to entire library.

    Returns:
        Number of files enqueued
    """
    # Check if calibrate_heads mode is enabled
    calibrate_heads = config.get("general", {}).get("calibrate_heads", False)

    if not calibrate_heads:
        raise HTTPException(
            status_code=403,
            detail="Bulk re-tagging not available. Set calibrate_heads: true in config to enable.",
        )

    try:
        # Use queue service to get and enqueue all tagged files
        count = queue_service.enqueue_all_tagged_files()

        if count == 0:
            return {"status": "ok", "message": "No tagged files found", "enqueued": 0}

        return {"status": "ok", "message": f"Enqueued {count} files for re-tagging", "enqueued": count}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to enqueue files: {e!s}") from e
