"""Library statistics and management endpoints for web UI."""

import asyncio
import logging
import threading
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from nomarr.helpers.dto.library_dto import SearchFilesQuery
from nomarr.helpers.exceptions import LibraryAlreadyScanningError, LibraryNotFoundError
from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.id_codec import decode_path_id, encode_id
from nomarr.interfaces.api.types.library_types import (
    CreateLibraryRequest,
    ErroredFileItemResponse,
    ErroredFilesResponse,
    FileTagsResponse,
    LibraryResponse,
    LibraryStatsResponse,
    ListLibrariesResponse,
    ReconcilePathsResponse,
    ReconcileStatusResponse,
    RetryErroredRequest,
    RetryErroredResponse,
    SearchFilesResponse,
    StartScanWithStatusResponse,
    StartTagWriteResponse,
    TagCleanupResponse,
    UniqueTagKeysResponse,
    UpdateLibraryRequest,
    UpdateWriteModeResponse,
    ValidateLibraryTagsResponse,
)
from nomarr.interfaces.api.web.dependencies import (
    get_config_service,
    get_file_watcher_service,
    get_library_service,
    get_metadata_service,
    get_ml_service,
    get_navidrome_service,
    get_tagging_service,
    get_vector_maintenance_service,
)

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.services.domain.library_svc import LibraryService
    from nomarr.services.domain.metadata_svc import MetadataService
    from nomarr.services.domain.navidrome_svc import NavidromeService
    from nomarr.services.domain.tagging_svc import TaggingService
    from nomarr.services.domain.vector_maintenance_svc import VectorMaintenanceService
    from nomarr.services.infrastructure.config_svc import ConfigService
    from nomarr.services.infrastructure.ml_svc import MLService
router = APIRouter(prefix="/libraries", tags=["Library"])


class VectorConfigResponse(BaseModel):
    """Per-library vector configuration with inheritance info."""

    vector_group_size: int
    vector_search_thoroughness: int
    is_group_size_inherited: bool
    is_thoroughness_inherited: bool


class VectorConfigUpdate(BaseModel):
    """Update per-library vector config. Null values clear override (inherit global)."""

    vector_group_size: int | None = None
    vector_search_thoroughness: int | None = None


class VectorStatsItem(BaseModel):
    """Per-backbone vector statistics for a library."""

    backbone_id: str
    hot_count: int
    cold_count: int
    index_exists: bool


class LibraryVectorStatsResponse(BaseModel):
    """Per-library vector statistics across all backbones."""

    library_key: str
    stats: list[VectorStatsItem]


@router.get("/stats", dependencies=[Depends(verify_session)])
async def web_library_stats(
    library_service: Annotated["LibraryService", Depends(get_library_service)],
) -> LibraryStatsResponse:
    """Get library statistics (total files, artists, albums, duration)."""
    try:
        stats = library_service.get_library_stats()
        return LibraryStatsResponse.from_dto(stats)
    except Exception as e:
        logger.exception("[Web API] Error getting library stats")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to get library stats")) from e


@router.get("", dependencies=[Depends(verify_session)])
async def list_libraries(
    enabled_only: bool = False,
    library_service: "LibraryService" = Depends(get_library_service),
) -> ListLibrariesResponse:
    """List all configured libraries."""
    try:
        libraries = library_service.list_libraries(enabled_only=enabled_only)
        return ListLibrariesResponse.from_dto(libraries)
    except Exception as e:
        logger.exception("[Web API] Error listing libraries")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to list libraries")) from e


class RecentFileItem(BaseModel):
    """A recently processed file."""

    file_id: str
    path: str
    title: str | None
    artist: str | None
    album: str | None
    last_tagged_at: int


class RecentFilesResponse(BaseModel):
    """Response for recently processed files."""

    files: list[RecentFileItem]


@router.get("/recent-activity", dependencies=[Depends(verify_session)])
async def web_library_recent_activity(
    library_service: Annotated["LibraryService", Depends(get_library_service)],
    limit: int = Query(default=20, ge=1, le=100, description="Number of recent files to return"),
    library_id: str | None = Query(default=None, description="Optional library ID to filter by"),
) -> RecentFilesResponse:
    """Get recently processed files.

    Returns files sorted by last_tagged_at descending.
    """
    try:
        decoded_library_id = decode_path_id(library_id) if library_id else None
        files = library_service.get_recently_processed(limit=limit, library_id=decoded_library_id)
        return RecentFilesResponse(files=[RecentFileItem(**f) for f in files])
    except Exception as e:
        logger.exception("[Web API] Error getting recent activity")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to get recent activity"),
        ) from e


