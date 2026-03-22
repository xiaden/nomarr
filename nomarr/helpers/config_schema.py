"""Config schema registry — single source of truth for all config keys.

This module defines the typed dataclasses, defaults, UI metadata, and derived
key sets that ConfigService and the web frontend consume.  Nothing else in the
codebase should hard-code config key names or defaults.

Architecture:
    StaticConfig  — frozen, startup-only (paths, admin password)
    DynamicConfig — mutable, web-editable (worker count, flags, API creds)
    DYNAMIC_FIELD_META — UI labels/descriptions co-located with DynamicConfig
    LibraryConfigFields — per-library document sub-schema (TypedDict)
"""

import dataclasses
from dataclasses import dataclass
from typing import Literal, TypedDict

# ---------------------------------------------------------------------------
# Static config — set once via file / ENV, never changed at runtime
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StaticConfig:
    """Startup-only configuration values.

    Set via config.yaml or environment variables during bootstrap.
    Never exposed to the web UI.  Never mutated after startup.
    """

    models_dir: str = "/app/models"
    db_path: str = "/app/config/db/nomarr.db"
    library_root: str = "/media"
    admin_password: str | None = None


# ---------------------------------------------------------------------------
# Dynamic config — web-editable, stored in DB, read from cache
# ---------------------------------------------------------------------------

@dataclass
class DynamicConfig:
    """User-configurable settings editable via the web UI.

    Stored in ArangoDB (stringified), cached in-memory by ConfigService.
    Defaults here match the bootstrap defaults that seed the DB on first run.
    """

    calibrate_heads: bool = False
    tagger_worker_count: int | None = None  # 1-8, None = auto (default 1)
    library_auto_tag: bool = True
    library_ignore_patterns: str = ""
    spotify_client_id: str | None = None
    spotify_client_secret: str | None = None
    navidrome_api_url: str | None = None
    navidrome_api_user: str | None = None
    navidrome_api_password: str | None = None
    m3u_output_path: str = ""
    vector_group_size: int = 15
    vector_search_thoroughness: int = 10

    # Personal playlists
    pp_enabled: bool = False
    pp_backbone_id: str = "effnet-discogs"
    pp_half_life_days: float = 30.0
    pp_top_n: int = 200
    pp_min_play_count: int = 3
    pp_max_songs: int = 50
    pp_min_songs: int = 10
    pp_overwrite_playlists: bool = True
    pp_type_familiar: bool = True
    pp_type_discovery: bool = True
    pp_type_hidden_gems: bool = True
    pp_type_genre: bool = True
    pp_type_universal: bool = True


# ---------------------------------------------------------------------------
# UI metadata for DynamicConfig fields
# ---------------------------------------------------------------------------


class FieldMeta(TypedDict, total=False):
    """UI metadata for a single config field."""

    label: str  # required
    description: str
    ui_type: Literal["text", "password", "boolean", "select", "number"]
    options: list[dict[str, str]]  # for select fields: [{value, label}]


DYNAMIC_FIELD_META: dict[str, FieldMeta] = {
    "calibrate_heads": {
        "label": "Auto-Calibrate Heads",
        "description": "Automatically calibrate tag thresholds for optimal results",
        "ui_type": "boolean",
    },
    "tagger_worker_count": {
        "label": "Worker Threads",
        "description": "Number of parallel worker processes for tagging (0 = auto-detect)",
        "ui_type": "text",
    },
    "library_auto_tag": {
        "label": "Auto-Tag New Files",
        "description": "Automatically process new files found during library scans",
        "ui_type": "boolean",
    },
    "library_ignore_patterns": {
        "label": "Ignore Patterns",
        "description": "Comma-separated patterns to ignore during scanning (e.g., */Audiobooks/*,*.tmp)",
        "ui_type": "text",
    },
    "spotify_client_id": {
        "label": "Spotify Client ID",
        "description": "From https://developer.spotify.com/dashboard - for playlist import",
        "ui_type": "text",
    },
    "spotify_client_secret": {
        "label": "Spotify Client Secret",
        "description": "From https://developer.spotify.com/dashboard - keep this private",
        "ui_type": "password",
    },
    "navidrome_api_url": {
        "label": "Navidrome API URL",
        "description": "Navidrome server URL (e.g. http://navidrome:4533)",
        "ui_type": "text",
    },
    "navidrome_api_user": {
        "label": "Navidrome Username",
        "description": "Navidrome admin username for API access",
        "ui_type": "text",
    },
    "navidrome_api_password": {
        "label": "Navidrome Password",
        "description": "Navidrome admin password for API access",
        "ui_type": "password",
    },
    "m3u_output_path": {
        "label": "M3U Output Path",
        "description": "Directory path (relative to library root) where M3U playlist files are saved. Leave empty to disable M3U file output.",
        "ui_type": "text",
    },
    "vector_group_size": {
        "label": "Songs per Neighborhood",
        "description": "Target number of songs in each similarity neighborhood (5-100). Lower values create more precise groupings but may slow index rebuilds.",
        "ui_type": "number",
    },
    "vector_search_thoroughness": {
        "label": "Search Thoroughness (%)",
        "description": "Percentage of neighborhoods to scan per search (1-100). Higher values improve recall at the cost of latency.",
        "ui_type": "number",
    },
    # -- Personal playlists --
    "pp_enabled": {
        "label": "Enabled",
        "description": "Enable personal playlist generation",
        "ui_type": "boolean",
    },
    "pp_backbone_id": {
        "label": "Backbone ID",
        "description": "Embedding backbone model ID used for similarity calculations",
        "ui_type": "text",
    },
    "pp_half_life_days": {
        "label": "Recency Half-Life (days)",
        "description": "Half-life in days for exponential time-decay weighting of play history",
        "ui_type": "number",
    },
    "pp_top_n": {
        "label": "Top Plays to Fetch",
        "description": "Number of top-played songs to consider when building taste profiles",
        "ui_type": "number",
    },
    "pp_min_play_count": {
        "label": "Min Play Count",
        "description": "Minimum play count for a song to be included in taste profile calculation",
        "ui_type": "number",
    },
    "pp_max_songs": {
        "label": "Max Songs per Playlist",
        "description": "Maximum number of songs in each generated playlist",
        "ui_type": "number",
    },
    "pp_min_songs": {
        "label": "Min Songs per Playlist",
        "description": "Minimum number of songs required to create a playlist",
        "ui_type": "number",
    },
    "pp_overwrite_playlists": {
        "label": "Overwrite Playlists",
        "description": "Replace existing playlists on each generation run instead of appending",
        "ui_type": "boolean",
    },
    "pp_type_familiar": {
        "label": "Familiar Type",
        "description": "Generate 'Familiar Favorites' playlists from highly-played songs",
        "ui_type": "boolean",
    },
    "pp_type_discovery": {
        "label": "Discovery Type",
        "description": "Generate 'Discovery' playlists with unheard songs similar to favorites",
        "ui_type": "boolean",
    },
    "pp_type_hidden_gems": {
        "label": "Hidden Gems Type",
        "description": "Generate 'Hidden Gems' playlists with rarely-played songs that match your taste",
        "ui_type": "boolean",
    },
    "pp_type_genre": {
        "label": "Genre Type",
        "description": "Generate genre-focused playlists based on top genre preferences",
        "ui_type": "boolean",
    },
    "pp_type_universal": {
        "label": "Universal Type",
        "description": "Generate a universal mix playlist blending all taste dimensions",
        "ui_type": "boolean",
    },
}

