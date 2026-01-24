"""Library statistics and management endpoints for web UI."""

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.id_codec import decode_path_id
from nomarr.interfaces.api.types.library_types import (
    CreateLibraryRequest,
    FileTagsResponse,
    LibraryResponse,
    LibraryStatsResponse,
    ListLibrariesResponse,
    ReconcilePathsResponse,
    ReconcileStatusResponse,
    ReconcileTagsResponse,
    SearchFilesResponse,
    StartScanWithStatusResponse,
    TagCleanupResponse,
    UniqueTagKeysResponse,
    UpdateLibraryRequest,
    UpdateWriteModeResponse,
)
from nomarr.interfaces.api.web.dependencies import get_library_service, get_metadata_service, get_tagging_service

if TYPE_CHECKING:
    from nomarr.services.domain.library_svc import LibraryService
    from nomarr.services.domain.metadata_svc import MetadataService
    from nomarr.services.domain.tagging_svc import TaggingService

router = APIRouter(prefix="/libraries", tags=["Library"])


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("/stats", dependencies=[Depends(verify_session)])
async def web_library_stats(
    library_service: "LibraryService" = Depends(get_library_service),
) -> LibraryStatsResponse:
    """Get library statistics (total files, artists, albums, duration)."""
    try:
        # Use service layer to get library stats (returns LibraryStatsResult DTO)
        stats = library_service.get_library_stats()

        # Transform DTO to Pydantic response
        return LibraryStatsResponse.from_dto(stats)

    except Exception as e:
        logging.exception("[Web API] Error getting library stats")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to get library stats")) from e


# ──────────────────────────────────────────────────────────────────────
# Multi-Library Management Endpoints
# ──────────────────────────────────────────────────────────────────────


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
        logging.exception("[Web API] Error listing libraries")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to list libraries")) from e


@router.get("/default", dependencies=[Depends(verify_session)])
async def get_default_library(
    library_service: "LibraryService" = Depends(get_library_service),
) -> LibraryResponse:
    """Get the default library."""
    try:
        library = library_service.get_default_library()
        if not library:
            raise HTTPException(status_code=404, detail="No default library configured")

        return LibraryResponse.from_dto(library)
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("[Web API] Error getting default library")
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to get default library")
        ) from e


@router.get("/{library_id}", dependencies=[Depends(verify_session)])
async def get_library(
    library_id: str,
    library_service: "LibraryService" = Depends(get_library_service),
) -> LibraryResponse:
    """Get a library by ID."""
    library_id = decode_path_id(library_id)
    try:
        library = library_service.get_library(library_id)
        return LibraryResponse.from_dto(library)
    except ValueError:
        raise HTTPException(status_code=404, detail="Library not found") from None
    except Exception as e:
        logging.exception(f"[Web API] Error getting library {library_id}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to get library")) from e


@router.post("", dependencies=[Depends(verify_session)])
async def create_library(
    request: CreateLibraryRequest,
    library_service: "LibraryService" = Depends(get_library_service),
) -> LibraryResponse:
    """Create a new library."""
    try:
        library = library_service.create_library(
            name=request.name,
            root_path=request.root_path,
            is_enabled=request.is_enabled,
            is_default=request.is_default,
            watch_mode=request.watch_mode,
        )
        return LibraryResponse.from_dto(library)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid library configuration") from None
    except Exception as e:
        logging.exception("[Web API] Error creating library")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to create library")) from e


@router.patch("/{library_id}", dependencies=[Depends(verify_session)])
async def update_library(
    library_id: str,
    request: UpdateLibraryRequest,
    library_service: "LibraryService" = Depends(get_library_service),
) -> LibraryResponse:
    """Update a library's properties."""
    library_id = decode_path_id(library_id)
    try:
        library = library_service.update_library(
            library_id,
            name=request.name,
            root_path=request.root_path,
            is_enabled=request.is_enabled,
            is_default=request.is_default,
            watch_mode=request.watch_mode,
        )
        return LibraryResponse.from_dto(library)

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid library update") from None
    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"[Web API] Error updating library {library_id}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to update library")) from e


@router.post("/{library_id}/set-default", dependencies=[Depends(verify_session)])
async def set_default_library(
    library_id: str,
    library_service: "LibraryService" = Depends(get_library_service),
) -> LibraryResponse:
    """Set a library as the default library."""
    library_id = decode_path_id(library_id)
    try:
        library = library_service.set_default_library(library_id)
        return LibraryResponse.from_dto(library)
    except ValueError:
        raise HTTPException(status_code=404, detail="Library not found") from None
    except Exception as e:
        logging.exception(f"[Web API] Error setting default library {library_id}")
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to set default library")
        ) from e


