"""Analytics endpoints for web UI."""
import asyncio
import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.types.analytics_types import (
    CollectionOverviewResponse,
    MoodAnalysisResponse,
    MoodDistributionResponse,
    TagCoOccurrenceRequest,
    TagCoOccurrencesResponse,
    TagCorrelationsResponse,
    TagFrequenciesResponse,
)
from nomarr.interfaces.api.web.dependencies import get_analytics_service

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.services.domain.analytics_svc import AnalyticsService
router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/tag-frequencies", dependencies=[Depends(verify_session)])
async def web_analytics_tag_frequencies(
    limit: int = 50,
    analytics_service: "AnalyticsService" = Depends(get_analytics_service),
) -> TagFrequenciesResponse:
    """Get tag frequency statistics."""
    try:
        result = await asyncio.to_thread(
            analytics_service.get_tag_frequencies_with_result, limit=limit
        )
        return TagFrequenciesResponse.from_dto(result)
    except Exception as e:
        logger.exception("[Web API] Error getting tag frequencies")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to get tag frequencies"),
        ) from e


@router.get("/mood-distribution", dependencies=[Depends(verify_session)])
async def web_analytics_mood_distribution(
    library_id: str | None = None,
    analytics_service: Annotated["AnalyticsService", Depends(get_analytics_service)] = None,  # type: ignore[assignment]
) -> MoodDistributionResponse:
    """Get mood tag distribution.

    Optionally filtered by library_id.
    """
    try:
        result = await asyncio.to_thread(
            analytics_service.get_mood_distribution_with_result, library_id=library_id
        )
        return MoodDistributionResponse.from_dto(result)
    except Exception as e:
        logger.exception("[Web API] Error getting mood distribution")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to get mood distribution"),
        ) from e


@router.get("/tag-correlations", dependencies=[Depends(verify_session)])
async def web_analytics_tag_correlations(
    top_n: int = 20,
    analytics_service: "AnalyticsService" = Depends(get_analytics_service),
) -> TagCorrelationsResponse:
    """Get VALUE-based correlation matrix for mood values, genres, and attributes.

    Returns mood-to-mood, mood-to-genre, and mood-to-tier correlations.
    """
    try:
        result_dto = await asyncio.to_thread(
            analytics_service.get_tag_correlation_matrix, top_n=top_n
        )
        return TagCorrelationsResponse.from_dto(result_dto)
    except Exception as e:
        logger.exception("[Web API] Error getting tag correlations")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to get tag correlations"),
        ) from e


@router.post("/tag-co-occurrences", dependencies=[Depends(verify_session)])
async def web_analytics_tag_co_occurrences(
    request: TagCoOccurrenceRequest,
    library_id: str | None = None,
    analytics_service: Annotated["AnalyticsService", Depends(get_analytics_service)] = None,  # type: ignore[assignment]
) -> TagCoOccurrencesResponse:
    """Get tag co-occurrence matrix for arbitrary tag sets.

    Computes a matrix where matrix[j][i] = count of files having both x[i] and y[j].
    Maximum 16x16 matrix size. Inputs exceeding limits are trimmed with warning.
    Optionally filtered by library_id.
    """
    try:
        x_tags = request.x_axis[:16]
        y_tags = request.y_axis[:16]
        if len(request.x_axis) > 16 or len(request.y_axis) > 16:
            logger.warning(
                f"[Web API] Tag co-occurrence request exceeded 16x16 limit. "
                f"Trimmed from {len(request.x_axis)}x{len(request.y_axis)} to {len(x_tags)}x{len(y_tags)}"
            )
        x_tuples = [(tag.key, tag.value) for tag in x_tags]
        y_tuples = [(tag.key, tag.value) for tag in y_tags]
        result_dto = await asyncio.to_thread(
            analytics_service.get_tag_co_occurrence,
            x_tags=x_tuples,
            y_tags=y_tuples,
            library_id=library_id,
        )
        return TagCoOccurrencesResponse.from_dto(result_dto)
    except Exception as e:
        logger.exception("[Web API] Error getting tag co-occurrences")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to get tag co-occurrences"),
        ) from e


@router.get("/collection-overview", dependencies=[Depends(verify_session)])
async def web_analytics_collection_overview(
    library_id: str | None = None,
    analytics_service: Annotated["AnalyticsService", Depends(get_analytics_service)] = None,  # type: ignore[assignment]
) -> CollectionOverviewResponse:
    """Get collection overview statistics.

    Returns library stats, year/genre/artist distributions.
    Optionally filtered by library_id.
    """
    try:
        result = await asyncio.to_thread(
            analytics_service.get_collection_overview, library_id=library_id
        )
        return CollectionOverviewResponse(
            stats=result["stats"],
            year_distribution=result["year_distribution"],
            genre_distribution=result["genre_distribution"],
            artist_distribution=result["artist_distribution"],
        )
    except Exception as e:
        logger.exception("[Web API] Error getting collection overview")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to get collection overview"),
        ) from e


@router.get("/mood-analysis", dependencies=[Depends(verify_session)])
async def web_analytics_mood_analysis(
    library_id: str | None = None,
    mood_tier: str = "strict",
    analytics_service: Annotated["AnalyticsService", Depends(get_analytics_service)] = None,  # type: ignore[assignment]
) -> MoodAnalysisResponse:
    """Get mood analysis statistics.

    Returns mood coverage, balance, top pairs, and dominant vibes.
    Optionally filtered by library_id and mood_tier.
    """
    try:
        result = await asyncio.to_thread(
            analytics_service.get_mood_analysis, library_id=library_id, mood_tier=mood_tier
        )
        return MoodAnalysisResponse(
            coverage=result["coverage"],
            balance=result["balance"],
            top_pairs=result["top_pairs"],
            dominant_vibes=result["dominant_vibes"],
        )
    except Exception as e:
        logger.exception("[Web API] Error getting mood analysis")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to get mood analysis"),
        ) from e
