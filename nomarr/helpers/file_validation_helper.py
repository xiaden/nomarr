"""File validation and skip logic utilities.

Pure utility functions for:
- File existence/readability checks
- Version tag checking (skip logic)
- Result formatting for skipped files

These are stateless helpers that only depend on stdlib and third-party libraries.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any


def validate_file_exists(path: str) -> None:
    """Check if file exists and is readable.

    This function operates on paths that are already in the processing queue/database.
    For user-supplied paths, validate through helpers.files first.

    Args:
        path: Path to audio file (from database/queue)

    Raises:
        RuntimeError: If file doesn't exist or isn't readable

    """
    # Use Path for safer filesystem checks
    file_path = Path(path)
    if not file_path.exists():
        msg = f"File not found: {path}"
        raise RuntimeError(msg)
    if not file_path.is_file():
        msg = f"Not a file: {path}"
        raise RuntimeError(msg)
    # Check readability using os.access for platform compatibility
    import os

    if not os.access(path, os.R_OK):
        msg = f"File not readable: {path}"
        raise RuntimeError(msg)


def check_already_tagged(
    path: str,
    namespace: str,
    version_tag_key: str,
    current_version: str,
) -> bool:
    """Check if file already has the correct version tag.

    This determines whether processing should be skipped.

    Args:
        path: Path to audio file
        namespace: Tag namespace (e.g., "essentia")
        version_tag_key: Key name for version tag
        current_version: Expected version string

    Returns:
        True if file is already tagged with current version, False otherwise

    """
    try:
        from mutagen._file import File as MutagenFile

        audio = MutagenFile(path)
        if not audio or not hasattr(audio, "tags") or not audio.tags:
            return False

        # Check for version tag in namespace
        for key in audio.tags:
            key_str = str(key)
            # MP4/M4A format
            if f"----:com.apple.iTunes:{namespace}:{version_tag_key}" in key_str:
                values = audio.tags[key]
                if values and hasattr(values[0], "decode"):
                    existing_version = values[0].decode("utf-8", errors="replace")
                    return existing_version == current_version  # type: ignore[no-any-return]
            # MP3 format
            elif key_str == f"TXXX:{namespace}:{version_tag_key}":
                values = audio.tags[key]
                if hasattr(values, "text") and values.text:
                    return str(values.text[0]) == current_version

        return False
    except Exception as e:
        logging.debug(f"[validation] Could not check version tag for {path}: {e}")
        return False


def should_skip_processing(
    path: str,
    force: bool,
    namespace: str,
    version_tag_key: str,
    tagger_version: str,
) -> tuple[bool, str | None]:
    """Determine if processing should be skipped for this file.

    Centralizes all skip logic so process_file() doesn't need to decide.

    Args:
        path: Path to audio file
        force: If True, never skip (force reprocessing)
        namespace: Tag namespace
        version_tag_key: Key name for version tag
        tagger_version: Current tagger version

    Returns:
        Tuple of (should_skip, skip_reason)
        - If should_skip is True, caller should not call process_file()
        - skip_reason explains why (for logging/reporting)

    """
    # Force mode: never skip
    if force:
        return (False, None)

    # Check if already tagged with current version
    if check_already_tagged(path, namespace, version_tag_key, tagger_version):
        return (True, f"already_tagged_v{tagger_version}")

    # Not skipped
    return (False, None)


def make_skip_result(path: str, skip_reason: str) -> dict[str, Any]:
    """Create a standardized result dict for skipped files.

    This matches the format returned by process_file() so callers
    can handle skipped and processed files uniformly.

    Args:
        path: Path to audio file
        skip_reason: Why processing was skipped

    Returns:
        Result dict matching process_file() output format

    """
    return {
        "file": path,
        "elapsed": 0.0,
        "duration": 0.0,
        "heads_processed": 0,
        "tags_written": 0,
        "skipped": True,
        "skip_reason": skip_reason,
        "tags": {},
    }
