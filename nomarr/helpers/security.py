"""
Security helpers for path validation and sanitization.

This module provides utilities to prevent common security vulnerabilities:
- Path traversal attacks
- Directory traversal
- Symlink attacks
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def validate_library_path(file_path: str, library_path: str) -> str:
    """
    Validate that a file path is within the configured library directory.

    This function prevents path traversal attacks by:
    1. Resolving both paths to absolute, normalized forms
    2. Checking that the target is within the library boundary
    3. Verifying the target exists and is a file

    Args:
        file_path: User-provided file path (absolute or relative)
        library_path: Configured library root directory

    Returns:
        Absolute, normalized file path within library

    Raises:
        ValueError: If path is outside library, doesn't exist, or isn't a file

    Examples:
        >>> validate_library_path("/music/song.mp3", "/music")
        "/music/song.mp3"

        >>> validate_library_path("../../etc/passwd", "/music")
        ValueError: Access denied: path outside library

        >>> validate_library_path("/music/../etc/passwd", "/music")
        ValueError: Access denied: path outside library
    """
    if not library_path:
        raise ValueError("Library path not configured")

    # Resolve to absolute paths and normalize (resolves .., symlinks, etc.)
    try:
        library = Path(library_path).resolve()
        target = Path(file_path).resolve()
    except (OSError, RuntimeError) as e:
        logger.warning(f"[security] Path resolution failed for {file_path}: {e}")
        raise ValueError("Invalid file path") from e

    # Check if target is within library boundary
    try:
        target.relative_to(library)
    except ValueError as e:
        logger.warning(f"[security] Path traversal attempt: {file_path} outside {library_path}")
        raise ValueError("Access denied: path outside library") from e

    # Verify file exists
    if not target.exists():
        raise ValueError("File not found")

    # Verify it's a file (not a directory or special file)
    if not target.is_file():
        raise ValueError("Not a valid file")

    return str(target)


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
