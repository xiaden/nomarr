"""
Analytics package.
"""

from .analytics import (
    compute_artist_tag_profile,
    compute_mood_distribution,
    compute_mood_value_co_occurrences,
    compute_tag_correlation_matrix,
    compute_tag_frequencies,
)

__all__ = [
    "compute_artist_tag_profile",
    "compute_mood_distribution",
    "compute_mood_value_co_occurrences",
    "compute_tag_correlation_matrix",
    "compute_tag_frequencies",
]
