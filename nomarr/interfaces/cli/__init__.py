"""
Cli package.
"""

from .ui import (
    COLOR_DONE,
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_PENDING,
    COLOR_RUNNING,
    COLOR_SUCCESS,
    COLOR_WARNING,
    InfoPanel,
    ProgressDisplay,
    TableDisplay,
    UILogHandler,
    WorkerPoolDisplay,
    attach_display_logger,
    detach_display_logger,
    print_error,
    print_info,
    print_success,
    print_warning,
    show_spinner,
)
from .utils import (
    api_call,
    format_duration,
    format_tag_summary,
)

__all__ = [
    "COLOR_DONE",
    "COLOR_ERROR",
    "COLOR_INFO",
    "COLOR_PENDING",
    "COLOR_RUNNING",
    "COLOR_SUCCESS",
    "COLOR_WARNING",
    "InfoPanel",
    "ProgressDisplay",
    "TableDisplay",
    "UILogHandler",
    "WorkerPoolDisplay",
    "api_call",
    "attach_display_logger",
    "detach_display_logger",
    "format_duration",
    "format_tag_summary",
    "print_error",
    "print_info",
    "print_success",
    "print_warning",
    "show_spinner",
]
