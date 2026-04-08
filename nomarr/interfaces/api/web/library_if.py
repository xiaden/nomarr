"""Library statistics and management endpoints for web UI."""

import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.id_codec import decode_path_id
from nomarr.interfaces.api.types.library_types import (
    CreateLibraryRequest,
    LibraryResponse,
    LibraryStatsResponse,
    ListLibrariesResponse,
    UpdateLibraryRequest,
)
from nomarr.interfaces.api.web.dependencies import (
    get_config_service,
    get_library_service,
    get_pipeline_service,
    get_vector_maintenance_service,
)
from nomarr.services.infrastructure.pipeline_svc import LibraryPipelineService

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.services.domain.library_svc import LibraryService
    from nomarr.services.domain.vector_maintenance_svc import VectorMaintenanceService
    from nomarr.services.infrastructure.config_svc import ConfigService

router = APIRouter(prefix="/library", tags=["Library"])


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
            file_write_mode=request.file_write_mode,
            library_auto_write=request.library_auto_write,
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
    library_id = decode_path_id(library_id)
    try:
        current_library = None
        if request.library_auto_write is not None:
            current_library = library_service.get_library(library_id)

        library = library_service.update_library(
            library_id,
            name=request.name,
            root_path=request.root_path,
            is_enabled=request.is_enabled,
            watch_mode=request.watch_mode,
            file_write_mode=request.file_write_mode,
            library_auto_write=request.library_auto_write,
        )

        if current_library is not None and current_library.library_auto_write != library.library_auto_write:
            pipeline_status = pipeline_service.get_pipeline_status(library_id)
            if pipeline_status is not None:
                if (
                    not current_library.library_auto_write
                    and library.library_auto_write
                    and pipeline_status.state == "write_ready"
                ):
                    pipeline_service.handle_auto_write_enabled(library_id)
                elif (
                    current_library.library_auto_write
                    and not library.library_auto_write
                    and pipeline_status.state == "writing"
                ):
                    pipeline_service.handle_auto_write_disabled(library_id)

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
        deleted = library_service.delete_library(library_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Library not found")
        return {"status": "success", "message": f"Library {library_id} deleted"}
    except ValueError:
        raise HTTPException(status_code=400, detail="Cannot delete library") from None
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[Web API] Error deleting library {library_id}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to delete library")) from e


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
    except Exception as e:
        logger.exception(f"[Web API] Error getting vector config for library {library_id}")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to get vector config"),
        ) from e


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
    except Exception as e:
        logger.exception(f"[Web API] Error updating vector config for library {library_id}")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to update vector config"),
        ) from e


@router.get("/{library_id}/vector-stats", dependencies=[Depends(verify_session)])
async def get_library_vector_stats(
    library_id: str,
    vector_maintenance_service: Annotated["VectorMaintenanceService", Depends(get_vector_maintenance_service)],
) -> LibraryVectorStatsResponse:
    """Get per-library vector statistics across all backbones.

    Returns hot/cold vector counts and index status for every discovered
    backbone in the given library.

    Args:
        library_id: Library ID to query
        vector_maintenance_service: VectorMaintenanceService instance (injected)

    Returns:
        LibraryVectorStatsResponse with per-backbone stats

    """
    library_id = decode_path_id(library_id)
    try:
        stats = vector_maintenance_service.get_library_vector_stats(library_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Library not found") from None
    except Exception as e:
        logger.exception(f"[Web API] Error getting vector stats for library {library_id}")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to get vector stats"),
        ) from e

    return LibraryVectorStatsResponse(
        library_key=library_id.rsplit("/", 1)[-1],
        stats=[
            VectorStatsItem(
                backbone_id=str(stat["backbone_id"]),
                hot_count=int(stat["hot_count"]),
                cold_count=int(stat["cold_count"]),
                index_exists=bool(stat["index_exists"]),
            )
            for stat in stats
        ],
    )
