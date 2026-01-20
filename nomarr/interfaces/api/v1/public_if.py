"""
Public API endpoints for system information.
Routes: /api/v1/info

ARCHITECTURE:
- These endpoints are thin HTTP boundaries
- All business logic is delegated to services
- Services handle configuration, namespace, and data access
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from nomarr.interfaces.api.types.info_types import PublicInfoResponse
from nomarr.interfaces.api.web.dependencies import get_info_service
from nomarr.services.infrastructure.info_svc import InfoService

# Router instance (will be included in main app under /api prefix)
router = APIRouter(prefix="/v1", tags=["public"])


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
