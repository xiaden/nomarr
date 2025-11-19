"""
Logging helpers for safe error handling and message sanitization.

This module provides utilities to prevent information leakage through
error messages while preserving detailed logging for debugging.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


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
