"""Vector search and maintenance API endpoints.

Routes:
- /vectors/search (POST) - Vector similarity search
- /vectors/track (GET) - Get track vector
- /vectors/stats (GET) - Get hot/cold stats
- /vectors/promote (POST) - Promote & rebuild

These routes will be mounted under /api/web via the web router.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.types.vector_types import (
    VectorGetResponse,
    VectorHotColdStats,
    VectorPromoteRequest,
    VectorPromoteResponse,
    VectorSearchRequest,
    VectorSearchResponse,
    VectorSearchResultItem,
    VectorStatsResponse,
)
from nomarr.interfaces.api.web.dependencies import (
    get_vector_maintenance_service,
    get_vector_search_service,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nomarr.services.domain.vector_maintenance_svc import VectorMaintenanceService
    from nomarr.services.domain.vector_search_svc import VectorSearchService

router = APIRouter(tags=["vectors"], prefix="/vectors")


@router.get("/backbones", dependencies=[Depends(verify_session)])
async def list_backbones(
    vector_maintenance_service: VectorMaintenanceService = Depends(get_vector_maintenance_service),
) -> dict[str, list[str]]:
    """List available vector backbones.

    Returns backbone IDs discovered from models directory structure.
    Use these IDs when calling other vector endpoints.

    Requires:
    - Authentication (admin or library owner)

    Returns:
        Dict with 'backbones' key containing list of available backbone IDs

    """
    return {"backbones": vector_maintenance_service.list_backbones()}


@router.post("/search", dependencies=[Depends(verify_session)])
async def search_vectors(
    request: VectorSearchRequest,
    vector_search_service: VectorSearchService = Depends(get_vector_search_service),
) -> VectorSearchResponse:
    """Search for similar vectors using ANN.

    Searches cold collection only (promoted vectors with indexes).
    Returns results as of last rebuild (stale is acceptable).

    Requires:
    - Authentication (admin or library owner)
    - Cold collection must have vector index

    Args:
        request: Search parameters (backbone_id, vector, limit, min_score)

    Returns:
        VectorSearchResponse with matching vectors and scores

    Raises:
        400: If vector dimension doesn't match backbone
        404: If backbone not found
        503: If cold collection has no vector index (search not available)

    """
    try:
        # Call service layer
        results = vector_search_service.search_similar_tracks(
            backbone_id=request.backbone_id,
            vector=request.vector,
            limit=request.limit,
            min_score=request.min_score,
        )

        # Convert to response model
        result_items = [
            VectorSearchResultItem(
                file_id=result["file_id"],
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

    Tries cold collection first, then falls back to hot if not found.
    Use this to retrieve a track's vector before performing similarity search.

    Requires:
    - Authentication (admin or library owner)

    Args:
        backbone_id: Backbone identifier (e.g., "effnet", "yamnet")
        file_id: Library file document ID

    Returns:
        VectorGetResponse with the track's embedding vector

    Raises:
        404: If vector not found in hot or cold collections

    """
    result = vector_search_service.get_track_vector(backbone_id, file_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No vector found for file '{file_id}' with backbone '{backbone_id}'",
        )

    return VectorGetResponse(
        file_id=file_id,
        backbone_id=backbone_id,
        vector=result["vector"],
    )


# Admin endpoints for vector maintenance
# Merge admin endpoints into main router (all web endpoints use same auth)
# No separate admin_router needed


@router.get("/stats", dependencies=[Depends(verify_session)])
async def get_vector_stats(
    vector_maintenance_service: VectorMaintenanceService = Depends(get_vector_maintenance_service),
) -> VectorStatsResponse:
    """Get hot/cold statistics for all backbones.

    Returns stats for all registered vector backbones.
    Use this endpoint to monitor hot collection sizes and decide when to rebuild.

    Requires:
    - Authentication (admin only)

    Returns:
        VectorStatsResponse with stats for all backbones

    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    known_backbones = vector_maintenance_service.list_backbones()

    def _get_stats_sync() -> list[VectorHotColdStats]:
        """Run blocking DB queries in thread pool."""
        stats_list = []
        for backbone_id in known_backbones:
            try:
                stats = vector_maintenance_service.get_hot_cold_stats(backbone_id)
                stats_list.append(
                    VectorHotColdStats(
                        backbone_id=backbone_id,
                        hot_count=int(stats["hot_count"]),
                        cold_count=int(stats["cold_count"]),
                        index_exists=bool(stats["index_exists"]),
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to get stats for backbone {backbone_id}: {e}")
                # Skip backbones that don't exist or have errors
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
