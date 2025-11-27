"""
Analytics API types - Pydantic models for Analytics domain.

External API contracts for analytics endpoints.
These models are thin adapters around DTOs from helpers/dto/analytics_dto.py.

Architecture:
- Response models use .from_dto() to convert DTOs to Pydantic
- Request models use .to_dto() to convert Pydantic to DTOs for service calls
- Services continue using DTOs (no Pydantic imports in services layer)
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from nomarr.helpers.dto.analytics_dto import (
    MoodCoOccurrenceData,
    MoodDistributionItem,
    MoodDistributionResult,
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
        default_factory=list, description="List of tag frequency statistics"
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
        default_factory=list, description="Mood distribution statistics"
    )

    @classmethod
    def from_dto(cls, dto: MoodDistributionResult) -> MoodDistributionResponse:
        """Convert MoodDistributionResult DTO to Pydantic response model."""
        return cls(mood_distribution=[MoodDistributionItemResponse.from_dto(item) for item in dto.mood_distribution])


class TagCorrelationsResponse(BaseModel):
    """Pydantic model for TagCorrelationData DTO."""

    mood_correlations: dict[str, dict[str, float]] = Field(
        default_factory=dict, description="Mood-to-mood correlation matrix"
    )
    mood_tier_correlations: dict[str, dict[str, float]] = Field(
        default_factory=dict, description="Mood-to-tier correlation matrix"
    )

    @classmethod
    def from_dto(cls, dto: TagCorrelationData) -> TagCorrelationsResponse:
        """Convert TagCorrelationData DTO to Pydantic response model."""
        return cls(
            mood_correlations=dto.mood_correlations,
            mood_tier_correlations=dto.mood_tier_correlations,
        )


class MoodCoOccurrenceItemResponse(BaseModel):
    """Single mood co-occurrence entry."""

    mood: str = Field(..., description="Mood value")
    count: int = Field(..., description="Co-occurrence count")
    percentage: float = Field(..., description="Co-occurrence percentage")


class GenreDistributionItemResponse(BaseModel):
    """Single genre distribution entry."""

    genre: str = Field(..., description="Genre name")
    count: int = Field(..., description="Track count")
    percentage: float = Field(..., description="Percentage")


class ArtistDistributionItemResponse(BaseModel):
    """Single artist distribution entry."""

    artist: str = Field(..., description="Artist name")
    count: int = Field(..., description="Track count")
    percentage: float = Field(..., description="Percentage")


class TagCoOccurrencesResponse(BaseModel):
    """Pydantic model for MoodCoOccurrenceData DTO."""

    mood_value: str = Field(..., description="The mood value being analyzed")
    total_occurrences: int = Field(..., description="Total number of occurrences")
    mood_co_occurrences: list[MoodCoOccurrenceItemResponse] = Field(
        default_factory=list, description="Co-occurring moods"
    )
    genre_distribution: list[GenreDistributionItemResponse] = Field(
        default_factory=list, description="Genre distribution for this mood"
    )
    artist_distribution: list[ArtistDistributionItemResponse] = Field(
        default_factory=list, description="Artist distribution for this mood"
    )

    @classmethod
    def from_dto(cls, dto: MoodCoOccurrenceData) -> TagCoOccurrencesResponse:
        """Convert MoodCoOccurrenceData DTO to Pydantic response model."""
        return cls(
            mood_value=dto.mood_value,
            total_occurrences=dto.total_occurrences,
            mood_co_occurrences=[
                MoodCoOccurrenceItemResponse(mood=mood, count=count, percentage=pct)
                for mood, count, pct in dto.mood_co_occurrences
            ],
            genre_distribution=[
                GenreDistributionItemResponse(genre=genre, count=count, percentage=pct)
                for genre, count, pct in dto.genre_distribution
            ],
            artist_distribution=[
                ArtistDistributionItemResponse(artist=artist, count=count, percentage=pct)
                for artist, count, pct in dto.artist_distribution
            ],
        )
