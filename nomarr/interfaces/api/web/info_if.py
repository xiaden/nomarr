"""System info and health endpoints for web UI."""

from typing import Any

from fastapi import APIRouter, Depends

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.types.info_types import HealthStatusResponse, SystemInfoResponse
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
