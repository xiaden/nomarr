"""Analytics endpoints for web UI."""

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from typing_extensions import TypedDict

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_analytics_service

if TYPE_CHECKING:
    from nomarr.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["Analytics"])


# ──────────────────────────────────────────────────────────────────────
# Response Types (HTTP/JSON Shapes Owned by Interface Layer)
# ──────────────────────────────────────────────────────────────────────


class TagFrequencyItem(TypedDict):
    """A single tag frequency entry."""

    tag_key: str
    total_count: int
    unique_values: int


class TagFrequenciesResponse(TypedDict):
    """Response for tag frequencies endpoint."""

    tag_frequencies: list[TagFrequencyItem]


class MoodDistributionItem(TypedDict):
    """A single mood distribution entry."""

    mood: str
    count: int
    percentage: float


class MoodDistributionResponse(TypedDict):
    """Response for mood distribution endpoint."""

    mood_distribution: list[MoodDistributionItem]


class TagCorrelationsResponse(TypedDict):
    """Response for tag correlations endpoint."""

    mood_correlations: dict[str, dict[str, float]]
    mood_tier_correlations: dict[str, dict[str, float]]


class MoodCoOccurrence(TypedDict):
    """A mood co-occurrence entry (mood, count, percentage)."""

    mood: str
    count: int
    percentage: float


class GenreDistribution(TypedDict):
    """A genre distribution entry (genre, count, percentage)."""

    genre: str
    count: int
    percentage: float


class ArtistDistribution(TypedDict):
    """An artist distribution entry (artist, count, percentage)."""

    artist: str
    count: int
    percentage: float


class TagCoOccurrencesResponse(TypedDict):
    """Response for tag co-occurrences endpoint."""

    mood_value: str
    total_occurrences: int
    mood_co_occurrences: list[MoodCoOccurrence]
    genre_distribution: list[GenreDistribution]
    artist_distribution: list[ArtistDistribution]


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
        tag_frequencies_data = analytics_service.get_tag_frequencies(limit=limit)
        # Convert to typed response
        tag_frequencies: list[TagFrequencyItem] = [
            TagFrequencyItem(
                tag_key=item["tag_key"],
                total_count=item["total_count"],
                unique_values=item["unique_values"],
            )
            for item in tag_frequencies_data
        ]
        response: TagFrequenciesResponse = {"tag_frequencies": tag_frequencies}
        return response
    except Exception as e:
        logging.exception("[Web API] Error getting tag frequencies")
        raise HTTPException(status_code=500, detail=f"Error getting tag frequencies: {e}") from e


@router.get("/mood-distribution", dependencies=[Depends(verify_session)])
async def web_analytics_mood_distribution(
    analytics_service: "AnalyticsService" = Depends(get_analytics_service),
) -> MoodDistributionResponse:
    """Get mood tag distribution."""
    try:
        mood_distribution = analytics_service.get_mood_distribution()
        response: MoodDistributionResponse = {"mood_distribution": mood_distribution}  # type: ignore[typeddict-item]
        return response
    except Exception as e:
        logging.exception("[Web API] Error getting mood distribution")
        raise HTTPException(status_code=500, detail=f"Error getting mood distribution: {e}") from e


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
        result = analytics_service.get_tag_correlation_matrix(top_n=top_n)
        # Map dataclass to response shape
        response: TagCorrelationsResponse = {
            "mood_correlations": result.mood_correlations,
            "mood_tier_correlations": result.mood_tier_correlations,
        }
        return response
    except Exception as e:
        logging.exception("[Web API] Error getting tag correlations")
        raise HTTPException(status_code=500, detail=f"Error getting tag correlations: {e}") from e


@router.get("/tag-co-occurrences/{tag}", dependencies=[Depends(verify_session)])
async def web_analytics_tag_co_occurrences(
    tag: str,
    limit: int = 10,
    analytics_service: "AnalyticsService" = Depends(get_analytics_service),
) -> TagCoOccurrencesResponse:
    """
    Get mood value co-occurrences and genre/artist relationships.
    Shows which moods appear together and what genres/artists correlate with a mood.
    """
    try:
        result = analytics_service.get_mood_value_co_occurrences(mood_value=tag, limit=limit)
        # Map dataclass to response shape
        response: TagCoOccurrencesResponse = {
            "mood_value": result.mood_value,
            "total_occurrences": result.total_occurrences,
            "mood_co_occurrences": [
                {"mood": mood, "count": count, "percentage": pct} for mood, count, pct in result.mood_co_occurrences
            ],
            "genre_distribution": [
                {"genre": genre, "count": count, "percentage": pct} for genre, count, pct in result.genre_distribution
            ],
            "artist_distribution": [
                {"artist": artist, "count": count, "percentage": pct}
                for artist, count, pct in result.artist_distribution
            ],
        }
        return response

    except Exception as e:
        logging.exception("[Web API] Error getting tag co-occurrences")
        raise HTTPException(status_code=500, detail=f"Error getting tag co-occurrences: {e}") from e