@router.delete("/{library_id}", dependencies=[Depends(verify_session)])
async def delete_library(
    library_id: str,
    library_service: "LibraryService" = Depends(get_library_service),
) -> dict[str, str]:
    """
    Delete a library.

    Removes the library entry but does NOT delete files on disk.
    Cannot delete the default library - set another as default first.
    """
    library_id = decode_path_id(library_id)
    try:
        deleted = library_service.delete_library(library_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Library not found")
        return {"status": "success", "message": f"Library {library_id} deleted"}
    except ValueError:
        raise HTTPException(status_code=400, detail="Cannot delete library") from None
    except Exception as e:
        logging.exception(f"[Web API] Error deleting library {library_id}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to delete library")) from e


@router.get("/files/search", dependencies=[Depends(verify_session)])
async def search_library_files(
    q: str = Query("", description="Search query for artist/album/title"),
    artist: str | None = Query(None, description="Filter by artist name"),
    album: str | None = Query(None, description="Filter by album name"),
    tag_key: str | None = Query(None, description="Filter by files with this tag key"),
    tag_value: str | None = Query(None, description="Filter by files with tag key=value"),
    tagged_only: bool = Query(False, description="Only show tagged files"),
    limit: int = Query(100, ge=1, le=1000, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    library_service: "LibraryService" = Depends(get_library_service),
) -> SearchFilesResponse:
    """
    Search library files with optional filtering.

    Returns paginated list of files with metadata.
    """
    try:
        # Call service (returns SearchFilesResult DTO)
        result = library_service.search_files(
            q=q,
            artist=artist,
            album=album,
            tag_key=tag_key,
            tag_value=tag_value,
            tagged_only=tagged_only,
            limit=limit,
            offset=offset,
        )

        # Transform DTO to Pydantic response
        return SearchFilesResponse.from_dto(result)

    except Exception as e:
        logging.exception("[Web API] Error searching library files")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to search files")) from e


class FileIdsRequest(BaseModel):
    """Request body for fetching files by IDs."""

    file_ids: list[str] = Field(..., description="List of file _ids to fetch", max_length=500)


@router.post("/files/by-ids", dependencies=[Depends(verify_session)])
async def get_files_by_ids(
    request: FileIdsRequest,
    library_service: "LibraryService" = Depends(get_library_service),
) -> SearchFilesResponse:
    """
    Get files by their IDs with full metadata and tags.

    Used for batch lookup (e.g., when browsing songs for an entity).
    Returns files in same order as input IDs where possible.
    """
    try:
        result = library_service.get_files_by_ids(request.file_ids)
        return SearchFilesResponse.from_dto(result)
    except Exception as e:
        logging.exception("[Web API] Error getting files by IDs")
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
    library_service: "LibraryService" = Depends(get_library_service),
) -> SearchFilesResponse:
    """
    Search files by tag value with distance sorting (float) or exact match (string).

    For float values: Returns files sorted by absolute distance from target value.
    For string values: Returns files with exact match on the tag value.
    """
    try:
        result = library_service.search_files_by_tag(
            tag_key=request.tag_key,
            target_value=request.target_value,
            limit=request.limit,
            offset=request.offset,
        )
        return SearchFilesResponse.from_dto(result)
    except Exception as e:
        logging.exception("[Web API] Error searching files by tag")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to search files")) from e


@router.get("/files/tags/unique-keys", dependencies=[Depends(verify_session)])
async def get_unique_tag_keys(
    nomarr_only: bool = Query(False, description="Only show Nomarr tags"),
    library_service: "LibraryService" = Depends(get_library_service),
) -> UniqueTagKeysResponse:
    """
    Get list of unique tag keys for filtering.

    Returns all distinct tag keys found in the database.
    """
    try:
        # Call service (returns UniqueTagKeysResult DTO)
        result = library_service.get_unique_tag_keys(nomarr_only=nomarr_only)

        # Transform DTO to Pydantic response
        return UniqueTagKeysResponse.from_dto(result)

    except Exception as e:
        logging.exception("[Web API] Error getting unique tag keys")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to get tag keys")) from e


@router.get("/files/tags/values", dependencies=[Depends(verify_session)])
async def get_unique_tag_values(
    tag_key: str = Query(..., description="Tag key to get values for"),
    nomarr_only: bool = Query(True, description="Only show Nomarr tag values"),
    library_service: "LibraryService" = Depends(get_library_service),
) -> UniqueTagKeysResponse:
    """
    Get list of unique values for a specific tag key.

    Returns all distinct values for the given tag key.
    """
    try:
        # Call service (returns UniqueTagKeysResult DTO with values in tag_keys field)
        result = library_service.get_unique_tag_values(tag_key=tag_key, nomarr_only=nomarr_only)

        # Transform DTO to Pydantic response (reusing same structure)
        return UniqueTagKeysResponse.from_dto(result)

    except Exception as e:
        logging.exception("[Web API] Error getting unique tag values")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to get tag values")) from e


