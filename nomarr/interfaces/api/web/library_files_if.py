"""Library file and tag endpoints for the web UI."""

import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from nomarr.helpers.dto.library_dto import SearchFilesQuery
from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.id_codec import decode_path_id, encode_id
from nomarr.interfaces.api.types.library_types import (
    ErroredFileItemResponse,
    ErroredFilesResponse,
    FileTagsResponse,
    RetryErroredRequest,
    RetryErroredResponse,
    SearchFilesResponse,
    TagCleanupResponse,
    UniqueTagKeysResponse,
)
from nomarr.interfaces.api.web.dependencies import get_library_service, get_tagging_service

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.services.domain.library_svc import LibraryService
    from nomarr.services.domain.tagging_svc import TaggingService

router = APIRouter(prefix="/library", tags=["Library"])


class FileIdsRequest(BaseModel):
    """Request body for fetching files by IDs."""

    file_ids: list[str] = Field(..., description="List of file _ids to fetch", max_length=500)


class TagSearchRequest(BaseModel):
    """Request body for searching files by tag value."""

    tag_key: str = Field(..., description="Tag key to search (e.g., 'nom:bpm', 'genre')")
    target_value: float | str = Field(..., description="Target value (float for distance sort, string for exact match)")
    limit: int = Field(100, ge=1, le=500, description="Maximum results")
    offset: int = Field(0, ge=0, description="Pagination offset")


@router.get("/file/search", dependencies=[Depends(verify_session)])
async def search_library_files(
    q: Annotated[str, Query(description="Search query for artist/album/title")] = "",
    artist: Annotated[str | None, Query(description="Filter by artist name")] = None,
    album: Annotated[str | None, Query(description="Filter by album name")] = None,
    tag_key: Annotated[str | None, Query(description="Filter by files with this tag key")] = None,
    tag_value: Annotated[str | None, Query(description="Filter by files with tag key=value")] = None,
    tagged_only: Annotated[bool, Query(description="Only show tagged files")] = False,
    limit: Annotated[int, Query(ge=1, le=1000, description="Max results")] = 100,
    offset: Annotated[int, Query(ge=0, description="Pagination offset")] = 0,
    library_service: "LibraryService" = Depends(get_library_service),
) -> SearchFilesResponse:
    """Search library files with optional filtering.

    Returns paginated list of files with metadata.
    """
    try:
        query = SearchFilesQuery(
            query_text=q,
            artist=artist,
            album=album,
            tag_key=tag_key,
            tag_value=tag_value,
            tagged_only=tagged_only,
            limit=limit,
            offset=offset,
        )
        result = library_service.search_files(query)
        return SearchFilesResponse.from_dto(result)
    except Exception as e:
        logger.exception("[Web API] Error searching library files")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to search files")) from e


@router.post("/file/by-ids", dependencies=[Depends(verify_session)])
async def get_files_by_ids(
    request: FileIdsRequest,
    library_service: Annotated["LibraryService", Depends(get_library_service)],
) -> SearchFilesResponse:
    """Get files by their IDs with full metadata and tags.

    Used for batch lookup (e.g., when browsing songs for an entity).
    Returns files in same order as input IDs where possible.

    Note: file_ids should be encoded (colon-separated), they will be decoded
    before querying the database.
    """
    try:
        decoded_ids = [decode_path_id(fid) for fid in request.file_ids]
        result = library_service.get_files_by_ids(decoded_ids)
        return SearchFilesResponse.from_dto(result)
    except Exception as e:
        logger.exception("[Web API] Error getting files by IDs")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to get files")) from e


@router.post("/file/by-tag", dependencies=[Depends(verify_session)])
async def search_files_by_tag(
    request: TagSearchRequest,
    tagging_service: Annotated["TaggingService", Depends(get_tagging_service)],
) -> SearchFilesResponse:
    """Search files by tag value with distance sorting (float) or exact match (string).

    For float values: Returns files sorted by absolute distance from target value.
    For string values: Returns files with exact match on the tag value.
    """
    try:
        result = tagging_service.search_files_by_tag(
            tag_key=request.tag_key,
            target_value=request.target_value,
            limit=request.limit,
            offset=request.offset,
        )
        return SearchFilesResponse.from_dto(result)
    except Exception as e:
        logger.exception("[Web API] Error searching files by tag")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to search files")) from e


@router.get("/file/tag/unique-keys", dependencies=[Depends(verify_session)])
async def get_unique_tag_keys(
    nomarr_only: Annotated[bool, Query(description="Only show Nomarr tags")] = False,
    tagging_service: "TaggingService" = Depends(get_tagging_service),
) -> UniqueTagKeysResponse:
    """Get list of unique tag keys for filtering.

    Returns all distinct tag keys found in the database.
    """
    try:
        result = tagging_service.get_unique_tag_keys(nomarr_only=nomarr_only)
        return UniqueTagKeysResponse.from_dto(result)
    except Exception as e:
        logger.exception("[Web API] Error getting unique tag keys")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to get tag keys")) from e


