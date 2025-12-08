"""Tag viewing endpoints for web UI."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_library_service
from nomarr.services.domain.library_svc import LibraryService

router = APIRouter(prefix="/tags", tags=["Tags"])


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("/show-tags", dependencies=[Depends(verify_session)])
async def web_show_tags(
    path: str,
    library_service: LibraryService = Depends(get_library_service),
) -> dict[str, Any]:
    """Read tags from an audio file (web UI proxy)."""
    try:
        tags = library_service.read_file_tags(path)

        return {
            "path": path,
            "namespace": library_service.cfg.namespace,
            "tags": tags,
            "count": len(tags),
        }

    except ValueError as e:
        # Path validation errors (security)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        # File reading errors
        logging.exception(f"[Web API] Error reading tags from {path}")
        raise HTTPException(status_code=500, detail=str(e)) from e