@router.get("/{library_id}", dependencies=[Depends(verify_session)])
async def get_library(
    library_id: str,
    library_service: Annotated["LibraryService", Depends(get_library_service)],
) -> LibraryResponse:
    """Get a library by ID."""
    library_id = decode_path_id(library_id)
    try:
        library = library_service.get_library(library_id)
        return LibraryResponse.from_dto(library)
    except ValueError:
        raise HTTPException(status_code=404, detail="Library not found") from None
    except Exception as e:
        logger.exception(f"[Web API] Error getting library {library_id}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to get library")) from e


@router.post("", dependencies=[Depends(verify_session)])
async def create_library(
    request: CreateLibraryRequest,
    library_service: Annotated["LibraryService", Depends(get_library_service)],
) -> LibraryResponse:
    """Create a new library."""
    try:
        library = library_service.create_library(
            name=request.name,
            root_path=request.root_path,
            is_enabled=request.is_enabled,
            watch_mode=request.watch_mode,
        )
        return LibraryResponse.from_dto(library)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid library configuration") from None
    except Exception as e:
        logger.exception("[Web API] Error creating library")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to create library")) from e


@router.patch("/{library_id}", dependencies=[Depends(verify_session)])
async def update_library(
    library_id: str,
    request: UpdateLibraryRequest,
    library_service: Annotated["LibraryService", Depends(get_library_service)],
) -> LibraryResponse:
    """Update a library's properties."""
    library_id = decode_path_id(library_id)
    try:
        library = library_service.update_library(
            library_id,
            name=request.name,
            root_path=request.root_path,
            is_enabled=request.is_enabled,
            watch_mode=request.watch_mode,
        )
        return LibraryResponse.from_dto(library)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid library update") from None
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[Web API] Error updating library {library_id}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to update library")) from e


@router.delete("/{library_id}", dependencies=[Depends(verify_session)])
async def delete_library(
    library_id: str,
    library_service: Annotated["LibraryService", Depends(get_library_service)],
) -> dict[str, str]:
    """Delete a library.

    Removes the library entry but does NOT delete files on disk.
    """
    library_id = decode_path_id(library_id)
    try:
        file_watcher = get_file_watcher_service()
        if file_watcher and library_id in file_watcher.observers:
            file_watcher.stop_watching_library(library_id)
            logger.info(f"[Web API] Stopped file watcher for library {library_id}")
        deleted = library_service.delete_library(library_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Library not found")
        return {"status": "success", "message": f"Library {library_id} deleted"}
    except ValueError:
        raise HTTPException(status_code=400, detail="Cannot delete library") from None
    except Exception as e:
        logger.exception(f"[Web API] Error deleting library {library_id}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to delete library")) from e


@router.get("/files/search", dependencies=[Depends(verify_session)])
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


class FileIdsRequest(BaseModel):
    """Request body for fetching files by IDs."""

    file_ids: list[str] = Field(..., description="List of file _ids to fetch", max_length=500)


@router.post("/files/by-ids", dependencies=[Depends(verify_session)])
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


class TagSearchRequest(BaseModel):
    """Request body for searching files by tag value."""

    tag_key: str = Field(..., description="Tag key to search (e.g., 'nom:bpm', 'genre')")
    target_value: float | str = Field(..., description="Target value (float for distance sort, string for exact match)")
    limit: int = Field(100, ge=1, le=500, description="Maximum results")
    offset: int = Field(0, ge=0, description="Pagination offset")


@router.post("/files/by-tag", dependencies=[Depends(verify_session)])
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


@router.get("/files/tags/unique-keys", dependencies=[Depends(verify_session)])
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


@router.get("/files/tags/values", dependencies=[Depends(verify_session)])
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


@router.get("/files/tags/mood-values", dependencies=[Depends(verify_session)])
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


