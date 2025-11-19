"""
Web UI endpoints - authentication and service access.
These endpoints handle web UI login and provide authenticated access to application services.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import mutagen
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from nomarr.app import application
from nomarr.helpers.files import validate_library_path
from nomarr.helpers.logging import sanitize_exception_message
from nomarr.interfaces.api.auth import (
    create_session,
    get_admin_password_hash,
    invalidate_session,
    verify_password,
    verify_session,
)
from nomarr.services.navidrome.config_generator import generate_navidrome_config, preview_tag_stats

router = APIRouter(prefix="/web", tags=["Web UI"])


# ----------------------------------------------------------------------
# Request/Response models
# ----------------------------------------------------------------------


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    session_token: str
    expires_in: int  # seconds


class LogoutResponse(BaseModel):
    status: str


# ----------------------------------------------------------------------
# Authentication endpoints
# ----------------------------------------------------------------------


@router.post("/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    Authenticate with admin password and receive a session token.
    The session token should be used for all subsequent /web/api/* requests.
    """
    try:
        password_hash = get_admin_password_hash()
    except RuntimeError as e:
        logging.error(f"[Web UI] Admin password not initialized: {e}")
        raise HTTPException(status_code=500, detail="Admin authentication not configured") from None

    if not verify_password(request.password, password_hash):
        logging.warning("[Web UI] Failed login attempt")
        raise HTTPException(status_code=403, detail="Invalid password")

    session_token = create_session()
    logging.info("[Web UI] New session created")

    return LoginResponse(
        session_token=session_token,
        expires_in=86400,  # 24 hours
    )


@router.post("/auth/logout", response_model=LogoutResponse, dependencies=[Depends(verify_session)])
async def logout(creds=Depends(verify_session)):
    """
    Invalidate the current session token (logout).
    """
    # Extract token from auth header
    from fastapi.security import HTTPBearer

    bearer = HTTPBearer(auto_error=False)
    auth = await bearer(creds)
    if auth:
        invalidate_session(auth.credentials)

    return LogoutResponse(status="logged_out")


# ----------------------------------------------------------------------
# API proxy endpoints - wrap service layer operations
# ----------------------------------------------------------------------
# These endpoints accept session tokens from the browser and directly
# call service layer operations (queue, processing, library, etc.).


# Request/Response models for web API (mirror internal models)
class ProcessRequest(BaseModel):
    path: str
    force: bool = False


class BatchProcessRequest(BaseModel):
    paths: list[str]
    force: bool = False


class RemoveRequest(BaseModel):
    job_id: int | None = None
    all: bool = False
    status: str | None = None


class AdminResetRequest(BaseModel):
    stuck: bool = False
    errors: bool = False


# Helper to get app state
def get_state():
    """
    Get application state for web endpoints.

    Returns SimpleNamespace with essential service references:
    - db: Database instance (for persistence operations)
    - queue: ProcessingQueue instance (for job queries)
    - cfg: Config dict (for configuration access)
    - queue_service: QueueService (for queue operations)
    - worker_service: WorkerService (for worker control)
    - processor_coord: ProcessingCoordinator (for direct job submission)
    - worker_pool: Worker pool list (for worker management)
    - event_broker: EventBroker (for SSE events)
    """
    from types import SimpleNamespace

    from nomarr.app import application

    # Get config via ConfigService
    config_service = application.get_service("config")
    config = config_service.get_config()

    return SimpleNamespace(
        # Infrastructure
        db=application.db,
        queue=application.queue,
        cfg=config,
        # Services
        queue_service=application.services.get("queue"),
        worker_service=application.services.get("worker"),
        # Processing coordination
        processor_coord=application.coordinator,
        worker_pool=application.workers,
        # Events
        event_broker=application.event_broker,
    )


# ----------------------------------------------------------------------
# Processing endpoints
# ----------------------------------------------------------------------


@router.post("/api/process", dependencies=[Depends(verify_session)])
async def web_process(request: ProcessRequest):
    """Process a single file synchronously (web UI proxy)."""
    s = get_state()

    # Check if coordinator is available
    if not s.processor_coord:
        raise HTTPException(status_code=503, detail="Processing coordinator not initialized")

    # Submit job and wait for result
    try:
        future = s.processor_coord.submit(request.path, request.force)
        result = await asyncio.get_event_loop().run_in_executor(None, future.result, 300)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"File not found: {request.path}") from e
    except Exception as e:
        logging.exception(f"[Web API] Error processing {request.path}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/batch-process", dependencies=[Depends(verify_session)])
