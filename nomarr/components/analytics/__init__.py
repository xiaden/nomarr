"""Analytics package."""

# Re-export DTOs from helpers/dto for backward compatibility
from nomarr.helpers.dto.analytics_dto import (
    ArtistTagProfile,
    MoodDistributionData,
    TagCoOccurrenceData,
    TagCorrelationData,
)

from .analytics_comp import (
    compute_artist_tag_profile,
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
    "compute_mood_distribution",
    "compute_tag_co_occurrence",
    "compute_tag_correlation_matrix",
    "compute_tag_frequencies",
]