@router.post("/cleanup-tags", dependencies=[Depends(verify_session)])
async def cleanup_orphaned_tags(
    dry_run: Annotated[bool, Query(description="Preview orphaned tags without deleting")] = False,
    tagging_service: "TaggingService" = Depends(get_tagging_service),
) -> TagCleanupResponse:
    """Clean up orphaned tags (tags not referenced by any file).

    This endpoint identifies and removes tags from the tags collection that are
    no longer referenced by any file via song_has_tags. Useful for database maintenance
    after deleting files or changing tag structures.

    Args:
        dry_run: If True, only count orphaned tags without deleting them
        tagging_service: TaggingService instance (injected)

    Returns:
        TagCleanupResponse with orphaned_count and deleted_count

    """
    try:
        result = tagging_service.cleanup_orphaned_tags(dry_run=dry_run)
        return TagCleanupResponse.from_dto(result)
    except Exception as e:
        logger.exception("[Web API] Error cleaning up orphaned tags")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to clean up tags")) from e


@router.post("/cleanup-entities", dependencies=[Depends(verify_session)])
async def cleanup_orphaned_entities(
    dry_run: Annotated[bool, Query(description="Preview orphaned entities without deleting")] = False,
    metadata_service: "MetadataService" = Depends(get_metadata_service),
) -> dict[str, int | dict[str, int]]:
    """Clean up orphaned entities (artists, albums, genres, labels, years).

    Entities become orphaned when:
    - Songs are deleted from the library
    - Song metadata is updated to reference different entities

    This endpoint identifies and removes entity vertices that have no incoming
    edges from songs. Useful for database maintenance after library changes.

    Args:
        dry_run: If True, only count orphaned entities without deleting them
        metadata_service: MetadataService instance (injected)

    Returns:
        Dict with orphaned_counts, deleted_counts, total_orphaned, total_deleted

    """
    try:
        return metadata_service.cleanup_orphaned_entities(dry_run=dry_run)
    except Exception as e:
        logger.exception("[Web API] Error cleaning up orphaned entities")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to clean up entities")) from e


@router.get("/files/{file_id}/tags", dependencies=[Depends(verify_session)])
async def get_file_tags(
    file_id: str,
    nomarr_only: Annotated[bool, Query(description="Only return Nomarr-generated tags")] = False,
    tagging_service: "TaggingService" = Depends(get_tagging_service),
) -> FileTagsResponse:
    """Get all tags for a specific file.

    Returns the complete tag data for a library file, including tag keys,
    values, types, and whether they are Nomarr-generated tags.

    Args:
        file_id: Library file ID to get tags for
        nomarr_only: If True, only return Nomarr-generated tags
        tagging_service: TaggingService instance (injected)

    Returns:
        FileTagsResponse with file_id, path, and list of tags

    Raises:
        HTTPException: 404 if file not found, 500 for other errors

    """
    file_id = decode_path_id(file_id)
    try:
        result = tagging_service.get_file_tags(file_id=file_id, nomarr_only=nomarr_only)
        return FileTagsResponse.from_dto(result)
    except ValueError:
        raise HTTPException(status_code=404, detail="File not found") from None
    except Exception as e:
        logger.exception(f"[Web API] Error getting tags for file {file_id}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to get file tags")) from e


@router.post("/{library_id}/scan/quick", dependencies=[Depends(verify_session)])
async def scan_library_quick(
    library_id: str,
    library_service: "LibraryService" = Depends(get_library_service),
) -> StartScanWithStatusResponse:
    """Start a quick scan for a specific library.

    Discovers new files and skips unchanged files based on hash comparison.

    Args:
        library_id: Library ID to scan
        library_service: LibraryService instance (injected)

    Returns:
        StartScanWithStatusResponse with scan statistics and status message

    Raises:
        HTTPException: 404 if library not found, 409 if already scanning, 500 for other errors

    """
    library_id = decode_path_id(library_id)
    try:
        stats = library_service.start_quick_scan(library_id=library_id)
        return StartScanWithStatusResponse.from_dto(stats, library_id)
    except LibraryNotFoundError:
        raise HTTPException(status_code=404, detail="Library not found") from None
    except LibraryAlreadyScanningError:
        raise HTTPException(status_code=409, detail="Library is already being scanned") from None
    except Exception as e:
        logger.exception(f"[Web API] Error starting quick scan for library {library_id}")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to start library scan"),
        ) from e