@router.post("/cleanup-tags", dependencies=[Depends(verify_session)])
async def cleanup_orphaned_tags(
    dry_run: bool = Query(False, description="Preview orphaned tags without deleting"),
    library_service: "LibraryService" = Depends(get_library_service),
) -> TagCleanupResponse:
    """
    Clean up orphaned tags (tags not referenced by any file).

    This endpoint identifies and removes tags from the library_tags table that are
    no longer referenced by any file in file_tags. Useful for database maintenance
    after deleting files or changing tag structures.

    Args:
        dry_run: If True, only count orphaned tags without deleting them
        library_service: LibraryService instance (injected)

    Returns:
        TagCleanupResponse with orphaned_count and deleted_count
    """
    try:
        # Call service layer to cleanup orphaned tags (returns TagCleanupResult DTO)
        result = library_service.cleanup_orphaned_tags(dry_run=dry_run)

        # Transform DTO to Pydantic response
        return TagCleanupResponse.from_dto(result)

    except Exception as e:
        logging.exception("[Web API] Error cleaning up orphaned tags")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to clean up tags")) from e


@router.post("/cleanup-entities", dependencies=[Depends(verify_session)])
async def cleanup_orphaned_entities(
    dry_run: bool = Query(False, description="Preview orphaned entities without deleting"),
    metadata_service: "MetadataService" = Depends(get_metadata_service),
) -> dict[str, int | dict[str, int]]:
    """
    Clean up orphaned entities (artists, albums, genres, labels, years).

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
        result = metadata_service.cleanup_orphaned_entities(dry_run=dry_run)
        return result

    except Exception as e:
        logging.exception("[Web API] Error cleaning up orphaned entities")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to clean up entities")) from e


@router.get("/files/{file_id}/tags", dependencies=[Depends(verify_session)])
async def get_file_tags(
    file_id: str,
    nomarr_only: bool = Query(False, description="Only return Nomarr-generated tags"),
    library_service: "LibraryService" = Depends(get_library_service),
) -> FileTagsResponse:
    """
    Get all tags for a specific file.

    Returns the complete tag data for a library file, including tag keys,
    values, types, and whether they are Nomarr-generated tags.

    Args:
        file_id: Library file ID to get tags for
        nomarr_only: If True, only return Nomarr-generated tags
        library_service: LibraryService instance (injected)

    Returns:
        FileTagsResponse with file_id, path, and list of tags

    Raises:
        HTTPException: 404 if file not found, 500 for other errors
    """
    file_id = decode_path_id(file_id)
    try:
        # Call service layer to get file tags (returns FileTagsResult DTO)
        result = library_service.get_file_tags(file_id=file_id, nomarr_only=nomarr_only)

        # Transform DTO to Pydantic response
        return FileTagsResponse.from_dto(result)

    except ValueError:
        raise HTTPException(status_code=404, detail="File not found") from None
    except Exception as e:
        logging.exception(f"[Web API] Error getting tags for file {file_id}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to get file tags")) from e


@router.post("/{library_id}/scan", dependencies=[Depends(verify_session)])
async def scan_library(
    library_id: str,
    scan_type: str = Query("quick", description="Scan type: 'quick' (skip unchanged files) or 'full' (rescan all)"),
    library_service: "LibraryService" = Depends(get_library_service),
) -> StartScanWithStatusResponse:
    """
    Start a scan for a specific library.

    This endpoint triggers a scan for the specified library, discovering files
    and enqueuing them for background processing. The scan uses the library's
    root_path and always runs recursively with clean_missing enabled.

    Args:
        library_id: Library ID to scan
        scan_type: Scan mode - 'quick' uses hash-based skipping, 'full' rescans all files
        library_service: LibraryService instance (injected)

    Returns:
        StartScanWithStatusResponse with scan statistics and status message

    Raises:
        HTTPException: 404 if library not found, 400 for invalid scan_type, 500 for other errors
    """
    library_id = decode_path_id(library_id)
    try:
        # Validate scan_type
        if scan_type not in ("quick", "full"):
            raise HTTPException(status_code=400, detail="scan_type must be 'quick' or 'full'")

        force_rescan = scan_type == "full"

        # Call the service layer to start scan for this specific library (returns StartScanResult DTO)
        stats = library_service.start_scan_for_library(library_id=library_id, force_rescan=force_rescan)

        # Transform DTO to wrapped Pydantic response
        return StartScanWithStatusResponse.from_dto(stats, library_id)

    except ValueError:
        raise HTTPException(status_code=404, detail="Library not found") from None
    except Exception as e:
        logging.exception(f"[Web API] Error starting scan for library {library_id}")
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to start library scan")
        ) from e


@router.post("/{library_id}/reconcile", dependencies=[Depends(verify_session)])
async def reconcile_library_paths(
    library_id: str,
    policy: str = Query("mark_invalid", description="Policy for invalid paths: dry_run, mark_invalid, delete_invalid"),
    batch_size: int = Query(1000, description="Number of files to process per batch", ge=1, le=10000),
    library_service: "LibraryService" = Depends(get_library_service),
) -> ReconcilePathsResponse:
    """
    Reconcile library paths after configuration changes.

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
        # Call service layer to reconcile paths (returns ReconcileResult)
        stats = library_service.reconcile_library_paths(
            policy=policy,
            batch_size=batch_size,
        )

        # Transform ReconcileResult to Pydantic response using from_dict
        return ReconcilePathsResponse.from_dict(stats)

    except ValueError as e:
        # Invalid policy or library not found
        error_msg = str(e).lower()
        if "policy" in error_msg:
            raise HTTPException(status_code=400, detail="Invalid reconciliation policy") from None
        raise HTTPException(status_code=404, detail="Library not found") from None
    except Exception as e:
        logging.exception(f"[Web API] Error reconciling paths for library {library_id}")
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to reconcile library paths")
        ) from e


