"""Navidrome package."""

from .playlist_builder_comp import (
    build_discovery_playlist,
    build_familiar_playlist,
    build_genre_playlists,
    build_hidden_gems_playlist,
    build_universal_playlist,
)
from .tag_query_comp import (
    find_files_matching_tag,
    get_nomarr_tag_names,
    get_playlist_preview_tracks,
    get_tag_value_counts,
)
from .templates_comp import (
    generate_template_files,
    get_all_templates,
    get_mixed_templates,
    get_mood_templates,
    get_quality_templates,
    get_style_templates,
    get_template_summary,
)

__all__ = [
    "build_discovery_playlist",
    "build_familiar_playlist",
    "build_genre_playlists",
    "build_hidden_gems_playlist",
    "build_universal_playlist",
    "find_files_matching_tag",
    "generate_template_files",
    "get_all_templates",
    "get_mixed_templates",
    "get_mood_templates",
    "get_nomarr_tag_names",
    "get_playlist_preview_tracks",
    "get_quality_templates",
    "get_style_templates",
    "get_tag_value_counts",
    "get_template_summary",
]