# Drift guard: every DynamicConfig field must have metadata and vice-versa.
_dynamic_field_names = {f.name for f in dataclasses.fields(DynamicConfig)}
assert set(DYNAMIC_FIELD_META) == _dynamic_field_names, (
    f"DYNAMIC_FIELD_META keys != DynamicConfig fields: "
    f"extra_meta={set(DYNAMIC_FIELD_META) - _dynamic_field_names}, "
    f"missing_meta={_dynamic_field_names - set(DYNAMIC_FIELD_META)}"
)

# ---------------------------------------------------------------------------
# Derived key sets — ConfigService imports these instead of maintaining its own
# ---------------------------------------------------------------------------

STATIC_KEYS: frozenset[str] = frozenset(f.name for f in dataclasses.fields(StaticConfig))
DYNAMIC_KEYS: frozenset[str] = frozenset(f.name for f in dataclasses.fields(DynamicConfig))
ALL_CONFIG_KEYS: frozenset[str] = STATIC_KEYS | DYNAMIC_KEYS
WEB_EDITABLE_KEYS: frozenset[str] = DYNAMIC_KEYS  # all dynamic keys are web-editable


# ---------------------------------------------------------------------------
# Per-library config schema
# ---------------------------------------------------------------------------

_VALID_WRITE_MODES = frozenset({"none", "minimal", "full"})


class LibraryConfigFields(TypedDict, total=False):
    """Per-library config fields stored on the library ArangoDB document.

    Not all fields are required --- missing keys inherit the application default.
    """

    file_write_mode: Literal["none", "minimal", "full"]
    vector_group_size: int
    vector_search_thoroughness: int


def validate_library_config(data: dict[str, object]) -> LibraryConfigFields:
    """Validate and narrow a raw dict to LibraryConfigFields.

    Args:
        data: Raw config dict (e.g. from API request body).

    Returns:
        Validated LibraryConfigFields.

    Raises:
        ValueError: If any field value is invalid.
    """
    result: LibraryConfigFields = {}
    if "file_write_mode" in data:
        mode = data["file_write_mode"]
        if mode not in _VALID_WRITE_MODES:
            msg = f"Invalid file_write_mode: {mode!r} (must be one of {sorted(_VALID_WRITE_MODES)})"
            raise ValueError(msg)
        result["file_write_mode"] = mode  # type: ignore[typeddict-item]

    if "vector_group_size" in data:
        gs = data["vector_group_size"]
        if not isinstance(gs, int) or not (5 <= gs <= 100):
            msg = f"Invalid vector_group_size: {gs!r} (must be int in range 5-100)"
            raise ValueError(msg)
        result["vector_group_size"] = gs

    if "vector_search_thoroughness" in data:
        th = data["vector_search_thoroughness"]
        if not isinstance(th, int) or not (1 <= th <= 100):
            msg = f"Invalid vector_search_thoroughness: {th!r} (must be int in range 1-100)"
            raise ValueError(msg)
        result["vector_search_thoroughness"] = th

    return result
