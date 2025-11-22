"""
Library scan API endpoints.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_library_service
from nomarr.services.library import LibraryService

router = APIRouter(prefix="/web/api/library", tags=["library"])


@router.post("/scan/start")
async def start_library_scan(
    library_service: LibraryService = Depends(get_library_service),
    _session: dict = Depends(verify_session),
):
    """
    Start a new library scan (discovers files and enqueues them for background processing).

    Returns:
        Dict with scan statistics
    """
    try:
        stats = library_service.start_scan()
        return {
            "status": "queued",
            "message": f"Library scan started: {stats['files_queued']} files queued",
            "stats": stats,
        }
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logging.error(f"[API] Failed to start library scan: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start scan: {e}") from e


@router.post("/scan/cancel")
async def cancel_library_scan(
    library_service: LibraryService = Depends(get_library_service),
    _session: dict = Depends(verify_session),
):
    """
    Cancel the currently running library scan.

    Returns:
        Dict with success status
    """
    try:
        success = library_service.cancel_scan()
        return {"success": success, "message": "Scan cancellation requested"}
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logging.error(f"[API] Failed to cancel library scan: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cancel scan: {e}") from e


@router.get("/scan/status")
async def get_library_scan_status(
    library_service: LibraryService = Depends(get_library_service),
    _session: dict = Depends(verify_session),
):
    """
    Get current library scan worker status.

    Returns:
        Dict with: configured, enabled, running, library_path, current_scan_id, current_progress
    """
    try:
        status = library_service.get_status()
        return status
    except Exception as e:
        logging.error(f"[API] Failed to get library scan status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get status: {e}") from e


@router.get("/scan/history")
async def get_library_scan_history(
    limit: int = 10,
    library_service: LibraryService = Depends(get_library_service),
    _session: dict = Depends(verify_session),
):
    """
    Get library scan history.

    Args:
        limit: Maximum number of scans to return

    Returns:
        List of scan records
    """
    try:
        scans = library_service.get_scan_history(limit=limit)
        return {"scans": scans}
    except Exception as e:
        logging.error(f"[API] Failed to get library scan history: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get history: {e}") from e


@router.post("/scan/pause")
async def pause_library_scanner(
    library_service: LibraryService = Depends(get_library_service),
    _session: dict = Depends(verify_session),
):
    """
    Pause the library scanner (stop processing new scans).

    Returns:
        Dict with success status
    """
    try:
        success = library_service.pause()
        return {"success": success, "message": "Library scanner paused"}
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logging.error(f"[API] Failed to pause library scanner: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to pause: {e}") from e


@router.post("/scan/resume")
async def resume_library_scanner(
    library_service: LibraryService = Depends(get_library_service),
    _session: dict = Depends(verify_session),
):
    """
    Resume the library scanner.

    Returns:
        Dict with success status
    """
    try:
        success = library_service.resume()
        return {"success": success, "message": "Library scanner resumed"}
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logging.error(f"[API] Failed to resume library scanner: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to resume: {e}") from e


@router.get("/stats")
async def get_library_stats(
    library_service: LibraryService = Depends(get_library_service),
    _session: dict = Depends(verify_session),
):
    """
    Get library statistics (total files, artists, albums, duration).

    Returns:
        Dict with library statistics
    """
    try:
        stats = library_service.get_library_stats()
        return stats
    except Exception as e:
        logging.error(f"[API] Failed to get library stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {e}") from e


@router.post("/clear")
async def clear_library_data(
    library_service: LibraryService = Depends(get_library_service),
    _session: dict = Depends(verify_session),
):
    """
    Clear all library data (files, tags, scans) to force a fresh rescan.
    Does not affect the job queue or system metadata.

    Note: Will fail if a library scan is currently running due to database locks.
    Cancel any running scan first.

    Returns:
        Dict with success status
    """
    try:
        library_service.clear_library_data()
        logging.info("[API] Library data cleared")
        return {"success": True, "message": "Library data cleared successfully"}
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:
        logging.error(f"[API] Failed to clear library data: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear library: {e}") from e
