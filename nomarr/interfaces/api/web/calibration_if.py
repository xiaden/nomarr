"""Calibration management endpoints for web UI."""

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.types.calibration_types import (
    ApplyCalibrationResponse,
    CalibrationRequest,
)
from nomarr.interfaces.api.web.dependencies import (
    get_calibration_service,
    get_tagging_service,
)

if TYPE_CHECKING:
    from nomarr.services.domain.calibration_svc import CalibrationService
    from nomarr.services.domain.tagging_svc import TaggingService

router = APIRouter(prefix="/calibration", tags=["Calibration"])


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.post("/apply", dependencies=[Depends(verify_session)])
async def apply_calibration_to_library(
    tagging_service: Any = Depends(get_tagging_service),
) -> ApplyCalibrationResponse:
    """
    Apply calibrated tags to all library files.
    This updates tier and mood tags by applying calibration to existing raw scores.

    Note: This is a synchronous operation that may take time for large libraries.
    """
    try:
        # Get config from tagging_service if available, otherwise use defaults
        # TODO: Should get these from ConfigService via dependency injection
        models_dir = "/app/models"  # Placeholder - needs proper config injection
        namespace = "nom"
        version_tag_key = "nom_version"
        calibrate_heads = False

        result = tagging_service.tag_library(
            models_dir=models_dir,
            namespace=namespace,
            version_tag_key=version_tag_key,
            calibrate_heads=calibrate_heads,
        )
        return ApplyCalibrationResponse.from_dto(result)

    except RuntimeError as e:
        logging.error(f"[Web API] Tagging service error: {e}")
        raise HTTPException(status_code=503, detail=sanitize_exception_message(e, "Tagging service unavailable")) from e
    except Exception as e:
        logging.exception("[Web API] Error during calibrated tag application")
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to apply calibrated tags")
        ) from e


@router.get("/status", dependencies=[Depends(verify_session)])
async def get_calibration_status(
    tagging_service: "TaggingService" = Depends(get_tagging_service),
) -> dict[str, Any]:
    """Get current calibration status with per-library breakdown.

    Returns:
        {
          "global_version": "abc123...",
          "last_run": 1234567890,
          "libraries": [
            {
              "library_id": "libraries/123",
              "library_name": "Main Library",
              "total_files": 10000,
              "current_count": 8500,
              "outdated_count": 1500,
              "percentage": 85.0
            }
          ]
        }
    """
    try:
        return tagging_service.get_calibration_status()
    except Exception as e:
        logging.exception("[Web API] Error fetching calibration status")
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to get calibration status")
        ) from e


@router.post("/clear", dependencies=[Depends(verify_session)])
async def clear_calibration_queue(
    tagging_service: Any = Depends(get_tagging_service),
) -> dict[str, str]:
    """DEPRECATED: Tagging no longer uses queues.

    This endpoint is kept for backward compatibility but does nothing.
    """
    return {"status": "ok", "message": "Tagging no longer uses queues (no-op)"}


@router.post("/generate", dependencies=[Depends(verify_session)])
async def generate_calibration(
    request: CalibrationRequest,
    calibration_service: "CalibrationService" = Depends(get_calibration_service),
):
    """
    DEPRECATED: Use /generate-histogram instead.

    This endpoint is kept for backward compatibility but now uses histogram calibration internally.
    """
    try:
        # Delegate to histogram calibration
        result = calibration_service.generate_histogram_calibration()
        return result
    except Exception as e:
        logging.error(f"[Web] Calibration generation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Calibration generation failed")
        ) from e


@router.post("/generate-histogram", dependencies=[Depends(verify_session)])
async def generate_histogram_calibration(
    calibration_service: "CalibrationService" = Depends(get_calibration_service),
) -> dict[str, Any]:
    """
    Generate calibrations using sparse uniform histogram approach (NEW).

    Stateless, idempotent. Always computes from current DB state.
    Uses 10,000 uniform bins per head, memory-bounded (~8 MB vs. ~1 GB old approach).

    Returns:
        {
          "version": int,
          "heads_processed": int,
          "heads_success": int,
          "heads_failed": int,
          "results": {head_key: {p5, p95, n, underflow_count, overflow_count}}
        }
    """
    try:
        # Run calibration in background thread
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            calibration_service.generate_histogram_calibration,
        )

        return result

    except Exception as e:
        logging.error(f"[Web] Histogram calibration generation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Histogram calibration failed")
        ) from e


@router.post("/start-histogram", dependencies=[Depends(verify_session)])
async def start_histogram_calibration_background(
    calibration_service: "CalibrationService" = Depends(get_calibration_service),
) -> dict[str, Any]:
    """
    Start histogram-based calibration generation in background thread.

    Non-blocking: returns immediately. Use GET /calibration/histogram-status to check progress.

    Returns:
        {"status": "started"} or {"status": "already_running"}
    """
    try:
        if calibration_service.is_generation_running():
            return {"status": "already_running", "message": "Calibration generation already in progress"}

        calibration_service.start_histogram_calibration_background()
        return {"status": "started", "message": "Calibration generation started in background"}

    except Exception as e:
        logging.error(f"[Web] Failed to start histogram calibration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to start calibration")) from e


@router.get("/histogram-status", dependencies=[Depends(verify_session)])
async def get_histogram_calibration_status(
    calibration_service: "CalibrationService" = Depends(get_calibration_service),
) -> dict[str, Any]:
    """
    Get status of histogram-based calibration generation.

    Returns:
        {
          "running": bool,
          "completed": bool,
          "error": str | None,
          "result": {heads_processed, heads_success, heads_failed, ...} | None
        }
    """
    try:
        status = calibration_service.get_generation_status()
        return status

    except Exception as e:
        logging.error(f"[Web] Failed to get histogram calibration status: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to get calibration status")
        ) from e


@router.get("/histogram-progress", dependencies=[Depends(verify_session)])
async def get_histogram_calibration_progress(
    calibration_service: "CalibrationService" = Depends(get_calibration_service),
) -> dict[str, Any]:
    """
    Get per-head progress of histogram calibration generation.

    Returns:
        {
          "total_heads": int,
          "completed_heads": int,
          "remaining_heads": int,
          "last_updated": int | None,
          "is_running": bool
        }
    """
    try:
        progress = calibration_service.get_generation_progress()
        return progress

    except Exception as e:
        logging.error(f"[Web] Failed to get histogram calibration progress: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to get calibration progress")
        ) from e
