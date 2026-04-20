"""Vector search and maintenance API endpoints.

Routes:
- /vector/search (POST) - Vector similarity search
- /vector/track (GET) - Get track vector
- /vector/stats (GET) - Get hot/cold stats
- /vector/promote (POST) - Promote hot→cold + rebuild index
- /vector/rebuild-index (POST) - Rebuild index only (no hot→cold drain)

These routes will be mounted under /api/web via the web router.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.id_codec import decode_id, decode_path_id, encode_id
from nomarr.interfaces.api.types.vector_types import (
    VectorGetResponse,
    VectorHotColdStats,
    VectorPromoteRequest,
    VectorPromoteResponse,
    VectorRebuildIndexRequest,
    VectorRebuildIndexResponse,
    VectorSearchRequest,
    VectorSearchResponse,
    VectorSearchResultItem,
    VectorStatsResponse,
)
from nomarr.interfaces.api.web.dependencies import (
    get_library_service,
    get_ml_service,
    get_vector_maintenance_service,
    get_vector_search_service,
)
from nomarr.services.domain.library_svc import LibraryService
from nomarr.services.domain.vector_maintenance_svc import VectorMaintenanceService
from nomarr.services.domain.vector_search_svc import VectorSearchService
from nomarr.services.infrastructure.ml_svc import MLService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Vector"], prefix="/vector")


@router.get("/backbone", dependencies=[Depends(verify_session)])
async def list_backbones(
    ml_service: MLService = Depends(get_ml_service),
) -> dict[str, list[str]]:
    """List available vector backbones.

    Returns backbone IDs discovered from models directory structure.
    Use these IDs when calling other vector endpoints.

    Requires:
    - Authentication (admin or library owner)

    Returns:
        Dict with 'backbones' key containing list of available backbone IDs

    """
    return {"backbones": ml_service.list_backbones()}


@router.post("/search", dependencies=[Depends(verify_session)])
async def search_vectors(
    request: VectorSearchRequest,
    vector_search_service: VectorSearchService = Depends(get_vector_search_service),
) -> VectorSearchResponse:
    """Search for similar vectors using ANN.

    Resolves the source track's vector internally from file_id, then
    searches cold collection(s). Returns results as of last rebuild.

    Requires:
    - Authentication (admin or library owner)
    - Cold collection must have vector index

    Args:
        request: Search parameters (file_id, backbone_id, limit, min_score)

    Returns:
        VectorSearchResponse with matching vectors and scores

    Raises:
        400: If file not found or no vector exists
        503: If cold collection has no vector index (search not available)

    """
    try:
        # Call service layer
        results = vector_search_service.search_similar_tracks(
            file_id=decode_id(request.file_id),
            backbone_id=request.backbone_id,
            limit=request.limit,
            min_score=request.min_score,
            library_scope=request.library_scope,
        )

        # Convert to response model
        result_items = [
            VectorSearchResultItem(
                file_id=encode_id(result["file_id"]),
                score=result["score"],
                vector=result["vector"],
            )
            for result in results
        ]

        return VectorSearchResponse(results=result_items)

    except ValueError as e:
        # Service raises ValueError for validation errors (e.g., no vector index)
        logger.warning(f"Vector search validation error: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from e

    except RuntimeError as e:
        # Service raises RuntimeError for query failures
        logger.error(f"Vector search failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Vector search failed") from e

    except Exception as e:
        logger.error(f"Unexpected error in vector search: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/track", dependencies=[Depends(verify_session)])
async def get_track_vector(
    backbone_id: str,
    file_id: str,
    vector_search_service: VectorSearchService = Depends(get_vector_search_service),
) -> VectorGetResponse:
    """Get embedding vector for a specific track.

    Resolves the owning library internally from the file ID.
    Searches cold (promoted) collection only.

    Requires:
    - Authentication (admin or library owner)

    Args:
        backbone_id: Backbone identifier (e.g., "effnet", "yamnet")
        file_id: Library file document ID (HTTP-encoded, e.g. "library_files:123")

    Returns:
        VectorGetResponse with the track's embedding vector

    Raises:
        404: If vector not found in cold collection

    """
    file_id = decode_path_id(file_id)
    result = vector_search_service.get_track_vector(backbone_id, file_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No vector found for file '{file_id}' with backbone '{backbone_id}'",
        )

    return VectorGetResponse(
        file_id=encode_id(file_id),
        backbone_id=backbone_id,
        vector=result["vector_n"],
    )


# Admin endpoints for vector maintenance
# Merge admin endpoints into main router (all web endpoints use same auth)
# No separate admin_router needed


@router.get("/stats", dependencies=[Depends(verify_session)])
async def get_vector_stats(
    ml_service: MLService = Depends(get_ml_service),
    vector_maintenance_service: VectorMaintenanceService = Depends(get_vector_maintenance_service),
    library_service: LibraryService = Depends(get_library_service),
) -> VectorStatsResponse:
    """Get hot/cold statistics for all backbones.

    Returns stats for all registered vector backbones.
    Use this endpoint to monitor hot collection sizes and decide when to rebuild.

    Requires:
    - Authentication (admin only)

    Returns:
        VectorStatsResponse with stats for all backbones

    """
    known_backbones = ml_service.list_backbones()

    def _get_stats_sync() -> list[VectorHotColdStats]:
        """Run blocking DB queries in thread pool."""
        stats_list = []
        libraries = library_service.list_libraries()
        for lib in libraries:
            library_key = lib._key
            for backbone_id in known_backbones:
                try:
                    stats = vector_maintenance_service.get_hot_cold_stats(backbone_id, library_key=library_key)
                    stats_list.append(
                        VectorHotColdStats(
                            backbone_id=backbone_id,
                            library_key=library_key,
                            hot_count=int(stats["hot_count"]),
                            cold_count=int(stats["cold_count"]),
                            index_exists=bool(stats["index_exists"]),
                        )
                    )
                except Exception as e:
                    logger.warning(f"Failed to get stats for backbone {backbone_id}, library {library_key}: {e}")
                    continue
        return stats_list

    # Run blocking DB operations in thread pool to avoid blocking event loop
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1) as executor:
        stats_list = await loop.run_in_executor(executor, _get_stats_sync)

    return VectorStatsResponse(stats=stats_list)


@router.post("/promote", dependencies=[Depends(verify_session)])
async def promote_vectors(
    request: VectorPromoteRequest,
    vector_maintenance_service: VectorMaintenanceService = Depends(get_vector_maintenance_service),
) -> VectorPromoteResponse:
    """Promote vectors from hot to cold and rebuild vector index.

    Synchronous operation - blocks until complete (may take several minutes).
    Auto-calculates nlists if not provided based on collection size.

    Requires:
    - Authentication (admin only)

    Args:
        request: Promote parameters (backbone_id, optional nlists)

    Returns:
        VectorPromoteResponse with operation status

    Raises:
        400: If backbone not found or invalid parameters
        500: If promote & rebuild fails
        504: If operation times out (>10 minutes)

    """
    try:
        # Call service layer (synchronous - blocks until complete)
        vector_maintenance_service.promote_and_rebuild(
            backbone_id=request.backbone_id,
            library_key=request.library_key,
            nlists=request.nlists,
        )

        return VectorPromoteResponse(
            status="success",
            backbone_id=request.backbone_id,
            message=f"Vectors promoted and index rebuilt for backbone '{request.backbone_id}'",
        )

    except ValueError as e:
        # Service raises ValueError for validation errors
        logger.warning(f"Vector promote validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e

    except RuntimeError as e:
        # Service raises RuntimeError for operation failures
        logger.error(f"Vector promote failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Promote & rebuild failed") from e

    except Exception as e:
        logger.error(f"Unexpected error in vector promote: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post("/rebuild-index", dependencies=[Depends(verify_session)])
async def rebuild_vector_index(
    request: VectorRebuildIndexRequest,
    vector_maintenance_service: VectorMaintenanceService = Depends(get_vector_maintenance_service),
) -> VectorRebuildIndexResponse:
    """Rebuild vector index without promoting hot vectors.

    Drops the existing index on the cold collection and trains a new one
    using the current cold data. Does not drain hot→cold.

    Use this to apply updated index parameters (e.g. nLists) when the
    cold collection is already fully populated and has no pending hot data.

    Requires:
    - Authentication (admin only)

    Args:
        request: backbone_id and optional nlists override

    Returns:
        VectorRebuildIndexResponse with operation status

    Raises:
        400: If backbone not found or cold collection missing
        500: If index creation fails
        504: If operation times out (>10 minutes)
    """
    try:
        vector_maintenance_service.rebuild_index(
            backbone_id=request.backbone_id,
            library_key=request.library_key,
            nlists=request.nlists,
        )

        return VectorRebuildIndexResponse(
            status="success",
            backbone_id=request.backbone_id,
            message=f"Vector index rebuilt for backbone '{request.backbone_id}'",
        )

    except ValueError as e:
        logger.warning(f"Vector rebuild-index validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e

    except RuntimeError as e:
        logger.error(f"Vector rebuild-index failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Rebuild index failed") from e

    except Exception as e:
        logger.error(f"Unexpected error in rebuild-index: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from e
