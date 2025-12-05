"""Library statistics and management endpoints for web UI."""

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.types.library_types import (
    CreateLibraryRequest,
    LibraryResponse,
    LibraryStatsResponse,
    ListLibrariesResponse,
    ScanLibraryRequest,
    StartScanWithStatusResponse,
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
