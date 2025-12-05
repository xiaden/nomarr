"""Calibration management endpoints for web UI."""

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.types.calibration_types import (
    ApplyCalibrationResponse,
    CalibrationRequest,
    ClearCalibrationQueueResponse,
    GenerateCalibrationResponse,
    RecalibrationStatusResponse,
)
from nomarr.interfaces.api.web.dependencies import (
    get_calibration_service,
    get_recalibration_service,
)

if TYPE_CHECKING:
    from nomarr.services.domain.calibration_svc import CalibrationService

router = APIRouter(prefix="/calibration", tags=["Calibration"])


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.post("/apply", dependencies=[Depends(verify_session)])
async def apply_calibration_to_library(
    recal_service: Any = Depends(get_recalibration_service),
) -> ApplyCalibrationResponse:
    """
    Queue all library files for recalibration.
    This updates tier and mood tags by applying calibration to existing raw scores.
    """
    try:
        result = recal_service.queue_library_for_recalibration()
        return ApplyCalibrationResponse.from_dto(result)

    except RuntimeError as e:
        logging.error(f"[Web API] Recalibration service error: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logging.exception("[Web API] Error queueing recalibration")
        raise HTTPException(status_code=500, detail=f"Error queueing recalibration: {e}") from e


@router.get("/status", dependencies=[Depends(verify_session)])
async def get_calibration_status(
    recal_service: Any = Depends(get_recalibration_service),
) -> RecalibrationStatusResponse:
    """Get current recalibration queue status."""
    try:
        status_dto, worker_alive, worker_busy = recal_service.get_status_with_worker_state()

        return RecalibrationStatusResponse.from_dto(status_dto, worker_alive, worker_busy)

    except Exception as e:
        logging.exception("[Web API] Error getting calibration status")
        raise HTTPException(status_code=500, detail=f"Error getting calibration status: {e}") from e


@router.post("/clear", dependencies=[Depends(verify_session)])
async def clear_calibration_queue(
    recal_service: Any = Depends(get_recalibration_service),
) -> ClearCalibrationQueueResponse:
    """Clear all pending and completed recalibration jobs."""
    try:
        result = recal_service.clear_queue_with_result()
        return ClearCalibrationQueueResponse.from_dto(result)

    except Exception as e:
        logging.exception("[Web API] Error clearing calibration queue")
        raise HTTPException(status_code=500, detail=f"Error clearing calibration queue: {e}") from e


@router.post("/generate", dependencies=[Depends(verify_session)])
async def generate_calibration(
    request: CalibrationRequest,
    calibration_service: "CalibrationService" = Depends(get_calibration_service),
) -> GenerateCalibrationResponse:
    """
    Generate min-max scale calibration from library tags.

    Analyzes all tagged files in the library to compute scaling parameters (5th/95th percentiles)
    for normalizing each model to a common [0, 1] scale. This makes model outputs comparable
    while preserving semantic meaning.

    Uses industry standard minimum of 1000 samples per tag for reliable calibration.

    If save_sidecars=True, writes calibration JSON files next to model files.
    """
    try:
        # Run calibration in background thread (can take time with 18k songs)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            calibration_service.generate_calibration_with_sidecars,
            request.save_sidecars,
        )

        return GenerateCalibrationResponse.from_dto(result)

    except Exception as e:
        logging.error(f"[Web] Calibration generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e
