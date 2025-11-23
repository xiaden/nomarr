"""
Analytics service - orchestrates between persistence and analytics layers.

ARCHITECTURE:
- Fetches raw data from persistence layer (nomarr.persistence.analytics_queries)
- Passes data to analytics layer for computation (nomarr.analytics.analytics)
- Returns formatted results to interface layer

This service maintains the original API signatures for backward compatibility
while properly separating persistence (SQL) from computation (analytics).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nomarr.components.analytics.analytics import (
    ArtistTagProfile,
    MoodCoOccurrenceData,
    TagCorrelationData,
    compute_artist_tag_profile,
    compute_mood_distribution,
    compute_mood_value_co_occurrences,
    compute_tag_correlation_matrix,
    compute_tag_frequencies,
)
from nomarr.persistence.analytics_queries import (
    fetch_artist_tag_profile_data,
    fetch_mood_distribution_data,
    fetch_mood_value_co_occurrence_data,
    fetch_tag_correlation_data,
    fetch_tag_frequencies_data,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


@dataclass
class AnalyticsConfig:
    """Configuration for AnalyticsService."""

    namespace: str


class AnalyticsService:
    """
    Service for tag analytics and statistics.

    Orchestrates data flow: persistence (SQL) → analytics (computation) → API-ready results.
    """

    def __init__(self, db: Database, cfg: AnalyticsConfig) -> None:
        """
        Initialize analytics service.

        Args:
            db: Database instance for accessing persistence layer
            cfg: Analytics configuration
        """
        self._db = db
        self.cfg = cfg

    def get_tag_frequencies(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        Get frequency counts for all tags in the library (API-ready format).

        Args:
            limit: Max results per category

        Returns:
            List of dicts with tag_key, total_count, unique_values for frontend
        """
        namespace_prefix = f"{self.cfg.namespace}:"
        data = fetch_tag_frequencies_data(db=self._db, namespace=self.cfg.namespace, limit=limit)
        result = compute_tag_frequencies(
            namespace_prefix=namespace_prefix,
            total_files=data["total_files"],
            nom_tag_rows=data["nom_tag_rows"],
            artist_rows=data["artist_rows"],
            genre_rows=data["genre_rows"],
            album_rows=data["album_rows"],
        )

        # Transform to API-ready format (add namespace prefix back for display)
        tag_frequencies = [
            {"tag_key": f"{self.cfg.namespace}:{tag}", "total_count": count, "unique_values": count}
            for tag, count in result.get("nom_tags", [])
        ]
        return tag_frequencies

    def get_tag_correlation_matrix(self, top_n: int = 20) -> TagCorrelationData:
        """
        Compute VALUE-based correlation matrix for mood tags.

        Args:
            top_n: Number of top moods to analyze

        Returns:
            TagCorrelationData with mood-to-mood and mood-to-tier correlations
        """
        data = fetch_tag_correlation_data(db=self._db, namespace=self.cfg.namespace, top_n=top_n)
        return compute_tag_correlation_matrix(
            namespace=self.cfg.namespace,
            top_n=top_n,
            mood_tag_rows=data["mood_tag_rows"],
            tier_tag_keys=data["tier_tag_keys"],
            tier_tag_rows=data["tier_tag_rows"],
        )

    def get_mood_distribution(self) -> list[dict[str, Any]]:
        """
        Get mood distribution across all tiers.

        Returns:
            List of mood distribution entries (mood, count, percentage)
        """
        mood_rows = fetch_mood_distribution_data(db=self._db, namespace=self.cfg.namespace)
        result = compute_mood_distribution(mood_rows=mood_rows)

        # Transform to list format with percentages
        top_moods = result.top_moods
        total_moods = sum(count for _, count in top_moods)

        mood_distribution = [
            {
                "mood": mood,
                "count": count,
                "percentage": round((count / total_moods * 100), 2) if total_moods > 0 else 0,
            }
            for mood, count in top_moods
        ]
        return mood_distribution

    def get_artist_tag_profile(self, artist: str, limit: int = 20) -> ArtistTagProfile:
        """
        Get tag profile for a specific artist.

        Args:
            artist: Artist name
            limit: Max number of top tags to return

        Returns:
            ArtistTagProfile with artist info, top tags, and mood statistics
        """
        namespace_prefix = f"{self.cfg.namespace}:"
        data = fetch_artist_tag_profile_data(db=self._db, artist=artist, namespace=self.cfg.namespace)
        return compute_artist_tag_profile(
            artist=artist,
            file_count=data["file_count"],
            namespace_prefix=namespace_prefix,
            tag_rows=data["tag_rows"],
            limit=limit,
        )

    def get_mood_value_co_occurrences(self, mood_value: str, limit: int = 10) -> MoodCoOccurrenceData:
        """
        Get co-occurrence statistics for a specific mood value.

        Args:
            mood_value: The mood value to analyze
            limit: Max results per category

        Returns:
            MoodCoOccurrenceData with co-occurrence patterns and distributions
        """
        data = fetch_mood_value_co_occurrence_data(db=self._db, mood_value=mood_value, namespace=self.cfg.namespace)
        result = compute_mood_value_co_occurrences(
            mood_value=mood_value,
            matching_file_ids=data["matching_file_ids"],
            mood_tag_rows=data["mood_tag_rows"],
            genre_rows=data["genre_rows"],
            artist_rows=data["artist_rows"],
            limit=limit,
        )
        return result
