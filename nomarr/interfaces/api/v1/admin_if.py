"""
Admin API endpoints for queue management and system control.
Routes: /v1/admin/queue/*, /v1/admin/cache/*, /v1/admin/worker/*

These routes will be mounted under /api/v1/admin via the integration router.

ARCHITECTURE:
- Thin HTTP boundary layer
- Calls workflows and components directly (no QueueService)
- Services handle complex orchestration only
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from nomarr.components.queue import cleanup_old_jobs
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
    get_database,
    get_event_broker,
    get_ml_service,
    get_workers_coordinator,
)
from nomarr.persistence.db import Database
from nomarr.services.calibration_svc import CalibrationService
from nomarr.services.ml_svc import MLService
from nomarr.services.workers_coordinator_svc import WorkersCoordinator
from nomarr.workflows.queue import clear_queue_workflow, remove_job_workflow

# Router instance (will be included under /api/v1/admin)
router = APIRouter(tags=["admin"], prefix="/v1/admin")


# ----------------------------------------------------------------------
#  POST /admin/queue/remove
# ----------------------------------------------------------------------
@router.post("/queue/remove", dependencies=[Depends(verify_key)])
async def admin_remove_job(
    payload: RemoveJobRequest,
    db: Database = Depends(get_database),
) -> JobRemovalResponse:
    """Remove a single job by ID (cannot remove if running)."""
    try:
        result = remove_job_workflow(db, job_id=int(payload.job_id), queue_type="tag")
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
    db: Database = Depends(get_database),
) -> FlushResponse:
    """Flush jobs by status (default: pending + error). Cannot flush running jobs."""
    statuses = payload.statuses if payload and payload.statuses else ["pending", "error"]

    try:
        # Convert statuses to JobStatus literals
        from nomarr.helpers.dto.queue_dto import JobStatus

        status_list: list[JobStatus] = []
        for s in statuses:
            if s in ("pending", "running", "done", "error"):
                status_list.append(s)  # type: ignore[arg-type]
            else:
                raise ValueError(f"Invalid status: {s}")

        result = clear_queue_workflow(db, queue_type="tag", statuses=status_list)
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
    db: Database = Depends(get_database),
) -> JobRemovalResponse:
    """
    Remove old finished jobs from the queue (done/error status).
    Matches CLI cleanup command behavior.
    Default: 168 hours (7 days).
    """
    count = cleanup_old_jobs(db, queue_type="tag", max_age_hours=max_age_hours)
    # Convert to JobRemovalResult DTO
    from nomarr.helpers.dto.admin_dto import JobRemovalResult

    result = JobRemovalResult(job_ids=[], count=count)
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
    db: Database = Depends(get_database),
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
        # TODO: Move this logic to a workflow in workflows/calibration/
        # For now, inline the logic
        from nomarr.app import application
        from nomarr.components.queue import enqueue_file

        config_service = application.get_service("config")
        calibrate_heads = config_service.get_config().get("general", {}).get("calibrate_heads", False)

        if not calibrate_heads:
            raise ValueError("Bulk re-tagging not available. Set calibrate_heads: true in config to enable.")

        # Get all tagged file paths
        tagged_paths = db.library_files.get_tagged_file_paths()

        if not tagged_paths:
            from nomarr.helpers.dto.admin_dto import RetagAllResult

            result = RetagAllResult(status="ok", message="No tagged files found", enqueued=0)
            return RetagAllResponse.from_dto(result)

        # Enqueue all tagged files
        count = 0
        for path in tagged_paths:
            try:
                enqueue_file(db, path, force=True, queue_type="tag")
                count += 1
            except Exception as e:
                import logging

                logging.error(f"Failed to enqueue {path}: {e}")

        from nomarr.helpers.dto.admin_dto import RetagAllResult

        result = RetagAllResult(status="ok", message=f"Enqueued {count} files for re-tagging", enqueued=count)
        return RetagAllResponse.from_dto(result)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to enqueue files: {e!s}") from e
