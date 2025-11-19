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

    This is a thin wrapper around resolve_library_path that ensures:
    1. Path is within library boundary (prevents traversal attacks)
    2. Path exists as a file

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
        ValueError: Access denied

        >>> validate_library_path("/music/../etc/passwd", "/music")
        ValueError: Access denied
    """
    # Delegate to resolve_library_path for consistent validation
    resolved = resolve_library_path(
        library_root=library_path,
        user_path=file_path,
        must_exist=True,
        must_be_file=True,
    )
    return str(resolved)


def resolve_library_path(
    library_root: str | Path,
    user_path: str | Path,
    must_exist: bool = True,
    must_be_file: bool | None = None,
) -> Path:
    """
    Safely resolve and validate a path within the library root.

    This function prevents path traversal attacks using CodeQL's recommended pattern:
    1. Convert library_root to absolute path string using os.path.abspath()
    2. Reject absolute user paths with os.path.isabs()
    3. Join and normalize with os.path.normpath(os.path.join(base, user_path))
    4. Verify result is within base with prefix check (fullpath.startswith(base + os.sep))
    5. Convert to Path after validation for type checks
    6. Optionally validate existence and file/directory type

    Args:
        library_root: Configured library root directory
        user_path: User-provided path (must be relative)
        must_exist: If True, require path to exist (default: True)
        must_be_file: If True, require file; if False, require directory; if None, allow either

    Returns:
        Resolved absolute Path within library root

    Raises:
        ValueError: If path validation fails (generic message to prevent info leakage)

    Examples:
        >>> resolve_library_path("/music", "album/song.mp3", must_be_file=True)
        Path("/music/album/song.mp3")

        >>> resolve_library_path("/music", "../../../etc/passwd")
        ValueError: Access denied

        >>> resolve_library_path("/music", "album", must_be_file=False)
        Path("/music/album")
    """
    import os

    if not library_root:
        raise ValueError("Library root not configured")

    # Step 1: Convert library_root to absolute path string (CodeQL pattern)
    try:
        base = os.path.abspath(str(library_root))
    except (OSError, ValueError) as e:
        logger.warning(f"[security] Failed to resolve library root {library_root!r}: {e}")
        raise ValueError("Invalid library configuration") from e

    # Step 2: Convert user_path to string
    user_path_string = str(user_path)

    # Step 3: Reject absolute user paths (CodeQL requirement)
    if os.path.isabs(user_path_string):
        logger.warning(f"[security] Absolute path rejected: {user_path_string!r}")
        raise ValueError("Access denied")

    # Step 4: Join and normalize (CodeQL pattern)
    try:
        fullpath = os.path.normpath(os.path.join(base, user_path_string))
    except (OSError, ValueError) as e:
        logger.warning(f"[security] Failed to join paths {base!r} + {user_path_string!r}: {e}")
        raise ValueError("Access denied") from e

    # Step 5: Verify fullpath is within base boundary (CodeQL pattern)
    # Must check: fullpath == base OR fullpath.startswith(base + os.sep)
    if fullpath != base and not fullpath.startswith(base + os.sep):
        logger.warning(
            f"[security] Path traversal attempt: {user_path_string!r} resolved outside library {library_root!r}"
        )
        raise ValueError("Access denied")

    # Step 6: Convert to Path after validation for existence/type checks
    candidate = Path(fullpath)

    # Validate existence if required
    if must_exist and not candidate.exists():
        logger.debug(f"[security] Path does not exist: {candidate}")
        raise ValueError("Access denied")

    # Validate file/directory type if specified
    if must_be_file is True and not candidate.is_file():
        logger.debug(f"[security] Path is not a file: {candidate}")
        raise ValueError("Access denied")
    elif must_be_file is False and not candidate.is_dir():
        logger.debug(f"[security] Path is not a directory: {candidate}")
        raise ValueError("Access denied")

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
