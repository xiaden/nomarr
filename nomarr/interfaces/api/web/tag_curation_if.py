"""Tag curation endpoints for web UI."""

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef
from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.helpers.tag_handle_codec import TagHandleError, decode_tag_handle, encode_tag_handle
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.id_codec import decode_library_name, decode_song_locator_or_400
from nomarr.interfaces.api.web.dependencies import get_library_service, get_tagging_service
from nomarr.services.domain.library_svc import LibraryService
from nomarr.services.domain.tagging_svc import (
    TaggingService,  # FastAPI resolves Annotated[...] at route registration
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tag-curation", tags=["Tag Curation"])


async def _resolve_optional_library(
    library_service: LibraryService,
    raw_name: str | None,
):
    """Resolve an optional URL-encoded natural library name to a domain ``Library``.

    Returns ``None`` when absent/blank (global scope) or when the library does
    not exist.
    """
    if not raw_name:
        return None
    name = decode_library_name(raw_name)
    return await asyncio.to_thread(library_service.get_library_by_name, name)


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
    tag_type: str
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
    """Rename a tag to a new value.

    ``request.tag_id`` is an opaque complete-``TagRef`` handle. The interface
    owns HTTP decoding: it decodes the handle to a ``TagRef`` before the service
    call. A malformed handle raises :class:`TagHandleError` (a ``ValueError``),
    mapping to the same 400 policy as curation validation.
    """
    try:
        source_tag = decode_tag_handle(request.tag_id)
        result = await asyncio.to_thread(
            tagging_service.rename_tag,
            source_tag=source_tag,
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
    """Merge multiple tags into a canonical tag.

    ``source_tag_ids``/``canonical_tag_id`` are opaque complete-``TagRef``
    handles decoded to ``TagRef`` values at the HTTP boundary before the service
    call. Malformed handles map to 400 (same policy as curation validation).
    """
    try:
        source_tags = [decode_tag_handle(s) for s in request.source_tag_ids]
        canonical_tag = decode_tag_handle(request.canonical_tag_id)
        result = await asyncio.to_thread(
            tagging_service.merge_tags,
            source_tags=source_tags,
            canonical_tag=canonical_tag,
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
    """Split selected songs from a tag into a new tag value.

    ``request.source_tag_id`` is an opaque complete-``TagRef`` handle decoded to
    a ``TagRef`` at the HTTP boundary before the service call. Malformed
    handles map to 400 (same policy as curation validation).
    """
    try:
        source_tag = decode_tag_handle(request.source_tag_id)
        result = await asyncio.to_thread(
            tagging_service.split_tag,
            source_tag=source_tag,
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
    """List tag values with optional filtering and pagination.

    Each listed ``id`` is an opaque complete-``TagRef`` handle encoded here at
    the HTTP boundary from the complete natural identity (``name``, ``value``,
    ``namespace``) the service projected, so two tags with identical
    (name, value) in different namespaces remain distinct. Public response
    fields stay ``id``/``name``/``value``/``song_count``; no persistence key or
    TagRef-internal field is exposed.
    """
    try:
        result = await asyncio.to_thread(
            tagging_service.list_tag_values,
            name=name,
            prefix=prefix,
            limit=limit,
            offset=offset,
        )
        tags = [
            TagValueItemResponse(
                id=encode_tag_handle(TagRef(name=t["name"], value=t["value"], namespace=t.get("namespace", "default"))),
                name=t["name"],
                value=t["value"],
                song_count=t["song_count"],
            )
            for t in result["tags"]
        ]
        return TagListResponse(tags=tags, total=result["total"])
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
    """Get songs linked to a tag with metadata.

    The path ``tag_id`` is an opaque complete-``TagRef`` handle. The interface
    owns HTTP decoding: it decodes the handle to a ``TagRef`` before the query
    service call. A malformed handle maps to 400 (malformed input); a service
    ValueError (e.g. a not-found identity surfaced by the service) maps to the
    route's existing 404 branch.
    """
    try:
        identity = decode_tag_handle(tag_id)
        result = await asyncio.to_thread(
            tagging_service.get_tag_songs,
            identity=identity,
            limit=limit,
            offset=offset,
        )
        return TagSongsResponse.model_validate(result)
    except TagHandleError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
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
    library_service: Annotated[
        "LibraryService", Depends(get_library_service)
    ],  # LibraryService is a RUNTIME import above (not TYPE_CHECKING-only), so
    #  FastAPI can resolve this Annotated dependency when it analyzes routes at
    #  registration. Keep the runtime import; the quoted form is equivalent to
    #  the unquoted form here and neither is what fixes the 3 TestCommitPendingTags
    #  422s — the runtime-resolvable import is.
) -> CommitResponse:
    """Commit pending tag writes to files."""
    try:
        library = await _resolve_optional_library(library_service, request.library_id)
        result = await asyncio.to_thread(
            tagging_service.commit_pending_tags,
            library=library,
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
    # Boundary validation gate mirroring songs_if GET /file/{file_id}/tag: reject
    # malformed/non-canonical SongLocator tokens with 400 before reaching the
    # service. The opaque token is forwarded to the service, which echoes it
    # verbatim into the response.
    decode_song_locator_or_400(file_id)
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
