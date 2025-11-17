"""Library statistics endpoints for web UI."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_database
from nomarr.persistence.db import Database

router = APIRouter(prefix="/api/library", tags=["Library"])


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("/stats", dependencies=[Depends(verify_session)])
async def web_library_stats(
    db: Database = Depends(get_database),
) -> dict[str, Any]:
    """Get library statistics (total files, artists, albums, duration)."""
    try:
        # Use persistence layer to get library stats
        stats = db.library.get_library_stats()

        return {
            "total_files": stats.get("total_files", 0) or 0,
            "unique_artists": stats.get("total_artists", 0) or 0,
            "unique_albums": stats.get("total_albums", 0) or 0,
            "total_duration_seconds": stats.get("total_duration", 0) or 0,
        }

    except Exception as e:
        logging.exception("[Web API] Error getting library stats")
        raise HTTPException(status_code=500, detail=f"Error getting library stats: {e}") from e