async def web_batch_process(request: BatchProcessRequest):
    """
    Add multiple paths to the database queue for processing (web UI proxy).
    Each path can be a file or directory - directories are recursively scanned for audio files.
    """
    s = get_state()

    results = []
    queued = 0
    errors = 0

    for path in request.paths:
        try:
            # Use QueueService for consistent queue operations
            result = s.queue_service.add_files(
                paths=[path],
                force=bool(request.force),
                recursive=True,  # Always scan directories recursively
            )

            # result contains: job_ids (list), files_queued (int), queue_depth, paths
            files_count = result["files_queued"]
            job_ids = result["job_ids"]

            if files_count > 1:
                # Directory with multiple files
                results.append(
                    {
                        "path": path,
                        "status": "queued",
                        "message": f"Added {files_count} files to queue (jobs {job_ids[0]}-{job_ids[-1]})",
                    }
                )
            else:
                # Single file
                results.append(
                    {
                        "path": path,
                        "status": "queued",
                        "message": f"Added to queue as job {job_ids[0]}",
                    }
                )

            queued += files_count

        except HTTPException as e:
            results.append({"path": path, "status": "error", "message": e.detail})
            errors += 1
        except Exception as e:
            # Sanitize exception to avoid leaking sensitive information
            safe_msg = sanitize_exception_message(e, "Failed to process file")
            results.append({"path": path, "status": "error", "message": safe_msg})
            errors += 1

    return {"queued": queued, "skipped": 0, "errors": errors, "results": results}


# ----------------------------------------------------------------------
# Queue endpoints
# ----------------------------------------------------------------------


@router.get("/api/list", dependencies=[Depends(verify_session)])
async def web_list(limit: int = 50, offset: int = 0, status: str | None = None):
    """List jobs with pagination and filtering (web UI proxy)."""
    s = get_state()

    # Use QueueService to list jobs
    return s.queue_service.list_jobs(limit=limit, offset=offset, status=status)


@router.get("/api/status/{job_id}", dependencies=[Depends(verify_session)])
async def web_status(job_id: int):
    """Get status of a specific job (web UI proxy)."""
    s = get_state()

    # Use QueueService to get job details
    job = s.queue_service.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return job


@router.get("/api/queue-depth", dependencies=[Depends(verify_session)])
async def web_queue_depth():
    """Get queue depth statistics (web UI proxy)."""
    s = get_state()

    # Use QueueService to get queue statistics
    return s.queue_service.get_status()


# ----------------------------------------------------------------------
# Admin endpoints
# ----------------------------------------------------------------------


@router.post("/api/admin/remove", dependencies=[Depends(verify_session)])
async def web_admin_remove(request: RemoveRequest):
    """Remove jobs from queue (web UI proxy)."""
    s = get_state()

    # Use QueueService to remove jobs
    removed = s.queue_service.remove_jobs(
        job_id=request.job_id,
        status=request.status,
        all=request.all,
    )

    # Publish queue stats update
    s.queue_service.publish_queue_update(s.event_broker)

    return {"removed": removed, "status": "ok"}


@router.post("/api/admin/flush", dependencies=[Depends(verify_session)])
async def web_admin_flush():
    """Remove all completed/error jobs (web UI proxy)."""
    s = get_state()

    # Use QueueService to remove done and error jobs
    done_count = s.queue_service.remove_jobs(status="done")
    error_count = s.queue_service.remove_jobs(status="error")
    total_removed = done_count + error_count

    # Publish queue stats update
    s.queue_service.publish_queue_update(s.event_broker)

    return {"removed": total_removed, "done": done_count, "errors": error_count, "status": "ok"}


@router.post("/api/admin/queue/clear-all", dependencies=[Depends(verify_session)])
async def web_admin_clear_all():
    """Clear all jobs from queue including running ones (web UI)."""
    s = get_state()

    # Use QueueService to remove all jobs (pending, done, error - not running)
    removed = s.queue_service.remove_jobs(all=True)

    # Publish queue stats update
    s.queue_service.publish_queue_update(s.event_broker)

    return {"removed": removed, "status": "ok"}


