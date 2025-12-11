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
from typing import TYPE_CHECKING, cast

from nomarr.components.analytics.analytics_comp import (
    compute_mood_distribution,
    compute_mood_value_co_occurrences,
    compute_tag_correlation_matrix,
    compute_tag_frequencies,
)
from nomarr.helpers.dto.analytics_dto import (
    ComputeMoodValueCoOccurrencesParams,
    ComputeTagCorrelationMatrixParams,
    ComputeTagFrequenciesParams,
    MoodCoOccurrenceData,
    MoodDistributionItem,
    MoodDistributionResult,
    TagCorrelationData,
    TagFrequenciesResult,
    TagFrequencyItem,
)
from nomarr.persistence.analytics_queries import (
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

    def get_tag_frequencies(self, limit: int = 50) -> list[TagFrequencyItem]:
        """
        Get frequency counts for tag VALUES in the library (API-ready format).

        Returns counts for mood values (e.g., "happy", "dark"), not tag keys.

        Args:
            limit: Max results per category

        Returns:
            List of TagFrequencyItem DTOs for frontend
        """
        namespace_prefix = f"{self.cfg.namespace}:"
        data = fetch_tag_frequencies_data(db=self._db, namespace=self.cfg.namespace, limit=limit)
        params = ComputeTagFrequenciesParams(
            namespace_prefix=namespace_prefix,
            total_files=data["total_files"],
            nom_tag_rows=data["nom_tag_rows"],
            artist_rows=data["artist_rows"],
            genre_rows=data["genre_rows"],
            album_rows=data["album_rows"],
        )
        result = compute_tag_frequencies(params=params)

        # nom_tags now contains (tag_key:tag_value, count) tuples
        # Return with namespace prefix for display
        return [
            TagFrequencyItem(
                tag_key=f"{self.cfg.namespace}:{tag}",  # tag is already "key:value"
                total_count=count,
                unique_values=1,  # Each entry is one unique value
            )
            for tag, count in result.nom_tags
        ]

    def get_tag_frequencies_with_result(self, limit: int = 50) -> TagFrequenciesResult:
        """
        Get frequency counts for all tags with wrapper DTO.

        Args:
            limit: Max results per category

        Returns:
            TagFrequenciesResult DTO with tag_frequencies list
        """
        tag_frequencies = self.get_tag_frequencies(limit=limit)
        return TagFrequenciesResult(tag_frequencies=tag_frequencies)

    def get_tag_correlation_matrix(self, top_n: int = 20) -> TagCorrelationData:
        """
        Compute VALUE-based correlation matrix for mood tags.

        Args:
            top_n: Number of top moods to analyze

        Returns:
            TagCorrelationData with mood-to-mood and mood-to-tier correlations
        """
        data = fetch_tag_correlation_data(db=self._db, namespace=self.cfg.namespace, top_n=top_n)
        params = ComputeTagCorrelationMatrixParams(
            namespace=self.cfg.namespace,
            top_n=top_n,
            mood_tag_rows=data["mood_tag_rows"],
            tier_tag_keys=data["tier_tag_keys"],
            tier_tag_rows=data["tier_tag_rows"],
        )
        return cast(TagCorrelationData, compute_tag_correlation_matrix(params=params))

    def get_mood_distribution(self) -> list[MoodDistributionItem]:
        """
        Get mood distribution across all tiers.

        Returns:
            List of MoodDistributionItem DTOs
        """
        mood_rows = fetch_mood_distribution_data(db=self._db, namespace=self.cfg.namespace)
        result = compute_mood_distribution(mood_rows=mood_rows)

        # Transform to list format with percentages
        top_moods = result.top_moods
        total_moods = sum(count for _, count in top_moods)

        return [
            MoodDistributionItem(
                mood=mood,
                count=count,
                percentage=round((count / total_moods * 100), 2) if total_moods > 0 else 0,
            )
            for mood, count in top_moods
        ]

    def get_mood_distribution_with_result(self) -> MoodDistributionResult:
        """
        Get mood distribution with wrapper DTO.

        Returns:
            MoodDistributionResult DTO with mood_distribution list
        """
        mood_distribution = self.get_mood_distribution()
        return MoodDistributionResult(mood_distribution=mood_distribution)

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
        params = ComputeMoodValueCoOccurrencesParams(
            mood_value=mood_value,
            matching_file_ids=data["matching_file_ids"],
            mood_tag_rows=data["mood_tag_rows"],
            genre_rows=data["genre_rows"],
            artist_rows=data["artist_rows"],
            limit=limit,
        )
        return cast(MoodCoOccurrenceData, compute_mood_value_co_occurrences(params=params))
