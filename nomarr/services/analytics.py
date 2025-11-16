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

from typing import TYPE_CHECKING, Any

from nomarr.analytics.analytics import (
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


class AnalyticsService:
    """
    Service for tag analytics and statistics.

    Orchestrates data flow: persistence (SQL) → analytics (computation) → results.
    """

    def __init__(self, db: Database) -> None:
        """
        Initialize analytics service.

        Args:
            db: Database instance for accessing persistence layer
        """
        self._db = db

    def get_tag_frequencies(self, namespace: str = "nom", limit: int = 50) -> dict[str, Any]:
        """
        Get frequency counts for all tags in the library.

        Args:
            namespace: Tag namespace to analyze (default: "nom")
            limit: Max results per category

        Returns:
            dict with nom_tags, standard_tags (artists/genres/albums), total_files
        """
        namespace_prefix = f"{namespace}:"
        data = fetch_tag_frequencies_data(db=self._db, namespace=namespace, limit=limit)
        return compute_tag_frequencies(
            namespace_prefix=namespace_prefix,
            total_files=data["total_files"],
            nom_tag_rows=data["nom_tag_rows"],
            artist_rows=data["artist_rows"],
            genre_rows=data["genre_rows"],
            album_rows=data["album_rows"],
        )

    def get_tag_correlation_matrix(self, namespace: str = "nom", top_n: int = 20) -> dict[str, Any]:
        """
        Compute VALUE-based correlation matrix for mood tags.

        Args:
            namespace: Tag namespace (default: "nom")
            top_n: Number of top moods to analyze

        Returns:
            dict with mood_correlations, mood_genre_correlations, mood_tier_correlations
        """
        data = fetch_tag_correlation_data(db=self._db, namespace=namespace, top_n=top_n)
        return compute_tag_correlation_matrix(
            namespace=namespace,
            top_n=top_n,
            mood_tag_rows=data["mood_tag_rows"],
            tier_tag_keys=data["tier_tag_keys"],
            tier_tag_rows=data["tier_tag_rows"],
        )

    def get_mood_distribution(self, namespace: str = "nom") -> dict[str, Any]:
        """
        Get mood distribution across all tiers.

        Args:
            namespace: Tag namespace (default: "nom")

        Returns:
            dict with mood_strict, mood_regular, mood_loose, top_moods
        """
        mood_rows = fetch_mood_distribution_data(db=self._db, namespace=namespace)
        return compute_mood_distribution(mood_rows=mood_rows)

    def get_artist_tag_profile(self, artist: str, namespace: str = "nom", limit: int = 20) -> dict[str, Any]:
        """
        Get tag profile for a specific artist.

        Args:
            artist: Artist name
            namespace: Tag namespace (default: "nom")
            limit: Max number of top tags to return

        Returns:
            dict with artist, file_count, top_tags, moods, avg_tags_per_file
        """
        namespace_prefix = f"{namespace}:"
        data = fetch_artist_tag_profile_data(db=self._db, artist=artist, namespace=namespace)
        return compute_artist_tag_profile(
            artist=artist,
            file_count=data["file_count"],
            namespace_prefix=namespace_prefix,
            tag_rows=data["tag_rows"],
            limit=limit,
        )

    def get_mood_value_co_occurrences(self, mood_value: str, namespace: str = "nom", limit: int = 20) -> dict[str, Any]:
        """
        Get co-occurrence statistics for a specific mood value.

        Args:
            mood_value: The mood value to analyze
            namespace: Tag namespace (default: "nom")
            limit: Max results per category

        Returns:
            dict with mood_value, total_occurrences, mood_co_occurrences,
                 genre_distribution, artist_distribution
        """
        data = fetch_mood_value_co_occurrence_data(db=self._db, mood_value=mood_value, namespace=namespace)
        return compute_mood_value_co_occurrences(
            mood_value=mood_value,
            matching_file_ids=data["matching_file_ids"],
            mood_tag_rows=data["mood_tag_rows"],
            genre_rows=data["genre_rows"],
            artist_rows=data["artist_rows"],
            limit=limit,
        )