@router.post("/{library_id}/scan/full", dependencies=[Depends(verify_session)])
async def scan_library_full(
    library_id: str,
    library_service: "LibraryService" = Depends(get_library_service),
) -> StartScanWithStatusResponse:
    """Start a full scan for a specific library.

    Rescans all files regardless of hash state.

    Args:
        library_id: Library ID to scan
        library_service: LibraryService instance (injected)

    Returns:
        StartScanWithStatusResponse with scan statistics and status message

    Raises:
        HTTPException: 404 if library not found, 409 if already scanning, 500 for other errors

    """
    library_id = decode_path_id(library_id)
    try:
        stats = library_service.start_full_scan(library_id=library_id)
        return StartScanWithStatusResponse.from_dto(stats, library_id)
    except LibraryNotFoundError:
        raise HTTPException(status_code=404, detail="Library not found") from None
    except LibraryAlreadyScanningError:
        raise HTTPException(status_code=409, detail="Library is already being scanned") from None
    except Exception as e:
        logger.exception(f"[Web API] Error starting full scan for library {library_id}")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to start library scan"),
        ) from e


@router.post("/{library_id}/reconcile", dependencies=[Depends(verify_session)])
async def reconcile_library_paths(
    library_id: str,
    policy: Annotated[
        str,
        Query(description="Policy for invalid paths: dry_run, mark_invalid, delete_invalid"),
    ] = "mark_invalid",
    batch_size: Annotated[int, Query(description="Number of files to process per batch", ge=1, le=10000)] = 1000,
    library_service: "LibraryService" = Depends(get_library_service),
) -> ReconcilePathsResponse:
    """Reconcile library paths after configuration changes.

    Re-validates all file paths in the specified library and handles invalid paths
    according to the specified policy. Useful after changing library root_path or
    when files have been moved/deleted outside of Nomarr.

    Policies:
    - dry_run: Only report invalid paths, make no changes
    - mark_invalid: Update file records with invalid status
    - delete_invalid: Remove invalid file records from database

    Args:
        library_id: Library ID to reconcile
        policy: How to handle invalid paths (default: mark_invalid)
        batch_size: Files to process per batch (default: 1000)
        library_service: LibraryService instance (injected)

    Returns:
        ReconcilePathsResponse with reconciliation statistics

    Raises:
        HTTPException: 404 if library not found, 400 for invalid policy, 500 for other errors

    """
    library_id = decode_path_id(library_id)
    try:
        stats = await asyncio.to_thread(library_service.reconcile_library_paths, policy=policy, batch_size=batch_size)
        return ReconcilePathsResponse.from_dict(stats)
    except ValueError as e:
        error_message = str(e).lower()
        if "policy" in error_message:
            raise HTTPException(status_code=400, detail="Invalid reconciliation policy") from None
        raise HTTPException(status_code=404, detail="Library not found") from None
    except Exception as e:
        logger.exception(f"[Web API] Error reconciling paths for library {library_id}")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to reconcile library paths"),
        ) from e


@router.post("/{library_id}/reconcile-tags", dependencies=[Depends(verify_session)], status_code=202)
async def reconcile_library_tags(
    library_id: str,
    tagging_service: "TaggingService" = Depends(get_tagging_service),
    navidrome_service: "NavidromeService" = Depends(get_navidrome_service),
) -> StartTagWriteResponse:
    """Reconcile file tags for a library.

    Starts background tag writes from database to audio files based on the
    library's file_write_mode.

    This handles:
    - Mode changes (e.g., switching from "full" to "minimal")
    - Calibration updates (new mood tag values)
    - New ML results (files analyzed but never written)

    Args:
        library_id: Library ID to reconcile
        tagging_service: TaggingService instance (injected)
        navidrome_service: NavidromeService instance (injected)

    Returns:
        StartTagWriteResponse with background task status and task id

    """
    library_id = decode_path_id(library_id)
    try:
        stop_event = threading.Event()

        def trigger_navidrome_rescan() -> None:
            navidrome_service.trigger_rescan()

        task_id = tagging_service.start_write_tags_background(
            library_id,
            stop_event=stop_event,
            on_complete=trigger_navidrome_rescan,
        )
        return StartTagWriteResponse(status="started", task_id=task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Library not found") from None
    except Exception as e:
        logger.exception(f"[Web API] Error reconciling tags for library {library_id}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to reconcile tags")) from e


