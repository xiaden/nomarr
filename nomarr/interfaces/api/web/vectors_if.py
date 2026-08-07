"""Vector search and maintenance API endpoints.

Auth: session token (verify_session). Admin-only for maintenance endpoints.
"""

from __future__ import annotations

import asyncio
import logging

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
    get_ml_service,
    get_vector_maintenance_service,
    get_vector_search_service,
)
from nomarr.services.domain.vector_maintenance_svc import (
    VectorMaintenanceService,  # noqa: TC001  # FastAPI resolves Annotated[...] at route registration
)
from nomarr.services.domain.vector_search_svc import (
    VectorSearchService,  # noqa: TC001  # FastAPI resolves Annotated[...] at route registration
)
from nomarr.services.infrastructure.ml_svc import (
    MLService,  # noqa: TC001  # FastAPI resolves Annotated[...] at route registration
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Vector"], prefix="/vector")


@router.get("/backbone", dependencies=[Depends(verify_session)])
async def list_backbones(
    ml_service: MLService = Depends(get_ml_service),
) -> dict[str, list[str]]:
    """List available vector backbones."""
    return {"backbones": ml_service.list_backbones()}


@router.post("/search", dependencies=[Depends(verify_session)])
async def search_vectors(
    request: VectorSearchRequest,
    vector_search_service: VectorSearchService = Depends(get_vector_search_service),
) -> VectorSearchResponse:
    """Search for similar vectors using ANN similarity."""
    try:
        results = await asyncio.to_thread(
            vector_search_service.search_similar_tracks,
            file_id=decode_id(request.file_id),
            backbone_id=request.backbone_id,
            limit=request.limit,
            min_score=request.min_score,
        )

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
        logger.warning(f"Vector search validation error: {e}")
        raise HTTPException(status_code=503, detail=str(e)) from e

    except RuntimeError as e:
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
    """Get embedding vector for a specific track."""
    decoded_file_id: int = decode_path_id(file_id)
    result = await asyncio.to_thread(vector_search_service.get_track_vector, backbone_id, decoded_file_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No vector found for file '{decoded_file_id}' with backbone '{backbone_id}'",
        )

    return VectorGetResponse(
        file_id=encode_id(file_id),
        backbone_id=backbone_id,
        vector=result["vector_n"],
    )


# Admin endpoints for vector maintenance — merged into main router
# (all web endpoints use same auth, no separate admin_router needed)


@router.get("/stats", dependencies=[Depends(verify_session)])
async def get_vector_stats(
    vector_maintenance_service: VectorMaintenanceService = Depends(get_vector_maintenance_service),
) -> VectorStatsResponse:
    """Get hot/cold statistics for all backbones."""

    stats_rows = await asyncio.to_thread(vector_maintenance_service.get_backbone_vector_stats)
    stats_list = [
        VectorHotColdStats(
            backbone_id=str(row["backbone_id"]),
            hot_count=int(row["hot_count"]),
            cold_count=int(row["cold_count"]),
            index_exists=bool(row["index_exists"]),
        )
        for row in stats_rows
    ]

    return VectorStatsResponse(stats=stats_list)


@router.post("/promote", dependencies=[Depends(verify_session)])
async def promote_vectors(
    request: VectorPromoteRequest,
    vector_maintenance_service: VectorMaintenanceService = Depends(get_vector_maintenance_service),
) -> VectorPromoteResponse:
    """Promote vectors from hot to cold and rebuild index."""
    try:
        await asyncio.to_thread(
            vector_maintenance_service.promote_and_rebuild,
            backbone_id=request.backbone_id,
            nlists=request.nlists,
        )

        return VectorPromoteResponse(
            status="success",
            backbone_id=request.backbone_id,
            message=f"Vectors promoted and index rebuilt for backbone '{request.backbone_id}'",
        )

    except ValueError as e:
        logger.warning(f"Vector promote validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e

    except RuntimeError as e:
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
    """Rebuild vector index without promoting hot vectors."""
    try:
        await asyncio.to_thread(
            vector_maintenance_service.rebuild_index,
            backbone_id=request.backbone_id,
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
