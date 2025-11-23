"""Queue monitoring and management endpoints for web UI."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_event_broker, get_ml_service, get_queue_service
from nomarr.services.queue_service import QueueService

router = APIRouter(prefix="/api", tags=["Queue"])


# ──────────────────────────────────────────────────────────────────────
# Request/Response Models
# ──────────────────────────────────────────────────────────────────────


class RemoveRequest(BaseModel):
    """Request to remove jobs from queue."""

    job_id: int | None = None
    status: str | None = None
    all: bool = False


class AdminResetRequest(BaseModel):
    """Request to reset stuck/error jobs."""

    stuck: bool = False
    errors: bool = False


# ──────────────────────────────────────────────────────────────────────
# Queue Monitoring Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("/status/{job_id}", dependencies=[Depends(verify_session)])
async def web_status(
    job_id: int,
    queue_service: QueueService = Depends(get_queue_service),
) -> dict[str, Any]:
    """Get status of a specific job (web UI proxy)."""
    # Use QueueService to get job details
    job = queue_service.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return job


@router.get("/queue-depth", dependencies=[Depends(verify_session)])
async def web_queue_depth(
    queue_service: QueueService = Depends(get_queue_service),
) -> dict[str, Any]:
    """Get queue depth statistics (web UI proxy)."""
    # Use QueueService to get queue statistics
    return queue_service.get_status()


# ──────────────────────────────────────────────────────────────────────
# Queue Admin Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.post("/admin/remove", dependencies=[Depends(verify_session)])
async def web_admin_remove(
    request: RemoveRequest,
    queue_service: QueueService = Depends(get_queue_service),
    event_broker: Any | None = Depends(get_event_broker),
) -> dict[str, Any]:
    """Remove jobs from queue (web UI proxy)."""
    # Use QueueService to remove jobs
    removed = queue_service.remove_jobs(
        job_id=request.job_id,
        status=request.status,
        all=request.all,
    )

    # Publish queue stats update
    queue_service.publish_queue_update(event_broker)

    return {"removed": removed, "status": "ok"}


@router.post("/admin/flush", dependencies=[Depends(verify_session)])
async def web_admin_flush(
    queue_service: QueueService = Depends(get_queue_service),
    event_broker: Any | None = Depends(get_event_broker),
) -> dict[str, Any]:
    """Remove all completed/error jobs (web UI proxy)."""
    # Use QueueService to remove done and error jobs
    done_count = queue_service.remove_jobs(status="done")
    error_count = queue_service.remove_jobs(status="error")
    total_removed = done_count + error_count

    # Publish queue stats update
    queue_service.publish_queue_update(event_broker)

    return {"removed": total_removed, "done": done_count, "errors": error_count, "status": "ok"}


@router.post("/admin/queue/clear-all", dependencies=[Depends(verify_session)])
async def web_admin_clear_all(
    queue_service: QueueService = Depends(get_queue_service),
    event_broker: Any | None = Depends(get_event_broker),
) -> dict[str, Any]:
    """Clear all jobs from queue including running ones (web UI)."""
    # Use QueueService to remove all jobs (pending, done, error - not running)
    removed = queue_service.remove_jobs(all=True)

    # Publish queue stats update
    queue_service.publish_queue_update(event_broker)

    return {"removed": removed, "status": "ok"}


@router.post("/admin/queue/clear-completed", dependencies=[Depends(verify_session)])
async def web_admin_clear_completed(
    queue_service: QueueService = Depends(get_queue_service),
    event_broker: Any | None = Depends(get_event_broker),
) -> dict[str, Any]:
    """Clear completed jobs from queue (web UI)."""
    removed = queue_service.remove_jobs(status="done")

    # Publish queue stats update
    queue_service.publish_queue_update(event_broker)

    return {"removed": removed, "status": "ok"}


@router.post("/admin/queue/clear-errors", dependencies=[Depends(verify_session)])
async def web_admin_clear_errors(
    queue_service: QueueService = Depends(get_queue_service),
    event_broker: Any | None = Depends(get_event_broker),
) -> dict[str, Any]:
    """Clear error jobs from queue (web UI)."""
    removed = queue_service.remove_jobs(status="error")

    # Publish queue stats update
    queue_service.publish_queue_update(event_broker)

    return {"removed": removed, "status": "ok"}


@router.post("/admin/cleanup", dependencies=[Depends(verify_session)])
async def web_admin_cleanup(
    max_age_hours: int = 168,
    queue_service: QueueService = Depends(get_queue_service),
    event_broker: Any | None = Depends(get_event_broker),
) -> dict[str, Any]:
    """Remove old completed/error jobs (web UI proxy)."""
    # Use QueueService to clean up old jobs
    removed = queue_service.cleanup_old_jobs(max_age_hours=max_age_hours)

    # Publish queue stats update
    queue_service.publish_queue_update(event_broker)

    return {"removed": removed, "max_age_hours": max_age_hours, "status": "ok"}


@router.post("/admin/cache-refresh", dependencies=[Depends(verify_session)])
async def web_admin_cache_refresh(
    ml_service: Any = Depends(get_ml_service),
) -> dict[str, str]:
    """Refresh model cache (web UI proxy)."""
    try:
        count = ml_service.warmup_cache()

        return {"status": "ok", "message": f"Model cache refreshed successfully ({count} predictors)"}
    except Exception as e:
        logging.exception("[Web API] Cache refresh failed")
        raise HTTPException(status_code=500, detail=f"Cache refresh failed: {e}") from e


@router.post("/admin/reset", dependencies=[Depends(verify_session)])
async def web_admin_reset(
    request: AdminResetRequest,
    queue_service: QueueService = Depends(get_queue_service),
    event_broker: Any | None = Depends(get_event_broker),
) -> dict[str, Any]:
    """Reset stuck/error jobs to pending (web UI proxy)."""
    if not request.stuck and not request.errors:
        raise HTTPException(status_code=400, detail="Must specify --stuck or --errors")

    # Use QueueService to reset jobs
    reset_count = queue_service.reset_jobs(stuck=request.stuck, errors=request.errors)

    # Publish queue stats update
    queue_service.publish_queue_update(event_broker)

    return {
        "status": "ok",
        "message": f"Reset {reset_count} job(s) to pending",
        "reset": reset_count,
    }
