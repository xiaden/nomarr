"""Tag curation endpoints for web UI."""

import asyncio
import logging
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.id_codec import decode_path_id
from nomarr.interfaces.api.web.dependencies import get_tagging_service

if TYPE_CHECKING:
    from nomarr.services.domain.tagging_svc import TaggingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tag-curation", tags=["Tag Curation"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class RenameTagRequest(BaseModel):
    tag_id: str
    new_value: str


class MergeTagsRequest(BaseModel):
    source_tag_ids: list[str]
    canonical_tag_id: str


class SplitTagRequest(BaseModel):
    source_tag_id: str
    song_ids: list[str]
    new_value: str


class CommitRequest(BaseModel):
    library_id: str | None = None


class UpdateFileTagsRequest(BaseModel):
    rel: str
    values: list[str]


# ---------------------------------------------------------------------------
# Curation endpoints
# ---------------------------------------------------------------------------


@router.post("/rename", dependencies=[Depends(verify_session)])
async def rename_tag(
    request: RenameTagRequest,
    tagging_service: Annotated["TaggingService", Depends(get_tagging_service)],
) -> dict[str, Any]:
    """Rename a tag to a new value."""
    try:
        result = await asyncio.to_thread(
            tagging_service.rename_tag,
            tag_id=request.tag_id,
            new_value=request.new_value,
        )
        return dict(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        logger.exception("[Web API] Error renaming tag")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to rename tag"),
        ) from e


@router.post("/merge", dependencies=[Depends(verify_session)])
async def merge_tags(
    request: MergeTagsRequest,
    tagging_service: Annotated["TaggingService", Depends(get_tagging_service)],
) -> dict[str, Any]:
    """Merge multiple tags into a canonical tag."""
    try:
        result = await asyncio.to_thread(
            tagging_service.merge_tags,
            source_tag_ids=request.source_tag_ids,
            canonical_tag_id=request.canonical_tag_id,
        )
        return dict(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        logger.exception("[Web API] Error merging tags")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to merge tags"),
        ) from e


@router.post("/split", dependencies=[Depends(verify_session)])
async def split_tag(
    request: SplitTagRequest,
    tagging_service: Annotated["TaggingService", Depends(get_tagging_service)],
) -> dict[str, Any]:
    """Split selected songs from a tag into a new tag value."""
    try:
        result = await asyncio.to_thread(
            tagging_service.split_tag,
            source_tag_id=request.source_tag_id,
            song_ids=request.song_ids,
            new_value=request.new_value,
        )
        return dict(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        logger.exception("[Web API] Error splitting tag")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to split tag"),
        ) from e


# ---------------------------------------------------------------------------
# Query endpoints
# ---------------------------------------------------------------------------


@router.get("/value", dependencies=[Depends(verify_session)])
async def list_tag_values(
    tagging_service: Annotated["TaggingService", Depends(get_tagging_service)],
    rel: Annotated[str | None, Query(description="Filter by tag rel (e.g. genre)")] = None,
    prefix: Annotated[str | None, Query(description="Substring search on tag value")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """List tag values with optional filtering and pagination."""
    try:
        result = await asyncio.to_thread(
            tagging_service.list_tag_values,
            rel=rel,
            prefix=prefix,
            limit=limit,
            offset=offset,
        )
        return dict(result)
    except Exception as e:
        logger.exception("[Web API] Error listing tag values")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to list tag values"),
        ) from e


@router.get("/{tag_id}/song", dependencies=[Depends(verify_session)])
async def get_tag_songs(
    tag_id: str,
    tagging_service: Annotated["TaggingService", Depends(get_tagging_service)],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """Get songs linked to a tag with metadata."""
    tag_id = decode_path_id(tag_id)
    try:
        return await asyncio.to_thread(
            tagging_service.get_tag_songs,
            tag_id=tag_id,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except Exception as e:
        logger.exception("[Web API] Error getting tag songs")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to get tag songs"),
        ) from e


# ---------------------------------------------------------------------------
# Commit endpoints
# ---------------------------------------------------------------------------


@router.post("/commit", dependencies=[Depends(verify_session)])
async def commit_pending_tags(
    request: CommitRequest,
    tagging_service: Annotated["TaggingService", Depends(get_tagging_service)],
) -> dict[str, Any]:
    """Commit pending tag writes to files."""
    try:
        result = await asyncio.to_thread(
            tagging_service.commit_pending_tags,
            library_id=request.library_id,
        )
        return dict(result)
    except Exception as e:
        logger.exception("[Web API] Error committing pending tags")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to commit tags"),
        ) from e


@router.get("/pending-count", dependencies=[Depends(verify_session)])
async def get_pending_commit_count(
    tagging_service: Annotated["TaggingService", Depends(get_tagging_service)],
) -> dict[str, int]:
    """Get count of files with pending tag writes."""
    try:
        count = await asyncio.to_thread(tagging_service.get_pending_commit_count)
        return {"count": count}
    except Exception as e:
        logger.exception("[Web API] Error getting pending commit count")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to get pending count"),
        ) from e


# ---------------------------------------------------------------------------
# Single-file tag edit
# ---------------------------------------------------------------------------


@router.patch("/file/{file_id}/tag", dependencies=[Depends(verify_session)])
async def update_file_tags(
    file_id: str,
    request: UpdateFileTagsRequest,
    tagging_service: Annotated["TaggingService", Depends(get_tagging_service)],
) -> dict[str, Any]:
    """Replace all tags for a file+rel with new values."""
    file_id = decode_path_id(file_id)
    try:
        return await asyncio.to_thread(
            tagging_service.update_file_tags,
            file_id=file_id,
            rel=request.rel,
            values=request.values,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        logger.exception(f"[Web API] Error updating tags for file {file_id}")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to update file tags"),
        ) from e
