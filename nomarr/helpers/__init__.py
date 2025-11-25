"""
Helpers package.
"""

from .dto.processing import ProcessorConfig, TagWriteProfile
from .file_validation import check_already_tagged, make_skip_result, should_skip_processing, validate_file_exists
from .files import AUDIO_EXTENSIONS, collect_audio_files, is_audio_file, resolve_library_path, validate_library_path
from .logging import sanitize_exception_message
from .navidrome_templates import (
    generate_template_files,
    get_all_templates,
    get_mixed_templates,
    get_mood_templates,
    get_quality_templates,
    get_style_templates,
    get_template_summary,
)

__all__ = [
    "AUDIO_EXTENSIONS",
    "ProcessorConfig",
    "TagWriteProfile",
    "check_already_tagged",
    "collect_audio_files",
    "generate_template_files",
    "get_all_templates",
    "get_mixed_templates",
    "get_mood_templates",
    "get_quality_templates",
    "get_style_templates",
    "get_template_summary",
    "is_audio_file",
    "make_skip_result",
    "resolve_library_path",
    "sanitize_exception_message",
    "should_skip_processing",
    "validate_file_exists",
    "validate_library_path",
]
