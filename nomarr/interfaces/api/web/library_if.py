"""Library statistics and management endpoints for web UI."""

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies_if import get_library_service

if TYPE_CHECKING:
    from nomarr.services.library_svc import LibraryService

router = APIRouter(prefix="/libraries", tags=["Library"])


# ──────────────────────────────────────────────────────────────────────
# Request/Response Models
# ──────────────────────────────────────────────────────────────────────


class CreateLibraryRequest(BaseModel):
    """Request body for creating a library."""

    name: str
    root_path: str
    is_enabled: bool = True
    is_default: bool = False


class UpdateLibraryRequest(BaseModel):
    """Request body for updating a library."""

    name: str | None = None
    root_path: str | None = None
    is_enabled: bool | None = None
    is_default: bool | None = None


class ScanRequest(BaseModel):
    """Request body for starting a library scan."""

    paths: list[str] | None = None
    recursive: bool = True
    force: bool = False
    clean_missing: bool = True


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("/stats", dependencies=[Depends(verify_session)])
async def web_library_stats(
    library_service: "LibraryService" = Depends(get_library_service),
) -> dict[str, Any]:
    """Get library statistics (total files, artists, albums, duration)."""
    try:
        # Use service layer to get library stats
        stats = library_service.get_library_stats()

        return {
            "total_files": stats.get("total_files", 0) or 0,
            "unique_artists": stats.get("total_artists", 0) or 0,
            "unique_albums": stats.get("total_albums", 0) or 0,
            "total_duration_seconds": stats.get("total_duration", 0) or 0,
        }

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
) -> list[dict[str, Any]]:
    """List all configured libraries."""
    try:
        return library_service.list_libraries(enabled_only=enabled_only)
    except Exception as e:
        logging.exception("[Web API] Error listing libraries")
        raise HTTPException(status_code=500, detail=f"Error listing libraries: {e}") from e


@router.get("/default", dependencies=[Depends(verify_session)])
async def get_default_library(
    library_service: "LibraryService" = Depends(get_library_service),
) -> dict[str, Any]:
    """Get the default library."""
    try:
        library = library_service.get_default_library()
        if not library:
            raise HTTPException(status_code=404, detail="No default library configured")
        return library
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("[Web API] Error getting default library")
        raise HTTPException(status_code=500, detail=f"Error getting default library: {e}") from e


@router.get("/{library_id}", dependencies=[Depends(verify_session)])
async def get_library(
    library_id: int,
    library_service: "LibraryService" = Depends(get_library_service),
) -> dict[str, Any]:
    """Get a library by ID."""
    try:
        return library_service.get_library(library_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logging.exception(f"[Web API] Error getting library {library_id}")
        raise HTTPException(status_code=500, detail=f"Error getting library: {e}") from e


@router.post("", dependencies=[Depends(verify_session)])
async def create_library(
    request: CreateLibraryRequest,
    library_service: "LibraryService" = Depends(get_library_service),
) -> dict[str, Any]:
    """Create a new library."""
    try:
        return library_service.create_library(
            name=request.name,
            root_path=request.root_path,
            is_enabled=request.is_enabled,
            is_default=request.is_default,
        )
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
) -> dict[str, Any]:
    """Update a library's properties."""
    try:
        # Update root_path if provided
        if request.root_path is not None:
            library_service.update_library_root(library_id, request.root_path)

        # Update is_default if provided
        if request.is_default is True:
            library_service.set_default_library(library_id)

        # Update name and/or is_enabled if provided
        if request.name is not None or request.is_enabled is not None:
            return library_service.update_library_metadata(
                library_id,
                name=request.name,
                is_enabled=request.is_enabled,
            )

        # If only root_path or is_default was updated, fetch and return the updated library
        return library_service.get_library(library_id)

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
) -> dict[str, Any]:
    """Set a library as the default library."""
    try:
        return library_service.set_default_library(library_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logging.exception(f"[Web API] Error setting default library {library_id}")
        raise HTTPException(status_code=500, detail=f"Error setting default library: {e}") from e


@router.post("/{library_id}/scan", dependencies=[Depends(verify_session)])
async def scan_library(
    library_id: int,
    request: ScanRequest,
    library_service: "LibraryService" = Depends(get_library_service),
) -> dict[str, Any]:
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
        Dict with scan statistics (files_queued, etc.)

    Raises:
        HTTPException: 404 if library not found, 500 for other errors
    """
    try:
        # Call the service layer to start scan for this specific library
        stats = library_service.start_scan_for_library(
            library_id=library_id,
            paths=request.paths,
            recursive=request.recursive,
            force=request.force,
            clean_missing=request.clean_missing,
        )

        return {
            "status": "queued",
            "message": f"Scan started for library {library_id}: {stats.get('files_queued', 0)} files queued",
            "stats": stats,
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logging.exception(f"[Web API] Error starting scan for library {library_id}")
        raise HTTPException(status_code=500, detail=f"Error starting library scan: {e}") from e
