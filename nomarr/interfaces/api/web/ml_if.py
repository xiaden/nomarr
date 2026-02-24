"""ML management endpoints for web UI."""

import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_ml_service

if TYPE_CHECKING:
    from nomarr.services.infrastructure.ml_svc import MLService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ml", tags=["ml"])


@router.post("/vram-probe", dependencies=[Depends(verify_session)])
async def ml_trigger_vram_probe(
    ml_service: Annotated["MLService", Depends(get_ml_service)],
) -> dict[str, str]:
    """Clear per-model VRAM measurements so the next worker startup re-probes.

    The probe runs automatically on the next discovery worker GPU warmup cycle.
    This endpoint only schedules the re-probe by clearing the existing measurements.
    """
    try:
        ml_service.clear_vram_measurements()
        return {"status": "probe_scheduled"}
    except Exception as e:
        logger.exception("[ml_if] Failed to clear VRAM measurements")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to schedule VRAM probe"),
        ) from e