@router.post("/api/admin/queue/clear-completed", dependencies=[Depends(verify_session)])
async def web_admin_clear_completed():
    """Clear completed jobs from queue (web UI)."""
    s = get_state()

    removed = s.queue_service.remove_jobs(status="done")

    # Publish queue stats update
    s.queue_service.publish_queue_update(s.event_broker)

    return {"removed": removed, "status": "ok"}


@router.post("/api/admin/queue/clear-errors", dependencies=[Depends(verify_session)])
async def web_admin_clear_errors():
    """Clear error jobs from queue (web UI)."""
    s = get_state()

    removed = s.queue_service.remove_jobs(status="error")

    # Publish queue stats update
    s.queue_service.publish_queue_update(s.event_broker)

    return {"removed": removed, "status": "ok"}


@router.post("/api/admin/cleanup", dependencies=[Depends(verify_session)])
async def web_admin_cleanup(max_age_hours: int = 168):
    """Remove old completed/error jobs (web UI proxy)."""
    s = get_state()

    # Use QueueService to clean up old jobs
    removed = s.queue_service.cleanup_old_jobs(max_age_hours=max_age_hours)

    # Publish queue stats update
    s.queue_service.publish_queue_update(s.event_broker)

    return {"removed": removed, "max_age_hours": max_age_hours, "status": "ok"}


@router.post("/api/admin/cache-refresh", dependencies=[Depends(verify_session)])
async def web_admin_cache_refresh():
    """Refresh model cache (web UI proxy)."""
    try:
        ml_service = application.services["ml"]
        count = ml_service.warmup_cache()

        return {"status": "ok", "message": f"Model cache refreshed successfully ({count} predictors)"}
    except Exception as e:
        logging.exception("[Web API] Cache refresh failed")
        raise HTTPException(status_code=500, detail=f"Cache refresh failed: {e}") from e


@router.post("/api/admin/reset", dependencies=[Depends(verify_session)])
async def web_admin_reset(request: AdminResetRequest):
    """Reset stuck/error jobs to pending (web UI proxy)."""
    s = get_state()

    if not request.stuck and not request.errors:
        raise HTTPException(status_code=400, detail="Must specify --stuck or --errors")

    # Use QueueService to reset jobs
    reset_count = s.queue_service.reset_jobs(stuck=request.stuck, errors=request.errors)

    # Publish queue stats update
    s.queue_service.publish_queue_update(s.event_broker)

    return {
        "status": "ok",
        "message": f"Reset {reset_count} job(s) to pending",
        "reset": reset_count,
    }


@router.post("/api/admin/worker/pause", dependencies=[Depends(verify_session)])
async def web_admin_worker_pause():
    """Pause the worker (web UI proxy)."""
    s = get_state()
    s.db.meta.set("worker_enabled", "false")

    # Stop all workers
    for worker in s.worker_pool:
        worker.stop()
    s.worker_pool.clear()

    # Publish worker state update
    if s.event_broker:
        s.event_broker.update_worker_state("main", {"enabled": False})

    return {"status": "paused", "message": "Worker paused successfully"}


@router.post("/api/admin/worker/resume", dependencies=[Depends(verify_session)])
async def web_admin_worker_resume():
    """Resume the worker (web UI proxy)."""
    s = get_state()

    # Use WorkerService to resume workers
    if s.worker_service:
        s.worker_service.enable()
        s.worker_pool = s.worker_service.start_workers(event_broker=s.event_broker)

    # Publish worker state update
    if s.event_broker:
        s.event_broker.update_worker_state("main", {"enabled": True})

    return {"status": "resumed", "message": "Worker resumed successfully"}


# Background task storage for restart
_RESTART_TASKS: set = set()


@router.post("/api/admin/restart", dependencies=[Depends(verify_session)])
async def web_admin_restart():
    """Restart the API server (useful after config changes)."""
    import sys

    logging.info("[Web API] Restart requested - restarting server...")

    # Use a background task to allow the response to be sent before restart
    async def do_restart():
        await asyncio.sleep(1)  # Give time for response to be sent
        logging.info("[Web API] Executing restart now")
        os.execv(sys.executable, [sys.executable, *sys.argv])

    # Store task to prevent garbage collection
    task = asyncio.create_task(do_restart())
    _RESTART_TASKS.add(task)
    task.add_done_callback(_RESTART_TASKS.discard)

    return {
        "status": "restarting",
        "message": "API server is restarting... Please refresh the page in a few seconds.",
    }


