"""Calibration management endpoints for web UI."""

import logging
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_calibration_service, get_tagging_service
from nomarr.services.domain.calibration_svc import HistogramGenerationCombinedStatusDict
from nomarr.services.domain.tagging_svc import ApplyCalibrationCombinedStatusDict

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.services.domain.calibration_svc import CalibrationService
    from nomarr.services.domain.tagging_svc import TaggingService
router = APIRouter(prefix="/calibration", tags=["Calibration"])


@router.delete("", dependencies=[Depends(verify_session)])
async def clear_calibration(
    calibration_service: Annotated["CalibrationService", Depends(get_calibration_service)],
) -> dict[str, Any]:
    """Clear all calibration data.

    Truncates calibration_state and calibration_history collections,
    removes calibration meta keys, and nulls calibration_hash on all library files.
    Calibration can be regenerated afterward.

    Returns:
        {"files_updated": int, "meta_keys_cleared": int}

    """
    try:
        return calibration_service.clear_calibration()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:
        logger.exception("[Web API] Error clearing calibration data")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to clear calibration data"),
        ) from e


@router.post("/apply/start", dependencies=[Depends(verify_session)])
async def start_apply_calibration(
    tagging_service: Annotated["TaggingService", Depends(get_tagging_service)],
) -> dict[str, Any]:
    """Start calibration apply in background thread.

    Non-blocking: returns immediately. Use GET /apply/status to check progress.

    Returns:
        {"status": "started"} or {"status": "already_running"}

    """
    try:
        if tagging_service.is_apply_running():
            return {"status": "already_running", "message": "Calibration apply already in progress"}

        tagging_service.start_apply_calibration_background()
        return {"status": "started", "message": "Calibration apply started in background"}
    except Exception as e:
        logger.error(f"[Web API] Failed to start calibration apply: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to start calibration apply")
        ) from e


@router.get("/apply/status", dependencies=[Depends(verify_session)])
async def get_apply_calibration_status(
    tagging_service: Annotated["TaggingService", Depends(get_tagging_service)],
) -> ApplyCalibrationCombinedStatusDict:
    """Get combined status and progress of background calibration apply.

    Returns:
        {
          "status": "idle" | "running" | "completed" | "failed",
          "result": {"processed": int, "failed": int, "total": int, "message": str} | None,
          "error": str | None,
          "total_files": int,
          "completed_files": int,
          "current_file": str | None,
          "is_running": bool,
        }

    """
    return tagging_service.get_apply_combined_status()


@router.get("/status", dependencies=[Depends(verify_session)])
async def get_calibration_status(
    tagging_service: Annotated["TaggingService", Depends(get_tagging_service)],
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
        logger.exception("[Web API] Error fetching calibration status")
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to get calibration status")
        ) from e


@router.post("/histogram/start", dependencies=[Depends(verify_session)])
async def start_histogram_calibration_background(
    calibration_service: Annotated["CalibrationService", Depends(get_calibration_service)],
) -> dict[str, Any]:
    """Start histogram-based calibration generation in background thread.

    Non-blocking: returns immediately. Use GET /calibration/histogram/status to check progress.

    On success, automatically triggers DB tag-writing (equivalent to POST /calibration/apply/start).
    Writing tags to audio files on disk remains a separate manual step (reconcile endpoint).

    Returns:
        {"status": "started"} or {"status": "already_running"}

    """
    try:
        if calibration_service.is_generation_running():
            return {"status": "already_running", "message": "Calibration generation already in progress"}
        calibration_service.start_histogram_calibration_background()
        return {"status": "started", "message": "Calibration generation started in background"}
    except Exception as e:
        logger.error(f"[Web] Failed to start histogram calibration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to start calibration")) from e


@router.get("/histogram/status", dependencies=[Depends(verify_session)])
async def get_histogram_calibration_status(
    calibration_service: Annotated["CalibrationService", Depends(get_calibration_service)],
) -> HistogramGenerationCombinedStatusDict:
    """Get combined status and progress of histogram-based calibration generation.

    Returns:
        {
          "running": bool,
          "completed": bool,
          "error": str | None,
          "result": {heads_processed, heads_success, heads_failed, ...} | None,
          "current_head": str | None,
          "current_head_index": int | None,
          "total_heads": int,
          "completed_heads": int,
          "remaining_heads": int,
          "last_updated": int | None,
          "is_running": bool,
        }

    """
    try:
        return calibration_service.get_generation_combined_status()
    except Exception as e:
        logger.error(f"[Web] Failed to get histogram calibration status: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to get calibration status")
        ) from e


@router.get("/histogram", dependencies=[Depends(verify_session)])
async def get_all_calibration_histograms(
    calibration_service: "CalibrationService" = Depends(get_calibration_service),
) -> dict[str, Any]:
    """Get all calibration states with histogram bins (per-label).

    Returns:
        {
          "calibrations": [
            {
              "model_key": str,
              "head_name": str,
              "label": str,
              "histogram_bins": [{val, count}, ...],
              "p5": float,
              "p95": float,
              "n": int,
              ...
            },
            ...
          ]
        }

    Note:
        Returns 22 items (one per label) instead of 12 (per head).

    """
    try:
        states = calibration_service.get_all_calibration_states()
        return {"calibrations": states}
    except Exception as e:
        logger.error(f"[Web] Failed to get all calibration histograms: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to get histograms")) from e
