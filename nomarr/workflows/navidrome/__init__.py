"""
Navidrome package.
"""

from nomarr.helpers.dto.navidrome_dto import SmartPlaylistFilter, TagCondition
from nomarr.helpers.exceptions import PlaylistQueryError

from .filter_engine_wf import execute_smart_playlist_filter
from .generate_navidrome_config_wf import generate_navidrome_config_workflow
from .generate_smart_playlist_wf import generate_smart_playlist_workflow
from .parse_smart_playlist_query_wf import (
    MAX_QUERY_LENGTH,
    parse_smart_playlist_query,
)
from .preview_smart_playlist_wf import preview_smart_playlist_workflow
from .preview_tag_stats_wf import preview_tag_stats_workflow

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
