"""System info and health endpoints for web UI."""
import logging
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.types.info_types import (
    GPUHealthResponse,
    HealthStatusResponse,
    SystemInfoResponse,
    WorkStatusResponse,
)
from nomarr.interfaces.api.web.dependencies import get_info_service, get_library_service

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.services.domain.library_svc import LibraryService
router = APIRouter(prefix="", tags=["Info"])

@router.get("/info", dependencies=[Depends(verify_session)])
async def web_info(info_service: Annotated[Any, Depends(get_info_service)]) -> SystemInfoResponse:
    """Get system info (web UI proxy)."""
    result = info_service.get_system_info()
    return SystemInfoResponse.from_dto(result)

@router.get("/health", dependencies=[Depends(verify_session)])
async def web_health(info_service: Annotated[Any, Depends(get_info_service)]) -> HealthStatusResponse:
    """Health check endpoint (web UI proxy)."""
    result = info_service.get_health_status()
    return HealthStatusResponse.from_dto(result)

@router.get("/health/gpu", dependencies=[Depends(verify_session)])
async def web_gpu_health(info_service: Annotated[Any, Depends(get_info_service)]) -> GPUHealthResponse:
    """GPU resource snapshot endpoint.

    Returns cached GPU probe results from GPUHealthMonitor.
    Does NOT run nvidia-smi inline (non-blocking).

    Returns 200 with GPU status even if unavailable (not a failure state).
    Clients should check the 'available' field to determine GPU readiness.

    Note: Monitor liveness should be checked via HealthMonitorService,
    not by inspecting this response.
    """
    try:
        result = info_service.get_gpu_health()
        return GPUHealthResponse.from_dto(result)
    except RuntimeError:
        return GPUHealthResponse(available=False, error_summary="GPU monitoring not available", monitor_healthy=False)

@router.get("/work-status", dependencies=[Depends(verify_session)])
async def web_work_status(library_service: Annotated["LibraryService", Depends(get_library_service)]) -> WorkStatusResponse:
    """Get unified work status for the system.

    Returns status of:
    - Scanning: Any library currently being scanned
    - Processing: ML inference on audio files (pending/processed counts)

    This endpoint is designed for frontend polling to show activity indicators.
    Poll at 1s intervals when busy, 30s when idle.
    """
    try:
        result = library_service.get_work_status()
        return WorkStatusResponse.from_dto(result)
    except Exception as e:
        logger.exception("[Web API] Error getting work status")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to get work status")) from e
