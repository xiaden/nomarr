"""Tag curation endpoints for web UI."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_tagging_service
from nomarr.services.domain.tagging_svc import (
    TaggingService,  # noqa: TC001  # FastAPI resolves Annotated[...] at route registration
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tag-curation", tags=["Tag Curation"])


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
    name: str
    values: list[str]


class RenameTagResponse(BaseModel):
    moved: int
    merged_into_existing: bool


class MergeTagsResponse(BaseModel):
    total_moved: int
    sources_removed: int


class SplitTagResponse(BaseModel):
    moved: int
    new_tag_created: bool


class TagValueItemResponse(BaseModel):
    id: str
    name: str
    value: str
    song_count: int


class TagListResponse(BaseModel):
    tags: list[TagValueItemResponse]
    total: int


class TagSongItemResponse(BaseModel):
    file_id: str
    title: str
    artist: str
    album: str
    path: str


class TagSongsResponse(BaseModel):
    songs: list[TagSongItemResponse]
    total: int


class CommitResponse(BaseModel):
    started: bool
    pending_files: int


class PendingCountResponse(BaseModel):
    count: int


class UpdateFileTagResponse(BaseModel):
    """Single tag returned after updating a file's tag values."""

    key: str
    value: str
    type: str
    is_nomarr: bool


class UpdateFileTagsResponse(BaseModel):
    file_id: str
    name: str
    tags: list[UpdateFileTagResponse]


@router.post("/rename", dependencies=[Depends(verify_session)], response_model=RenameTagResponse)
async def rename_tag(
    request: RenameTagRequest,
    tagging_service: Annotated[TaggingService, Depends(get_tagging_service)],
) -> RenameTagResponse:
    """Rename a tag to a new value."""
    try:
        result = await asyncio.to_thread(
            tagging_service.rename_tag,
            tag_id=request.tag_id,
            new_value=request.new_value,
        )
        return RenameTagResponse.model_validate(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        logger.exception("[Web API] Error renaming tag")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to rename tag"),
        ) from e


@router.post("/merge", dependencies=[Depends(verify_session)], response_model=MergeTagsResponse)
async def merge_tags(
    request: MergeTagsRequest,
    tagging_service: Annotated[TaggingService, Depends(get_tagging_service)],
) -> MergeTagsResponse:
    """Merge multiple tags into a canonical tag."""
    try:
        result = await asyncio.to_thread(
            tagging_service.merge_tags,
            source_tag_ids=request.source_tag_ids,
            canonical_tag_id=request.canonical_tag_id,
        )
        return MergeTagsResponse.model_validate(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        logger.exception("[Web API] Error merging tags")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to merge tags"),
        ) from e


@router.post("/split", dependencies=[Depends(verify_session)], response_model=SplitTagResponse)
async def split_tag(
    request: SplitTagRequest,
    tagging_service: Annotated[TaggingService, Depends(get_tagging_service)],
) -> SplitTagResponse:
    """Split selected songs from a tag into a new tag value."""
    try:
        result = await asyncio.to_thread(
            tagging_service.split_tag,
            source_tag_id=request.source_tag_id,
            song_ids=request.song_ids,
            new_value=request.new_value,
        )
        return SplitTagResponse.model_validate(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        logger.exception("[Web API] Error splitting tag")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to split tag"),
        ) from e


@router.get("/value", dependencies=[Depends(verify_session)], response_model=TagListResponse)
async def list_tag_values(
    tagging_service: Annotated[TaggingService, Depends(get_tagging_service)],
    name: Annotated[str | None, Query(description="Filter by tag name (e.g. genre)")] = None,
    prefix: Annotated[str | None, Query(description="Substring search on tag value")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TagListResponse:
    """List tag values with optional filtering and pagination."""
    try:
        result = await asyncio.to_thread(
            tagging_service.list_tag_values,
            name=name,
            prefix=prefix,
            limit=limit,
            offset=offset,
        )
        return TagListResponse.model_validate(result)
    except Exception as e:
        logger.exception("[Web API] Error listing tag values")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to list tag values"),
        ) from e


@router.get("/{tag_id}/song", dependencies=[Depends(verify_session)], response_model=TagSongsResponse)
async def get_tag_songs(
    tag_id: str,
    tagging_service: Annotated[TaggingService, Depends(get_tagging_service)],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TagSongsResponse:
    """Get songs linked to a tag with metadata."""
    try:
        result = await asyncio.to_thread(
            tagging_service.get_tag_songs,
            tag_id=tag_id,
            limit=limit,
            offset=offset,
        )
        return TagSongsResponse.model_validate(result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except Exception as e:
        logger.exception("[Web API] Error getting tag songs")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to get tag songs"),
        ) from e


@router.post("/commit", dependencies=[Depends(verify_session)], response_model=CommitResponse)
async def commit_pending_tags(
    request: CommitRequest,
    tagging_service: Annotated[TaggingService, Depends(get_tagging_service)],
) -> CommitResponse:
    """Commit pending tag writes to files."""
    try:
        result = await asyncio.to_thread(
            tagging_service.commit_pending_tags,
            library_id=request.library_id,
        )
        return CommitResponse.model_validate(result)
    except Exception as e:
        logger.exception("[Web API] Error committing pending tags")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to commit tags"),
        ) from e


@router.get("/pending-count", dependencies=[Depends(verify_session)], response_model=PendingCountResponse)
async def get_pending_commit_count(
    tagging_service: Annotated[TaggingService, Depends(get_tagging_service)],
) -> PendingCountResponse:
    """Get count of files with pending tag writes."""
    try:
        count = await asyncio.to_thread(tagging_service.get_pending_commit_count)
        return PendingCountResponse(count=count)
    except Exception as e:
        logger.exception("[Web API] Error getting pending commit count")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to get pending count"),
        ) from e


@router.patch("/file/{file_id}/tag", dependencies=[Depends(verify_session)], response_model=UpdateFileTagsResponse)
async def update_file_tags(
    file_id: str,
    request: UpdateFileTagsRequest,
    tagging_service: Annotated[TaggingService, Depends(get_tagging_service)],
) -> UpdateFileTagsResponse:
    """Replace all tags for a file+name with new values."""
    try:
        result = await asyncio.to_thread(
            tagging_service.update_song_tags,
            song_id=file_id,
            name=request.name,
            values=request.values,
        )
        return UpdateFileTagsResponse.model_validate(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        logger.exception(f"[Web API] Error updating tags for file {file_id}")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to update file tags"),
        ) from e