@router.get("/{library_id}/reconcile-status", dependencies=[Depends(verify_session)])
async def get_reconcile_status(
    library_id: str,
    tagging_service: Annotated["TaggingService", Depends(get_tagging_service)],
) -> ReconcileStatusResponse:
    """Get tag reconciliation status for a library.

    Returns the count of files needing reconciliation and whether
    a reconciliation operation is currently in progress.

    Args:
        library_id: Library ID to check
        tagging_service: TaggingService instance (injected)

    Returns:
        ReconcileStatusResponse with pending_count and in_progress status

    """
    library_id = decode_path_id(library_id)
    try:
        status = tagging_service.get_reconcile_status(library_id=library_id)
        return ReconcileStatusResponse(pending_count=status["pending_count"], in_progress=status["in_progress"])
    except ValueError:
        raise HTTPException(status_code=404, detail="Library not found") from None
    except Exception as e:
        logger.exception(f"[Web API] Error getting reconcile status for library {library_id}")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to get reconcile status"),
        ) from e


@router.patch("/{library_id}/write-mode", dependencies=[Depends(verify_session)])
async def update_write_mode(
    library_id: str,
    file_write_mode: Annotated[str, Query(description="New write mode: 'none', 'minimal', or 'full'")],
    library_service: Annotated["LibraryService", Depends(get_library_service)],
    tagging_service: Annotated["TaggingService", Depends(get_tagging_service)],
) -> UpdateWriteModeResponse:
    """Update the file write mode for a library.

    Changes how tags are written to audio files:
    - 'none': Remove all essentia:* tags
    - 'minimal': Only mood-tier tags (mood-strict, mood-regular, mood-loose)
    - 'full': All available tags from DB

    Returns information about whether reconciliation is needed.

    Args:
        library_id: Library ID to update
        file_write_mode: New write mode
        library_service: LibraryService instance (injected)
        tagging_service: TaggingService instance (injected)

    Returns:
        UpdateWriteModeResponse with mode, requires_reconciliation, and affected_file_count

    """
    library_id = decode_path_id(library_id)
    if file_write_mode not in ("none", "minimal", "full"):
        raise HTTPException(status_code=400, detail="file_write_mode must be 'none', 'minimal', or 'full'")
    try:
        library_service.update_library(library_id, file_write_mode=file_write_mode)
        tagging_service.mark_tags_stale(library_id)
        status = tagging_service.get_reconcile_status(library_id=library_id)
        return UpdateWriteModeResponse(
            file_write_mode=file_write_mode,
            requires_reconciliation=status["pending_count"] > 0,
            affected_file_count=status["pending_count"],
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Library not found") from None
    except Exception as e:
        logger.exception(f"[Web API] Error updating write mode for library {library_id}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to update write mode")) from e


@router.post("/{library_id}/validate-tags", dependencies=[Depends(verify_session)])
async def validate_library_tags(
    library_id: str,
    auto_repair: Annotated[bool, Query(description="Auto-repair incomplete files by marking for re-tagging")] = True,
    library_service: "LibraryService" = Depends(get_library_service),
) -> ValidateLibraryTagsResponse:
    """Validate tag completeness for a library's files.

    Checks that every file marked as tagged has edges for all discovered
    ML heads. Optionally auto-repairs incomplete files by marking them
    for re-tagging on the next scan.

    Args:
        library_id: Library ID to validate
        auto_repair: If true, mark incomplete files for re-tagging
        library_service: LibraryService instance (injected)

    Returns:
        ValidateLibraryTagsResponse with validation summary

    """
    library_id = decode_path_id(library_id)
    try:
        result = library_service.validate_library_tags(library_id=library_id, auto_repair=auto_repair)
        return ValidateLibraryTagsResponse(
            files_checked=result["files_checked"],
            complete_files=result["complete_files"],
            incomplete_files=result["incomplete_files"],
            files_repaired=result["files_repaired"],
            expected_heads=result["expected_heads"],
            missing_rels_summary=result.get("missing_rels_summary", {}),
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Library not found") from None
    except Exception as e:
        logger.exception(f"[Web API] Error validating tags for library {library_id}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to validate tags")) from e


