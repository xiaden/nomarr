"""
Public API endpoints for system information and job management.
Routes: /api/v1/list, /api/v1/info

ARCHITECTURE:
- These endpoints are thin HTTP boundaries
- All business logic is delegated to services
- Services handle configuration, namespace, and data access
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from nomarr.interfaces.api.auth import verify_key
from nomarr.interfaces.api.web.dependencies_if import (
    get_config,
    get_ml_service,
    get_queue_service,
    get_worker_pool,
    get_worker_service,
)
from nomarr.services.queue_svc import QueueService
from nomarr.services.worker_svc import WorkerService

# Router instance (will be included in main app under /api prefix)
router = APIRouter(prefix="/v1", tags=["public"])


# ----------------------------------------------------------------------
#  GET /list
# ----------------------------------------------------------------------
@router.get("/list", dependencies=[Depends(verify_key)])
async def list_jobs(
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    queue_service: QueueService = Depends(get_queue_service),
):
    """
    List jobs with pagination and optional status filtering.

    Args:
        limit: Maximum number of jobs to return (default 50)
        offset: Number of jobs to skip for pagination (default 0)
        status: Filter by status (pending/running/done/error), or None for all
        queue_service: Injected QueueService

    Returns:
        {
            "total": total count of jobs matching filter,
            "jobs": [...],
            "counts": {pending, running, done, error},
            "limit": limit used,
            "offset": offset used
        }
    """
    # Validate status parameter
    if status and status not in ("pending", "running", "done", "error"):
        raise HTTPException(
            status_code=400, detail=f"Invalid status '{status}'. Must be one of: pending, running, done, error"
        )

    try:
        result = queue_service.list_jobs(limit=limit, offset=offset, status=status)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing jobs: {e}") from e


# ----------------------------------------------------------------------
#  GET /info
# ----------------------------------------------------------------------
@router.get("/info")
async def get_info(
    config: dict = Depends(get_config),
    queue_service: QueueService = Depends(get_queue_service),
    worker_service: WorkerService = Depends(get_worker_service),
    worker_pool: list = Depends(get_worker_pool),
    ml_service=Depends(get_ml_service),
):
    """
    Get comprehensive system info: config, models, queue status, workers.
    Unified schema matching CLI info command.
    """
    # Get queue stats
    queue_info = queue_service.get_status()

    # Worker status
    worker_enabled = worker_service.is_enabled()
    worker_alive = any(w.is_alive() for w in worker_pool) if worker_enabled else False
    last_hb = max((w.last_heartbeat() for w in worker_pool if w.is_alive()), default=None) if worker_enabled else None

    # Get model/head breakdown (matching CLI info)
    heads = ml_service.discover_heads()
    embeddings = sorted({h.backbone for h in heads})

    # Extract relevant config values
    api_config = config.get("api", {})
    tagger_config = config.get("tagger", {})

    return {
        "config": {
            "db_path": config.get("db_path"),
            "models_dir": ml_service.cfg.models_dir,
            "namespace": tagger_config.get("namespace", config.get("namespace", "nom")),
            "api_host": api_config.get("host"),
            "api_port": api_config.get("port"),
            "worker_enabled": worker_enabled,
            "worker_enabled_default": worker_service.cfg.default_enabled,
            "worker_count": worker_service.cfg.worker_count,
            "poll_interval": worker_service.cfg.poll_interval,
        },
        "models": {
            "total_heads": len(heads),
            "embeddings": embeddings,
        },
        "queue": {
            "depth": queue_info.depth,
            "counts": queue_info.counts,
        },
        "worker": {
            "enabled": worker_enabled,
            "alive": worker_alive,
            "last_heartbeat": last_hb,
        },
    }
