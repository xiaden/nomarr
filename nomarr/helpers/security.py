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


def resolve_library_path(
    library_root: str | Path,
    user_path: str | Path,
    must_exist: bool = True,
    must_be_file: bool | None = None,
) -> Path:
    """
    Safely resolve and validate a path within the library root.

    This function prevents path traversal attacks and validates path properties:
    1. Resolves library_root to absolute, canonical path
    2. Joins user_path to library_root and resolves (handling .., symlinks)
    3. Ensures result is within library_root boundary
    4. Optionally validates existence and file/directory type

    Args:
        library_root: Configured library root directory
        user_path: User-provided path (relative or absolute)
        must_exist: If True, require path to exist (default: True)
        must_be_file: If True, require file; if False, require directory; if None, allow either

    Returns:
        Resolved absolute Path within library root

    Raises:
        ValueError: If path validation fails (generic message, no info leakage)

    Examples:
        >>> resolve_library_path("/music", "album/song.mp3", must_be_file=True)
        Path("/music/album/song.mp3")

        >>> resolve_library_path("/music", "../../../etc/passwd")
        ValueError: Access denied

        >>> resolve_library_path("/music", "album", must_be_file=False)
        Path("/music/album")
    """
    if not library_root:
        raise ValueError("Library root not configured")

    # Resolve library root to absolute path
    try:
        lib_root = Path(library_root).resolve()
    except (OSError, RuntimeError) as e:
        logger.warning(f"[security] Failed to resolve library root {library_root!r}: {e}")
        raise ValueError("Invalid library configuration") from e

    # Construct candidate path by joining library_root with user_path
    try:
        candidate = (lib_root / user_path).resolve()
    except (OSError, RuntimeError) as e:
        logger.warning(f"[security] Failed to resolve user path {user_path!r}: {e}")
        raise ValueError("Access denied") from e

    # Ensure candidate is within library_root boundary
    try:
        candidate.relative_to(lib_root)
    except ValueError as e:
        logger.warning(f"[security] Path traversal attempt: {user_path!r} resolved outside library {library_root!r}")
        raise ValueError("Access denied") from e

    # Validate existence if required
    if must_exist and not candidate.exists():
        logger.debug(f"[security] Path does not exist: {candidate}")
        raise ValueError("Path not found")

    # Validate file/directory type if specified
    if must_be_file is True and not candidate.is_file():
        logger.debug(f"[security] Path is not a file: {candidate}")
        raise ValueError("Path is not a file")
    elif must_be_file is False and not candidate.is_dir():
        logger.debug(f"[security] Path is not a directory: {candidate}")
        raise ValueError("Path is not a directory")

    return candidate


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
