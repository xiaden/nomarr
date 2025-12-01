"""
Public API endpoints for system information and job management.
Routes: /api/v1/list, /api/v1/info

ARCHITECTURE:
- These endpoints are thin HTTP boundaries
- All business logic is delegated to services
- Services handle configuration, namespace, and data access
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from nomarr.interfaces.api.auth import verify_key
from nomarr.interfaces.api.types.info_types import PublicInfoResponse
from nomarr.interfaces.api.types.queue_types import ListJobsResponse
from nomarr.interfaces.api.web.dependencies import get_info_service, get_queue_service
from nomarr.services.info_svc import InfoService
from nomarr.services.queue_svc import QueueService

# Router instance (will be included in main app under /api prefix)
router = APIRouter(prefix="/v1", tags=["public"])


# ----------------------------------------------------------------------
#  GET /list
# ----------------------------------------------------------------------
@router.get("/list", dependencies=[Depends(verify_key)])
async def list_jobs(
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    queue_service: QueueService = Depends(get_queue_service),
) -> ListJobsResponse:
    """
    List jobs with pagination and optional status filtering.

    Args:
        limit: Maximum number of jobs to return (default 50)
        offset: Number of jobs to skip for pagination (default 0)
        status: Filter by status (pending/running/done/error), or None for all
        queue_service: Injected QueueService

    Returns:
        ListJobsResponse with jobs, total count, limit, and offset
    """
    # Validate status parameter
    if status and status not in ("pending", "running", "done", "error"):
        raise HTTPException(
            status_code=400, detail=f"Invalid status '{status}'. Must be one of: pending, running, done, error"
        )

    try:
        result = queue_service.list_jobs(limit=limit, offset=offset, status=status)
        return ListJobsResponse.from_dto(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing jobs: {e}") from e


# ----------------------------------------------------------------------
#  GET /info
# ----------------------------------------------------------------------
@router.get("/info")
async def get_info(
    info_service: InfoService = Depends(get_info_service),
) -> PublicInfoResponse:
    """
    Get comprehensive system info: config, models, queue status, workers.
    Unified schema matching CLI info command.
    """
    result = info_service.get_public_info()
    return PublicInfoResponse.from_dto(result)
