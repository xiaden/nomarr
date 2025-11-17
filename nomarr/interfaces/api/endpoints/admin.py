"""
Admin API endpoints for queue management and system control.
Routes: /admin/queue/*, /admin/cache/*, /admin/worker/*
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from nomarr.app import application
from nomarr.interfaces.api.auth import verify_key
from nomarr.interfaces.api.models import FlushRequest, RemoveJobRequest
from nomarr.ml.cache import warmup_predictor_cache

# Router instance (will be included in main app)
router = APIRouter(tags=["admin"], prefix="/admin")


# ----------------------------------------------------------------------
#  Dependency: get app globals
# ----------------------------------------------------------------------
def get_globals():
    """Get global instances (db, queue, services, etc.) from application."""

    return {
        "db": application.db,
        "queue": application.queue,
        "queue_service": application.get_service("queue"),
        "worker_service": application.get_service("worker"),
        "worker_pool": application.workers,
        "processor_coord": application.coordinator,
        "event_broker": application.event_broker,
    }


# ----------------------------------------------------------------------
#  POST /admin/queue/remove
# ----------------------------------------------------------------------
@router.post("/queue/remove", dependencies=[Depends(verify_key)])
async def admin_remove_job(payload: RemoveJobRequest):
    """Remove a single job by ID (cannot remove if running)."""
    g = get_globals()
    queue_service = g["queue_service"]
    worker_service = g["worker_service"]

    job_id = int(payload.job_id)

    # Check if job exists and is not running
    job = queue_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] == "running":
        raise HTTPException(status_code=409, detail="Cannot remove a running job")

    # Remove job using service
    queue_service.remove_jobs(job_id=job_id)

    # Auto-resume worker after removing jobs
    if worker_service:
        worker_service.enable()
        updated_pool = worker_service.start_workers()
        # Update application worker pool
        application.workers = updated_pool

    return {"status": "ok", "removed": job_id, "worker_enabled": True}


# ----------------------------------------------------------------------
#  POST /admin/queue/flush
# ----------------------------------------------------------------------
@router.post("/queue/flush", dependencies=[Depends(verify_key)])
async def admin_flush_queue(payload: FlushRequest = Body(default=None)):
    """Flush jobs by status (default: pending + error). Cannot flush running jobs."""
    g = get_globals()
    queue_service = g["queue_service"]
    worker_service = g["worker_service"]

    statuses = payload.statuses if payload and payload.statuses else ["pending", "error"]
    valid = {"pending", "running", "done", "error"}
    bad = [s for s in statuses if s not in valid]
    if bad:
        raise HTTPException(status_code=400, detail=f"Invalid statuses: {bad}")
    if "running" in statuses:
        raise HTTPException(status_code=409, detail="Refusing to flush 'running' jobs")

    # Remove jobs by status using service
    total_removed = 0
    for status in statuses:
        removed = queue_service.remove_jobs(status=status)
        total_removed += removed

    # Auto-resume worker after flushing
    if worker_service:
        worker_service.enable()
        updated_pool = worker_service.start_workers()
        application.workers = updated_pool

    return {"status": "ok", "flushed_statuses": statuses, "removed": total_removed, "worker_enabled": True}


# ----------------------------------------------------------------------
#  POST /admin/queue/cleanup
# ----------------------------------------------------------------------
@router.post("/queue/cleanup", dependencies=[Depends(verify_key)])
async def admin_cleanup_queue(max_age_hours: int = 168):
    """
    Remove old finished jobs from the queue (done/error status).
    Matches CLI cleanup command behavior.
    Default: 168 hours (7 days).
    """
    g = get_globals()
    queue_service = g["queue_service"]

    # Use service to cleanup old jobs
    removed = queue_service.cleanup_old_jobs(max_age_hours=max_age_hours)

    return {
        "status": "ok",
        "max_age_hours": max_age_hours,
        "jobs_removed": removed,
    }


# ----------------------------------------------------------------------
#  POST /admin/cache/refresh
# ----------------------------------------------------------------------
@router.post("/cache/refresh", dependencies=[Depends(verify_key)])
async def admin_cache_refresh():
    """Force rebuild of the predictor cache (discover heads and load missing)."""
    try:
        g = get_globals()
        config_service = g["config_service"]
        cfg = config_service.get_config()

        models_dir = str(cfg["models_dir"])
        cache_idle_timeout = int(cfg.get("cache_idle_timeout", 300))

        num = warmup_predictor_cache(
            models_dir=models_dir,
            cache_idle_timeout=cache_idle_timeout,
        )
        return {"status": "ok", "predictors": num}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cache refresh failed: {e}") from e


# ----------------------------------------------------------------------
#  POST /admin/worker/pause
# ----------------------------------------------------------------------
@router.post("/worker/pause", dependencies=[Depends(verify_key)])
async def admin_pause_worker():
    """Pause the background worker (stops processing new jobs)."""
    g = get_globals()
    worker_service = g["worker_service"]
    event_broker = g.get("event_broker")

    if worker_service:
        worker_service.disable()

    # Publish worker status update
    if event_broker:
        event_broker.update_worker_state({"enabled": False})

    return {"status": "ok", "worker_enabled": False}


# ----------------------------------------------------------------------
#  POST /admin/worker/resume
# ----------------------------------------------------------------------
@router.post("/worker/resume", dependencies=[Depends(verify_key)])
async def admin_resume_worker():
    """Resume the background worker (starts processing again)."""
    g = get_globals()
    worker_service = g["worker_service"]
    event_broker = g.get("event_broker")

    if worker_service:
        worker_service.enable()
        updated_pool = worker_service.start_workers(event_broker=event_broker)
        application.workers = updated_pool

    # Publish worker status update
    if event_broker:
        event_broker.update_worker_state({"enabled": True})

    return {"status": "ok", "worker_enabled": True}


# ----------------------------------------------------------------------
#  POST /admin/calibration/run
# ----------------------------------------------------------------------
@router.post("/calibration/run", dependencies=[Depends(verify_key)])
async def admin_run_calibration():
    """
    Generate calibrations with drift tracking (requires calibrate_heads=true).

    Analyzes library tags, calculates drift metrics, saves versioned files,
    and updates reference files for unstable heads.

    Returns:
        Calibration summary with drift metrics per head
    """
    from nomarr.services.calibration import CalibrationService

    g = get_globals()
    db = g["db"]

    # Check if calibrate_heads mode is enabled
    calibrate_heads = application.calibrate_heads

    if not calibrate_heads:
        raise HTTPException(
            status_code=403,
            detail="Calibration generation disabled. Set calibrate_heads: true in config to enable.",
        )

    # Get config service for calibration thresholds
    from nomarr.services.config import (
        INTERNAL_CALIBRATION_APD_THRESHOLD,
        INTERNAL_CALIBRATION_IQR_THRESHOLD,
        INTERNAL_CALIBRATION_JSD_THRESHOLD,
        INTERNAL_CALIBRATION_MEDIAN_THRESHOLD,
        INTERNAL_CALIBRATION_SRD_THRESHOLD,
    )

    # Get config values
    models_dir = application.models_dir
    namespace = application.namespace
    thresholds = {
        "apd_p5": INTERNAL_CALIBRATION_APD_THRESHOLD,
        "apd_p95": INTERNAL_CALIBRATION_APD_THRESHOLD,
        "srd": INTERNAL_CALIBRATION_SRD_THRESHOLD,
        "jsd": INTERNAL_CALIBRATION_JSD_THRESHOLD,
        "median": INTERNAL_CALIBRATION_MEDIAN_THRESHOLD,
        "iqr": INTERNAL_CALIBRATION_IQR_THRESHOLD,
    }

    # Run calibration service
    service = CalibrationService(db=db, models_dir=models_dir, namespace=namespace, thresholds=thresholds)

    try:
        result = service.generate_calibration_with_tracking()
        return {"status": "ok", "calibration": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Calibration generation failed: {e!s}") from e


# ----------------------------------------------------------------------
#  GET /admin/calibration/history
# ----------------------------------------------------------------------
@router.get("/calibration/history", dependencies=[Depends(verify_key)])
async def admin_calibration_history(model: str | None = None, head: str | None = None, limit: int = 100):
    """
    Get calibration history with drift metrics.

    Query params:
        model: Filter by model name (optional)
        head: Filter by head name (optional)
        limit: Maximum number of results (default 100)

    Returns:
        List of calibration runs with drift metrics
    """
    g = get_globals()
    db = g["db"]

    # Check if calibrate_heads mode is enabled
    calibrate_heads = application.calibrate_heads

    if not calibrate_heads:
        raise HTTPException(
            status_code=403,
            detail="Calibration history not available. Set calibrate_heads: true in config to enable.",
        )

    try:
        runs = db.calibration.list_calibration_runs(model_name=model, head_name=head, limit=limit)
        return {"status": "ok", "runs": runs, "count": len(runs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve calibration history: {e!s}") from e


# ----------------------------------------------------------------------
#  POST /admin/calibration/retag-all
# ----------------------------------------------------------------------
@router.post("/calibration/retag-all", dependencies=[Depends(verify_key)])
async def admin_retag_all():
    """
    Mark all tagged files for re-tagging (requires calibrate_heads=true).

    This enqueues all library_files with tagged=1 for ML re-tagging.
    Use after deciding final calibration is stable and want to apply it
    to entire library.

    Returns:
        Number of files enqueued
    """
    g = get_globals()
    db = g["db"]

    # Check if calibrate_heads mode is enabled
    calibrate_heads = application.calibrate_heads

    if not calibrate_heads:
        raise HTTPException(
            status_code=403,
            detail="Bulk re-tagging not available. Set calibrate_heads: true in config to enable.",
        )

    try:
        # Get all tagged files from library
        all_files, _ = db.list_library_files(limit=100000)  # Large limit to get all files
        tagged_files = [f for f in all_files if f.get("tagged")]

        if not tagged_files:
            return {"status": "ok", "message": "No tagged files found", "enqueued": 0}

        # Enqueue all tagged files for re-tagging
        count = 0
        for file in tagged_files:
            try:
                db.enqueue(file["path"], force=True)  # Force re-tag even if already tagged
                count += 1
            except Exception as e:
                import logging

                logging.error(f"Failed to enqueue {file['path']}: {e}")

        return {"status": "ok", "message": f"Enqueued {count} files for re-tagging", "enqueued": count}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to enqueue files: {e!s}") from e
