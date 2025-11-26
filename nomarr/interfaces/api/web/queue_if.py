"""Queue monitoring and management endpoints for web UI."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.types.queue_types import JobRemovalResult, OperationResult, QueueJobItem, QueueStatusResponse
from nomarr.interfaces.api.web.dependencies_if import get_event_broker, get_ml_service, get_queue_service
from nomarr.services.queue_svc import QueueService

router = APIRouter(prefix="/queue", tags=["Queue"])


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
) -> QueueJobItem:
    """Get status of a specific job (web UI proxy)."""
    # Use QueueService to get job details
    job = queue_service.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Transform DTO to API response
    return QueueJobItem.from_dto(job, queue_type="processing")


@router.get("/queue-depth", dependencies=[Depends(verify_session)])
async def web_queue_depth(
    queue_service: QueueService = Depends(get_queue_service),
) -> QueueStatusResponse:
    """Get queue depth statistics (web UI proxy)."""
    # Use QueueService to get queue statistics
    stats = queue_service.get_status()

    # Transform DTO to API response
    return QueueStatusResponse.from_dto(stats)


# ──────────────────────────────────────────────────────────────────────
# Queue Admin Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.post("/admin/remove", dependencies=[Depends(verify_session)])
async def web_admin_remove(
    request: RemoveRequest,
    queue_service: QueueService = Depends(get_queue_service),
    event_broker: Any | None = Depends(get_event_broker),
) -> JobRemovalResult:
    """Remove jobs from queue (web UI proxy)."""
    # Use QueueService to remove jobs
    removed = queue_service.remove_jobs(
        job_id=request.job_id,
        status=request.status,
        all=request.all,
    )

    # Publish queue stats update
    queue_service.publish_queue_update(event_broker)

    return JobRemovalResult(
        removed=removed,
        message=f"Removed {removed} job(s)" if removed > 0 else "No jobs removed",
    )


@router.post("/admin/flush", dependencies=[Depends(verify_session)])
async def web_admin_flush(
    queue_service: QueueService = Depends(get_queue_service),
    event_broker: Any | None = Depends(get_event_broker),
) -> JobRemovalResult:
    """Remove all completed/error jobs (web UI proxy)."""
    # Use QueueService to remove done and error jobs
    done_count = queue_service.remove_jobs(status="done")
    error_count = queue_service.remove_jobs(status="error")
    total_removed = done_count + error_count

    # Publish queue stats update
    queue_service.publish_queue_update(event_broker)

    return JobRemovalResult(
        removed=total_removed,
        message=f"Removed {done_count} completed and {error_count} error jobs",
    )


@router.post("/admin/clear-all", dependencies=[Depends(verify_session)])
async def web_admin_clear_all(
    queue_service: QueueService = Depends(get_queue_service),
    event_broker: Any | None = Depends(get_event_broker),
) -> JobRemovalResult:
    """Clear all jobs from queue including running ones (web UI)."""
    # Use QueueService to remove all jobs (pending, done, error - not running)
    removed = queue_service.remove_jobs(all=True)

    # Publish queue stats update
    queue_service.publish_queue_update(event_broker)

    return JobRemovalResult(
        removed=removed,
        message=f"Cleared all jobs ({removed} removed)",
    )


@router.post("/admin/clear-completed", dependencies=[Depends(verify_session)])
async def web_admin_clear_completed(
    queue_service: QueueService = Depends(get_queue_service),
    event_broker: Any | None = Depends(get_event_broker),
) -> JobRemovalResult:
    """Clear completed jobs from queue (web UI)."""
    removed = queue_service.remove_jobs(status="done")

    # Publish queue stats update
    queue_service.publish_queue_update(event_broker)

    return JobRemovalResult(
        removed=removed,
        message=f"Cleared {removed} completed job(s)",
    )


@router.post("/admin/clear-errors", dependencies=[Depends(verify_session)])
async def web_admin_clear_errors(
    queue_service: QueueService = Depends(get_queue_service),
    event_broker: Any | None = Depends(get_event_broker),
) -> JobRemovalResult:
    """Clear error jobs from queue (web UI)."""
    removed = queue_service.remove_jobs(status="error")

    # Publish queue stats update
    queue_service.publish_queue_update(event_broker)

    return JobRemovalResult(
        removed=removed,
        message=f"Cleared {removed} error job(s)",
    )


@router.post("/admin/cleanup", dependencies=[Depends(verify_session)])
async def web_admin_cleanup(
    max_age_hours: int = 168,
    queue_service: QueueService = Depends(get_queue_service),
    event_broker: Any | None = Depends(get_event_broker),
) -> JobRemovalResult:
    """Remove old completed/error jobs (web UI proxy)."""
    # Use QueueService to clean up old jobs
    removed = queue_service.cleanup_old_jobs(max_age_hours=max_age_hours)

    # Publish queue stats update
    queue_service.publish_queue_update(event_broker)

    return JobRemovalResult(
        removed=removed,
        message=f"Cleaned up {removed} jobs older than {max_age_hours} hours",
    )


@router.post("/admin/cache-refresh", dependencies=[Depends(verify_session)])
async def web_admin_cache_refresh(
    ml_service: Any = Depends(get_ml_service),
) -> OperationResult:
    """Refresh model cache (web UI proxy)."""
    try:
        count = ml_service.warmup_cache()

        return OperationResult(
            status="success",
            message=f"Model cache refreshed successfully ({count} predictors)",
        )
    except Exception as e:
        logging.exception("[Web API] Cache refresh failed")
        raise HTTPException(status_code=500, detail=f"Cache refresh failed: {e}") from e


@router.post("/admin/reset", dependencies=[Depends(verify_session)])
async def web_admin_reset(
    request: AdminResetRequest,
    queue_service: QueueService = Depends(get_queue_service),
    event_broker: Any | None = Depends(get_event_broker),
) -> OperationResult:
    """Reset stuck/error jobs to pending (web UI proxy)."""
    if not request.stuck and not request.errors:
        raise HTTPException(status_code=400, detail="Must specify --stuck or --errors")

    # Use QueueService to reset jobs
    reset_count = queue_service.reset_jobs(stuck=request.stuck, errors=request.errors)

    # Publish queue stats update
    queue_service.publish_queue_update(event_broker)

    return OperationResult(
        status="success",
        message=f"Reset {reset_count} job(s) to pending",
    )
