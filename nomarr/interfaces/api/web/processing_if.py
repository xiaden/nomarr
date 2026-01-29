"""Processing endpoints for web UI.

NOTE: With the discovery-based worker system, manual file enqueuing is no longer supported.
Processing happens automatically via discovery workers that query library_files.
Files are marked as needing processing during library scans.
"""

import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_library_service

if TYPE_CHECKING:
    from nomarr.services.domain.library_svc import LibraryService

router = APIRouter(prefix="/processing", tags=["Processing"])


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("/status", dependencies=[Depends(verify_session)])
async def web_processing_status(
    library_service: Annotated["LibraryService", Depends(get_library_service)],
) -> dict[str, int]:
    """Get current processing status (files pending processing).

    With discovery-based workers, processing state is derived from library_files:
    - needs_tagging=1: File waiting to be processed
    - needs_tagging=0: File has been processed
    """
    try:
        stats = library_service.get_library_stats()
        pending = stats.needs_tagging_count or 0
        processed = stats.total_files - pending
        return {
            "pending": pending,
            "processed": processed,
            "total": stats.total_files,
        }
    except Exception as e:
        logging.exception("[Web API] Error getting processing status")
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to get processing status"),
        ) from e
