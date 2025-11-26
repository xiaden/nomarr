"""System info and health endpoints for web UI."""

from typing import Any

from fastapi import APIRouter, Depends

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies_if import (
    get_config,
    get_processor_coordinator,
    get_queue_service,
    get_worker_service,
)
from nomarr.services.coordinator_svc import CoordinatorService
from nomarr.services.queue_svc import QueueService

router = APIRouter(prefix="", tags=["Info"])


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("/info", dependencies=[Depends(verify_session)])
async def web_info(
    cfg: dict = Depends(get_config),
    worker_service: Any | None = Depends(get_worker_service),
) -> dict[str, Any]:
    """Get system info (web UI proxy)."""
    return {
        "version": "1.2",
        "namespace": cfg.get("namespace", "essentia"),
        "models_dir": cfg.get("models_dir", "/app/models"),
        "worker_enabled": worker_service.is_enabled() if worker_service else False,
        "worker_count": worker_service.worker_count if worker_service else 0,
    }


@router.get("/health", dependencies=[Depends(verify_session)])
async def web_health(
    queue_service: QueueService = Depends(get_queue_service),
    processor_coord: CoordinatorService | None = Depends(get_processor_coordinator),
) -> dict[str, Any]:
    """Health check endpoint (web UI proxy)."""
    # Get queue statistics via QueueService
    queue_stats = queue_service.get_status()

    # Detect potential issues
    warnings = []
    worker_count = processor_coord.worker_count if processor_coord else 0
    running_jobs = queue_stats.get("running", 0)

    # Check for more running jobs than workers (stuck jobs)
    if running_jobs > worker_count:
        warnings.append(
            f"More running jobs ({running_jobs}) than workers ({worker_count}). "
            f"Some jobs may be stuck in 'running' state."
        )

    return {
        "status": "healthy" if not warnings else "degraded",
        "processor_initialized": processor_coord is not None,
        "worker_count": worker_count,
        "queue": queue_stats,
        "warnings": warnings,
    }
