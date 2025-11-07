"""
Admin API endpoints for queue management and system control.
Routes: /admin/queue/*, /admin/cache/*, /admin/worker/*
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

import nomarr.app as app
from nomarr.interfaces.api.auth import verify_key
from nomarr.interfaces.api.models import FlushRequest, RemoveJobRequest
from nomarr.ml.cache import warmup_predictor_cache

# Router instance (will be included in main app)
router = APIRouter(tags=["admin"], prefix="/admin")


# ----------------------------------------------------------------------
#  Dependency: get app globals
# ----------------------------------------------------------------------
def get_globals():
    """Get global instances (db, queue, queue_service, worker_service, etc.) from app app."""

    return {
        "db": app.db,
        "queue": app.queue,
        "queue_service": app.queue_service,
        "worker_service": app.worker_service,
        "worker_pool": app.worker_pool,
        "processor_coord": app.processor_coord,
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
        # Update global pool reference
        from nomarr.interfaces import api

        api.worker_pool = updated_pool

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
        from nomarr.interfaces import api

        api.worker_pool = updated_pool

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
        num = warmup_predictor_cache()
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
        from nomarr.interfaces import api

        api.worker_pool = updated_pool

    # Publish worker status update
    if event_broker:
        event_broker.update_worker_state({"enabled": True})

    return {"status": "ok", "worker_enabled": True}
