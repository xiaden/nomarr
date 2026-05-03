"""Navidrome domain DTOs.

Data transfer objects for smart playlist queries and Navidrome integration.
These form cross-layer contracts between interfaces, services, and workflows.

Rules:
- Import only stdlib and typing (no nomarr.* imports)
- Pure data structures only (no I/O, no DB access, no business logic)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict

# Maximum nesting depth for rule groups to prevent stack overflow
MAX_RULE_GROUP_DEPTH = 5


class TrackPlayData(TypedDict):
    """Play data for a single track from graph traversal.

    Returned by ``NavidromePlaycountsOperations.get_top_plays`` which queries
    bucketed playcount vertices filtered by ``userid`` sorted by ``playcount
    DESC``, then walks inbound ``has_plays`` edges to reach
    ``navidrome_tracks`` and outbound ``has_nd_id`` edges to ``library_files``.

    ``file_id`` is None when no ``has_nd_id`` edge exists for the track
    (i.e. the track hasn't been resolved to a Nomarr library file yet).
    """

    nd_id: str
    file_id: str | None
    playcount: int
    last_played: int | None


# Standard ID3/metadata tags that are NOT prefixed with "nom:"
# These are stored directly by taglib without namespace
class NdSyncResult(TypedDict):
    """Result of a Navidrome sync operation (graph-based).

    Returned by ``sync_navidrome`` workflow with statistics about the sync run.
    """

    total_songs: int
    resolved: int
    unresolved: int
    tracks_upserted: int
    play_edges_upserted: int
    orphans_removed: int
    duration_ms: int


# Standard ID3/metadata tags that are NOT prefixed with "nom:"
# These are stored directly by taglib without namespace
STANDARD_TAG_NAMES = frozenset(
    {
        "artist",
        "artists",
        "album",
        "album_artist",
        "genre",
        "year",
        "date",
        "bpm",
        "composer",
        "label",
        "publisher",
        "title",
        "lyricist",
    }
)


@dataclass
class TagCondition:
    """A single tag condition in a smart playlist query.

    Represents: tag:KEY OPERATOR VALUE
    """

    tag_key: str
    """Full tag key with namespace (e.g., "nom:mood_happy")"""

    operator: Literal[">", "<", "=", "!=", "contains", "notcontains"]
    """Comparison operator"""

    value: float | int | str
    """Value to compare against (typed)"""


@dataclass
class RuleGroup:
    """Recursive rule group for nested smart playlist queries.

    Supports nesting of AND/OR groups: (A AND B) OR (C AND D)
    """

    logic: Literal["AND", "OR"]
    """Logic operator for this group"""

    conditions: list[TagCondition]
    """Tag conditions directly in this group"""

    groups: list[RuleGroup]
    """Nested child groups (recursive structure)"""

    @property
    def depth(self) -> int:
        """Calculate max nesting depth of this group tree."""
        if not self.groups:
            return 1
        return 1 + max(g.depth for g in self.groups)


@dataclass
class SmartPlaylistFilter:
    """Structured filter representing a smart playlist query.

    Now supports nested rule groups via root RuleGroup.
    For backward compatibility, flat queries are represented as a single root group.
    """

    root: RuleGroup
    """Root rule group containing the query structure"""

    @property
    def is_simple_and(self) -> bool:
        """True if root is AND with no nested groups."""
        return self.root.logic == "AND" and len(self.root.groups) == 0

    @property
    def is_simple_or(self) -> bool:
        """True if root is OR with no nested groups."""
        return self.root.logic == "OR" and len(self.root.groups) == 0


@dataclass
class PlaylistPreviewResult:
    """Result from smart playlist preview operation.

    Contains both the total count of matching tracks and a sample of tracks
    for preview purposes.
    """

    total_count: int
    """Total number of tracks matching the query"""

    sample_tracks: list[dict[str, str]]
    """Sample of matching tracks (each dict has: path, title, artist, album)"""

    query: str
    """Original query string"""


@dataclass
class PreviewTagStatsResult:
    """Result from navidrome_service.preview_tag_stats()."""

    stats: dict[str, dict[str, str | int | float]]


@dataclass
class GeneratePlaylistResult:
    """Result from navidrome_service.generate_playlist().

    The playlist_structure dict uses Any because NSP format is recursive
    with mixed types: str, int, float, and nested all/any dicts.
    """

    playlist_structure: dict[str, Any]


@dataclass
class TemplateSummaryItem:
    """Single template item from get_template_summary()."""

    template_id: str
    name: str
    description: str


@dataclass
class GetTemplateSummaryResult:
    """Result from navidrome_service.get_template_summary()."""

    templates: list[TemplateSummaryItem]


@dataclass
class GenerateTemplateFilesResult:
    """Result from navidrome_service.generate_template_files()."""

    files_generated: dict[str, str]


@dataclass
class StaticPlaylistResult:
    """Result from static playlist generation.

    Used for vector-search-to-M3U export where tracks are a fixed set
    of file IDs rather than a dynamic tag query.
    """

    playlist_name: str
    m3u_content: str
    track_count: int
    missing_ids: list[str]
    saved_path: str | None = None


@dataclass(frozen=True)
class PushPlaylistResult:
    """Result from pushing a playlist to Navidrome via Subsonic API.

    Attributes:
        resolved_count: Number of file IDs successfully mapped to Navidrome song IDs.
        unresolved_count: Number of file IDs with no Navidrome mapping.
        playlist_id: Navidrome playlist ID (from create or replace).
    """

    resolved_count: int
    unresolved_count: int
    playlist_id: str


class NavidromeStaticPlaylistResult(TypedDict):
    """Result from pushing a static playlist to Navidrome.

    Returned to the frontend after a vector-search playlist is pushed
    via the Subsonic API.  Platform-prefixed to distinguish from future
    Plex / Jellyfin equivalents.

    Attributes:
        playlist_name: Display name written to Navidrome.
        playlist_id: Navidrome-assigned playlist ID.
        track_nd_ids: Navidrome song IDs that were successfully resolved.
        unresolved_file_ids: Nomarr file ``_id`` values with no ND mapping.
    """

    playlist_name: str
    playlist_id: str
    track_nd_ids: list[str]
    unresolved_file_ids: list[str]


class TasteProfile(TypedDict):
    """Per-user taste profile computed from play history.

    Contains a recency-weighted centroid embedding representing the user's
    listening preferences.  Generated by ``compute_taste_profile`` component.
    """

    user_id: str
    centroid: list[float]
    backbone_id: str
    library_key: str
    track_count: int
    generated_at_ms: int


class TasteCluster(TypedDict):
    """A genre-scoped cluster within a taste profile.

    Used by playlist generation to represent a user's affinity for a
    specific genre.  ``centroid`` is the L2-normalised weighted mean of
    the genre's track embeddings.
    """

    label: str
    centroid: list[float]
    track_count: int


class NavidromePersonalPlaylistContext(TypedDict):
    """Input context for personal playlist builder components.

    Constructed by the workflow from taste-profile and play-history data,
    then passed uniformly to every ``build_*`` component function.
    All fields are always present — every builder receives the same shape.

    ``played_file_ids`` uses ``list[str]`` (not ``set``) because TypedDict
    values must be JSON-serialisable; builders convert to ``set`` internally.

    ``played_tracks`` includes the full play data (playcount + last_played) for
    builders that need to compute per-entity centroids (e.g. genre playlists).

    ``max_genre_playlists`` caps the number of per-genre playlists produced;
    enforced by the genre builder. Hard server-side cap is 25.

    ``half_life_days`` is the recency decay parameter used for per-genre
    centroid computation in the genre builder.
    """

    backbone_id: str
    library_key: str
    centroid: list[float]
    max_songs: int
    played_file_ids: list[str]
    played_tracks: list[TrackPlayData]
    max_genre_playlists: int
    half_life_days: float


class NavidromePersonalPlaylistEntry(TypedDict):
    """Output from a single personal playlist builder component.

    Each ``build_*`` function returns one or more entries (genre playlists
    produce one per qualifying genre).  ``file_ids`` are Nomarr
    ``library_files/_id`` values — Navidrome ``nd_id`` resolution happens
    in the interface layer, not here.
    """

    playlist_type: str
    playlist_name: str
    file_ids: list[str]


@dataclass
class NavidromeGeneratePlaylistsResult:
    """Result of a personal playlist generation run.

    Attributes:
        status: Outcome of the generation run.

            - ``"ok"`` — playlists were generated successfully.
            - ``"no_data"`` — no taste profile found or zero playlists produced;
              ``playlists`` will be empty.
            - ``"misconfigured"`` — a required configuration value was absent;
              the interface layer raises HTTP 422 when this occurs.

        message: Human-readable detail. Empty string on ``"ok"``.
        playlists: Generated playlists, each with a ``playlist_type``,
            ``playlist_name``, and list of ``file_ids``.
            Empty when ``status`` is not ``"ok"``.
    """

    status: Literal["ok", "no_data", "misconfigured"]
    message: str
    playlists: list[NavidromePersonalPlaylistEntry]
