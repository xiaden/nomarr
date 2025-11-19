"""Analytics endpoints for web UI."""

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_database

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("/tag-frequencies", dependencies=[Depends(verify_session)])
async def web_analytics_tag_frequencies(
    limit: int = 50,
    db: Database = Depends(get_database),
) -> dict[str, Any]:
    """Get tag frequency statistics."""
    try:
        from nomarr.app import application
        from nomarr.services.analytics import AnalyticsService

        namespace = application.namespace
        analytics_service = AnalyticsService(db)
        result = analytics_service.get_tag_frequencies(namespace=namespace, limit=limit)

        # Transform to format expected by frontend
        # Backend returns: {"nom_tags": [(tag, count), ...], ...} (tags without namespace prefix)
        # Frontend expects: {"tag_frequencies": [{"tag_key": tag, "total_count": count}, ...]}
        # Add namespace prefix back for display
        tag_frequencies = [
            {"tag_key": f"{namespace}:{tag}", "total_count": count, "unique_values": count}
            for tag, count in result.get("nom_tags", [])
        ]

        return {"tag_frequencies": tag_frequencies}

    except Exception as e:
        logging.exception("[Web API] Error getting tag frequencies")
        raise HTTPException(status_code=500, detail=f"Error getting tag frequencies: {e}") from e


@router.get("/mood-distribution", dependencies=[Depends(verify_session)])
async def web_analytics_mood_distribution(
    db: Database = Depends(get_database),
) -> dict[str, Any]:
    """Get mood tag distribution."""
    try:
        from nomarr.app import application
        from nomarr.services.analytics import AnalyticsService

        namespace = application.namespace
        analytics_service = AnalyticsService(db)
        result = analytics_service.get_mood_distribution(namespace=namespace)

        # Transform to format expected by frontend
        # Backend returns: {"top_moods": [(mood, count), ...], ...}
        # Frontend expects: {"mood_distribution": [{"mood": mood, "count": count, "percentage": %}, ...]}
        top_moods = result.get("top_moods", [])
        total_moods = sum(count for _, count in top_moods)

        mood_distribution = [
            {
                "mood": mood,
                "count": count,
                "percentage": round((count / total_moods * 100), 2) if total_moods > 0 else 0,
            }
            for mood, count in top_moods
        ]

        return {"mood_distribution": mood_distribution}

    except Exception as e:
        logging.exception("[Web API] Error getting mood distribution")
        raise HTTPException(status_code=500, detail=f"Error getting mood distribution: {e}") from e


@router.get("/tag-correlations", dependencies=[Depends(verify_session)])
async def web_analytics_tag_correlations(
    top_n: int = 20,
    db: Database = Depends(get_database),
) -> dict[str, Any]:
    """
    Get VALUE-based correlation matrix for mood values, genres, and attributes.
    Returns mood-to-mood, mood-to-genre, and mood-to-tier correlations.
    """
    try:
        from nomarr.app import application
        from nomarr.services.analytics import AnalyticsService

        namespace = application.namespace
        analytics_service = AnalyticsService(db)
        result = analytics_service.get_tag_correlation_matrix(namespace=namespace, top_n=top_n)
        return result

    except Exception as e:
        logging.exception("[Web API] Error getting tag correlations")
        raise HTTPException(status_code=500, detail=f"Error getting tag correlations: {e}") from e


@router.get("/tag-co-occurrences/{tag}", dependencies=[Depends(verify_session)])
async def web_analytics_tag_co_occurrences(
    tag: str,
    limit: int = 10,
    db: Database = Depends(get_database),
) -> dict[str, Any]:
    """
    Get mood value co-occurrences and genre/artist relationships.
    Shows which moods appear together and what genres/artists correlate with a mood.
    """
    try:
        from nomarr.app import application
        from nomarr.services.analytics import AnalyticsService

        namespace = application.namespace
        analytics_service = AnalyticsService(db)

        # Mood value co-occurrence analysis
        result = analytics_service.get_mood_value_co_occurrences(mood_value=tag, namespace=namespace, limit=limit)

        # Transform to frontend format
        co_occurrences = [
            {"tag": mood, "count": count, "percentage": pct} for mood, count, pct in result["mood_co_occurrences"]
        ]

        top_artists = [
            {"name": artist, "count": count, "percentage": pct} for artist, count, pct in result["artist_distribution"]
        ]

        top_genres = [
            {"name": genre, "count": count, "percentage": pct} for genre, count, pct in result["genre_distribution"]
        ]

        return {
            "tag": tag,
            "total_occurrences": result["total_occurrences"],
            "co_occurrences": co_occurrences,
            "top_artists": top_artists,
            "top_genres": top_genres,
            "limit": limit,
        }

    except Exception as e:
        logging.exception("[Web API] Error getting tag co-occurrences")
        raise HTTPException(status_code=500, detail=f"Error getting tag co-occurrences: {e}") from e