# ----------------------------------------------------------------------
# Utility endpoints
# ----------------------------------------------------------------------


def _extract_mp3_tags(audio: Any, namespace: str) -> dict[str, Any]:
    """Extract tags from MP3 (ID3v2) format."""
    tags = {}
    if hasattr(audio, "tags") and audio.tags:
        for key in audio.tags:
            if key.startswith("TXXX:"):
                tag_name = key[5:]
                if tag_name.startswith(f"{namespace}:"):
                    clean_name = tag_name[len(namespace) + 1 :]
                    values = audio.tags[key].text
                    tags[clean_name] = values if len(values) > 1 else values[0]
    return tags


def _extract_mp4_tags(audio: Any, namespace: str) -> dict[str, Any]:
    """Extract tags from MP4/M4A format."""
    tags = {}
    if hasattr(audio, "tags") and hasattr(audio.tags, "get"):
        for key, value in audio.tags.items():
            if key.startswith("----:com.apple.iTunes:"):
                tag_name = key[22:]
                if tag_name.startswith(f"{namespace}:"):
                    clean_name = tag_name[len(namespace) + 1 :]
                    tags[clean_name] = value[0].decode("utf-8") if isinstance(value[0], bytes) else str(value[0])
    return tags


@router.get("/api/show-tags", dependencies=[Depends(verify_session)])
async def web_show_tags(path: str):
    """Read tags from an audio file (web UI proxy)."""
    s = get_state()
    namespace = s.cfg.get("namespace", "essentia")
    library_path = s.cfg.get("library_path", "")

    # Validate path to prevent directory traversal (includes existence check)
    validated_path = validate_library_path(path, library_path)

    try:
        audio = mutagen.File(validated_path)
        if audio is None:
            raise HTTPException(status_code=400, detail="Unsupported audio format")

        # Try MP3 format first, then MP4
        tags = _extract_mp3_tags(audio, namespace)
        if not tags:
            tags = _extract_mp4_tags(audio, namespace)

        return {
            "path": validated_path,
            "namespace": namespace,
            "tags": tags,
            "count": len(tags),
        }

    except Exception as e:
        logging.exception(f"[Web API] Error reading tags from {path}")
        raise HTTPException(status_code=500, detail=f"Error reading tags: {e}") from e


@router.get("/api/info", dependencies=[Depends(verify_session)])
async def web_info():
    """Get system info (web UI proxy)."""
    s = get_state()

    return {
        "version": "1.2",
        "namespace": s.cfg.get("namespace", "essentia"),
        "models_dir": s.cfg.get("namespace", "/app/models"),
        "worker_enabled": s.worker_service.is_enabled() if s.worker_service else False,
        "worker_count": s.worker_service.worker_count if s.worker_service else 0,
    }


@router.get("/api/health", dependencies=[Depends(verify_session)])
async def web_health():
    """Health check endpoint (web UI proxy)."""
    s = get_state()

    # Get queue statistics via QueueService
    queue_stats = s.queue_service.get_status()

    # Detect potential issues
    warnings = []
    worker_count = s.processor_coord.worker_count if s.processor_coord else 0
    running_jobs = queue_stats.get("running", 0)

    # Check for more running jobs than workers (stuck jobs)
    if running_jobs > worker_count:
        warnings.append(
            f"More running jobs ({running_jobs}) than workers ({worker_count}). "
            f"Some jobs may be stuck in 'running' app."
        )

    return {
        "status": "healthy" if not warnings else "degraded",
        "processor_initialized": s.processor_coord is not None,
        "event_broker_initialized": s.event_broker is not None,
        "worker_count": worker_count,
        "queue": queue_stats,
        "warnings": warnings,
    }


# ----------------------------------------------------------------------
# Navidrome integration endpoints
# ----------------------------------------------------------------------


