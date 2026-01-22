"""System info and health endpoints for web UI."""

from typing import Any

from fastapi import APIRouter, Depends

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.types.info_types import GPUHealthResponse, HealthStatusResponse, SystemInfoResponse
from nomarr.interfaces.api.web.dependencies import get_info_service

router = APIRouter(prefix="", tags=["Info"])


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("/info", dependencies=[Depends(verify_session)])
async def web_info(
    info_service: Any = Depends(get_info_service),
) -> SystemInfoResponse:
    """Get system info (web UI proxy)."""
    result = info_service.get_system_info()
    return SystemInfoResponse.from_dto(result)


@router.get("/health", dependencies=[Depends(verify_session)])
async def web_health(
    info_service: Any = Depends(get_info_service),
) -> HealthStatusResponse:
    """Health check endpoint (web UI proxy)."""
    result = info_service.get_health_status()
    return HealthStatusResponse.from_dto(result)


@router.get("/health/gpu", dependencies=[Depends(verify_session)])
async def web_gpu_health(
    info_service: Any = Depends(get_info_service),
) -> GPUHealthResponse:
    """
    GPU resource snapshot endpoint.

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
        # Event broker not configured - GPU monitoring disabled
        return GPUHealthResponse(
            available=False,
            error_summary="GPU monitoring not available",
            monitor_healthy=False,
        )
