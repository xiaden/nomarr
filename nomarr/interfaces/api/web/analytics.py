"""Analytics endpoints for web UI."""

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_analytics_service

if TYPE_CHECKING:
    from nomarr.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("/tag-frequencies", dependencies=[Depends(verify_session)])
async def web_analytics_tag_frequencies(
    limit: int = 50,
    analytics_service: "AnalyticsService" = Depends(get_analytics_service),
) -> dict[str, Any]:
    """Get tag frequency statistics."""
    try:
        tag_frequencies = analytics_service.get_tag_frequencies(limit=limit)
        return {"tag_frequencies": tag_frequencies}
    except Exception as e:
        logging.exception("[Web API] Error getting tag frequencies")
        raise HTTPException(status_code=500, detail=f"Error getting tag frequencies: {e}") from e


@router.get("/mood-distribution", dependencies=[Depends(verify_session)])
async def web_analytics_mood_distribution(
    analytics_service: "AnalyticsService" = Depends(get_analytics_service),
) -> dict[str, Any]:
    """Get mood tag distribution."""
    try:
        mood_distribution = analytics_service.get_mood_distribution()
        return {"mood_distribution": mood_distribution}
    except Exception as e:
        logging.exception("[Web API] Error getting mood distribution")
        raise HTTPException(status_code=500, detail=f"Error getting mood distribution: {e}") from e


@router.get("/tag-correlations", dependencies=[Depends(verify_session)])
async def web_analytics_tag_correlations(
    top_n: int = 20,
    analytics_service: "AnalyticsService" = Depends(get_analytics_service),
) -> dict[str, Any]:
    """
    Get VALUE-based correlation matrix for mood values, genres, and attributes.
    Returns mood-to-mood, mood-to-genre, and mood-to-tier correlations.
    """
    try:
        result = analytics_service.get_tag_correlation_matrix(top_n=top_n)
        return result
    except Exception as e:
        logging.exception("[Web API] Error getting tag correlations")
        raise HTTPException(status_code=500, detail=f"Error getting tag correlations: {e}") from e


@router.get("/tag-co-occurrences/{tag}", dependencies=[Depends(verify_session)])
async def web_analytics_tag_co_occurrences(
    tag: str,
    limit: int = 10,
    analytics_service: "AnalyticsService" = Depends(get_analytics_service),
) -> dict[str, Any]:
    """
    Get mood value co-occurrences and genre/artist relationships.
    Shows which moods appear together and what genres/artists correlate with a mood.
    """
    try:
        result = analytics_service.get_mood_value_co_occurrences(mood_value=tag, limit=limit)
        return result

    except Exception as e:
        logging.exception("[Web API] Error getting tag co-occurrences")
        raise HTTPException(status_code=500, detail=f"Error getting tag co-occurrences: {e}") from e
