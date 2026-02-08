"""Analytics domain DTOs.

Data transfer objects for analytics results and statistics.
These form cross-layer contracts between components, services, and interfaces.

Rules:
- Import only stdlib and typing (no nomarr.* imports)
- Pure data structures only (no I/O, no DB access, no business logic)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


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
class TagSpec:
    """Tag specification for co-occurrence queries."""

    key: str  # e.g., "mood-strict", "genre", "artist"
    value: str  # e.g., "happy", "rock", "Beatles"


@dataclass
class TagCoOccurrenceData:
    """Domain result for generic tag co-occurrence analysis."""

    x_tags: list[TagSpec]  # X-axis tags
    y_tags: list[TagSpec]  # Y-axis tags
    matrix: list[list[int]]  # matrix[j][i] = count of files with both x_tags[i] and y_tags[j]


# ──────────────────────────────────────────────────────────────────────
# Parameter DTOs (for simplifying function signatures)
# ──────────────────────────────────────────────────────────────────────


@dataclass
class ComputeTagCorrelationMatrixParams:
    """Parameters for compute_tag_correlation_matrix."""

    namespace: str
    top_n: int
    mood_tag_rows: Sequence[tuple[int, str]]  # (file_id, tag_value) - tag_value is JSON array string
    tier_tag_keys: Sequence[str]
    tier_tag_rows: dict[str, Sequence[tuple[int, str]]]


@dataclass
class ComputeTagFrequenciesParams:
    """Parameters for compute_tag_frequencies."""

    namespace_prefix: str
    total_files: int
    nom_tag_rows: Sequence[tuple[str, int]]
    artist_rows: Sequence[tuple[str, int]]
    genre_rows: Sequence[tuple[str, int]]
    album_rows: Sequence[tuple[str, int]]


@dataclass
class ComputeArtistTagProfileParams:
    """Parameters for compute_artist_tag_profile."""

    artist: str
    file_count: int
    namespace_prefix: str
    tag_rows: Sequence[tuple[str, str]]  # (tag_key, tag_value) - tag_value is JSON array string
    limit: int


@dataclass
class ComputeTagCoOccurrenceParams:
    """Parameters for compute_tag_co_occurrence."""

    x_tags: list[TagSpec]
    y_tags: list[TagSpec]
    tag_data: dict[tuple[str, str], set[str]]  # (key, value) -> set of file_ids (ArangoDB _id)


# ──────────────────────────────────────────────────────────────────────
# Result DTOs
# ──────────────────────────────────────────────────────────────────────


@dataclass
class ComputeTagFrequenciesResult:
    """Result from compute_tag_frequencies."""

    nom_tags: list[tuple[str, int]]  # (tag, count)
    standard_tags: dict[str, list[tuple[str, int]]]  # {category: [(name, count)]}
    total_files: int


# ──────────────────────────────────────────────────────────────────────
# Service-layer DTOs for API responses
# ──────────────────────────────────────────────────────────────────────


@dataclass
class TagFrequencyItem:
    """Single tag frequency item from analytics_svc.get_tag_frequencies."""

    tag_key: str
    total_count: int
    unique_values: int


@dataclass
class MoodDistributionItem:
    """Single mood distribution item from analytics_svc.get_mood_distribution."""

    mood: str
    count: int
    percentage: float


@dataclass
class TagFrequenciesResult:
    """Wrapper result from analytics_svc.get_tag_frequencies_with_result."""

    tag_frequencies: list[TagFrequencyItem]


@dataclass
class MoodDistributionResult:
    """Wrapper result from analytics_svc.get_mood_distribution_with_result."""

    mood_distribution: list[MoodDistributionItem]



# ──────────────────────────────────────────────────────────────────────────────
# Collection Profile Analytics DTOs
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class LibraryStatsResult:
    """Library aggregate statistics."""

    file_count: int
    total_duration_ms: int
    total_file_size_bytes: int
    avg_track_length_ms: float


@dataclass
class YearDistributionItem:
    """Single year in year distribution."""

    year: int | str
    count: int


@dataclass
class GenreDistributionItem:
    """Single genre in genre distribution."""

    genre: str
    count: int


@dataclass
class ArtistDistributionItem:
    """Single artist in artist distribution."""

    artist: str
    count: int


@dataclass
class ArtistDistributionResult:
    """Artist distribution with long tail count."""

    top_artists: list[ArtistDistributionItem]
    others_count: int
    total_artists: int


@dataclass
class CollectionOverviewResult:
    """Result from analytics_svc.get_collection_overview."""

    stats: LibraryStatsResult
    year_distribution: list[YearDistributionItem]
    genre_distribution: list[GenreDistributionItem]
    artist_distribution: ArtistDistributionResult


@dataclass
class MoodCoverageTier:
    """Coverage data for a single mood tier."""

    tagged: int
    percentage: float


@dataclass
class MoodCoverageResult:
    """Mood coverage across all tiers."""

    total_files: int
    tiers: dict[str, MoodCoverageTier]


@dataclass
class MoodBalanceItem:
    """Single mood in balance distribution."""

    mood: str
    count: int


@dataclass
class MoodPairItem:
    """Co-occurring mood pair."""

    mood1: str
    mood2: str
    count: int


@dataclass
class DominantVibeItem:
    """Dominant mood vibe."""

    mood: str
    percentage: float


@dataclass
class MoodAnalysisResult:
    """Result from analytics_svc.get_mood_analysis."""

    coverage: MoodCoverageResult
    balance: dict[str, list[MoodBalanceItem]]
    top_pairs: list[MoodPairItem]
    dominant_vibes: list[DominantVibeItem]
