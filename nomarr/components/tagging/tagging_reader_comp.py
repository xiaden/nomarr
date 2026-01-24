"""Tag reading operations - extract tags from audio files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import mutagen  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from nomarr.helpers.dto.path_dto import LibraryPath

logger = logging.getLogger(__name__)

# Default namespace for nomarr tags - must match INTERNAL_NAMESPACE in config_svc.py
DEFAULT_NAMESPACE = "nom"


def read_nomarr_namespace(path: LibraryPath, namespace: str = DEFAULT_NAMESPACE) -> set[str]:
    """
    Check which nomarr tags exist in an audio file.

    Returns the set of tag names found under the specified namespace.
    Used to detect if files have been written to by nomarr, and to
    infer the write mode used.

    Args:
        path: LibraryPath to audio file (must be valid)
        namespace: Tag namespace to check (default: "nom")

    Returns:
        Set of tag names found (e.g., {"mood-strict", "mood-regular", "yamnet-class"})
        Empty set if no nomarr tags found or file cannot be read.

    Note:
        Does not raise exceptions - returns empty set on any error.
        This is intentional for scanning performance.
    """
    try:
        if not path.is_valid():
            return set()
        return set(read_tags_from_file(path, namespace).keys())
    except Exception:
        # Silently return empty set - scanning shouldn't fail on read errors
        return set()


# Mood-tier tag names - written in "minimal" mode
MOOD_TIER_TAGS = {"mood-strict", "mood-regular", "mood-loose"}


def infer_write_mode_from_tags(tag_names: set[str]) -> str | None:
    """
    Infer what write mode was used based on the tags present.

    Args:
        tag_names: Set of tag names found in the file

    Returns:
        "none" if no tags found
        "minimal" if only mood tags found
        "full" if any non-mood tags found
        None if indeterminate
    """
    if not tag_names:
        return "none"

    # Check if we have any non-mood tags
    has_non_mood = any(name not in MOOD_TIER_TAGS for name in tag_names)

    if has_non_mood:
        return "full"
    elif tag_names & MOOD_TIER_TAGS:  # Has at least one mood tag
        return "minimal"
    else:
        return None


def read_tags_from_file(path: LibraryPath, namespace: str) -> dict[str, Any]:
    """
    Read namespaced tags from an audio file.

    Args:
        path: LibraryPath to audio file (must be valid)
        namespace: Tag namespace to filter (e.g., "nom", "essentia")

    Returns:
        Dictionary of tag name -> value(s)
        Multi-value tags returned as lists, single values as strings

    Raises:
        ValueError: If path is invalid or file format is unsupported
        RuntimeError: If file cannot be read
    """
    # Enforce validation before file operations
    if not path.is_valid():
        raise ValueError(f"Cannot read tags from invalid path ({path.status}): {path.absolute} - {path.reason}")

    try:
        # Infer format from file extension - faster than loading file
        path_str = str(path.absolute)
        ext = Path(path_str).suffix.lower()

        # Route to appropriate extractor based on extension
        if ext == ".mp3":
            audio = mutagen.File(path_str)  # type: ignore[attr-defined]
            if audio is None:
                raise ValueError(f"Failed to load MP3 file: {path_str}")
            return _extract_id3_tags(audio, namespace)

        elif ext in (".m4a", ".mp4", ".m4b", ".m4p"):
            audio = mutagen.File(path_str)  # type: ignore[attr-defined]
            if audio is None:
                raise ValueError(f"Failed to load MP4 file: {path_str}")
            return _extract_mp4_tags(audio, namespace)

        elif ext in (".flac", ".ogg", ".opus"):
            audio = mutagen.File(path_str)  # type: ignore[attr-defined]
            if audio is None:
                raise ValueError(f"Failed to load Vorbis file: {path_str}")
            return _extract_vorbis_tags(audio, namespace)

        else:
            raise ValueError(f"Unsupported audio format: {ext}")

    except Exception as e:
        logger.exception(f"[TagReader] Failed to read tags from {path_str}")
        raise RuntimeError(f"Failed to read tags: {e}") from e


def _extract_id3_tags(audio: Any, namespace: str) -> dict[str, Any]:
    """
    Extract tags from ID3v2 format (MP3).

    Reads TXXX (user-defined text) frames with namespace prefix.
    """
    tags: dict[str, Any] = {}
    if not hasattr(audio, "tags") or not audio.tags:
        return tags

    for key in audio.tags:
        if not isinstance(key, str) or not key.startswith("TXXX:"):
            continue

        tag_name = key[5:]  # Remove "TXXX:" prefix
        if not tag_name.startswith(f"{namespace}:"):
            continue

        clean_name = tag_name[len(namespace) + 1 :]  # Remove namespace prefix
        values = audio.tags[key].text

        # Multi-value handling: list if multiple values, single string if one
        tags[clean_name] = values if len(values) > 1 else values[0]

    return tags


def _extract_mp4_tags(audio: Any, namespace: str) -> dict[str, Any]:
    """
    Extract tags from MP4/M4A format.

    Reads iTunes freeform atoms (----:com.apple.iTunes:) with namespace prefix.
    """
    tags: dict[str, Any] = {}
    if not hasattr(audio, "tags") or not hasattr(audio.tags, "items"):
        return tags

    for key, value in audio.tags.items():
        if not isinstance(key, str) or not key.startswith("----:com.apple.iTunes:"):
            continue

        tag_name = key[22:]  # Remove "----:com.apple.iTunes:" prefix
        if not tag_name.startswith(f"{namespace}:"):
            continue

        clean_name = tag_name[len(namespace) + 1 :]  # Remove namespace prefix

        # MP4 freeform atoms are lists of MP4FreeForm objects
        try:
            if isinstance(value, list):
                decoded = []
                for item in value:
                    if isinstance(item, bytes) or hasattr(item, "decode"):
                        decoded.append(item.decode("utf-8"))
                    else:
                        decoded.append(str(item))

                # Return single value if only one, otherwise return list
                tags[clean_name] = decoded[0] if len(decoded) == 1 else decoded
            else:
                # Fallback for non-list values
                tags[clean_name] = value.decode("utf-8") if isinstance(value, bytes) else str(value)
        except Exception as e:
            # Log and skip malformed tags
            logger.warning(f"[TagReader] Failed to decode tag {key}: {e}")
            continue

    return tags


def _extract_vorbis_tags(audio: Any, namespace: str) -> dict[str, Any]:
    """
    Extract tags from Vorbis comments format (FLAC, OGG, Opus).

    Vorbis tags use uppercase keys with underscores.
    Example: "ESSENTIA_YAMNET_HAPPY" for namespace "essentia"
    """
    tags: dict[str, Any] = {}
    if not hasattr(audio, "tags") or not audio.tags:
        return tags

    # Convert namespace to uppercase with underscore for Vorbis format
    vorbis_prefix = f"{namespace.upper()}_"

    for key, values in audio.tags.items():
        if not isinstance(key, str) or not key.startswith(vorbis_prefix):
            continue

        clean_name = key[len(vorbis_prefix) :].lower().replace("_", "-")

        # Multi-value handling
        tags[clean_name] = values if len(values) > 1 else values[0]

    return tags
