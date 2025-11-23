"""
File system helpers for audio file operations.

This module provides the secure, library-scoped filesystem API for Nomarr.
All path operations enforce validation to prevent traversal attacks and
ensure paths remain within configured library boundaries.

Path validation is built into this module - use these functions for all
filesystem operations involving user-provided paths.
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

    This function prevents path traversal attacks using CodeQL's recommended pattern
    with structural validation (no character whitelists - supports Unicode/kanji):
    1. Convert library_root to absolute path string using os.path.abspath()
    2. Structural pre-validation using pathlib.PurePath (before join):
       - Reject absolute paths
       - Reject ".." in any path component
       - Reject NUL bytes
    3. Join and normalize with os.path.normpath(os.path.join(base, user_path))
    4. Verify result is within base with prefix check (fullpath.startswith(base + os.sep))
    5. Convert to Path after validation for type checks
    6. Optionally validate existence and file/directory type

    Structural blacklist (no character restrictions):
    - Absolute paths (PurePath.is_absolute())
    - Parent directory traversal (any ".." in PurePath.parts)
    - NUL bytes (\x00)

    Args:
        library_root: Configured library root directory
        user_path: User-provided path (must be relative, no traversal)
        must_exist: If True, require path to exist (default: True)
        must_be_file: If True, require file; if False, require directory; if None, allow either

    Returns:
        Resolved absolute Path within library root

    Raises:
        ValueError: If path validation fails (generic message to prevent info leakage)

    Examples:
        >>> resolve_library_path("/music", "album/song.mp3", must_be_file=True)
        Path("/music/album/song.mp3")

        >>> resolve_library_path("/music", "アーティスト/曲.mp3", must_be_file=True)
        Path("/music/アーティスト/曲.mp3")

        >>> resolve_library_path("/music", "../../../etc/passwd")
        ValueError: Access denied

        >>> resolve_library_path("/music", "album", must_be_file=False)
        Path("/music/album")
    """
    import os
    from pathlib import PurePath

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

    # Step 2a: STRUCTURAL PRE-JOIN VALIDATION
    # Use PurePath for structural analysis without filesystem access
    # This satisfies CodeQL's requirement to validate BEFORE filesystem operations

    # Reject NUL bytes (can cause issues with filesystem operations)
    if "\x00" in user_path_string:
        logger.warning(f"[security] NUL byte detected in path: {user_path_string!r}")
        raise ValueError("Access denied")

    # Build PurePath for structural validation (platform-independent)
    try:
        pure_path = PurePath(user_path_string)
    except (ValueError, TypeError) as e:
        logger.warning(f"[security] Invalid path structure: {user_path_string!r}: {e}")
        raise ValueError("Access denied") from e

    # Reject absolute paths
    if pure_path.is_absolute():
        logger.warning(f"[security] Absolute path rejected: {user_path_string!r}")
        raise ValueError("Access denied")

    # Reject any path component that is exactly ".."
    if ".." in pure_path.parts:
        logger.warning(f"[security] Path traversal component '..' detected in: {user_path_string!r}")
        raise ValueError("Access denied")

    # Step 3: Join and normalize (CodeQL pattern)
    try:
        fullpath = os.path.normpath(os.path.join(base, user_path_string))
    except (OSError, ValueError) as e:
        logger.warning(f"[security] Failed to join paths {base!r} + {user_path_string!r}: {e}")
        raise ValueError("Access denied") from e

    # Step 4: Verify fullpath is within base boundary (CodeQL pattern)
    # Must check: fullpath == base OR fullpath.startswith(base + os.sep)
    if fullpath != base and not fullpath.startswith(base + os.sep):
        logger.warning(
            f"[security] Path traversal attempt: {user_path_string!r} resolved outside library {library_root!r}"
        )
        raise ValueError("Access denied")

    # Step 6: Convert to Path and resolve symlinks for canonical path validation
    candidate = Path(fullpath)
    # Canonicalize both base and candidate by resolving symlinks
    try:
        resolved_base = Path(base).resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=must_exist)
    except (OSError, RuntimeError) as e:
        logger.warning(f"[security] Failed to resolve symlink for {candidate!r}: {e}")
        raise ValueError("Access denied") from e

    # Ensure symlinks don't escape the root
    try:
        resolved_candidate.relative_to(resolved_base)
    except ValueError as e:
        logger.warning(
            f"[security] Symlink traversal detected: {resolved_candidate!r} is outside library {resolved_base!r}"
        )
        raise ValueError("Access denied") from e

    # Validate existence if required
    if must_exist and not resolved_candidate.exists():
        logger.debug(f"[security] Path does not exist: {resolved_candidate}")
        raise ValueError("Access denied")

    # Validate file/directory type if specified
    if must_be_file is True and not resolved_candidate.is_file():
        logger.debug(f"[security] Path is not a file: {resolved_candidate}")
        raise ValueError("Access denied")
    elif must_be_file is False and not resolved_candidate.is_dir():
        logger.debug(f"[security] Path is not a directory: {resolved_candidate}")
        raise ValueError("Access denied")

    return resolved_candidate


# Supported audio file extensions
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".mp4", ".flac", ".ogg", ".wav", ".aac", ".opus"}


def collect_audio_files(paths: list[str] | str, recursive: bool = True) -> list[str]:
    """
    Collect audio files from one or more paths (files or directories).

    Args:
        paths: Single path string or list of path strings
        recursive: If True, recursively scan directories. If False, only immediate children.

    Returns:
        Sorted list of absolute paths to audio files (deduplicated).

    Note:
        For user-provided paths, validate using validate_library_path() or
        resolve_library_path() before calling this function.
    """
    # Normalize to list
    if isinstance(paths, str):
        paths = [paths]

    files = []
    for path_str in paths:
        path = Path(path_str)

        if not path.exists():
            continue  # Skip non-existent paths

        if path.is_file():
            # Single file - check if it's audio
            if path.suffix.lower() in AUDIO_EXTENSIONS:
                files.append(str(path.resolve()))
        elif path.is_dir():
            # Directory - find all audio files
            if recursive:
                for ext in AUDIO_EXTENSIONS:
                    files.extend([str(p.resolve()) for p in path.rglob(f"*{ext}")])
            else:
                for ext in AUDIO_EXTENSIONS:
                    files.extend([str(p.resolve()) for p in path.glob(f"*{ext}")])

    return sorted(set(files))  # Deduplicate and sort


def is_audio_file(path: str) -> bool:
    """
    Check if a file path is a supported audio file.

    Args:
        path: File path to check

    Returns:
        True if the file extension is in AUDIO_EXTENSIONS, False otherwise.
    """
    return Path(path).suffix.lower() in AUDIO_EXTENSIONS
