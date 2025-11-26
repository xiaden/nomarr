"""Calibration management endpoints for web UI."""

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies_if import (
    get_calibration_service,
    get_library_service,
    get_recalibration_service,
)

if TYPE_CHECKING:
    from nomarr.services.calibration_svc import CalibrationService
    from nomarr.services.library_svc import LibraryService

router = APIRouter(prefix="/calibration", tags=["Calibration"])


# ──────────────────────────────────────────────────────────────────────
# Request/Response Models
# ──────────────────────────────────────────────────────────────────────


class CalibrationRequest(BaseModel):
    """Request to generate calibration."""

    save_sidecars: bool = True  # Save calibration files next to models by default


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.post("/apply", dependencies=[Depends(verify_session)])
async def apply_calibration_to_library(
    library_service: "LibraryService" = Depends(get_library_service),
    recal_service: Any = Depends(get_recalibration_service),
) -> dict[str, Any]:
    """
    Queue all library files for recalibration.
    This updates tier and mood tags by applying calibration to existing raw scores.
    """
    try:
        # Get all library file paths from service layer
        paths = library_service.get_all_library_paths()

        if not paths:
            return {"queued": 0, "message": "No library files found"}

        # Enqueue all files
        count = recal_service.enqueue_library(paths)

        return {"queued": count, "message": f"Queued {count} files for recalibration"}

    except RuntimeError as e:
        logging.error(f"[Web API] Recalibration service error: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logging.exception("[Web API] Error queueing recalibration")
        raise HTTPException(status_code=500, detail=f"Error queueing recalibration: {e}") from e


@router.get("/status", dependencies=[Depends(verify_session)])
async def get_calibration_status(
    recal_service: Any = Depends(get_recalibration_service),
) -> dict[str, Any]:
    """Get current recalibration queue status."""
    try:
        status = recal_service.get_status()
        worker_alive = recal_service.is_worker_alive()
        worker_busy = recal_service.is_worker_busy()

        return {
            **status,
            "worker_alive": worker_alive,
            "worker_busy": worker_busy,
        }

    except Exception as e:
        logging.exception("[Web API] Error getting calibration status")
        raise HTTPException(status_code=500, detail=f"Error getting calibration status: {e}") from e


@router.post("/clear", dependencies=[Depends(verify_session)])
async def clear_calibration_queue(
    recal_service: Any = Depends(get_recalibration_service),
) -> dict[str, Any]:
    """Clear all pending and completed recalibration jobs."""
    try:
        count = recal_service.clear_queue()

        return {"cleared": count, "message": f"Cleared {count} jobs from calibration queue"}

    except Exception as e:
        logging.exception("[Web API] Error clearing calibration queue")
        raise HTTPException(status_code=500, detail=f"Error clearing calibration queue: {e}") from e


@router.post("/generate", dependencies=[Depends(verify_session)])
async def generate_calibration(
    request: CalibrationRequest,
    calibration_service: "CalibrationService" = Depends(get_calibration_service),
) -> dict[str, Any]:
    """
    Generate min-max scale calibration from library tags.

    Analyzes all tagged files in the library to compute scaling parameters (5th/95th percentiles)
    for normalizing each model to a common [0, 1] scale. This makes model outputs comparable
    while preserving semantic meaning.

    Uses industry standard minimum of 1000 samples per tag for reliable calibration.

    If save_sidecars=True, writes calibration JSON files next to model files.
    """
    try:
        from dataclasses import asdict

        # Run calibration in background thread (can take time with 18k songs)
        loop = asyncio.get_event_loop()
        calibration_data = await loop.run_in_executor(
            None,
            calibration_service.generate_minmax_calibration,
        )

        # Optionally save sidecars (service method accepts dict for backward compat)
        save_result = None
        if request.save_sidecars:
            save_result = await loop.run_in_executor(
                None,
                calibration_service.save_calibration_sidecars,
                asdict(calibration_data),
            )

        # Return DTO fields inline for JSON serialization
        return {
            "status": "success",
            "data": {
                "method": calibration_data.method,
                "library_size": calibration_data.library_size,
                "min_samples": calibration_data.min_samples,
                "calibrations": calibration_data.calibrations,
                "skipped_tags": calibration_data.skipped_tags,
            },
            "saved_files": (
                {
                    "saved_files": save_result.saved_files,
                    "total_files": save_result.total_files,
                    "total_labels": save_result.total_labels,
                }
                if save_result and not isinstance(save_result, dict)
                else save_result
            ),
        }

    except Exception as e:
        logging.error(f"[Web] Calibration generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e
