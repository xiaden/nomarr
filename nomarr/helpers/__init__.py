"""
Helpers package.
"""

from .dto.processing_dto import ProcessorConfig, TagWriteProfile
from .dto.queue_dto import DequeueResult, Job, ListJobsResult
from .file_validation_helper import (
    check_already_tagged,
    make_skip_result,
    should_skip_processing,
    validate_file_exists,
)
from .files_helper import (
    AUDIO_EXTENSIONS,
    collect_audio_files,
    is_audio_file,
    resolve_library_path,
    validate_library_path,
)
from .logging_helper import sanitize_exception_message
from .navidrome_templates_helper import (
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
    "DequeueResult",
    "Job",
    "ListJobsResult",
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