@router.get("/api/navidrome/preview", dependencies=[Depends(verify_session)])
async def web_navidrome_preview():
    """Get preview of tags for Navidrome config generation (web UI proxy)."""
    s = get_state()
    namespace = s.cfg.get("namespace", "nom")

    try:
        stats = preview_tag_stats(s.db, namespace=namespace)

        # Convert to list format for easier frontend consumption
        tag_list = []
        for tag_key, tag_stats in sorted(stats.items()):
            tag_list.append(
                {
                    "tag_key": tag_key,
                    "type": tag_stats["type"],
                    "is_multivalue": tag_stats["is_multivalue"],
                    "summary": tag_stats["summary"],
                    "total_count": tag_stats["total_count"],
                }
            )

        return {
            "namespace": namespace,
            "tag_count": len(tag_list),
            "tags": tag_list,
        }

    except Exception as e:
        logging.exception("[Web API] Error generating Navidrome preview")
        raise HTTPException(status_code=500, detail=f"Error generating preview: {e}") from e


@router.get("/api/navidrome/config", dependencies=[Depends(verify_session)])
async def web_navidrome_config():
    """Generate Navidrome TOML configuration (web UI proxy)."""
    s = get_state()
    namespace = s.cfg.get("namespace", "nom")

    try:
        toml_config = generate_navidrome_config(s.db, namespace=namespace)

        return {
            "namespace": namespace,
            "config": toml_config,
        }

    except Exception as e:
        logging.exception("[Web API] Error generating Navidrome config")
        raise HTTPException(status_code=500, detail=f"Error generating config: {e}") from e


@router.post("/api/navidrome/playlists/preview", dependencies=[Depends(verify_session)])
async def web_navidrome_playlist_preview(request: dict):
    """Preview Smart Playlist query results."""
    try:
        from nomarr.services.navidrome.playlist_generator import PlaylistQueryError, preview_playlist_query

        query = request.get("query", "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")

        preview_limit = request.get("preview_limit", 10)

        db_path = application.db_path
        namespace = application.namespace

        try:
            result = preview_playlist_query(db_path, query, namespace, preview_limit)
            return result
        except PlaylistQueryError as e:
            raise HTTPException(status_code=400, detail=f"Invalid query: {e}") from e

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("[Web API] Error previewing playlist")
        raise HTTPException(status_code=500, detail=f"Error previewing playlist: {e}") from e


@router.post("/api/navidrome/playlists/generate", dependencies=[Depends(verify_session)])
async def web_navidrome_playlist_generate(request: dict):
    """Generate Navidrome Smart Playlist (.nsp) from query."""
    try:
        from nomarr.services.navidrome.playlist_generator import PlaylistQueryError, generate_nsp_playlist

        query = request.get("query", "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")

        playlist_name = request.get("playlist_name", "Playlist")
        comment = request.get("comment", "")
        limit = request.get("limit")
        sort = request.get("sort")

        db_path = application.db_path
        namespace = application.namespace

        try:
            nsp_content = generate_nsp_playlist(
                db_path,
                query,
                playlist_name,
                comment,
                namespace,
                sort,
                limit,
            )

            return {
                "playlist_name": playlist_name,
                "query": query,
                "content": nsp_content,
                "format": "nsp",
            }
        except PlaylistQueryError as e:
            raise HTTPException(status_code=400, detail=f"Invalid query: {e}") from e

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("[Web API] Error generating playlist")
        raise HTTPException(status_code=500, detail=f"Error generating playlist: {e}") from e


@router.get("/api/navidrome/templates/list", dependencies=[Depends(verify_session)])
async def web_navidrome_templates_list():
    """Get list of all available playlist templates."""
    try:
        from nomarr.services.navidrome.templates import get_template_summary

        templates = get_template_summary()
        return {"templates": templates, "total_count": len(templates)}

    except Exception as e:
        logging.exception("[Web API] Error listing templates")
        raise HTTPException(status_code=500, detail=f"Error listing templates: {e}") from e


@router.post("/api/navidrome/templates/generate", dependencies=[Depends(verify_session)])
async def web_navidrome_templates_generate():
    """Generate all playlist templates as a batch."""
    try:
        from nomarr.services.navidrome.templates import generate_template_files

        templates = generate_template_files()
        return {"templates": templates, "total_count": len(templates)}

    except Exception as e:
        logging.exception("[Web API] Error generating templates")
        raise HTTPException(status_code=500, detail=f"Error generating templates: {e}") from e


