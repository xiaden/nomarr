"""Navidrome API types - Pydantic models for Navidrome domain.

External API contracts for Navidrome integration endpoints.
These models are thin adapters around DTOs from helpers/dto/navidrome_dto.py.

Architecture:
- Response models use .from_dto() to convert DTOs to Pydantic
- Request models use .to_dto() to convert Pydantic to DTOs for service calls
- Services continue using DTOs (no Pydantic imports in services layer)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from nomarr.helpers.dto.navidrome_dto import (
        GeneratePlaylistResult,
        GetTemplateSummaryResult,
        NavidromeStaticPlaylistResult,
        PlaylistPreviewResult,
        PreviewTagStatsResult,
        RuleGroup,
        SmartPlaylistFilter,
        StaticPlaylistResult,
        TagCondition,
        TemplateSummaryItem,
    )

# ──────────────────────────────────────────────────────────────────────
# Response Models
# ──────────────────────────────────────────────────────────────────────


class TagConditionResponse(BaseModel):
    """Pydantic model for TagCondition DTO."""

    tag_key: str = Field(..., description="Full tag key with namespace (e.g., 'nom:mood_happy')")
    operator: Literal[">", "<", "=", "!=", "contains", "notcontains"] = Field(..., description="Comparison operator")
    value: float | int | str = Field(..., description="Value to compare against")

    @classmethod
    def from_dto(cls, dto: TagCondition) -> TagConditionResponse:
        """Convert TagCondition DTO to Pydantic response model."""
        return cls(
            tag_key=dto.tag_key,
            operator=dto.operator,
            value=dto.value,
        )


class RuleGroupResponse(BaseModel):
    """Pydantic model for RuleGroup DTO."""

    logic: Literal["AND", "OR"] = Field(..., description="Logic operator for this group")
    conditions: list[TagConditionResponse] = Field(
        default_factory=list, description="Tag conditions directly in this group"
    )
    groups: list[RuleGroupResponse] = Field(
        default_factory=list, description="Nested child groups (recursive structure)"
    )

    @classmethod
    def from_dto(cls, dto: RuleGroup) -> RuleGroupResponse:
        """Convert RuleGroup DTO to Pydantic response model."""
        return cls(
            logic=dto.logic,
            conditions=[TagConditionResponse.from_dto(c) for c in dto.conditions],
            groups=[RuleGroupResponse.from_dto(g) for g in dto.groups],
        )


class SmartPlaylistFilterResponse(BaseModel):
    """Pydantic model for SmartPlaylistFilter DTO."""

    root: RuleGroupResponse = Field(..., description="Root rule group containing the query structure")

    @classmethod
    def from_dto(cls, dto: SmartPlaylistFilter) -> SmartPlaylistFilterResponse:
        """Convert SmartPlaylistFilter DTO to Pydantic response model."""
        return cls(root=RuleGroupResponse.from_dto(dto.root))


class PlaylistPreviewResponse(BaseModel):
    """Pydantic model for PlaylistPreviewResult DTO."""

    total_count: int = Field(..., description="Total number of tracks matching the query")
    sample_tracks: list[dict[str, str]] = Field(
        default_factory=list,
        description="Sample of matching tracks (path, title, artist, album)",
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
        default_factory=dict,
        description="Tag statistics keyed by tag name",
    )

    @classmethod
    def from_dto(cls, dto: PreviewTagStatsResult) -> PreviewTagStatsResponse:
        """Convert PreviewTagStatsResult DTO to Pydantic response model."""
        return cls(stats=dto.stats)


class TagValuesResponse(BaseModel):
    """Response containing distinct values for a specific tag."""

    name: str = Field(..., description="Tag name")
    values: list[str] = Field(default_factory=list, description="Sorted distinct values")


class NavidromeConfigResponse(BaseModel):
    """Pydantic model for Navidrome TOML configuration response."""

    config: str = Field(..., description="TOML configuration content")

    @classmethod
    def from_toml(cls, toml_content: str) -> NavidromeConfigResponse:
        """Create response from TOML string content."""
        return cls(config=toml_content)


class GeneratePlaylistResponse(BaseModel):
    """Pydantic model for GeneratePlaylistResult DTO."""

    # NSP structure is recursive with mixed types:
    # {"name": str, "comment": str, "all"|"any": [{"op": {field: value}}, ...], ...}
    # Values can be str, int, float, or nested all/any dicts
    playlist_structure: dict[str, Any] = Field(
        ...,
        description="Navidrome .nsp playlist structure",
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
            template_id=dto.template_id,
            name=dto.name,
            description=dto.description,
        )


class GetTemplateSummaryResponse(BaseModel):
    """Pydantic model for GetTemplateSummaryResult DTO."""

    templates: list[TemplateSummaryItemResponse] = Field(
        default_factory=list,
        description="List of available templates",
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


# ──────────────────────────────────────────────────────────────────────
# Static Playlist (Vector Search → M3U)
# ──────────────────────────────────────────────────────────────────────


class StaticPlaylistRequest(BaseModel):
    """Request model for static playlist generation from file IDs."""

    file_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Library file IDs to include in the playlist",
    )
    playlist_name: str = Field("Vector Search Playlist", description="Name for the generated playlist")


class StaticPlaylistResponse(BaseModel):
    """Response model for static playlist generation."""

    playlist_name: str = Field(..., description="Name of the generated playlist")
    m3u_content: str = Field(..., description="M3U playlist file content")
    track_count: int = Field(..., description="Number of tracks in the playlist")
    missing_ids: list[str] = Field(default_factory=list, description="File IDs not found in the library")
    saved_path: str | None = Field(None, description="Server-side path where M3U was saved, null if disabled")

    @classmethod
    def from_dto(cls, dto: StaticPlaylistResult) -> StaticPlaylistResponse:
        """Convert StaticPlaylistResult DTO to Pydantic response model."""
        return cls(
            playlist_name=dto.playlist_name,
            m3u_content=dto.m3u_content,
            track_count=dto.track_count,
            missing_ids=dto.missing_ids,
            saved_path=dto.saved_path,
        )


class SyncSongsResponse(BaseModel):
    """Response for Navidrome song sync."""

    total_songs: int = Field(..., description="Total songs found in Navidrome")
    resolved: int = Field(..., description="Songs matched to Nomarr library files")
    unresolved: int = Field(..., description="Songs that could not be matched")
    tracks_upserted: int = Field(..., description="Track vertices upserted")
    play_edges_upserted: int = Field(..., description="Play count edges upserted")
    orphans_removed: int = Field(..., description="Orphan tracks removed")
    duration_ms: int = Field(..., description="Sync duration in milliseconds")


class TriggerPersonalPlaylistsResponse(BaseModel):
    """Response after triggering personal playlist generation and push."""

    status: str = Field(..., description="Outcome: 'ok' or 'no_data'")
    message: str = Field("", description="Human-readable detail; empty on success")
    playlists_generated: int = Field(..., description="Number of playlists generated")
    playlists_pushed: int = Field(..., description="Number successfully pushed to Navidrome")


class PingResponse(BaseModel):
    """Response from the Navidrome connection test endpoint."""

    ok: bool
    error: str | None = None


class NavidromeStatusResponse(BaseModel):
    """Response indicating whether Navidrome integration is configured."""

    configured: bool = Field(..., description="True when Navidrome credentials are fully set")


class PushStaticPlaylistResponse(BaseModel):
    """Response after pushing a static playlist to Navidrome."""

    playlist_name: str = Field(..., description="Display name written to Navidrome")
    playlist_id: str = Field(..., description="Navidrome-assigned playlist ID")
    track_count: int = Field(..., description="Number of tracks resolved and pushed")
    unresolved_count: int = Field(..., description="Number of file IDs with no Navidrome mapping")

    @classmethod
    def from_dto(cls, dto: NavidromeStaticPlaylistResult) -> PushStaticPlaylistResponse:
        """Convert NavidromeStaticPlaylistResult DTO to Pydantic response."""
        return cls(
            playlist_name=dto["playlist_name"],
            playlist_id=dto["playlist_id"],
            track_count=len(dto["track_nd_ids"]),
            unresolved_count=len(dto["unresolved_file_ids"]),
        )
