"""Calibration management endpoints for web UI."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.types.calibration_types import (
    ApplyCalibrationResultResponse,
    ApplyCalibrationStatusResponse,
    BackgroundStartResponse,
    CalibrationStatusResponse,
    ClearCalibrationResponse,
    GetAllCalibrationHistogramsResponse,
    HistogramGenerationStatusResponse,
    LibraryCalibrationStatusResponse,
)
from nomarr.interfaces.api.web.dependencies import get_calibration_service, get_tagging_service

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.services.domain.calibration_svc import CalibrationService
    from nomarr.services.domain.tagging_svc import TaggingService
router = APIRouter(prefix="/calibration", tags=["Calibration"])


@router.delete("", response_model=ClearCalibrationResponse, dependencies=[Depends(verify_session)])
async def clear_calibration(
    calibration_service: Annotated[CalibrationService, Depends(get_calibration_service)],
) -> ClearCalibrationResponse:
    """Clear all calibration data and return files-updated / meta-keys-cleared counts."""
    try:
        result = calibration_service.clear_calibration()
        return ClearCalibrationResponse(**result)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:
        logger.exception("[Web API] Error clearing calibration data")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to clear calibration data"),
        ) from e


@router.post("/apply/start", response_model=BackgroundStartResponse, dependencies=[Depends(verify_session)])
async def start_apply_calibration(
    tagging_service: Annotated[TaggingService, Depends(get_tagging_service)],
) -> BackgroundStartResponse:
    """Start calibration apply in a background thread (non-blocking)."""
    try:
        if tagging_service.is_apply_running():
            return BackgroundStartResponse(status="already_running", message="Calibration apply already in progress")

        tagging_service.start_apply_calibration_background()
        return BackgroundStartResponse(status="started", message="Calibration apply started in background")
    except Exception as e:
        logger.error(f"[Web API] Failed to start calibration apply: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to start calibration apply")
        ) from e


@router.get("/apply/status", response_model=ApplyCalibrationStatusResponse, dependencies=[Depends(verify_session)])
async def get_apply_calibration_status(
    tagging_service: Annotated[TaggingService, Depends(get_tagging_service)],
) -> ApplyCalibrationStatusResponse:
    """Get combined status and progress of background calibration apply."""
    status = tagging_service.get_apply_combined_status()
    apply_result = status.get("result")
    return ApplyCalibrationStatusResponse(
        status=status["status"],
        result=ApplyCalibrationResultResponse(**apply_result) if apply_result else None,
        error=status.get("error"),
        total_files=status["total_files"],
        completed_files=status["completed_files"],
        current_file=status.get("current_file"),
        is_running=status["is_running"],
    )


@router.get("/status", response_model=CalibrationStatusResponse, dependencies=[Depends(verify_session)])
async def get_calibration_status(
    tagging_service: Annotated[TaggingService, Depends(get_tagging_service)],
) -> CalibrationStatusResponse:
    """Get current calibration status with per-library breakdown."""
    try:
        result = tagging_service.get_calibration_status()
        return CalibrationStatusResponse(
            global_version=result["global_version"],
            last_run=result["last_run"],
            libraries=[LibraryCalibrationStatusResponse(**lib) for lib in result["libraries"]],
        )
    except Exception as e:
        logger.exception("[Web API] Error fetching calibration status")
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to get calibration status")
        ) from e


@router.post("/histogram/start", response_model=BackgroundStartResponse, dependencies=[Depends(verify_session)])
async def start_histogram_calibration_background(
    calibration_service: Annotated[CalibrationService, Depends(get_calibration_service)],
) -> BackgroundStartResponse:
    """Start histogram-based calibration generation in a background thread (non-blocking)."""
    try:
        if calibration_service.is_generation_running():
            return BackgroundStartResponse(
                status="already_running", message="Calibration generation already in progress"
            )
        calibration_service.start_histogram_calibration_background()
        return BackgroundStartResponse(status="started", message="Calibration generation started in background")
    except Exception as e:
        logger.error(f"[Web] Failed to start histogram calibration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to start calibration")) from e


@router.get(
    "/histogram/status", response_model=HistogramGenerationStatusResponse, dependencies=[Depends(verify_session)]
)
async def get_histogram_calibration_status(
    calibration_service: Annotated[CalibrationService, Depends(get_calibration_service)],
) -> HistogramGenerationStatusResponse:
    """Get combined status and progress of histogram-based calibration generation."""
    try:
        return HistogramGenerationStatusResponse(**calibration_service.get_generation_combined_status())
    except Exception as e:
        logger.error(f"[Web] Failed to get histogram calibration status: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to get calibration status")
        ) from e


@router.get("/histogram", response_model=GetAllCalibrationHistogramsResponse, dependencies=[Depends(verify_session)])
async def get_all_calibration_histograms(
    calibration_service: CalibrationService = Depends(get_calibration_service),
) -> GetAllCalibrationHistogramsResponse:
    """Get all calibration states with histogram bins (22 items, one per label)."""
    try:
        states = calibration_service.get_all_calibration_states()
        return GetAllCalibrationHistogramsResponse(calibrations=states)
    except Exception as e:
        logger.error(f"[Web] Failed to get all calibration histograms: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to get histograms")) from e
