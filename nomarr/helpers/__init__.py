"""Helpers layer — pure utility code and cross-cutting data structures.

Helpers are leaf utilities with no layer-level dependencies. They provide:

- **DTOs** (``dto/``) — Domain-specific data-transfer objects used as contracts
  between all layers (interfaces → services → workflows → components).
- **Time utilities** (``time_helper.py``) — Type-safe wall-clock and monotonic
  time with distinct ``Milliseconds``/``Seconds`` newtypes.
- **File utilities** (``files_helper.py``, ``file_validation_helper.py``) —
  Library path resolution with security validation and audio file collection.
- **Exceptions** (``exceptions.py``) — Shared exception hierarchy across layers.
- **Logging** (``logging_helper.py``) — Structured context logging with
  sanitized exception messages.
- **Vector params** (``vector_params_helper.py``) — ArangoDB ANN index
  parameter computation (nLists, nProbe).
- **Configuration** (``config_schema.py``) — Static/dynamic config models and
  validation.
- **Constants** (``constants/``) — Domain constants for file states and pipeline
  axes shared across layers.

Rules:
- No I/O beyond what stdlib provides (no DB, no network).
- No imports from services, workflows, or components.
- Pure functions and dataclasses only.
"""

from .dto.processing_dto import ProcessorConfig, TagWriteProfile
from .exceptions import MisconfiguredError
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
from .logging_helper import (
    NomarrLogFilter,
    clear_log_context,
    get_log_context,
    sanitize_exception_message,
    set_log_context,
)
from .managed_task import ManagedTask
from .time_helper import (
    MS_PER_SECOND,
    NS_PER_MS,
    NS_PER_SECOND,
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    SECONDS_PER_MINUTE,
    InternalMilliseconds,
    InternalSeconds,
    Milliseconds,
    Seconds,
    format_internal_timestamp,
    format_internal_timestamp_local,
    format_wall_timestamp,
    format_wall_timestamp_local,
    internal_ms,
    internal_ms_to_s,
    internal_s,
    internal_s_to_ms,
    ms_to_s,
    now_ms,
    now_s,
    s_to_ms,
    to_wall_ms,
    to_wall_s,
)

__all__ = [
    "AUDIO_EXTENSIONS",
    "MS_PER_SECOND",
    "NS_PER_MS",
    "NS_PER_SECOND",
    "SECONDS_PER_DAY",
    "SECONDS_PER_HOUR",
    "SECONDS_PER_MINUTE",
    "InternalMilliseconds",
    "InternalSeconds",
    "ManagedTask",
    "Milliseconds",
    "MisconfiguredError",
    "NomarrLogFilter",
    "ProcessorConfig",
    "Seconds",
    "TagWriteProfile",
    "check_already_tagged",
    "clear_log_context",
    "collect_audio_files",
    "format_internal_timestamp",
    "format_internal_timestamp_local",
    "format_wall_timestamp",
    "format_wall_timestamp_local",
    "get_log_context",
    "internal_ms",
    "internal_ms_to_s",
    "internal_s",
    "internal_s_to_ms",
    "is_audio_file",
    "make_skip_result",
    "ms_to_s",
    "now_ms",
    "now_s",
    "resolve_library_path",
    "s_to_ms",
    "sanitize_exception_message",
    "set_log_context",
    "should_skip_processing",
    "to_wall_ms",
    "to_wall_s",
    "validate_file_exists",
    "validate_library_path",
]
