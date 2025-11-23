"""
Navidrome integration workflows.

Workflows for generating Navidrome configurations and smart playlists.
"""

from nomarr.workflows.navidrome.generate_navidrome_config import (
    generate_navidrome_config_workflow,
)
from nomarr.workflows.navidrome.generate_smart_playlist import (
    generate_smart_playlist_workflow,
)
from nomarr.workflows.navidrome.parse_smart_playlist_query import (
    SmartPlaylistFilter,
    TagCondition,
    parse_smart_playlist_query,
)
from nomarr.workflows.navidrome.preview_smart_playlist import (
    preview_smart_playlist_workflow,
)
from nomarr.workflows.navidrome.preview_tag_stats import (
    preview_tag_stats_workflow,
)

__all__ = [
    "SmartPlaylistFilter",
    "TagCondition",
    "generate_navidrome_config_workflow",
    "generate_smart_playlist_workflow",
    "parse_smart_playlist_query",
    "preview_smart_playlist_workflow",
    "preview_tag_stats_workflow",
]
