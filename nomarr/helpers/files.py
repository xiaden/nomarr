"""
File system helpers for audio file operations.

TRUST BOUNDARY:
These functions operate on paths that have already been validated at the interface layer
(via helpers.security.validate_library_path or resolve_library_path), or are from trusted
admin/CLI inputs. They do NOT perform path traversal validation themselves.

SECURITY:
- Path validation must happen at interface boundaries (API, CLI, Web)
- Use helpers.security for all user-controlled path validation
- Do not reimplement traversal checks here

Shared across all interfaces (CLI, API, Web) and core functionality.
"""

from __future__ import annotations

from pathlib import Path

# Supported audio file extensions
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".mp4", ".flac", ".ogg", ".wav", ".aac", ".opus", ".wma"}


def collect_audio_files(paths: list[str] | str, recursive: bool = True) -> list[str]:
    """
    Collect audio files from one or more paths (files or directories).

    SECURITY: This function operates on paths that have been validated at the
    interface layer. It does NOT perform path traversal validation. Callers must
    validate user-provided paths using helpers.security before calling this.

    Args:
        paths: Single path string or list of path strings (pre-validated)
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
