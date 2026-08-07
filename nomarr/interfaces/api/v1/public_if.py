"""Public API endpoints for system information.  Routes: /api/v1/info."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from nomarr.interfaces.api.types.info_types import PublicInfoResponse
from nomarr.interfaces.api.web.dependencies import get_info_service
from nomarr.services.infrastructure.info_svc import (
    InfoService,  # noqa: TC001  # FastAPI resolves Annotated[...] at route registration
)

# Router instance (will be included in main app under /api prefix)
router = APIRouter(prefix="/v1", tags=["public"])


@router.get("/info")
async def get_info(
    info_service: Annotated[InfoService, Depends(get_info_service)],
) -> PublicInfoResponse:
    """Get comprehensive system info: config, models, queue status, workers.
    Unified schema matching CLI info command.
    """
    result = info_service.get_public_info()
    return PublicInfoResponse.from_dto(result)