# ──────────────────────────────────────────────────────────────────────
# Tag Writing Reconciliation Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.post("/{library_id}/reconcile-tags", dependencies=[Depends(verify_session)])
async def reconcile_library_tags(
    library_id: str,
    batch_size: int = Query(100, description="Number of files to process per batch", ge=1, le=1000),
    tagging_service: "TaggingService" = Depends(get_tagging_service),
) -> ReconcileTagsResponse:
    """
    Reconcile file tags for a library.

    Writes tags from database to audio files based on the library's file_write_mode.
    This handles:
    - Mode changes (e.g., switching from "full" to "minimal")
    - Calibration updates (new mood tag values)
    - New ML results (files analyzed but never written)

    Args:
        library_id: Library ID to reconcile
        batch_size: Files to process per batch (default: 100)
        tagging_service: TaggingService instance (injected)

    Returns:
        ReconcileTagsResponse with processed, remaining, and failed counts
    """
    library_id = decode_path_id(library_id)
    try:
        result = tagging_service.reconcile_library(library_id=library_id, batch_size=batch_size)
        return ReconcileTagsResponse.from_dto(result)
    except ValueError:
        raise HTTPException(status_code=404, detail="Library not found") from None
    except Exception as e:
        logging.exception(f"[Web API] Error reconciling tags for library {library_id}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to reconcile tags")) from e


@router.get("/{library_id}/reconcile-status", dependencies=[Depends(verify_session)])
async def get_reconcile_status(
    library_id: str,
    tagging_service: "TaggingService" = Depends(get_tagging_service),
) -> ReconcileStatusResponse:
    """
    Get tag reconciliation status for a library.

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
        return ReconcileStatusResponse(
            pending_count=status["pending_count"],
            in_progress=status["in_progress"],
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Library not found") from None
    except Exception as e:
        logging.exception(f"[Web API] Error getting reconcile status for library {library_id}")
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to get reconcile status")
        ) from e


@router.patch("/{library_id}/write-mode", dependencies=[Depends(verify_session)])
async def update_write_mode(
    library_id: str,
    file_write_mode: str = Query(..., description="New write mode: 'none', 'minimal', or 'full'"),
    library_service: "LibraryService" = Depends(get_library_service),
    tagging_service: "TaggingService" = Depends(get_tagging_service),
) -> UpdateWriteModeResponse:
    """
    Update the file write mode for a library.

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

    # Validate mode
    if file_write_mode not in ("none", "minimal", "full"):
        raise HTTPException(
            status_code=400,
            detail="file_write_mode must be 'none', 'minimal', or 'full'",
        )

    try:
        # Update the library
        library_service.update_library(library_id, file_write_mode=file_write_mode)

        # Check if reconciliation is needed
        status = tagging_service.get_reconcile_status(library_id=library_id)

        return UpdateWriteModeResponse(
            file_write_mode=file_write_mode,
            requires_reconciliation=status["pending_count"] > 0,
            affected_file_count=status["pending_count"],
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Library not found") from None
    except Exception as e:
        logging.exception(f"[Web API] Error updating write mode for library {library_id}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to update write mode")) from e
