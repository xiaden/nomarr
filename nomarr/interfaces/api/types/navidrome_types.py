"""
Navidrome API types - Pydantic models for Navidrome domain.

External API contracts for Navidrome integration endpoints.
These models are thin adapters around DTOs from helpers/dto/navidrome_dto.py.

Architecture:
- Response models use .from_dto() to convert DTOs to Pydantic
- Request models use .to_dto() to convert Pydantic to DTOs for service calls
- Services continue using DTOs (no Pydantic imports in services layer)
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from nomarr.helpers.dto.navidrome_dto import (
    GeneratePlaylistResult,
    GetTemplateSummaryResult,
    PlaylistPreviewResult,
    PreviewTagStatsResult,
    SmartPlaylistFilter,
    TagCondition,
    TemplateSummaryItem,
)

# ──────────────────────────────────────────────────────────────────────
# Response Models
# ──────────────────────────────────────────────────────────────────────


class TagConditionResponse(BaseModel):
    """Pydantic model for TagCondition DTO."""

    tag_key: str = Field(..., description="Full tag key with namespace (e.g., 'nom:mood_happy')")
    operator: Literal[">", "<", ">=", "<=", "=", "!=", "contains"] = Field(..., description="Comparison operator")
    value: float | int | str = Field(..., description="Value to compare against")

    @classmethod
    def from_dto(cls, dto: TagCondition) -> TagConditionResponse:
        """Convert TagCondition DTO to Pydantic response model."""
        return cls(
            tag_key=dto.tag_key,
            operator=dto.operator,
            value=dto.value,
        )


class SmartPlaylistFilterResponse(BaseModel):
    """Pydantic model for SmartPlaylistFilter DTO."""

    all_conditions: list[TagConditionResponse] = Field(
        default_factory=list, description="Conditions joined by AND (all must match)"
    )
    any_conditions: list[TagConditionResponse] = Field(
        default_factory=list, description="Conditions joined by OR (any must match)"
    )

    @classmethod
    def from_dto(cls, dto: SmartPlaylistFilter) -> SmartPlaylistFilterResponse:
        """Convert SmartPlaylistFilter DTO to Pydantic response model."""
        return cls(
            all_conditions=[TagConditionResponse.from_dto(c) for c in dto.all_conditions],
            any_conditions=[TagConditionResponse.from_dto(c) for c in dto.any_conditions],
        )


class PlaylistPreviewResponse(BaseModel):
    """Pydantic model for PlaylistPreviewResult DTO."""

    total_count: int = Field(..., description="Total number of tracks matching the query")
    sample_tracks: list[dict[str, str]] = Field(
        default_factory=list, description="Sample of matching tracks (path, title, artist, album)"
    )
    query: str = Field(..., description="Original query string")

    @classmethod
    def from_dto(cls, dto: PlaylistPreviewResult) -> PlaylistPreviewResponse:
        """Convert PlaylistPreviewResult DTO to Pydantic response model."""
        return cls(
            total_count=dto.total_count,
            sample_tracks=dto.sample_tracks,
            query=dto.query,
        )


class PreviewTagStatsResponse(BaseModel):
    """Pydantic model for PreviewTagStatsResult DTO."""

    stats: dict[str, dict[str, str | int | float]] = Field(
        default_factory=dict, description="Tag statistics keyed by tag name"
    )

    @classmethod
    def from_dto(cls, dto: PreviewTagStatsResult) -> PreviewTagStatsResponse:
        """Convert PreviewTagStatsResult DTO to Pydantic response model."""
        return cls(stats=dto.stats)


class NavidromeConfigResponse(BaseModel):
    """Pydantic model for Navidrome TOML configuration response."""

    config: str = Field(..., description="TOML configuration content")

    @classmethod
    def from_toml(cls, toml_content: str) -> NavidromeConfigResponse:
        """Create response from TOML string content."""
        return cls(config=toml_content)


class GeneratePlaylistResponse(BaseModel):
    """Pydantic model for GeneratePlaylistResult DTO."""

    playlist_structure: dict[str, str | int | list[dict[str, str]]] = Field(
        ..., description="Navidrome .nsp playlist structure"
    )

    @classmethod
    def from_dto(cls, dto: GeneratePlaylistResult) -> GeneratePlaylistResponse:
        """Convert GeneratePlaylistResult DTO to Pydantic response model."""
        return cls(playlist_structure=dto.playlist_structure)


class TemplateSummaryItemResponse(BaseModel):
    """Pydantic model for TemplateSummaryItem DTO."""

    template_id: str = Field(..., description="Template ID")
    name: str = Field(..., description="Template display name")
    description: str = Field(..., description="Template description")

    @classmethod
    def from_dto(cls, dto: TemplateSummaryItem) -> TemplateSummaryItemResponse:
        """Convert TemplateSummaryItem DTO to Pydantic response model."""
        return cls(
            id=dto.id,
            name=dto.name,
            description=dto.description,
        )


class GetTemplateSummaryResponse(BaseModel):
    """Pydantic model for GetTemplateSummaryResult DTO."""

    templates: list[TemplateSummaryItemResponse] = Field(
        default_factory=list, description="List of available templates"
    )

    @classmethod
    def from_dto(cls, dto: GetTemplateSummaryResult) -> GetTemplateSummaryResponse:
        """Convert GetTemplateSummaryResult DTO to Pydantic response model."""
        return cls(templates=[TemplateSummaryItemResponse.from_dto(t) for t in dto.templates])


class GenerateTemplateFilesResponse(BaseModel):
    """Response for template file generation."""

    files_generated: dict[str, str] = Field(default_factory=dict, description="Map of template_id -> file_path")


# ──────────────────────────────────────────────────────────────────────
# Request Models
# ──────────────────────────────────────────────────────────────────────


class PlaylistPreviewRequest(BaseModel):
    """Request model for playlist preview."""

    query: str = Field(..., min_length=1, description="Smart playlist query string")
    preview_limit: int = Field(10, ge=1, le=100, description="Number of sample tracks to return")


class PlaylistGenerateRequest(BaseModel):
    """Request model for playlist generation."""

    query: str = Field(..., min_length=1, description="Smart playlist query string")
    playlist_name: str = Field("Playlist", description="Name for the generated playlist")
    comment: str = Field("", description="Optional comment/description")
    sort: str | None = Field(None, description="Sort parameter (e.g., 'title', '-rating')")
    limit: int | None = Field(None, ge=1, le=10000, description="Maximum number of tracks")


class GenerateTemplateFilesRequest(BaseModel):
    """Request model for template file generation."""

    template_id: str | None = Field(None, description="Optional template ID (generates all if not provided)")
    output_dir: str | None = Field(None, description="Optional output directory")
