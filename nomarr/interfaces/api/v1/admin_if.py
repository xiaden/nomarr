"""
Admin API endpoints for system control.
Routes: /v1/admin/cache/*, /v1/admin/worker/*, /v1/admin/calibration/*

These routes will be mounted under /api/v1/admin via the integration router.

NOTE: Queue management endpoints have been removed with the discovery-based worker system.
Processing state is now managed directly via library_files.needs_tagging field.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_key
from nomarr.interfaces.api.types.admin_types import (
    CacheRefreshResponse,
    WorkerOperationResponse,
)
from nomarr.interfaces.api.web.dependencies import (
    get_calibration_service,
    get_ml_service,
    get_workers_coordinator,
)
from nomarr.services.domain.calibration_svc import CalibrationService
from nomarr.services.infrastructure.ml_svc import MLService
from nomarr.services.infrastructure.worker_system_svc import WorkerSystemService

# Router instance (will be included under /api/v1/admin)
router = APIRouter(tags=["admin"], prefix="/v1/admin")


# ----------------------------------------------------------------------
#  POST /admin/cache/refresh
# ----------------------------------------------------------------------
@router.post("/cache/refresh", dependencies=[Depends(verify_key)])
async def admin_cache_refresh(
    ml_service: MLService = Depends(get_ml_service),
) -> CacheRefreshResponse:
    """Force rebuild of the predictor cache (discover heads and load missing)."""
    try:
        result = ml_service.warmup_cache_for_admin()
        return CacheRefreshResponse.from_dto(result)
    except Exception as e:
        logging.exception("[Admin API] Cache refresh failed")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Cache refresh failed")) from e


# ----------------------------------------------------------------------
#  POST /admin/worker/pause
# ----------------------------------------------------------------------
@router.post("/worker/pause", dependencies=[Depends(verify_key)])
async def admin_pause_worker(
    workers_coordinator: WorkerSystemService = Depends(get_workers_coordinator),
) -> WorkerOperationResponse:
    """Pause all background workers (stops processing new jobs)."""
    result = workers_coordinator.pause_worker_system()
    return WorkerOperationResponse.from_dto(result)


# ----------------------------------------------------------------------
#  POST /admin/worker/resume
# ----------------------------------------------------------------------
@router.post("/worker/resume", dependencies=[Depends(verify_key)])
async def admin_resume_worker(
    workers_coordinator: WorkerSystemService = Depends(get_workers_coordinator),
) -> WorkerOperationResponse:
    """Resume all background workers (starts processing again)."""
    result = workers_coordinator.resume_worker_system()
    return WorkerOperationResponse.from_dto(result)


# ----------------------------------------------------------------------
#  POST /admin/calibration/run
# ----------------------------------------------------------------------
@router.post("/calibration/run", dependencies=[Depends(verify_key)])
async def admin_run_calibration(
    calibration_service: CalibrationService = Depends(get_calibration_service),
):
    """
    Generate calibrations using histogram-based approach.

    Analyzes library tags using DB histogram queries (memory-bounded).
    Computes p5/p95 percentiles for each head.

    Returns:
        Calibration summary with per-head results
    """
    try:
        if not calibration_service.cfg.calibrate_heads:
            raise HTTPException(
                status_code=403,
                detail="Calibration generation disabled. Set calibrate_heads: true in config to enable.",
            )

        result = calibration_service.generate_histogram_calibration()
        return result
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("[Admin API] Calibration generation failed")
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Calibration generation failed")
        ) from e


# NOTE: /admin/calibration/history endpoint removed - was part of old drift tracking system


# ----------------------------------------------------------------------
#  POST /admin/calibration/backfill
# ----------------------------------------------------------------------
@router.post("/calibration/backfill", dependencies=[Depends(verify_key)])
async def admin_backfill_calibration_hashes(
    set_to_current: bool = False,
    calibration_service: CalibrationService = Depends(get_calibration_service),
):
    """
    Backfill calibration_hash for files currently showing as NULL.

    Two strategies:
    - set_to_current=False (default): Leave as NULL, users must recalibrate
    - set_to_current=True: Set to current global hash (assumes files are current)

    Returns:
        Summary of backfill operation
    """
    try:
        from nomarr.workflows.calibration.backfill_calibration_hash_wf import backfill_calibration_hashes_wf

        result = backfill_calibration_hashes_wf(db=calibration_service._db, set_to_current=set_to_current)
        return result
    except Exception as e:
        logging.exception("[Admin API] Backfill failed")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Backfill failed")) from e
