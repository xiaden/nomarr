"""Queue monitoring and management endpoints for web UI."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.id_codec import decode_path_id
from nomarr.interfaces.api.types.admin_types import CacheRefreshResponse
from nomarr.interfaces.api.types.queue_types import (
    JobRemovalResult,
    ListJobsResponse,
    OperationResult,
    QueueJobResponse,
    QueueStatusResponse,
)
from nomarr.interfaces.api.web.dependencies import get_ml_service, get_queue_service
from nomarr.services.infrastructure.queue_svc import QueueService

router = APIRouter(prefix="/queue", tags=["Queue"])


# ──────────────────────────────────────────────────────────────────────
# Request/Response Models
# ──────────────────────────────────────────────────────────────────────


class RemoveRequest(BaseModel):
    """Request to remove jobs from queue."""

    job_id: str | None = None
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
    job_id: str,
    queue_service: QueueService = Depends(get_queue_service),
) -> QueueJobResponse:
    """Get status of a specific job (web UI proxy)."""
    job_id = decode_path_id(job_id)
    # Use QueueService to get job details
    job = queue_service.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Transform DTO to API response
    return QueueJobResponse.from_dto(job)


@router.get("/list", dependencies=[Depends(verify_session)])
async def web_list_jobs(
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    queue_service: QueueService = Depends(get_queue_service),
) -> ListJobsResponse:
    """List jobs with pagination and filtering (web UI proxy)."""
    result = queue_service.list_jobs(limit=limit, offset=offset, status=status)
    return ListJobsResponse.from_dto(result)


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
) -> JobRemovalResult:
    """Remove jobs from queue (web UI proxy)."""
    result = queue_service.remove_jobs_for_admin(
        job_id=request.job_id,
        status=request.status,
        all=request.all,
    )
    return JobRemovalResult.from_dto(result)


@router.post("/admin/flush", dependencies=[Depends(verify_session)])
async def web_admin_flush(
    queue_service: QueueService = Depends(get_queue_service),
) -> JobRemovalResult:
    """Remove all completed/error jobs (web UI proxy)."""
    result = queue_service.flush_completed_and_errors_for_admin()
    return JobRemovalResult.from_dto(result)


@router.post("/admin/clear-all", dependencies=[Depends(verify_session)])
async def web_admin_clear_all(
    queue_service: QueueService = Depends(get_queue_service),
) -> JobRemovalResult:
    """Clear all jobs from queue including running ones (web UI)."""
    result = queue_service.clear_all_for_admin()
    return JobRemovalResult.from_dto(result)


@router.post("/admin/clear-completed", dependencies=[Depends(verify_session)])
async def web_admin_clear_completed(
    queue_service: QueueService = Depends(get_queue_service),
) -> JobRemovalResult:
    """Clear completed jobs from queue (web UI)."""
    result = queue_service.clear_completed_for_admin()
    return JobRemovalResult.from_dto(result)


@router.post("/admin/clear-errors", dependencies=[Depends(verify_session)])
async def web_admin_clear_errors(
    queue_service: QueueService = Depends(get_queue_service),
) -> JobRemovalResult:
    """Clear error jobs from queue (web UI)."""
    result = queue_service.clear_errors_for_admin()
    return JobRemovalResult.from_dto(result)


@router.post("/admin/cleanup", dependencies=[Depends(verify_session)])
async def web_admin_cleanup(
    max_age_hours: int = 168,
    queue_service: QueueService = Depends(get_queue_service),
) -> JobRemovalResult:
    """Remove old completed/error jobs (web UI proxy)."""
    result = queue_service.cleanup_old_jobs_for_admin(max_age_hours=max_age_hours)
    return JobRemovalResult.from_dto(result)


@router.post("/admin/cache-refresh", dependencies=[Depends(verify_session)])
async def web_admin_cache_refresh(
    ml_service: Any = Depends(get_ml_service),
) -> CacheRefreshResponse:
    """Refresh model cache (web UI proxy)."""
    try:
        result = ml_service.warmup_cache_for_admin()
        return CacheRefreshResponse.from_dto(result)
    except Exception as e:
        logging.exception("[Web API] Cache refresh failed")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Cache refresh failed")) from e


@router.post("/admin/reset", dependencies=[Depends(verify_session)])
async def web_admin_reset(
    request: AdminResetRequest,
    queue_service: QueueService = Depends(get_queue_service),
) -> OperationResult:
    """Reset stuck/error jobs to pending (web UI proxy)."""
    try:
        result = queue_service.reset_jobs_for_admin(stuck=request.stuck, errors=request.errors)
        return OperationResult.from_dto(result)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid reset request") from None
