"""Path validation DTOs for secure filesystem operations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidatedPath:
    """
    A filesystem path that has been validated for security and existence.

    This DTO proves that a path has gone through proper validation:
    - Security: validated against library root (prevents path traversal)
    - Existence: file exists and is accessible
    - Type: confirmed as a file (not directory)
    - Audio file: confirmed to be a supported audio format

    **IMPORTANT**: Do NOT construct ValidatedPath directly. Use the factory function:
        from nomarr.helpers.dto.path_dto import validated_path_from_string
        validated = validated_path_from_string(raw_path, library_root)

    The factory function enforces validation. Direct construction bypasses
    security checks and should only be used in tests.

    Persistence layer accepts ValidatedPath instead of raw strings,
    making it impossible to pass unvalidated paths through the type system.
    """

    path: str  # Absolute, validated, normalized path


def validated_path_from_string(
    file_path: str,
    library_root: str | None = None,
) -> ValidatedPath:
    """
    Validate a file path and return a ValidatedPath DTO.

    This is the ONLY public way to construct ValidatedPath from a string.
    It enforces all security and validation rules:
    - Path exists as a file
    - Path is a supported audio format
    - If library_root provided: path is within library boundary (no traversal)

    Args:
        file_path: Raw file path (absolute or relative)
        library_root: Optional library root for boundary validation

    Returns:
        ValidatedPath DTO proving validation occurred

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If path fails validation (not audio, outside boundary, etc.)

    Example:
        # With library boundary check
        validated = validated_path_from_string("/music/song.mp3", "/music")

        # Without library boundary check (for already-trusted paths)
        validated = validated_path_from_string("/music/song.mp3")
    """
    from pathlib import Path

    from nomarr.helpers.files_helper import is_audio_file, validate_library_path

    # If library_root provided, use full security validation
    if library_root:
        validated_str = validate_library_path(file_path, library_root)
    else:
        # No library boundary check - just validate file exists and is audio
        path_obj = Path(file_path)
        if not path_obj.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        if not path_obj.is_file():
            raise ValueError(f"Not a file: {file_path}")
        if not is_audio_file(str(path_obj)):
            raise ValueError(f"Not a supported audio file: {file_path}")
        validated_str = str(path_obj.resolve())

    return ValidatedPath(path=validated_str)
