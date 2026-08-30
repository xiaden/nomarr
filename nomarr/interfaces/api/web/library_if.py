"""Library statistics and management endpoints for web UI."""

import asyncio
import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from nomarr.components.library.library_song_query_comp import get_library_counts
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.id_codec import decode_library_name
from nomarr.interfaces.api.types.library_types import (
    CreateLibraryRequest,
    LibraryResponse,
    LibraryStatsResponse,
    ListLibrariesResponse,
    UpdateLibraryRequest,
)
from nomarr.interfaces.api.web.dependencies import (
    get_library_service,
    get_pipeline_service,
    get_vector_maintenance_service,
)
from nomarr.services.infrastructure.pipeline_svc import LibraryPipelineService

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.services.domain.library_svc import LibraryService
    from nomarr.services.domain.vector_maintenance_svc import VectorMaintenanceService

router = APIRouter(prefix="/library", tags=["Library"])


async def _resolve_library(library_service, raw_name: str) -> Library:
    """Resolve a URL-encoded natural library name to a domain ``Library``.

    Mechanism A (TASK-library-domain-facades-A): the wire identity is the
    natural ``Library.name``. Missing names map to 404.

    Args:
        library_service: LibraryService instance.
        raw_name: URL-encoded natural library name from a path segment.

    Returns:
        Resolved domain ``Library``.

    Raises:
        HTTPException: 404 if the library does not exist.

    """
    name = decode_library_name(raw_name)
    library = await asyncio.to_thread(library_service.get_library_by_name, name)
    if library is None:
        raise HTTPException(status_code=404, detail="Library not found")
    return library


class VectorStatsItem(BaseModel):
    """Per-backbone vector statistics."""

    backbone_id: str
    hot_count: int
    cold_count: int
    index_exists: bool


class BackboneVectorStatsResponse(BaseModel):
    """Vector statistics across all backbones for one library.

    ``library_key`` is removed because vector collections are per-backbone,
    not per-library. Use ``/api/web/vector/stats`` for global stats.
    """

    stats: list[VectorStatsItem]


class DeleteLibraryResponse(BaseModel):
    """Confirmation response for library deletion."""

    status: str
    message: str


class ClearLibraryDataResponse(BaseModel):
    """Confirmation response for clearing all library data."""

    status: str
    message: str


@router.get("/stats", dependencies=[Depends(verify_session)])
async def web_library_stats(
    library_service: Annotated["LibraryService", Depends(get_library_service)],
) -> LibraryStatsResponse:
    """Get library statistics (total files, artists, albums, duration)."""
    try:
        stats = await asyncio.to_thread(library_service.get_library_stats)
        return LibraryStatsResponse.from_dto(stats)
    except Exception as e:
        logger.exception("[Web API] Error getting library stats")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to get library stats")) from e


@router.get("", dependencies=[Depends(verify_session)])
async def list_libraries(
    library_service: Annotated["LibraryService", Depends(get_library_service)],
    enabled_only: bool = False,
) -> ListLibrariesResponse:
    """List all configured libraries."""
    try:
        libraries = await asyncio.to_thread(library_service.list_libraries, enabled_only=enabled_only)
        # Transport projection: build the name-keyed file/folder counts and
        # per-library scan status in the interface adapter (P4-S8).
        counts = await asyncio.to_thread(get_library_counts, library_service.db)
        scans = {lib.name: await asyncio.to_thread(library_service.get_status, lib) for lib in libraries}
        return ListLibrariesResponse.from_dto(libraries, counts=counts, scans=scans)
    except Exception as e:
        logger.exception("[Web API] Error listing libraries")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to list libraries")) from e


@router.get("/{library_name}", dependencies=[Depends(verify_session)])
async def get_library(
    library_name: str,
    library_service: Annotated["LibraryService", Depends(get_library_service)],
) -> LibraryResponse:
    """Get a library by natural name (mechanism A)."""
    try:
        library = await _resolve_library(library_service, library_name)
        return LibraryResponse.from_dto(library)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[Web API] Error getting library {decode_library_name(library_name)}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to get library")) from e


@router.post("", dependencies=[Depends(verify_session)])
async def create_library(
    request: CreateLibraryRequest,
    library_service: Annotated["LibraryService", Depends(get_library_service)],
) -> LibraryResponse:
    """Create a new library."""
    try:
        library = await asyncio.to_thread(
            library_service.create_library,
            name=request.name,
            root_path=request.root_path,
            is_enabled=request.is_enabled,
            watch_mode=request.watch_mode,
            file_write_mode=request.file_write_mode,
            library_auto_write=request.library_auto_write,
        )
        return LibraryResponse.from_dto(library)
    except ValueError as e:
        logger.warning("[Web API] Library configuration error: %s", e)
        raise HTTPException(status_code=400, detail="Invalid library configuration") from None
    except Exception as e:
        logger.exception("[Web API] Error creating library")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to create library")) from e


