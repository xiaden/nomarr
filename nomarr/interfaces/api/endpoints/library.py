"""
Library scan API endpoints.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

import nomarr.app as app
from nomarr.interfaces.api.auth import verify_session

router = APIRouter(prefix="/web/api/library", tags=["library"])


@router.post("/scan/start")
async def start_library_scan(_session: dict = Depends(verify_session)):
    """
    Start a new library scan (queues it for background processing).

    Returns:
        Dict with scan_id and status
    """
    if not app.application.library_scan_worker:
        raise HTTPException(status_code=503, detail="Library scanner not configured (no library_path)")

    try:
        scan_id = app.application.library_scan_worker.request_scan()
        return {
            "scan_id": scan_id,
            "status": "queued",
            "message": "Library scan queued successfully",
        }
    except Exception as e:
        logging.error(f"[API] Failed to start library scan: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start scan: {e}") from e


@router.post("/scan/cancel")
async def cancel_library_scan(_session: dict = Depends(verify_session)):
    """
    Cancel the currently running library scan.

    Returns:
        Dict with success status
    """
    if not app.application.library_scan_worker:
        raise HTTPException(status_code=503, detail="Library scanner not configured")

    try:
        app.application.library_scan_worker.cancel_scan()
        return {"success": True, "message": "Scan cancellation requested"}
    except Exception as e:
        logging.error(f"[API] Failed to cancel library scan: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cancel scan: {e}") from e


@router.get("/scan/status")
async def get_library_scan_status(_session: dict = Depends(verify_session)):
    """
    Get current library scan worker status.

    Returns:
        Dict with: configured, enabled, running, library_path, current_scan_id, current_progress
    """
    if not app.application.library_scan_worker:
        return {
            "configured": False,
            "enabled": False,
            "running": False,
            "library_path": None,
            "current_scan_id": None,
            "current_progress": None,
        }

    try:
        status = app.application.library_scan_worker.get_status()
        status["configured"] = True
        status["library_path"] = app.LIBRARY_PATH
        return status
    except Exception as e:
        logging.error(f"[API] Failed to get library scan status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get status: {e}") from e


@router.get("/scan/history")
async def get_library_scan_history(limit: int = 10, _session: dict = Depends(verify_session)):
    """
    Get library scan history.

    Args:
        limit: Maximum number of scans to return

    Returns:
        List of scan records
    """
    try:
        scans = app.db.list_library_scans(limit=limit)
        return {"scans": scans}
    except Exception as e:
        logging.error(f"[API] Failed to get library scan history: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get history: {e}") from e


@router.post("/scan/pause")
async def pause_library_scanner(_session: dict = Depends(verify_session)):
    """
    Pause the library scanner (stop processing new scans).

    Returns:
        Dict with success status
    """
    if not app.application.library_scan_worker:
        raise HTTPException(status_code=503, detail="Library scanner not configured")

    try:
        app.application.library_scan_worker.pause()
        return {"success": True, "message": "Library scanner paused"}
    except Exception as e:
        logging.error(f"[API] Failed to pause library scanner: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to pause: {e}") from e


@router.post("/scan/resume")
async def resume_library_scanner(_session: dict = Depends(verify_session)):
    """
    Resume the library scanner.

    Returns:
        Dict with success status
    """
    if not app.application.library_scan_worker:
        raise HTTPException(status_code=503, detail="Library scanner not configured")

    try:
        app.application.library_scan_worker.resume()
        return {"success": True, "message": "Library scanner resumed"}
    except Exception as e:
        logging.error(f"[API] Failed to resume library scanner: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to resume: {e}") from e


@router.get("/stats")
async def get_library_stats(_session: dict = Depends(verify_session)):
    """
    Get library statistics (total files, artists, albums, duration).

    Returns:
        Dict with library statistics
    """
    try:
        stats = app.db.get_library_stats()
        return stats
    except Exception as e:
        logging.error(f"[API] Failed to get library stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {e}") from e


@router.post("/clear")
async def clear_library_data(_session: dict = Depends(verify_session)):
    """
    Clear all library data (files, tags, scans) to force a fresh rescan.
    Does not affect the job queue or system metadata.

    Note: Will fail if a library scan is currently running due to database locks.
    Cancel any running scan first.

    Returns:
        Dict with success status
    """
    if not app.application.library_scan_worker:
        raise HTTPException(status_code=503, detail="Library scanner not configured")

    # Check if a scan is currently running
    worker_status = app.application.library_scan_worker.get_status()
    if worker_status.get("current_scan_id") is not None:
        raise HTTPException(
            status_code=409, detail="Cannot clear library while a scan is running. Please cancel the scan first."
        )

    try:
        app.db.clear_library_data()
        logging.info("[API] Library data cleared")
        return {"success": True, "message": "Library data cleared successfully"}
    except Exception as e:
        logging.error(f"[API] Failed to clear library data: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear library: {e}") from e
