"""Playlist Import API types - Pydantic models for playlist conversion.

External API contracts for playlist import endpoints.
These models are thin adapters around DTOs from helpers/dto/playlist_import_dto.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, field_validator

from nomarr.interfaces.api.id_codec import decode_id

if TYPE_CHECKING:
    from nomarr.helpers.dto.playlist_import_dto import (
        MatchResult,
        PlaylistConversionResult,
        PlaylistMetadata,
        PlaylistTrackInput,
    )


# ──────────────────────────────────────────────────────────────────────
# Request Models
# ──────────────────────────────────────────────────────────────────────


class ConvertPlaylistRequest(BaseModel):
    """Request to convert a streaming playlist URL."""

    playlist_url: str = Field(
        ...,
        description="Full URL to a Spotify or Deezer playlist",
        examples=[
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
            "https://www.deezer.com/playlist/1234567890",
            "https://link.deezer.com/s/32pxbZMVkKIxZyRZwEBEN",
        ],
    )
    library_id: str | None = Field(
        default=None,
        description="Optional library _id to restrict matching scope",
    )

    @field_validator("library_id", mode="before")
    @classmethod
    def decode_library_id(cls, v: str | None) -> str | None:
        """Decode encoded library_id (libraries:123 -> libraries/123)."""
        if v is None or v == "":
            return None
        return decode_id(v)


# ──────────────────────────────────────────────────────────────────────
# Response Models
# ──────────────────────────────────────────────────────────────────────


class PlaylistTrackInputResponse(BaseModel):
    """Track from the source streaming playlist."""

    title: str = Field(..., description="Track title")
    artist: str = Field(..., description="Artist name(s)")
    album: str | None = Field(None, description="Album name")
    isrc: str | None = Field(None, description="ISRC code if available")
    position: int = Field(..., description="Position in source playlist (0-indexed)")

    @classmethod
    def from_dto(cls, dto: PlaylistTrackInput) -> PlaylistTrackInputResponse:
        """Convert DTO to response model."""
        return cls(
            title=dto.title,
            artist=dto.artist,
            album=dto.album,
            isrc=dto.isrc,
            position=dto.position,
        )


class MatchResultResponse(BaseModel):
    """Result of matching a single track."""

    input_track: PlaylistTrackInputResponse = Field(
        ..., description="Original track from streaming playlist"
    )
    status: Literal[
        "exact_isrc", "exact_metadata", "fuzzy", "ambiguous", "not_found"
    ] = Field(..., description="Type of match achieved")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Match confidence score (0-1)"
    )
    matched_path: str | None = Field(
        None, description="Path to matched library file"
    )
    alternatives: list[str] = Field(
        default_factory=list,
        description="Alternative match paths for ambiguous matches",
    )

    @classmethod
    def from_dto(cls, dto: MatchResult) -> MatchResultResponse:
        """Convert DTO to response model."""
        return cls(
            input_track=PlaylistTrackInputResponse.from_dto(dto.input_track),
            status=dto.status,
            confidence=dto.confidence,
            matched_path=dto.matched_path,
            alternatives=list(dto.alternatives),
        )


class PlaylistMetadataResponse(BaseModel):
    """Metadata about the source playlist."""

    name: str = Field(..., description="Playlist name")
    description: str | None = Field(None, description="Playlist description")
    track_count: int = Field(..., description="Total tracks in source playlist")
    source_platform: Literal["spotify", "deezer"] = Field(
        ..., description="Source streaming platform"
    )
    source_url: str = Field(..., description="Original playlist URL")

    @classmethod
    def from_dto(cls, dto: PlaylistMetadata) -> PlaylistMetadataResponse:
        """Convert DTO to response model."""
        return cls(
            name=dto.name,
            description=dto.description,
            track_count=dto.track_count,
            source_platform=dto.source_platform,
            source_url=dto.source_url,
        )


class ConvertPlaylistResponse(BaseModel):
    """Response from playlist conversion."""

    playlist_metadata: PlaylistMetadataResponse = Field(
        ..., description="Source playlist metadata"
    )
    m3u_content: str = Field(
        ..., description="Generated M3U playlist content (ready to save)"
    )
    total_tracks: int = Field(..., description="Total tracks in source playlist")
    matched_count: int = Field(
        ..., description="Successfully matched tracks (exact + fuzzy)"
    )
    exact_matches: int = Field(
        ..., description="Tracks matched by ISRC or exact metadata"
    )
    fuzzy_matches: int = Field(..., description="Tracks matched via fuzzy matching")
    ambiguous_count: int = Field(
        ..., description="Tracks with multiple possible matches (need review)"
    )
    not_found_count: int = Field(
        ..., description="Tracks that could not be matched"
    )
    match_rate: float = Field(
        ..., ge=0.0, le=1.0, description="Percentage matched (0-1)"
    )
    # Detailed results for review
    unmatched_tracks: list[PlaylistTrackInputResponse] = Field(
        default_factory=list,
        description="Tracks that couldn't be matched",
    )
    ambiguous_matches: list[MatchResultResponse] = Field(
        default_factory=list,
        description="Matches with low confidence requiring review",
    )

    @classmethod
    def from_dto(cls, dto: PlaylistConversionResult) -> ConvertPlaylistResponse:
        """Convert DTO to response model."""
        return cls(
            playlist_metadata=PlaylistMetadataResponse.from_dto(
                dto.playlist_metadata
            ),
            m3u_content=dto.m3u_content,
            total_tracks=dto.total_tracks,
            matched_count=dto.matched_count,
            exact_matches=dto.exact_matches,
            fuzzy_matches=dto.fuzzy_matches,
            ambiguous_count=dto.ambiguous_count,
            not_found_count=dto.not_found_count,
            match_rate=dto.match_rate,
            unmatched_tracks=[
                PlaylistTrackInputResponse.from_dto(r.input_track)
                for r in dto.get_unmatched()
            ],
            ambiguous_matches=[
                MatchResultResponse.from_dto(r) for r in dto.get_ambiguous()
            ],
        )


class SpotifyCredentialsStatusResponse(BaseModel):
    """Status of Spotify credentials configuration."""

    configured: bool = Field(
        ..., description="True if Spotify credentials are configured"
    )
    message: str = Field(
        ..., description="Human-readable status message"
    )