@router.get("/api/analytics/tag-frequencies", dependencies=[Depends(verify_session)])
async def web_analytics_tag_frequencies(limit: int = 50):
    """Get tag frequency statistics."""
    try:
        from nomarr.services.analytics import AnalyticsService

        namespace = application.namespace
        analytics_service = AnalyticsService(application.db)
        result = analytics_service.get_tag_frequencies(namespace=namespace, limit=limit)

        # Transform to format expected by frontend
        # Backend returns: {"nom_tags": [(tag, count), ...], ...} (tags without namespace prefix)
        # Frontend expects: {"tag_frequencies": [{"tag_key": tag, "total_count": count}, ...]}
        # Add namespace prefix back for display
        tag_frequencies = [
            {"tag_key": f"{namespace}:{tag}", "total_count": count, "unique_values": count}
            for tag, count in result.get("nom_tags", [])
        ]

        return {"tag_frequencies": tag_frequencies}

    except Exception as e:
        logging.exception("[Web API] Error getting tag frequencies")
        raise HTTPException(status_code=500, detail=f"Error getting tag frequencies: {e}") from e


@router.get("/api/analytics/mood-distribution", dependencies=[Depends(verify_session)])
async def web_analytics_mood_distribution():
    """Get mood tag distribution."""
    try:
        from nomarr.services.analytics import AnalyticsService

        namespace = application.namespace
        analytics_service = AnalyticsService(application.db)
        result = analytics_service.get_mood_distribution(namespace=namespace)

        # Transform to format expected by frontend
        # Backend returns: {"top_moods": [(mood, count), ...], ...}
        # Frontend expects: {"mood_distribution": [{"mood": mood, "count": count, "percentage": %}, ...]}
        top_moods = result.get("top_moods", [])
        total_moods = sum(count for _, count in top_moods)

        mood_distribution = [
            {
                "mood": mood,
                "count": count,
                "percentage": round((count / total_moods * 100), 2) if total_moods > 0 else 0,
            }
            for mood, count in top_moods
        ]

        return {"mood_distribution": mood_distribution}

    except Exception as e:
        logging.exception("[Web API] Error getting mood distribution")
        raise HTTPException(status_code=500, detail=f"Error getting mood distribution: {e}") from e


@router.get("/api/analytics/tag-correlations", dependencies=[Depends(verify_session)])
async def web_analytics_tag_correlations(top_n: int = 20):
    """
    Get VALUE-based correlation matrix for mood values, genres, and attributes.
    Returns mood-to-mood, mood-to-genre, and mood-to-tier correlations.
    """
    try:
        from nomarr.services.analytics import AnalyticsService

        namespace = application.namespace
        analytics_service = AnalyticsService(application.db)
        result = analytics_service.get_tag_correlation_matrix(namespace=namespace, top_n=top_n)
        return result

    except Exception as e:
        logging.exception("[Web API] Error getting tag correlations")
        raise HTTPException(status_code=500, detail=f"Error getting tag correlations: {e}") from e


@router.get("/api/analytics/tag-co-occurrences/{tag}", dependencies=[Depends(verify_session)])
async def web_analytics_tag_co_occurrences(tag: str, limit: int = 10):
    """
    Get mood value co-occurrences and genre/artist relationships.
    Shows which moods appear together and what genres/artists correlate with a mood.
    """
    try:
        from nomarr.services.analytics import AnalyticsService

        namespace = application.namespace
        analytics_service = AnalyticsService(application.db)

        # Mood value co-occurrence analysis
        result = analytics_service.get_mood_value_co_occurrences(mood_value=tag, namespace=namespace, limit=limit)

        # Transform to frontend format
        co_occurrences = [
            {"tag": mood, "count": count, "percentage": pct} for mood, count, pct in result["mood_co_occurrences"]
        ]

        top_artists = [
            {"name": artist, "count": count, "percentage": pct} for artist, count, pct in result["artist_distribution"]
        ]

        top_genres = [
            {"name": genre, "count": count, "percentage": pct} for genre, count, pct in result["genre_distribution"]
        ]

        return {
            "tag": tag,
            "total_occurrences": result["total_occurrences"],
            "co_occurrences": co_occurrences,
            "top_artists": top_artists,
            "top_genres": top_genres,
            "limit": limit,
        }

    except Exception as e:
        logging.exception("[Web API] Error getting tag co-occurrences")
        raise HTTPException(status_code=500, detail=f"Error getting tag co-occurrences: {e}") from e


