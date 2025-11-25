"""
Navidrome package.
"""

from nomarr.helpers.dto.navidrome import SmartPlaylistFilter, TagCondition
from nomarr.helpers.exceptions import PlaylistQueryError

from .filter_engine import execute_smart_playlist_filter
from .generate_navidrome_config import generate_navidrome_config_workflow
from .generate_smart_playlist import generate_smart_playlist_workflow
from .parse_smart_playlist_query import (
    MAX_QUERY_LENGTH,
    parse_smart_playlist_query,
)
from .preview_smart_playlist import preview_smart_playlist_workflow
from .preview_tag_stats import preview_tag_stats_workflow

__all__ = [
    "MAX_QUERY_LENGTH",
    "PlaylistQueryError",
    "SmartPlaylistFilter",
    "TagCondition",
    "execute_smart_playlist_filter",
    "generate_navidrome_config_workflow",
    "generate_smart_playlist_workflow",
    "parse_smart_playlist_query",
    "preview_smart_playlist_workflow",
    "preview_tag_stats_workflow",
]
