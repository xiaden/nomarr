"""
Analytics domain DTOs.

Data transfer objects for analytics results and statistics.
These form cross-layer contracts between components, services, and interfaces.

Rules:
- Import only stdlib and typing (no nomarr.* imports)
- Pure data structures only (no I/O, no DB access, no business logic)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TagCorrelationData:
    """Domain result for tag correlation analysis."""

    mood_correlations: dict[str, dict[str, float]]
    mood_tier_correlations: dict[str, dict[str, float]]


@dataclass
class MoodDistributionData:
    """Domain result for mood distribution analysis."""

    mood_strict: dict[str, int]
    mood_regular: dict[str, int]
    mood_loose: dict[str, int]
    top_moods: list[tuple[str, int]]


@dataclass
class ArtistTagProfile:
    """Domain result for artist tag profile."""

    artist: str
    file_count: int
    top_tags: list[tuple[str, int, float]]  # (tag, count, avg_value)
    moods: list[tuple[str, int]]
    avg_tags_per_file: float


@dataclass
class MoodCoOccurrenceData:
    """Domain result for mood co-occurrence analysis."""

    mood_value: str
    total_occurrences: int
    mood_co_occurrences: list[tuple[str, int, float]]  # (mood, count, percentage)
    genre_distribution: list[tuple[str, int, float]]  # (genre, count, percentage)
    artist_distribution: list[tuple[str, int, float]]  # (artist, count, percentage)
