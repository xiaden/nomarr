"""
Internal API endpoints for CLI admin commands.
Routes: /internal/health, /internal/admin-reset
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

import nomarr.app as app
from nomarr.interfaces.api.auth import verify_internal_key

# Router instance (will be included in main app)
router = APIRouter(tags=["internal"], prefix="/internal")


# ----------------------------------------------------------------------
#  Dependency: get app globals
# ----------------------------------------------------------------------
def get_globals():
    """Get global instances (queue_service, worker_service, etc.) from app app."""

    return {
        "queue_service": app.queue_service,
        "worker_service": app.worker_service,
        "event_broker": app.event_broker,
    }


# ----------------------------------------------------------------------
#  GET /internal/health
# ----------------------------------------------------------------------
@router.get("/health")
async def internal_health():
    """Health check for internal API (no auth required for health)."""
    g = get_globals()
    worker_service = g.get("worker_service")

    return {
        "status": "ok",
        "cache_initialized": True,  # Cache is warmed on startup
        "worker_enabled": worker_service.is_enabled() if worker_service else False,
    }


# ----------------------------------------------------------------------
#  POST /internal/admin-reset
# ----------------------------------------------------------------------
@router.post("/admin-reset", dependencies=[Depends(verify_internal_key)])
async def internal_admin_reset(
    flag: str = Query(..., description="Reset mode: --stuck or --errors"), force: bool = Query(False)
):
    """
    Admin command to reset jobs to pending status.
    Supports resetting stuck running jobs (--stuck) or error jobs (--errors).
    """
    g = get_globals()
    queue_service = g["queue_service"]
    event_broker = g.get("event_broker")

    try:
        if flag == "--stuck":
            reset_count = queue_service.reset_jobs(stuck=True, errors=False)
            queue_service.publish_queue_update(event_broker)

            if reset_count == 0:
                return {"status": "ok", "message": "No running jobs found", "reset": 0}
            return {"status": "ok", "message": f"Reset {reset_count} stuck job(s) to pending", "reset": reset_count}

        elif flag == "--errors":
            reset_count = queue_service.reset_jobs(stuck=False, errors=True)
            queue_service.publish_queue_update(event_broker)

            if reset_count == 0:
                return {"status": "ok", "message": "No error jobs found", "reset": 0}
            return {"status": "ok", "message": f"Reset {reset_count} error job(s) to pending", "reset": reset_count}

        else:
            raise HTTPException(status_code=400, detail="Invalid flag. Use --stuck or --errors")

    except Exception as e:
        logging.exception(f"[Internal] Error resetting jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
