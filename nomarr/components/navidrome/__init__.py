"""Navidrome package."""

from .tag_query_comp import (
    find_files_matching_tag,
    get_nomarr_tag_rels,
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
    "find_files_matching_tag",
    "generate_template_files",
    "get_all_templates",
    "get_mixed_templates",
    "get_mood_templates",
    "get_nomarr_tag_rels",
    "get_playlist_preview_tracks",
    "get_quality_templates",
    "get_style_templates",
    "get_tag_value_counts",
    "get_template_summary",
]