@router.get("/{library_id}/vector-config", dependencies=[Depends(verify_session)])
async def get_library_vector_config(
    library_id: str,
    library_service: Annotated["LibraryService", Depends(get_library_service)],
    config_service: Annotated["ConfigService", Depends(get_config_service)],
) -> VectorConfigResponse:
    """Get effective vector configuration for a library.

    Returns the resolved vector_group_size and vector_search_thoroughness,
    along with flags indicating whether each value is inherited from the
    global default or overridden at the library level.

    Args:
        library_id: Library ID to query
        library_service: LibraryService instance (injected)
        config_service: ConfigService instance (injected)

    Returns:
        VectorConfigResponse with effective values and inheritance flags

    """
    library_id = decode_path_id(library_id)
    try:
        result = library_service.get_vector_config(library_id, config_service)
        return VectorConfigResponse(**result)
    except ValueError:
        raise HTTPException(status_code=404, detail="Library not found") from None


@router.put("/{library_id}/vector-config", dependencies=[Depends(verify_session)])
async def update_library_vector_config(
    library_id: str,
    request: VectorConfigUpdate,
    library_service: Annotated["LibraryService", Depends(get_library_service)],
    config_service: Annotated["ConfigService", Depends(get_config_service)],
) -> VectorConfigResponse:
    """Update per-library vector configuration.

    Non-null values are validated and stored on the library document.
    Null values clear the per-library override so the global default is used.

    Args:
        library_id: Library ID to update
        request: VectorConfigUpdate with optional overrides
        library_service: LibraryService instance (injected)
        config_service: ConfigService instance (injected)

    Returns:
        VectorConfigResponse with updated effective values

    """
    library_id = decode_path_id(library_id)
    try:
        library_service.update_vector_config(
            library_id,
            vector_group_size=request.vector_group_size,
            vector_search_thoroughness=request.vector_search_thoroughness,
        )
        result = library_service.get_vector_config(library_id, config_service)
        return VectorConfigResponse(**result)
    except ValueError as e:
        detail = str(e)
        status = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=status, detail=detail) from None


@router.get("/{library_id}/vector-stats", dependencies=[Depends(verify_session)])
async def get_library_vector_stats(
    library_id: str,
    library_service: Annotated["LibraryService", Depends(get_library_service)],
    ml_service: Annotated["MLService", Depends(get_ml_service)],
    vector_maintenance_service: Annotated["VectorMaintenanceService", Depends(get_vector_maintenance_service)],
) -> LibraryVectorStatsResponse:
    """Get per-library vector statistics across all backbones.

    Returns hot/cold vector counts and index status for every discovered
    backbone in the given library.

    Args:
        library_id: Library ID to query
        library_service: LibraryService instance (injected)
        ml_service: MLService instance (injected)
        vector_maintenance_service: VectorMaintenanceService instance (injected)

    Returns:
        LibraryVectorStatsResponse with per-backbone stats

    """
    library_id = decode_path_id(library_id)
    try:
        library = library_service.get_library(library_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Library not found") from None

    library_key = library._key
    stats: list[VectorStatsItem] = []
    for backbone_id in ml_service.list_backbones():
        try:
            s = vector_maintenance_service.get_hot_cold_stats(backbone_id, library_key)
            stats.append(
                VectorStatsItem(
                    backbone_id=backbone_id,
                    hot_count=int(s["hot_count"]),
                    cold_count=int(s["cold_count"]),
                    index_exists=bool(s["index_exists"]),
                )
            )
        except Exception:
            logger.debug("Failed to get vector stats for backbone %s, library %s", backbone_id, library_key)
            continue

    return LibraryVectorStatsResponse(library_key=library_key, stats=stats)


@router.get("/{library_id}/errored-files", dependencies=[Depends(verify_session)])
async def get_errored_files(
    library_id: str,
    library_service: "LibraryService" = Depends(get_library_service),
) -> ErroredFilesResponse:
    """Get errored files for a library.

    Returns files that failed ML processing and are currently in the errored state.

    Args:
        library_id: Library ID to query
        library_service: LibraryService instance (injected)

    Returns:
        ErroredFilesResponse with list of errored files and total count

    """
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
    """Retry errored files by clearing their errored state and re-queuing for tagging.

    Optionally accepts a list of file IDs to retry selectively. If no file IDs
    are provided, all errored files in the library are retried.

    Args:
        library_id: Library ID to retry errored files for
        request: Optional request body with file_ids to retry selectively
        library_service: LibraryService instance (injected)

    Returns:
        RetryErroredResponse with count of retried files

    """
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
            status_code=500, detail=sanitize_exception_message(e, "Failed to retry errored files")
        ) from e
