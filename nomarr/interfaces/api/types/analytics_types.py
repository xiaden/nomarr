"""Analytics API types - Pydantic models for Analytics domain.

External API contracts for analytics endpoints.
These models are thin adapters around DTOs from helpers/dto/analytics_dto.py.

Architecture:
- Response models use .from_dto() to convert DTOs to Pydantic
- Request models use .to_dto() to convert Pydantic to DTOs for service calls
- Services continue using DTOs (no Pydantic imports in services layer)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from nomarr.helpers.dto.analytics_dto import (
        MoodDistributionItem,
        MoodDistributionResult,
        TagCoOccurrenceData,
        TagCorrelationData,
        TagFrequenciesResult,
        TagFrequencyItem,
    )

# ──────────────────────────────────────────────────────────────────────
# Response Models
# ──────────────────────────────────────────────────────────────────────


class TagFrequencyItemResponse(BaseModel):
    """Pydantic model for TagFrequencyItem DTO."""

    tag_key: str = Field(..., description="Full tag key (e.g., 'nom:mood_happy')")
    total_count: int = Field(..., description="Total number of tracks with this tag")
    unique_values: int = Field(..., description="Number of unique values for this tag")

    @classmethod
    def from_dto(cls, dto: TagFrequencyItem) -> TagFrequencyItemResponse:
        """Convert TagFrequencyItem DTO to Pydantic response model."""
        return cls(
            tag_key=dto.tag_key,
            total_count=dto.total_count,
            unique_values=dto.unique_values,
        )


class TagFrequenciesResponse(BaseModel):
    """Response for tag frequencies endpoint."""

    tag_frequencies: list[TagFrequencyItemResponse] = Field(
        default_factory=list, description="List of tag frequency statistics",
    )

    @classmethod
    def from_dto(cls, dto: TagFrequenciesResult) -> TagFrequenciesResponse:
        """Convert TagFrequenciesResult DTO to Pydantic response model."""
        return cls(tag_frequencies=[TagFrequencyItemResponse.from_dto(item) for item in dto.tag_frequencies])


class MoodDistributionItemResponse(BaseModel):
    """Pydantic model for MoodDistributionItem DTO."""

    mood: str = Field(..., description="Mood tag value")
    count: int = Field(..., description="Number of tracks with this mood")
    percentage: float = Field(..., description="Percentage of total tracks")

    @classmethod
    def from_dto(cls, dto: MoodDistributionItem) -> MoodDistributionItemResponse:
        """Convert MoodDistributionItem DTO to Pydantic response model."""
        return cls(
            mood=dto.mood,
            count=dto.count,
            percentage=dto.percentage,
        )


class MoodDistributionResponse(BaseModel):
    """Response for mood distribution endpoint."""

    mood_distribution: list[MoodDistributionItemResponse] = Field(
        default_factory=list, description="Mood distribution statistics",
    )

    @classmethod
    def from_dto(cls, dto: MoodDistributionResult) -> MoodDistributionResponse:
        """Convert MoodDistributionResult DTO to Pydantic response model."""
        return cls(mood_distribution=[MoodDistributionItemResponse.from_dto(item) for item in dto.mood_distribution])


class TagCorrelationsResponse(BaseModel):
    """Pydantic model for TagCorrelationData DTO."""

    mood_correlations: dict[str, dict[str, float]] = Field(
        default_factory=dict, description="Mood-to-mood correlation matrix",
    )
    mood_tier_correlations: dict[str, dict[str, float]] = Field(
        default_factory=dict, description="Mood-to-tier correlation matrix",
    )

    @classmethod
    def from_dto(cls, dto: TagCorrelationData) -> TagCorrelationsResponse:
        """Convert TagCorrelationData DTO to Pydantic response model."""
        return cls(
            mood_correlations=dto.mood_correlations,
            mood_tier_correlations=dto.mood_tier_correlations,
        )


class TagSpecRequest(BaseModel):
    """Tag specification for co-occurrence requests."""

    key: str = Field(..., description="Tag key (e.g., 'mood-strict', 'genre')")
    value: str = Field(..., description="Tag value (e.g., 'happy', 'rock')")


class TagCoOccurrenceRequest(BaseModel):
    """Request model for tag co-occurrence matrix."""

    x_axis: list[TagSpecRequest] = Field(..., alias="x", description="X-axis tags (max 16)", max_length=16)
    y_axis: list[TagSpecRequest] = Field(..., alias="y", description="Y-axis tags (max 16)", max_length=16)


class TagCoOccurrencesResponse(BaseModel):
    """Response model for tag co-occurrence matrix."""

    x_axis: list[TagSpecRequest] = Field(..., alias="x", description="X-axis tags")
    y_axis: list[TagSpecRequest] = Field(..., alias="y", description="Y-axis tags")
    matrix: list[list[int]] = Field(..., description="Co-occurrence matrix where matrix[j][i] = count")

    @classmethod
    def from_dto(cls, dto: TagCoOccurrenceData) -> TagCoOccurrencesResponse:
        """Convert TagCoOccurrenceData DTO to Pydantic response model."""
        return cls(
            x=[TagSpecRequest(key=tag.key, value=tag.value) for tag in dto.x_tags],
            y=[TagSpecRequest(key=tag.key, value=tag.value) for tag in dto.y_tags],
            matrix=dto.matrix,
        )



# ──────────────────────────────────────────────────────────────────────
# Collection Profile Response Models
# ──────────────────────────────────────────────────────────────────────


class LibraryStatsResponse(BaseModel):
    """Library aggregate statistics."""

    file_count: int = Field(..., description="Total number of files")
    total_duration_ms: int = Field(..., description="Total duration in milliseconds")
    total_file_size_bytes: int = Field(..., description="Total file size in bytes")
    avg_track_length_ms: float = Field(..., description="Average track length in milliseconds")


class YearDistributionItemResponse(BaseModel):
    """Single year in year distribution."""

    year: int | str = Field(..., description="Year or 'Unknown'")
    count: int = Field(..., description="Number of tracks")


class GenreDistributionItemResponse(BaseModel):
    """Single genre in distribution."""

    genre: str = Field(..., description="Genre name")
    count: int = Field(..., description="Number of tracks")


class ArtistDistributionItemResponse(BaseModel):
    """Single artist in distribution."""

    artist: str = Field(..., description="Artist name")
    count: int = Field(..., description="Number of tracks")


class ArtistDistributionResponse(BaseModel):
    """Artist distribution with long tail count."""

    top_artists: list[ArtistDistributionItemResponse] = Field(
        default_factory=list, description="Top artists by track count",
    )
    others_count: int = Field(..., description="Track count from remaining artists")
    total_artists: int = Field(..., description="Total unique artists")


class CollectionOverviewResponse(BaseModel):
    """Response for collection overview endpoint."""

    stats: LibraryStatsResponse = Field(..., description="Library statistics")
    year_distribution: list[YearDistributionItemResponse] = Field(
        default_factory=list, description="Year distribution",
    )
    genre_distribution: list[GenreDistributionItemResponse] = Field(
        default_factory=list, description="Genre distribution",
    )
    artist_distribution: ArtistDistributionResponse = Field(..., description="Artist distribution")


class MoodCoverageTierResponse(BaseModel):
    """Coverage for a single mood tier."""

    tagged: int = Field(..., description="Number of files with mood tags")
    percentage: float = Field(..., description="Percentage of files tagged")


class MoodCoverageResponse(BaseModel):
    """Mood coverage across all tiers."""

    total_files: int = Field(..., description="Total files in scope")
    tiers: dict[str, MoodCoverageTierResponse] = Field(
        default_factory=dict, description="Coverage per tier (strict, relaxed, genre)",
    )


class MoodBalanceItemResponse(BaseModel):
    """Single mood in balance distribution."""

    mood: str = Field(..., description="Mood value")
    count: int = Field(..., description="Number of tracks")


class MoodPairItemResponse(BaseModel):
    """Co-occurring mood pair."""

    mood1: str = Field(..., description="First mood")
    mood2: str = Field(..., description="Second mood")
    count: int = Field(..., description="Co-occurrence count")


class DominantVibeItemResponse(BaseModel):
    """Dominant mood vibe."""

    mood: str = Field(..., description="Mood value")
    percentage: float = Field(..., description="Percentage of tracks")


class MoodAnalysisResponse(BaseModel):
    """Response for mood analysis endpoint."""

    coverage: MoodCoverageResponse = Field(..., description="Mood coverage statistics")
    balance: dict[str, list[MoodBalanceItemResponse]] = Field(
        default_factory=dict, description="Mood balance per tier",
    )
    top_pairs: list[MoodPairItemResponse] = Field(
        default_factory=list, description="Top co-occurring mood pairs",
    )
    dominant_vibes: list[DominantVibeItemResponse] = Field(
        default_factory=list, description="Dominant mood vibes",
    )
