"""Tag viewing endpoints for web UI."""
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_tagging_service
from nomarr.services.domain.tagging_svc import TaggingService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tags", tags=["Tags"])

@router.get("/show-tags", dependencies=[Depends(verify_session)])
async def web_show_tags(path: str, tagging_service: Annotated[TaggingService, Depends(get_tagging_service)]) -> dict[str, Any]:
    """Read tags from an audio file (web UI proxy)."""
    try:
        namespace = tagging_service.namespace
        tags = tagging_service.read_file_tags(path, namespace)
        return {"path": path, "namespace": namespace, "tags": tags, "count": len(tags)}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file path") from None
    except RuntimeError as e:
        logger.exception(f"[Web API] Error reading tags from {path}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to read tags")) from e

@router.delete("/remove-tags", dependencies=[Depends(verify_session)])
async def web_remove_tags(path: str, tagging_service: Annotated[TaggingService, Depends(get_tagging_service)]) -> dict[str, Any]:
    """Remove all namespaced tags from an audio file (web UI proxy)."""
    try:
        namespace = tagging_service.namespace
        count = tagging_service.remove_file_tags(path, namespace)
        return {"path": path, "namespace": namespace, "removed": count}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file path") from None
    except RuntimeError as e:
        logger.exception(f"[Web API] Error removing tags from {path}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to remove tags")) from e