@router.patch("/{library_name}", dependencies=[Depends(verify_session)])
async def update_library(
    library_name: str,
    request: UpdateLibraryRequest,
    library_service: Annotated["LibraryService", Depends(get_library_service)],
    pipeline_service: Annotated[LibraryPipelineService, Depends(get_pipeline_service)],
) -> LibraryResponse:
    """Update a library's properties.

    Reactive pipeline side-effect: if ``library_auto_write`` changes, this
    endpoint inspects the current pipeline state and either starts or cancels
    the write stage automatically:
    - Enabling auto-write while the pipeline is in ``write_ready`` → dispatches
      write immediately.
    - Disabling auto-write while the pipeline is ``writing`` → requests
      graceful write cancellation.
    """
    try:
        current_library = await _resolve_library(library_service, library_name)
        if request.library_auto_write is not None:
            # Re-fetch current value so the auto-write transition check is
            # based on persisted state, not the incoming (possibly unchanged) one.
            current_library = await asyncio.to_thread(library_service.get_library, current_library)

        library = await asyncio.to_thread(
            library_service.update_library,
            current_library,
            name=request.name,
            root_path=request.root_path,
            is_enabled=request.is_enabled,
            watch_mode=request.watch_mode,
            file_write_mode=request.file_write_mode,
            library_auto_write=request.library_auto_write,
        )

        if current_library.library_auto_write != library.library_auto_write:
            pipeline_status = await asyncio.to_thread(pipeline_service.get_pipeline_status, library)
            if pipeline_status is not None:
                if (
                    not current_library.library_auto_write
                    and library.library_auto_write
                    and pipeline_status.tag_write_state == "not_written"
                ):
                    pipeline_service.handle_auto_write_enabled(library)
                elif (
                    current_library.library_auto_write
                    and not library.library_auto_write
                    and pipeline_status.tag_write_state == "writing"
                ):
                    pipeline_service.handle_auto_write_disabled(library)

        return LibraryResponse.from_dto(library)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid library update") from None
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[Web API] Error updating library {decode_library_name(library_name)}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to update library")) from e


@router.delete("/{library_name}", dependencies=[Depends(verify_session)])
async def delete_library(
    library_name: str,
    library_service: Annotated["LibraryService", Depends(get_library_service)],
) -> DeleteLibraryResponse:
    """Delete a library.

    Removes the library entry but does NOT delete files on disk.
    """
    try:
        library = await _resolve_library(library_service, library_name)
        deleted = await asyncio.to_thread(library_service.delete_library, library)
        if not deleted:
            raise HTTPException(status_code=404, detail="Library not found")
        return DeleteLibraryResponse(status="success", message=f"Library {library.name} deleted")
    except ValueError:
        raise HTTPException(status_code=400, detail="Cannot delete library") from None
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[Web API] Error deleting library {decode_library_name(library_name)}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to delete library")) from e


@router.post("/clear-data", dependencies=[Depends(verify_session)])
async def clear_library_data(
    library_service: Annotated["LibraryService", Depends(get_library_service)],
) -> ClearLibraryDataResponse:
    """Clear all library data (files, tags, vectors, pipeline states).

    Wipes the entire library database — all files, tags, edges, vectors, scan
    records, and pipeline states — and resets the system to a clean slate.
    Requires no scans to be running. Intended for use from the admin UI when a
    full re-import is needed.
    """
    try:
        await asyncio.to_thread(library_service.clear_library_data)
        return ClearLibraryDataResponse(status="success", message="Library data cleared")
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        logger.exception("[Web API] Error clearing library data")
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to clear library data")
        ) from e


# Per-library vector config endpoints removed — vector configuration is
# global-only (per-library overrides eliminated). Use the global vector
# config from the config service or /api/web/config endpoint.


@router.get("/{library_name}/vector-stats", dependencies=[Depends(verify_session)])
async def get_library_vector_stats(
    library_name: str,
    library_service: Annotated["LibraryService", Depends(get_library_service)],
    vector_maintenance_service: Annotated["VectorMaintenanceService", Depends(get_vector_maintenance_service)],
) -> BackboneVectorStatsResponse:
    """Get vector statistics across all backbones for the requested library."""
    try:
        library = await _resolve_library(library_service, library_name)
        stats = await asyncio.to_thread(vector_maintenance_service.get_backbone_vector_stats, library)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[Web API] Error getting vector stats for library {decode_library_name(library_name)}")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to get vector stats"),
        ) from e

    return BackboneVectorStatsResponse(
        stats=[
            VectorStatsItem(
                backbone_id=str(row["backbone_id"]),
                hot_count=int(row["hot_count"]),
                cold_count=int(row["cold_count"]),
                index_exists=bool(row["index_exists"]),
            )
            for row in stats
        ],
    )
