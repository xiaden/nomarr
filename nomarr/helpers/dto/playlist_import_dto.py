"""DTOs for playlist import and conversion.

These dataclasses represent input tracks from streaming services,
match results, and final conversion output.
"""

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class PlaylistTrackInput:
    """A track from a streaming playlist to be matched.

    Contains metadata from Spotify/Deezer API responses.
    All fields are normalized to common format.
    """

    title: str
    artist: str
    album: str | None = None
    isrc: str | None = None
    duration_ms: int | None = None
    # Original position in source playlist (0-indexed)
    position: int = 0


@dataclass(frozen=True)
class MatchResult:
    """Result of matching a single track against the library.

    Contains the input track, match status, and matched file info.
    """

    input_track: PlaylistTrackInput
    status: Literal["exact_isrc", "exact_metadata", "fuzzy", "ambiguous", "not_found"]
    confidence: float  # 0.0 to 1.0
    # Matched library file path (None if not_found)
    matched_path: str | None = None
    # Matched file's library_files document _id
    matched_file_id: str | None = None
    # For ambiguous matches, alternative candidates
    alternatives: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PlaylistMetadata:
    """Metadata about the source playlist."""

    name: str
    description: str | None = None
    track_count: int = 0
    source_platform: Literal["spotify", "deezer"] = "spotify"
    source_url: str = ""


@dataclass(frozen=True)
class PlaylistConversionResult:
    """Complete result of playlist conversion.

    Contains the generated playlist content, match statistics,
    and details about unmatched/ambiguous tracks.
    """

    playlist_metadata: PlaylistMetadata
    # Generated M3U content (ready to save)
    m3u_content: str
    # Match statistics
    total_tracks: int
    matched_count: int
    exact_matches: int  # ISRC or exact metadata
    fuzzy_matches: int
    ambiguous_count: int
    not_found_count: int
    # Details for user review
    match_results: tuple[MatchResult, ...]

    @property
    def match_rate(self) -> float:
        """Percentage of tracks successfully matched."""
        if self.total_tracks == 0:
            return 0.0
        return self.matched_count / self.total_tracks

    def get_unmatched(self) -> list[MatchResult]:
        """Return list of tracks that couldn't be matched."""
        return [r for r in self.match_results if r.status == "not_found"]

    def get_ambiguous(self) -> list[MatchResult]:
        """Return list of tracks with ambiguous matches."""
        return [r for r in self.match_results if r.status == "ambiguous"]
