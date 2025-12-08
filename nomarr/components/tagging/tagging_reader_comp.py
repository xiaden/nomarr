"""Tag reading operations - extract tags from audio files."""

from __future__ import annotations

import logging
from typing import Any

import mutagen  # type: ignore[import-untyped]
from mutagen.id3 import ID3
from mutagen.mp4 import MP4

logger = logging.getLogger(__name__)


def read_tags_from_file(path: str, namespace: str) -> dict[str, Any]:
    """
    Read namespaced tags from an audio file.

    Args:
        path: Absolute path to audio file
        namespace: Tag namespace to filter (e.g., "nom", "essentia")

    Returns:
        Dictionary of tag name -> value(s)
        Multi-value tags returned as lists, single values as strings

    Raises:
        ValueError: If file format is unsupported
        RuntimeError: If file cannot be read
    """
    try:
        audio = mutagen.File(path)  # type: ignore[attr-defined]
        if audio is None:
            raise ValueError(f"Unsupported audio format: {path}")

        # Try MP3 format first
        if isinstance(audio, ID3) or (hasattr(audio, "tags") and hasattr(audio.tags, "getall")):
            return _extract_id3_tags(audio, namespace)

        # Try MP4/M4A format
        if isinstance(audio, MP4) or (hasattr(audio, "tags") and hasattr(audio.tags, "items")):
            return _extract_mp4_tags(audio, namespace)

        # Vorbis comments (FLAC, OGG, Opus)
        if hasattr(audio, "tags") and hasattr(audio.tags, "get"):
            return _extract_vorbis_tags(audio, namespace)

        raise ValueError(f"No supported tag format found in: {path}")

    except Exception as e:
        logger.exception(f"[TagReader] Failed to read tags from {path}")
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
