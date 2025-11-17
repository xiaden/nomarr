"""Calibration management endpoints for web UI."""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_database
from nomarr.persistence.db import Database

router = APIRouter(prefix="/api/calibration", tags=["Calibration"])


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
async def apply_calibration_to_library() -> dict[str, Any]:
    """
    Queue all library files for recalibration.
    This updates tier and mood tags by applying calibration to existing raw scores.
    """
    from nomarr.app import application

    try:
        recal_service = application.services.get("recalibration")
        if not recal_service:
            raise HTTPException(status_code=503, detail="Recalibration service not available")

        # Get all library file paths from persistence layer
        paths = application.db.library.get_all_library_paths()

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
async def get_calibration_status() -> dict[str, Any]:
    """Get current recalibration queue status."""
    from nomarr.app import application

    try:
        recal_service = application.services.get("recalibration")
        if not recal_service:
            raise HTTPException(status_code=503, detail="Recalibration service not available")

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
async def clear_calibration_queue() -> dict[str, Any]:
    """Clear all pending and completed recalibration jobs."""
    from nomarr.app import application

    try:
        recal_service = application.services.get("recalibration")
        if not recal_service:
            raise HTTPException(status_code=503, detail="Recalibration service not available")

        count = recal_service.clear_queue()

        return {"cleared": count, "message": f"Cleared {count} jobs from calibration queue"}

    except Exception as e:
        logging.exception("[Web API] Error clearing calibration queue")
        raise HTTPException(status_code=500, detail=f"Error clearing calibration queue: {e}") from e


@router.post("/generate", dependencies=[Depends(verify_session)])
async def generate_calibration(
    request: CalibrationRequest,
    db: Database = Depends(get_database),
) -> dict[str, Any]:
    """
    Generate min-max scale calibration from library tags.

    Analyzes all tagged files in the library to compute scaling parameters (5th/95th percentiles)
    for normalizing each model to a common [0, 1] scale. This makes model outputs comparable
    while preserving semantic meaning.

    Uses industry standard minimum of 1000 samples per tag for reliable calibration.

    If save_sidecars=True, writes calibration JSON files next to model files.
    """
    from nomarr.app import application

    try:
        from nomarr.ml.calibration import (
            generate_minmax_calibration,
            save_calibration_sidecars,
        )

        # Run calibration in background thread (can take time with 18k songs)
        loop = asyncio.get_event_loop()
        calibration_data = await loop.run_in_executor(
            None,
            generate_minmax_calibration,
            db,
            application.namespace,
        )

        # Optionally save sidecars
        save_result = None
        if request.save_sidecars:
            models_dir = application.models_dir
            save_result = await loop.run_in_executor(
                None,
                save_calibration_sidecars,
                calibration_data,
                models_dir,
                1,  # version
            )

        return {
            "status": "success",
            "data": calibration_data,
            "saved_files": save_result,
        }

    except Exception as e:
        logging.error(f"[Web] Calibration generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e