@router.get("/api/library/stats", dependencies=[Depends(verify_session)])
async def web_library_stats():
    """Get library statistics (total files, artists, albums, duration)."""
    try:
        # Use persistence layer to get library stats
        stats = application.db.library.get_library_stats()

        return {
            "total_files": stats.get("total_files", 0) or 0,
            "unique_artists": stats.get("total_artists", 0) or 0,
            "unique_albums": stats.get("total_albums", 0) or 0,
            "total_duration_seconds": stats.get("total_duration", 0) or 0,
        }

    except Exception as e:
        logging.exception("[Web API] Error getting library stats")
        raise HTTPException(status_code=500, detail=f"Error getting library stats: {e}") from e


# ----------------------------------------------------------------------
# Calibration Management
# ----------------------------------------------------------------------


@router.post("/api/calibration/apply", dependencies=[Depends(verify_session)])
async def apply_calibration_to_library():
    """
    Queue all library files for recalibration.
    This updates tier and mood tags by applying calibration to existing raw scores.
    """
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


@router.get("/api/calibration/status", dependencies=[Depends(verify_session)])
async def get_calibration_status():
    """Get current recalibration queue status."""
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


@router.post("/api/calibration/clear", dependencies=[Depends(verify_session)])
async def clear_calibration_queue():
    """Clear all pending and completed recalibration jobs."""
    try:
        recal_service = application.services.get("recalibration")
        if not recal_service:
            raise HTTPException(status_code=503, detail="Recalibration service not available")

        count = recal_service.clear_queue()

        return {"cleared": count, "message": f"Cleared {count} jobs from calibration queue"}

    except Exception as e:
        logging.exception("[Web API] Error clearing calibration queue")
        raise HTTPException(status_code=500, detail=f"Error clearing calibration queue: {e}") from e


# ----------------------------------------------------------------------
# Config Management
# ----------------------------------------------------------------------


class ConfigUpdateRequest(BaseModel):
    """Request model for updating configuration values."""

    key: str
    value: str


@router.get("/api/config")
def get_config(_session: dict = Depends(verify_session)):
    """Get current configuration values (user-editable subset)."""
    try:
        config_service = application.get_service("config")

        config = config_service.get_config()

        # Get user-editable config values
        # Some from DB meta, some from config dict
        worker_enabled = application.db.meta.get("worker_enabled")
        if worker_enabled is None:
            worker_enabled = str(config.get("worker_enabled", True)).lower()

        return {
            # Tag writing settings
            "namespace": config.get("namespace", "essentia"),
            "version_tag": config.get("version_tag", "essentia_at_version"),
            "overwrite_tags": config.get("overwrite_tags", True),
            # Processing rules
            "min_duration_s": config.get("min_duration_s", 7),
            "allow_short": config.get("allow_short", False),
            # Worker settings
            "worker_enabled": worker_enabled == "true",
            "worker_count": config.get("worker_count", 1),
            "poll_interval": config.get("poll_interval", 2),
            "cleanup_age_hours": config.get("cleanup_age_hours", 168),
            # API settings
            "blocking_mode": config.get("blocking_mode", True),
            "blocking_timeout": config.get("blocking_timeout", 3600),
            # Cache settings
            "cache_idle_timeout": config.get("cache_idle_timeout", 300),
            "cache_auto_evict": config.get("cache_auto_evict", True),
            # Library settings
            "library_path": config.get("library_path", ""),
            "library_scan_poll_interval": config.get("library_scan_poll_interval", 10),
        }

    except Exception as e:
        logging.exception("[Web API] Error getting config")
        raise HTTPException(status_code=500, detail=f"Error getting config: {e}") from e


