"""
Public API endpoints for Lidarr integration and job management.
Routes: /api/v1/tag, /api/v1/list, /api/v1/status/{id}, /api/v1/info
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from nomarr.app import application
from nomarr.interfaces.api.auth import verify_key
from nomarr.interfaces.api.models import TagRequest

# Router instance (will be included in main app)
router = APIRouter(prefix="/api/v1", tags=["public"])


# ----------------------------------------------------------------------
#  Dependency: get app globals from parent scope
# ----------------------------------------------------------------------
def get_globals():
    """Get global instances (db, queue, services, etc.) from application."""
    config_service = application.get_service("config")
    config = config_service.get_config()

    return {
        "db": application.db,
        "queue": application.queue,
        "queue_service": application.get_service("queue"),
        "worker_service": application.get_service("worker"),
        "worker_pool": application.workers,
        "processor_coord": application.coordinator,
        "BLOCKING_MODE": application.blocking_mode,
        "BLOCKING_TIMEOUT": application.blocking_timeout,
        "WORKER_ENABLED_DEFAULT": application.worker_enabled_default,
        "WORKER_COUNT": application.worker_count,
        "WORKER_POLL_INTERVAL": application.worker_poll_interval,
        "cfg": config,
        "DB_PATH": application.db_path,
        "API_HOST": application.api_host,
        "API_PORT": application.api_port,
    }


# ----------------------------------------------------------------------
#  GET /list
# ----------------------------------------------------------------------
@router.get("/list", dependencies=[Depends(verify_key)])
async def list_jobs(limit: int = 50, offset: int = 0, status: str | None = None):
    """
    List jobs with pagination and optional status filtering.

    Args:
        limit: Maximum number of jobs to return (default 50)
        offset: Number of jobs to skip for pagination (default 0)
        status: Filter by status (pending/running/done/error), or None for all

    Returns:
        {
            "total": total count of jobs matching filter,
            "jobs": [...],
            "counts": {pending, running, done, error},
            "limit": limit used,
            "offset": offset used
        }
    """
    g = get_globals()
    db = g["db"]
    queue = g["queue"]

    # Validate status parameter
    if status and status not in ("pending", "running", "done", "error"):
        raise HTTPException(
            status_code=400, detail=f"Invalid status '{status}'. Must be one of: pending, running, done, error"
        )

    # Get status counts from persistence layer
    counts = db.queue.queue_stats()

    # Get jobs with pagination
    jobs_list, total = queue.list(limit=limit, offset=offset, status=status)

    # Convert to dicts
    # Build job list (use Job.to_dict() for consistent schema)
    jobs_data = []
    for j in jobs_list:
        jobs_data.append(j.to_dict())

    return {
        "total": total,
        "jobs": jobs_data,
        "counts": {
            "pending": counts.get("pending", 0),
            "running": counts.get("running", 0),
            "done": counts.get("done", 0),
            "error": counts.get("error", 0),
        },
        "limit": limit,
        "offset": offset,
    }


# ----------------------------------------------------------------------
#  POST /tag
# ----------------------------------------------------------------------
@router.post("/tag", dependencies=[Depends(verify_key)])
async def tag_audio(req: TagRequest):
    """
    Queue audio file(s) for tagging.
    If path is a directory, recursively queues all audio files.
    If path is a file, queues that single file.
    Blocks until processing completes if blocking_mode=true (for single files only).
    """
    g = get_globals()
    queue_service = g["queue_service"]
    BLOCKING_MODE = g["BLOCKING_MODE"]
    BLOCKING_TIMEOUT = g["BLOCKING_TIMEOUT"]

    file_path = req.path.strip()
    force = bool(req.force) if req.force is not None else False

    # Ensure worker is running before queueing (if enabled)
    worker_service = g.get("worker_service")
    if worker_service and worker_service.is_enabled():
        worker_service.start_workers()

    # Use QueueService to add files (handles files, directories, and lists)
    try:
        result = queue_service.add_files(paths=file_path, force=force, recursive=True)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    job_ids = result["job_ids"]
    files_queued = result["files_queued"]

    # If multiple files were queued (directory), return batch summary
    if files_queued > 1:
        return {
            "job_ids": job_ids,
            "queue_depth": result["queue_depth"],
            "files_queued": files_queued,
            "path": file_path,
            "blocking": False,  # Never block for batch operations
        }

    # Single file: use original behavior
    job_id = job_ids[0]
    job = g["queue"].get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found after enqueue")

    # Respect configured blocking mode for single files
    if not BLOCKING_MODE:
        # Non-blocking: return job immediately with blocking flag
        job_dict = job.to_dict()
        job_dict["blocking"] = False
        return job_dict

    # Blocking behavior: wait for completion with configured timeout
    queue_service = g["queue_service"]
    final = await queue_service.wait_for_job_completion(job_id, BLOCKING_TIMEOUT)
    final["blocking"] = True
    return final


# ----------------------------------------------------------------------
#  GET /status/{job_id}
# ----------------------------------------------------------------------
@router.get("/status/{job_id}", dependencies=[Depends(verify_key)])
async def get_status(job_id: int):
    """
    Get job status by ID.
    Returns Job.to_dict() for consistent schema across all endpoints.
    """
    g = get_globals()
    queue = g["queue"]

    job = queue.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Use to_dict() for consistent field naming (id, not job_id)
    return job.to_dict()


# ----------------------------------------------------------------------
#  GET /info
# ----------------------------------------------------------------------
@router.get("/info")
async def get_info():
    """
    Get comprehensive system info: config, models, queue status, worker app.
    Unified schema matching CLI info command.
    """
    g = get_globals()
    db = g["db"]
    queue = g["queue"]
    worker_pool = g["worker_pool"]
    cfg = g["cfg"]
    DB_PATH = g["DB_PATH"]
    API_HOST = g["API_HOST"]
    API_PORT = g["API_PORT"]
    WORKER_ENABLED_DEFAULT = g["WORKER_ENABLED_DEFAULT"]
    WORKER_COUNT = g["WORKER_COUNT"]
    WORKER_POLL_INTERVAL = g["WORKER_POLL_INTERVAL"]
    BLOCKING_MODE = g["BLOCKING_MODE"]
    BLOCKING_TIMEOUT = g["BLOCKING_TIMEOUT"]

    # Get queue stats from persistence layer
    counts = db.queue.queue_stats()
    q_depth = queue.depth()

    # Worker status
    worker_service = g.get("worker_service")
    worker_enabled = worker_service.is_enabled() if worker_service else WORKER_ENABLED_DEFAULT
    worker_alive = any(w.is_alive() for w in worker_pool) if worker_enabled else False
    last_hb = max((w.last_heartbeat() for w in worker_pool if w.is_alive()), default=None) if worker_enabled else None

    # Get model/head breakdown (matching CLI info)
    ml_service = application.services["ml"]
    heads = ml_service.discover_heads()
    embeddings = sorted({h.backbone for h in heads})

    return {
        "config": {
            "db_path": DB_PATH,
            "models_dir": ml_service.models_dir,
            "namespace": cfg.get("tagger", {}).get("namespace", cfg.get("namespace", "essentia")),
            "api_host": API_HOST,
            "api_port": API_PORT,
            "worker_enabled": worker_enabled,
            "worker_enabled_default": WORKER_ENABLED_DEFAULT,
            "worker_count": WORKER_COUNT,
            "poll_interval": WORKER_POLL_INTERVAL,
            "blocking_mode": BLOCKING_MODE,
            "blocking_timeout": BLOCKING_TIMEOUT,
        },
        "models": {
            "total_heads": len(heads),
            "embeddings": embeddings,
        },
        "queue": {
            "depth": q_depth,
            "counts": counts,
        },
        "worker": {"enabled": worker_enabled, "alive": worker_alive, "last_heartbeat": last_hb},
    }
