"""
Persistence package.
"""

from .analytics_queries import (
    fetch_artist_tag_profile_data,
    fetch_mood_distribution_data,
    fetch_mood_value_co_occurrence_data,
    fetch_tag_correlation_data,
    fetch_tag_frequencies_data,
)
from .db import SCHEMA, SCHEMA_VERSION, Database, now_ms

__all__ = [
    "SCHEMA",
    "SCHEMA_VERSION",
    "Database",
    "fetch_artist_tag_profile_data",
    "fetch_mood_distribution_data",
    "fetch_mood_value_co_occurrence_data",
    "fetch_tag_correlation_data",
    "fetch_tag_frequencies_data",
    "now_ms",
]