@router.post("/api/config")
def update_config(request: ConfigUpdateRequest, _session: dict = Depends(verify_session)):
    """
    Update a configuration value in the database.

    Changes are stored in the DB meta table and will override YAML/env config on restart.
    worker_enabled also updates immediately for live effect.
    """
    try:
        key = request.key
        value = request.value

        # Validate key is user-editable
        editable_keys = {
            "namespace",
            "version_tag",
            "overwrite_tags",
            "min_duration_s",
            "allow_short",
            "worker_enabled",
            "worker_count",
            "poll_interval",
            "cleanup_age_hours",
            "blocking_mode",
            "blocking_timeout",
            "cache_idle_timeout",
            "cache_auto_evict",
            "library_path",
            "library_scan_poll_interval",
        }

        if key not in editable_keys:
            raise HTTPException(status_code=400, detail=f"Config key '{key}' is not editable")

        # Store in DB meta (prefixed with "config_")
        # The value will be parsed to correct type when loaded by compose()
        application.db.meta.set(f"config_{key}", value)

        # Special handling for worker_enabled - also update runtime state
        if key == "worker_enabled":
            application.db.meta.set("worker_enabled", value)

        return {
            "success": True,
            "message": f"Config '{key}' updated. Use 'Restart Server' for changes to take full effect.",
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.exception("[Web API] Error updating config")
        raise HTTPException(status_code=500, detail=f"Error updating config: {e}") from e


# ----------------------------------------------------------------------
# Server-Sent Events (SSE) endpoint for real-time updates
# ----------------------------------------------------------------------


@router.get("/events/status")
async def web_sse_status(token: str):
    """
    Server-Sent Events endpoint for real-time system status updates.
    Requires session token as query parameter for authentication.

    Provides real-time updates for:
    - Queue statistics (pending/running/completed counts)
    - Active job state (progress, current head being processed)
    - Worker state (files being processed, progress)
    """
    import asyncio
    import json

    from fastapi.responses import StreamingResponse

    from nomarr.interfaces.api.auth import validate_session

    s = get_state()

    # Verify session token
    if not validate_session(token):
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    # Subscribe to state broker
    client_id, event_queue = s.event_broker.subscribe(["queue:status", "queue:jobs", "worker:*:status"])

    async def event_generator():
        """Generate SSE events from state broker."""
        try:
            # Send initial connection event
            yield f"event: connected\ndata: {json.dumps({'message': 'Connected to status stream'})}\n\n"

            # Stream updates
            while True:
                try:
                    # Check for new events (non-blocking with timeout)
                    await asyncio.sleep(0.1)  # Prevent tight loop
                    try:
                        event = event_queue.get_nowait()

                        # Map internal event types to client-friendly events
                        event_type = event.get("type", "update")
                        if event_type in ("snapshot", "state_update"):
                            # Queue state update
                            yield f"event: queue_update\ndata: {json.dumps(event.get('state', {}))}\n\n"
                        elif event_type == "job_update":
                            # Job processing update
                            yield f"event: processing_update\ndata: {json.dumps(event.get('job', {}))}\n\n"
                        elif event_type == "worker_update":
                            # Worker status update
                            yield f"event: worker_update\ndata: {json.dumps(event.get('worker', {}))}\n\n"

                    except __import__("queue").Empty:
                        # No events, send periodic keepalive (every ~3 seconds)
                        await asyncio.sleep(3)
                        yield ": keepalive\n\n"

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logging.error(f"[Web SSE] Error in event stream: {e}")
                    break

        finally:
            # Cleanup subscription
            s.event_broker.unsubscribe(client_id)
            logging.info(f"[Web SSE] Client {client_id} disconnected")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


# ----------------------------------------------------------------------
# Calibration endpoints
# ----------------------------------------------------------------------


class CalibrationRequest(BaseModel):
    save_sidecars: bool = True  # Save calibration files next to models by default


@router.post("/api/calibration/generate", dependencies=[Depends(verify_session)])
async def generate_calibration(request: CalibrationRequest):
    """
    Generate min-max scale calibration from library tags.

    Analyzes all tagged files in the library to compute scaling parameters (5th/95th percentiles)
    for normalizing each model to a common [0, 1] scale. This makes model outputs comparable
    while preserving semantic meaning.

    Uses industry standard minimum of 1000 samples per tag for reliable calibration.

    If save_sidecars=True, writes calibration JSON files next to model files.
    """
    s = get_state()

    try:
        from nomarr.services.calibration import CalibrationService

        # Create service with dependencies
        calibration_service = CalibrationService(
            db=s.db,
            models_dir=str(application.models_dir),
            namespace=application.namespace,
        )

        # Run calibration in background thread (can take time with 18k songs)
        loop = asyncio.get_event_loop()
        calibration_data = await loop.run_in_executor(
            None,
            calibration_service.generate_minmax_calibration,
        )

        # Optionally save sidecars
        save_result = None
        if request.save_sidecars:
            save_result = await loop.run_in_executor(
                None,
                calibration_service.save_calibration_sidecars,
                calibration_data,
            )

        return {
            "status": "success",
            "data": calibration_data,
            "saved_files": save_result,
        }

    except Exception as e:
        logging.error(f"[Web] Calibration generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e
