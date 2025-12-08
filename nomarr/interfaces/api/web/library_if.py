"""Library statistics and management endpoints for web UI."""

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.types.library_types import (
    CreateLibraryRequest,
    LibraryResponse,
    LibraryStatsResponse,
    ListLibrariesResponse,
    ScanLibraryRequest,
    SearchFilesResponse,
    StartScanWithStatusResponse,
    UniqueTagKeysResponse,
    UpdateLibraryRequest,
)
from nomarr.interfaces.api.web.dependencies import get_library_service

if TYPE_CHECKING:
    from nomarr.services.domain.library_svc import LibraryService

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
        raise HTTPException(status_code=500, detail=f"Error getting library stats: {e}") from e


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
        raise HTTPException(status_code=500, detail=f"Error listing libraries: {e}") from e


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
        raise HTTPException(status_code=500, detail=f"Error getting default library: {e}") from e


@router.get("/{library_id}", dependencies=[Depends(verify_session)])
async def get_library(
    library_id: int,
    library_service: "LibraryService" = Depends(get_library_service),
) -> LibraryResponse:
    """Get a library by ID."""
    try:
        library = library_service.get_library(library_id)
        return LibraryResponse.from_dto(library)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logging.exception(f"[Web API] Error getting library {library_id}")
        raise HTTPException(status_code=500, detail=f"Error getting library: {e}") from e


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
        )
        return LibraryResponse.from_dto(library)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logging.exception("[Web API] Error creating library")
        raise HTTPException(status_code=500, detail=f"Error creating library: {e}") from e


@router.patch("/{library_id}", dependencies=[Depends(verify_session)])
async def update_library(
    library_id: int,
    request: UpdateLibraryRequest,
    library_service: "LibraryService" = Depends(get_library_service),
) -> LibraryResponse:
    """Update a library's properties."""
    try:
        library = library_service.update_library(
            library_id,
            name=request.name,
            root_path=request.root_path,
            is_enabled=request.is_enabled,
            is_default=request.is_default,
        )
        return LibraryResponse.from_dto(library)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"[Web API] Error updating library {library_id}")
        raise HTTPException(status_code=500, detail=f"Error updating library: {e}") from e


@router.post("/{library_id}/set-default", dependencies=[Depends(verify_session)])
async def set_default_library(
    library_id: int,
    library_service: "LibraryService" = Depends(get_library_service),
) -> LibraryResponse:
    """Set a library as the default library."""
    try:
        library = library_service.set_default_library(library_id)
        return LibraryResponse.from_dto(library)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logging.exception(f"[Web API] Error setting default library {library_id}")
        raise HTTPException(status_code=500, detail=f"Error setting default library: {e}") from e


@router.delete("/{library_id}", dependencies=[Depends(verify_session)])
async def delete_library(
    library_id: int,
    library_service: "LibraryService" = Depends(get_library_service),
) -> dict[str, str]:
    """
    Delete a library.

    Removes the library entry but does NOT delete files on disk.
    Cannot delete the default library - set another as default first.
    """
    try:
        deleted = library_service.delete_library(library_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Library not found")
        return {"status": "success", "message": f"Library {library_id} deleted"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logging.exception(f"[Web API] Error deleting library {library_id}")
        raise HTTPException(status_code=500, detail=f"Error deleting library: {e}") from e


@router.post("/{library_id}/preview", dependencies=[Depends(verify_session)])
async def preview_library_scan(
    library_id: int,
    request: ScanLibraryRequest,
    library_service: "LibraryService" = Depends(get_library_service),
) -> dict[str, int]:
    """
    Preview file count for a library path without scanning.

    Returns:
        Dictionary with file_count (total audio files found)
    """
    try:
        from nomarr.helpers.files_helper import collect_audio_files

        # Get library to resolve root path
        library = library_service.get_library(library_id)

        # Resolve paths to scan
        if request.paths:
            # User specified sub-paths - validate they're within library root
            resolved_paths = []
            for path in request.paths:
                resolved = library_service._resolve_path_within_library(
                    library_root=library.root_path,
                    user_path=path,
                    must_exist=True,
                    must_be_file=False,
                )
                resolved_paths.append(str(resolved))
        else:
            # No paths specified - scan entire library root (no need to resolve)
            resolved_paths = [library.root_path]

        # Count files using helper
        all_files = []
        for root_path in resolved_paths:
            files = collect_audio_files(root_path, recursive=request.recursive)
            all_files.extend(files)

        return {"file_count": len(set(all_files))}

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logging.exception(f"[Web API] Error previewing library {library_id}")
        raise HTTPException(status_code=500, detail=f"Error previewing library: {e}") from e


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
        raise HTTPException(status_code=500, detail=f"Error searching files: {e}") from e


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
        raise HTTPException(status_code=500, detail=f"Error getting tag keys: {e}") from e


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
        raise HTTPException(status_code=500, detail=f"Error getting tag values: {e}") from e


@router.post("/{library_id}/scan", dependencies=[Depends(verify_session)])
async def scan_library(
    library_id: int,
    request: ScanLibraryRequest,
    library_service: "LibraryService" = Depends(get_library_service),
) -> StartScanWithStatusResponse:
    """
    Start a scan for a specific library.

    This endpoint triggers a scan for the specified library, discovering files
    and enqueuing them for background processing. The scan respects the library's
    root_path and only processes files within that directory tree.

    Args:
        library_id: Library ID to scan
        request: Scan configuration (paths, recursive, force, clean_missing)
        library_service: LibraryService instance (injected)

    Returns:
        StartScanWithStatusResponse with scan statistics and status message

    Raises:
        HTTPException: 404 if library not found, 500 for other errors
    """
    try:
        # Call the service layer to start scan for this specific library (returns StartScanResult DTO)
        stats = library_service.start_scan_for_library(
            library_id=library_id,
            paths=request.paths,
            recursive=request.recursive,
            force=request.force,
            clean_missing=request.clean_missing,
        )

        # Transform DTO to wrapped Pydantic response
        return StartScanWithStatusResponse.from_dto(stats, library_id)

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logging.exception(f"[Web API] Error starting scan for library {library_id}")
        raise HTTPException(status_code=500, detail=f"Error starting library scan: {e}") from e
