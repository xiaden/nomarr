"""
Navidrome package.
"""

from .config_generator import generate_navidrome_config, preview_tag_stats
from .playlist_generator import PlaylistGenerator, PlaylistQueryError, generate_nsp_playlist, preview_playlist_query
from .templates import (
    generate_template_files,
    get_all_templates,
    get_mixed_templates,
    get_mood_templates,
    get_quality_templates,
    get_style_templates,
    get_template_summary,
)

__all__ = ['PlaylistGenerator', 'PlaylistQueryError', 'generate_navidrome_config', 'generate_nsp_playlist', 'generate_template_files', 'get_all_templates', 'get_mixed_templates', 'get_mood_templates', 'get_quality_templates', 'get_style_templates', 'get_template_summary', 'preview_playlist_query', 'preview_tag_stats']
