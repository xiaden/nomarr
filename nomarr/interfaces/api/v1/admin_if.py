"""Admin API endpoints for system control.
Routes: /v1/admin/worker/*, /v1/admin/calibration/*.

These routes will be mounted under /api/v1/admin via the integration router.

NOTE: Queue management endpoints have been removed with the discovery-based worker system.
Processing state is now managed directly via library_files.needs_tagging field.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_key
from nomarr.interfaces.api.types.admin_types import WorkerOperationResponse
from nomarr.interfaces.api.web.dependencies import get_calibration_service, get_config_service, get_workers_coordinator
from nomarr.services.domain.calibration_svc import CalibrationService
from nomarr.services.infrastructure.config_svc import ConfigService
from nomarr.services.infrastructure.worker_system_svc import WorkerSystemService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["admin"], prefix="/v1/admin")


@router.post("/worker/pause", dependencies=[Depends(verify_key)])
async def admin_pause_worker(
    workers_coordinator: Annotated[WorkerSystemService, Depends(get_workers_coordinator)],
) -> WorkerOperationResponse:
    """Pause all background workers (stops processing new jobs)."""
    result = workers_coordinator.pause_worker_system()
    return WorkerOperationResponse.from_dto(result)


@router.post("/worker/resume", dependencies=[Depends(verify_key)])
async def admin_resume_worker(
    workers_coordinator: Annotated[WorkerSystemService, Depends(get_workers_coordinator)],
) -> WorkerOperationResponse:
    """Resume all background workers (starts processing again)."""
    result = workers_coordinator.resume_worker_system()
    return WorkerOperationResponse.from_dto(result)


@router.post("/calibration/run", dependencies=[Depends(verify_key)])
async def admin_run_calibration(
    calibration_service: Annotated[CalibrationService, Depends(get_calibration_service)],
    config_service: Annotated[ConfigService, Depends(get_config_service)],
):
    """Generate calibrations using histogram-based approach.

    Analyzes library tags using DB histogram queries (memory-bounded).
    Computes p5/p95 percentiles for each head.

    Returns:
        Calibration summary with per-head results

    """
    try:
        if not config_service.get("calibrate_heads", False):
            raise HTTPException(
                status_code=403,
                detail="Calibration generation disabled. Set calibrate_heads: true in config to enable.",
            )
        return calibration_service.generate_histogram_calibration()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Admin API] Calibration generation failed")
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Calibration generation failed")
        ) from e
