"""Queue monitoring and management endpoints for web UI."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from nomarr.components.queue import cleanup_old_jobs, get_job, get_queue_stats
from nomarr.helpers.dto.admin_dto import JobRemovalResult as JobRemovalResultDTO
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.types.admin_types import CacheRefreshResponse
from nomarr.interfaces.api.types.queue_types import (
    JobRemovalResult,
    OperationResult,
    QueueJobResponse,
    QueueStatusResponse,
)
from nomarr.interfaces.api.web.dependencies import get_database, get_ml_service
from nomarr.persistence.db import Database
from nomarr.workflows.queue import (
    clear_all_workflow,
    clear_completed_workflow,
    clear_errors_workflow,
    clear_queue_workflow,
    remove_job_workflow,
    reset_errors_workflow,
    reset_stuck_workflow,
)

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
    db: Database = Depends(get_database),
) -> QueueJobResponse:
    """Get status of a specific job (web UI proxy)."""
    # Use queue component to get job details
    job = get_job(db, job_id, queue_type="tag")

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Transform DTO to API response
    return QueueJobResponse.from_dto(job)


@router.get("/queue-depth", dependencies=[Depends(verify_session)])
async def web_queue_depth(
    db: Database = Depends(get_database),
) -> QueueStatusResponse:
    """Get queue depth statistics (web UI proxy)."""
    # Use queue component to get queue statistics
    stats = get_queue_stats(db, queue_type="tag")

    # Transform DTO to API response
    return QueueStatusResponse.from_dto(stats)


# ──────────────────────────────────────────────────────────────────────
# Queue Admin Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.post("/admin/remove", dependencies=[Depends(verify_session)])
async def web_admin_remove(
    request: RemoveRequest,
    db: Database = Depends(get_database),
) -> JobRemovalResult:
    """Remove jobs from queue (web UI proxy)."""
    if request.job_id:
        # Remove specific job
        result = remove_job_workflow(db, request.job_id, queue_type="tag")
        return JobRemovalResult.from_dto(result)
    elif request.status:
        # Remove by status
        from nomarr.helpers.dto.queue_dto import JobStatus

        status_list: list[JobStatus] = [request.status]  # type: ignore[list-item]
        result = clear_queue_workflow(db, queue_type="tag", statuses=status_list)
        return JobRemovalResult.from_dto(result)
    elif request.all:
        # Remove all jobs
        result = clear_all_workflow(db, queue_type="tag")
        return JobRemovalResult.from_dto(result)
    else:
        raise HTTPException(status_code=400, detail="Must specify job_id, status, or all")


@router.post("/admin/flush", dependencies=[Depends(verify_session)])
async def web_admin_flush(
    db: Database = Depends(get_database),
) -> JobRemovalResult:
    """Remove all completed/error jobs (web UI proxy)."""
    # Flush = clear completed + errors
    result = clear_queue_workflow(db, queue_type="tag", statuses=["done", "error"])  # type: ignore[list-item]
    return JobRemovalResult.from_dto(result)


@router.post("/admin/clear-all", dependencies=[Depends(verify_session)])
async def web_admin_clear_all(
    db: Database = Depends(get_database),
) -> JobRemovalResult:
    """Clear all jobs from queue including running ones (web UI)."""
    result = clear_all_workflow(db, queue_type="tag")
    return JobRemovalResult.from_dto(result)


@router.post("/admin/clear-completed", dependencies=[Depends(verify_session)])
async def web_admin_clear_completed(
    db: Database = Depends(get_database),
) -> JobRemovalResult:
    """Clear completed jobs from queue (web UI)."""
    result = clear_completed_workflow(db, queue_type="tag")
    return JobRemovalResult.from_dto(result)


@router.post("/admin/clear-errors", dependencies=[Depends(verify_session)])
async def web_admin_clear_errors(
    db: Database = Depends(get_database),
) -> JobRemovalResult:
    """Clear error jobs from queue (web UI)."""
    result = clear_errors_workflow(db, queue_type="tag")
    return JobRemovalResult.from_dto(result)


@router.post("/admin/cleanup", dependencies=[Depends(verify_session)])
async def web_admin_cleanup(
    max_age_hours: int = 168,
    db: Database = Depends(get_database),
) -> JobRemovalResult:
    """Remove old completed/error jobs (web UI proxy)."""
    count = cleanup_old_jobs(db, queue_type="tag", max_age_hours=max_age_hours)
    # Convert to DTO
    result_dto = JobRemovalResultDTO(job_ids=[], count=count)
    return JobRemovalResult.from_dto(result_dto)


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
        raise HTTPException(status_code=500, detail=f"Cache refresh failed: {e}") from e


@router.post("/admin/reset", dependencies=[Depends(verify_session)])
async def web_admin_reset(
    request: AdminResetRequest,
    db: Database = Depends(get_database),
) -> OperationResult:
    """Reset stuck/error jobs to pending (web UI proxy)."""
    try:
        if request.stuck and request.errors:
            # Reset both
            stuck_count = reset_stuck_workflow(db, queue_type="tag")
            error_count = reset_errors_workflow(db, queue_type="tag")
            from nomarr.helpers.dto.admin_dto import WorkerOperationResult

            result = WorkerOperationResult(
                status="success", message=f"Reset {stuck_count + error_count} job(s) to pending"
            )
            return OperationResult.from_dto(result)
        elif request.stuck:
            count = reset_stuck_workflow(db, queue_type="tag")
            from nomarr.helpers.dto.admin_dto import WorkerOperationResult

            result = WorkerOperationResult(status="success", message=f"Reset {count} stuck job(s) to pending")
            return OperationResult.from_dto(result)
        elif request.errors:
            count = reset_errors_workflow(db, queue_type="tag")
            from nomarr.helpers.dto.admin_dto import WorkerOperationResult

            result = WorkerOperationResult(status="success", message=f"Reset {count} error job(s) to pending")
            return OperationResult.from_dto(result)
        else:
            raise ValueError("Must specify --stuck or --errors")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
