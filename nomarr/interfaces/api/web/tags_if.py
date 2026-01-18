"""Tag viewing endpoints for web UI."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_tagging_service
from nomarr.services.domain.tagging_svc import TaggingService

router = APIRouter(prefix="/tags", tags=["Tags"])


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("/show-tags", dependencies=[Depends(verify_session)])
async def web_show_tags(
    path: str,
    tagging_service: TaggingService = Depends(get_tagging_service),
) -> dict[str, Any]:
    """Read tags from an audio file (web UI proxy)."""
    try:
        namespace = tagging_service.namespace
        tags = tagging_service.read_file_tags(path, namespace)

        return {
            "path": path,
            "namespace": namespace,
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


@router.delete("/remove-tags", dependencies=[Depends(verify_session)])
async def web_remove_tags(
    path: str,
    tagging_service: TaggingService = Depends(get_tagging_service),
) -> dict[str, Any]:
    """Remove all namespaced tags from an audio file (web UI proxy)."""
    try:
        namespace = tagging_service.namespace
        count = tagging_service.remove_file_tags(path, namespace)

        return {
            "path": path,
            "namespace": namespace,
            "removed": count,
        }

    except ValueError as e:
        # Path validation errors (security)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        # File modification errors
        logging.exception(f"[Web API] Error removing tags from {path}")
        raise HTTPException(status_code=500, detail=str(e)) from e
