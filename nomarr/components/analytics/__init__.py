"""
Analytics package.
"""

from .analytics import (
    ArtistTagProfile,
    MoodCoOccurrenceData,
    MoodDistributionData,
    TagCorrelationData,
    compute_artist_tag_profile,
    compute_mood_distribution,
    compute_mood_value_co_occurrences,
    compute_tag_correlation_matrix,
    compute_tag_frequencies,
)

__all__ = [
    "ArtistTagProfile",
    "MoodCoOccurrenceData",
    "MoodDistributionData",
    "TagCorrelationData",
    "compute_artist_tag_profile",
    "compute_mood_distribution",
    "compute_mood_value_co_occurrences",
    "compute_tag_correlation_matrix",
    "compute_tag_frequencies",
]
