"""
Logging helpers for safe error handling and message sanitization.

This module provides:
- NomarrLogFilter: Automatic identity/role tags + optional context injection
- sanitize_exception_message: Safe error messages for user display
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

# Thread-safe log context storage for dynamic instance identifiers
_log_context: ContextVar[dict[str, Any] | None] = ContextVar("log_context", default=None)

logger = logging.getLogger(__name__)

# Known suffixes and their role tags (exact endswith match)
_SUFFIX_TO_ROLE: dict[str, str] = {
    "_svc": "Service",
    "_wf": "Workflow",
    "_comp": "Component",
    "_aql": "AQL",
    "_dto": "DTO",
    "_if": "Interface",
    "_helper": "Helper",
}


class NomarrLogFilter(logging.Filter):
    """
    Unified logging filter that injects identity, role, and context tags.

    Automatically derives module identity and role from logger name using
    Nomarr naming conventions. Also injects optional dynamic context.

    Injected attributes:
        nomarr_identity_tag: "[Health Monitor]" or full logger name if unknown
        nomarr_role_tag: "[Service]" or "" if unknown suffix
        context_str: "" or "[worker_id=0 job_id=123] " if context set

    If logger basename does not match a known suffix, the full logger name
    is preserved as identity_tag (intentionally loud to expose violations).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Inject Nomarr tags and context into LogRecord."""
        try:
            self._inject_identity_and_role(record)
            self._inject_context(record)
        except Exception:
            # Safety fallback - never crash, always set all fields
            record.nomarr_identity_tag = record.name
            record.nomarr_role_tag = ""
            record.context_str = ""
        return True

    def _inject_identity_and_role(self, record: logging.LogRecord) -> None:
        """Derive identity and role tags from logger name."""
        name = record.name

        # Extract basename (after last dot)
        if "." in name:
            basename = name.rsplit(".", 1)[1]
        else:
            basename = name

        # Check for known suffix
        for suffix, role in _SUFFIX_TO_ROLE.items():
            if basename.endswith(suffix):
                stem = basename[: -len(suffix)]
                # Empty stem is invalid (e.g., "_svc") - fall back to full name
                if not stem:
                    record.nomarr_identity_tag = name
                    record.nomarr_role_tag = ""
                    return
                # Format: "health_monitor" → "Health Monitor"
                stem_pretty = stem.replace("_", " ").title()
                record.nomarr_identity_tag = f"[{stem_pretty}]"
                record.nomarr_role_tag = f"[{role}]"
                return

        # Unknown suffix - use full logger name, no role tag
        record.nomarr_identity_tag = name
        record.nomarr_role_tag = ""

    def _inject_context(self, record: logging.LogRecord) -> None:
        """Inject dynamic context (worker_id, job_id, etc.) if set."""
        context = _log_context.get()
        if context:
            parts = [f"{k}={v}" for k, v in context.items()]
            record.context_str = f"[{' '.join(parts)}] "
        else:
            record.context_str = ""


def set_log_context(**kwargs: Any) -> None:
    """
    Set log context for all subsequent logs in this execution context.

    Context is thread-safe via contextvars and automatically propagates
    to child coroutines/tasks.

    Args:
        **kwargs: Context key-value pairs (e.g., worker_id="worker_0", library_id="lib123")

    Example:
        >>> set_log_context(worker_id="worker_0", library_id="lib123")
        >>> logger.info("Scanning file")  # Automatically includes worker_id and library_id
    """
    current = _log_context.get()
    if current is None:
        current = {}
    else:
        current = current.copy()
    current.update(kwargs)
    _log_context.set(current)


def clear_log_context() -> None:
    """
    Clear all log conNonext in current execution context.

    Useful for cleanup at worker shutdown or between test cases.
    """
    _log_context.set({})


def get_log_context() -> dict[str, Any]:
    """
    Get current log context.

    Returns:
        Copy of current context dict
    """
    context = _log_context.get()
    return context.copy() if context else {}


def sanitize_exception_message(e: Exception, safe_message: str = "An error occurred") -> str:
    """
    Sanitize exception message for user display.

    Prevents information leakage through detailed error messages while
    preserving the ability to log full details.

    Args:
        e: The exception to sanitize
        safe_message: Generic message to return to users

    Returns:
        Safe error message for user display

    Example:
        >>> try:
        ...     raise ValueError("/secret/path/file.txt not found")
        ... except Exception as e:
        ...     user_msg = sanitize_exception_message(e, "File not found")
        ...     logger.exception("Full error")  # Logs details
        ...     return {"error": user_msg}  # Returns generic message
    """
    # Log the full exception for debugging
    logger.exception(f"[security] Exception sanitized: {e}")

    # Return generic message to user
    return safe_message
