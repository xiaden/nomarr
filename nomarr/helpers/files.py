"""
File system helpers for audio file operations.
Shared across all interfaces (CLI, API, Web) and core functionality.
"""

from __future__ import annotations

from pathlib import Path

# Supported audio file extensions
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".mp4", ".flac", ".ogg", ".wav", ".aac", ".opus", ".wma"}


def collect_audio_files(paths: list[str] | str, recursive: bool = True) -> list[str]:
    """
    Collect audio files from one or more paths (files or directories).

    Args:
        paths: Single path string or list of path strings
        recursive: If True, recursively scan directories. If False, only immediate children.

    Returns:
        Sorted list of absolute paths to audio files (deduplicated).
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
