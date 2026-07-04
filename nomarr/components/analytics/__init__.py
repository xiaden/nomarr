"""Analytics components — tag frequencies, correlations, and mood distributions.

Provides computation components for library-wide analytics: tag frequency
counts, correlation matrices, mood distribution data, and co-occurrence
statistics. All computations operate on AQL query results from persistence.
"""

# Re-export DTOs from helpers/dto for backward compatibility
from nomarr.helpers.dto.analytics_dto import (
    ArtistTagProfile,
    MoodDistributionData,
    TagCoOccurrenceData,
    TagCorrelationData,
)

from .analytics_comp import (
    compute_artist_tag_profile,
    compute_dominant_vibes,
    compute_mood_distribution,
    compute_tag_co_occurrence,
    compute_tag_correlation_matrix,
    compute_tag_frequencies,
)

__all__ = [
    "ArtistTagProfile",
    "MoodDistributionData",
    "TagCoOccurrenceData",
    "TagCorrelationData",
    "compute_artist_tag_profile",
    "compute_dominant_vibes",
    "compute_mood_distribution",
    "compute_tag_co_occurrence",
    "compute_tag_correlation_matrix",
    "compute_tag_frequencies",
]