@router.get("/file/tag/values", dependencies=[Depends(verify_session)])
async def get_unique_tag_values(
    tag_key: Annotated[str, Query(description="Tag key to get values for")],
    nomarr_only: Annotated[bool, Query(description="Only show Nomarr tag values")] = True,
    tagging_service: "TaggingService" = Depends(get_tagging_service),
) -> UniqueTagKeysResponse:
    """Get list of unique values for a specific tag key.

    Returns all distinct values for the given tag key.
    """
    try:
        result = tagging_service.get_unique_tag_values(tag_key=tag_key, nomarr_only=nomarr_only)
        return UniqueTagKeysResponse.from_dto(result)
    except Exception as e:
        logger.exception("[Web API] Error getting unique tag values")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to get tag values")) from e


@router.get("/file/tag/mood-values", dependencies=[Depends(verify_session)])
async def get_unique_mood_values(
    mood_tier: Annotated[str, Query(description="Mood tier (mood-strict, mood-regular, mood-loose)")] = "mood-strict",
    limit: Annotated[int, Query(description="Maximum values to return")] = 100,
    tagging_service: "TaggingService" = Depends(get_tagging_service),
) -> UniqueTagKeysResponse:
    """Get unique individual mood values from tuple string tags.

    Parses mood tags stored as tuple strings like "('aggressive', 'party-like')"
    and extracts individual mood terms.

    Returns:
        List of unique mood values (e.g., ["aggressive", "happy", "party-like"])
    """
    try:
        result = tagging_service.get_unique_mood_values(mood_tier=mood_tier, limit=limit)
        return UniqueTagKeysResponse.from_dto(result)
    except Exception as e:
        logger.exception("[Web API] Error getting unique mood values")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to get mood values")) from e


@router.post("/cleanup-tag", dependencies=[Depends(verify_session)])
async def cleanup_orphaned_tags(
    dry_run: Annotated[bool, Query(description="Preview orphaned tags without deleting")] = False,
    tagging_service: "TaggingService" = Depends(get_tagging_service),
) -> TagCleanupResponse:
    """Clean up orphaned tags (tags not referenced by any file).

    This endpoint identifies and removes tags from the tags collection that are
    no longer referenced by any file via song_has_tags. Useful for database maintenance
    after deleting files or changing tag structures.
    """
    try:
        result = tagging_service.cleanup_orphaned_tags(dry_run=dry_run)
        return TagCleanupResponse.from_dto(result)
    except Exception as e:
        logger.exception("[Web API] Error cleaning up orphaned tags")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to clean up tags")) from e


@router.get("/file/{file_id}/tag", dependencies=[Depends(verify_session)])
async def get_file_tags(
    file_id: str,
    nomarr_only: Annotated[bool, Query(description="Only return Nomarr-generated tags")] = False,
    tagging_service: "TaggingService" = Depends(get_tagging_service),
) -> FileTagsResponse:
    """Get all tags for a specific file."""
    file_id = decode_path_id(file_id)
    try:
        result = tagging_service.get_file_tags(file_id=file_id, nomarr_only=nomarr_only)
        return FileTagsResponse.from_dto(result)
    except ValueError:
        raise HTTPException(status_code=404, detail="File not found") from None
    except Exception as e:
        logger.exception(f"[Web API] Error getting tags for file {file_id}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to get file tags")) from e


@router.get("/{library_id}/errored-file", dependencies=[Depends(verify_session)])
async def get_errored_files(
    library_id: str,
    library_service: "LibraryService" = Depends(get_library_service),
) -> ErroredFilesResponse:
    """Get errored files for a library."""
    library_id = decode_path_id(library_id)
    try:
        result = library_service.get_errored_files(library_id=library_id)
        return ErroredFilesResponse(
            files=[
                ErroredFileItemResponse(
                    file_id=encode_id(f["_id"]),
                    path=f["path"],
                    duration_seconds=f["duration_seconds"],
                    artist=f["artist"],
                    title=f["title"],
                )
                for f in result["files"]
            ],
            total=result["total"],
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Library not found") from None
    except Exception as e:
        logger.exception(f"[Web API] Error getting errored files for library {library_id}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to get errored files")) from e


@router.post("/{library_id}/retry-errored", dependencies=[Depends(verify_session)])
async def retry_errored_files(
    library_id: str,
    request: RetryErroredRequest | None = None,
    library_service: "LibraryService" = Depends(get_library_service),
) -> RetryErroredResponse:
    """Retry errored files by clearing their errored state and re-queuing for tagging."""
    library_id = decode_path_id(library_id)
    file_ids = [decode_path_id(fid) for fid in request.file_ids] if request and request.file_ids else None
    try:
        result = library_service.retry_errored_files(library_id=library_id, file_ids=file_ids)
        return RetryErroredResponse(retried=result["retried"])
    except ValueError:
        raise HTTPException(status_code=404, detail="Library not found") from None
    except Exception as e:
        logger.exception(f"[Web API] Error retrying errored files for library {library_id}")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to retry errored files"),
        ) from e
