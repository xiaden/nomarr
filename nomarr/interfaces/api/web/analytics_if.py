"""Analytics endpoints for web UI."""

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException

from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.types.analytics_types import (
    MoodDistributionResponse,
    TagCoOccurrenceRequest,
    TagCoOccurrencesResponse,
    TagCorrelationsResponse,
    TagFrequenciesResponse,
)
from nomarr.interfaces.api.web.dependencies import get_analytics_service

if TYPE_CHECKING:
    from nomarr.services.domain.analytics_svc import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["Analytics"])


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("/tag-frequencies", dependencies=[Depends(verify_session)])
async def web_analytics_tag_frequencies(
    limit: int = 50,
    analytics_service: "AnalyticsService" = Depends(get_analytics_service),
) -> TagFrequenciesResponse:
    """Get tag frequency statistics."""
    try:
        result = analytics_service.get_tag_frequencies_with_result(limit=limit)
        return TagFrequenciesResponse.from_dto(result)

    except Exception as e:
        logging.exception("[Web API] Error getting tag frequencies")
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to get tag frequencies")
        ) from e


@router.get("/mood-distribution", dependencies=[Depends(verify_session)])
async def web_analytics_mood_distribution(
    analytics_service: "AnalyticsService" = Depends(get_analytics_service),
) -> MoodDistributionResponse:
    """Get mood tag distribution."""
    try:
        result = analytics_service.get_mood_distribution_with_result()
        return MoodDistributionResponse.from_dto(result)

    except Exception as e:
        logging.exception("[Web API] Error getting mood distribution")
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to get mood distribution")
        ) from e


@router.get("/tag-correlations", dependencies=[Depends(verify_session)])
async def web_analytics_tag_correlations(
    top_n: int = 20,
    analytics_service: "AnalyticsService" = Depends(get_analytics_service),
) -> TagCorrelationsResponse:
    """
    Get VALUE-based correlation matrix for mood values, genres, and attributes.
    Returns mood-to-mood, mood-to-genre, and mood-to-tier correlations.
    """
    try:
        result_dto = analytics_service.get_tag_correlation_matrix(top_n=top_n)

        # Transform DTO to Pydantic response
        return TagCorrelationsResponse.from_dto(result_dto)

    except Exception as e:
        logging.exception("[Web API] Error getting tag correlations")
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to get tag correlations")
        ) from e


@router.post("/tag-co-occurrences", dependencies=[Depends(verify_session)])
async def web_analytics_tag_co_occurrences(
    request: TagCoOccurrenceRequest,
    analytics_service: "AnalyticsService" = Depends(get_analytics_service),
) -> TagCoOccurrencesResponse:
    """
    Get tag co-occurrence matrix for arbitrary tag sets.

    Computes a matrix where matrix[j][i] = count of files having both x[i] and y[j].
    Maximum 16x16 matrix size. Inputs exceeding limits are trimmed with warning.
    """
    try:
        # Enforce 16x16 limit
        x_tags = request.x_axis[:16]
        y_tags = request.y_axis[:16]

        if len(request.x_axis) > 16 or len(request.y_axis) > 16:
            logging.warning(
                f"[Web API] Tag co-occurrence request exceeded 16x16 limit. "
                f"Trimmed from {len(request.x_axis)}x{len(request.y_axis)} to {len(x_tags)}x{len(y_tags)}"
            )

        # Convert Pydantic models to tuples for service
        x_tuples = [(tag.key, tag.value) for tag in x_tags]
        y_tuples = [(tag.key, tag.value) for tag in y_tags]

        result_dto = analytics_service.get_tag_co_occurrence(x_tags=x_tuples, y_tags=y_tuples)

        # Transform DTO to Pydantic response
        return TagCoOccurrencesResponse.from_dto(result_dto)

    except Exception as e:
        logging.exception("[Web API] Error getting tag co-occurrences")
        raise HTTPException(
            status_code=500, detail=sanitize_exception_message(e, "Failed to get tag co-occurrences")
        ) from e
