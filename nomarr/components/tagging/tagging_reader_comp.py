"""Tag reading operations - extract tags from audio files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, cast

import mutagen

from nomarr.helpers.dto.tags_dto import Tag, Tags, TagValue

if TYPE_CHECKING:
    from nomarr.helpers.dto.path_dto import LibraryPath

logger = logging.getLogger(__name__)

# Default namespace for nomarr tags - must match INTERNAL_NAMESPACE in config_svc.py
DEFAULT_NAMESPACE = "nom"


def read_nomarr_namespace(path: LibraryPath, namespace: str = DEFAULT_NAMESPACE) -> set[str]:
    """Return the set of nomarr-prefixed tag names found in the file."""
    try:
        if not path.is_valid():
            return set()
        tags = read_tags_from_file(path, namespace)
        return {tag.key for tag in tags}
    except (ValueError, RuntimeError):
        return set()


# Mood-tier tag names - written in "minimal" mode
MOOD_TIER_TAGS = {"mood-strict", "mood-regular", "mood-loose"}


def infer_write_mode_from_tags(tag_names: set[str]) -> str | None:
    """Infer write mode from tag names: "none" | "minimal" | "full" | None."""
    if not tag_names:
        return "none"

    has_non_mood = any(name not in MOOD_TIER_TAGS for name in tag_names)

    if has_non_mood:
        return "full"
    if tag_names & MOOD_TIER_TAGS:  # Has at least one mood tag
        return "minimal"
    return None


def read_tags_from_file(path: LibraryPath, namespace: str) -> Tags:
    """Read namespaced tags from an audio file."""
    if not path.is_valid():
        msg = f"Cannot read tags from invalid path ({path.status}): {path.absolute} - {path.reason}"
        raise ValueError(msg)

    try:
        path_str = str(path.absolute)
        ext = Path(path_str).suffix.lower()

        if ext == ".mp3":
            audio = cast("mutagen.FileType", mutagen.File(path_str))
            if audio is None:
                msg = f"Failed to load MP3 file: {path_str}"
                raise ValueError(msg)
            tag_dict = _extract_id3_tags(audio, namespace)

        elif ext in (".m4a", ".mp4", ".m4b", ".m4p"):
            audio = cast("mutagen.FileType", mutagen.File(path_str))
            if audio is None:
                msg = f"Failed to load MP4 file: {path_str}"
                raise ValueError(msg)
            tag_dict = _extract_mp4_tags(audio, namespace)

        elif ext in (".flac", ".ogg", ".opus"):
            audio = cast("mutagen.FileType", mutagen.File(path_str))
            if audio is None:
                msg = f"Failed to load Vorbis file: {path_str}"
                raise ValueError(msg)
            tag_dict = _extract_vorbis_tags(audio, namespace)

        else:
            msg = f"Unsupported audio format: {ext}"
            raise ValueError(msg)

        items = tuple(Tag(key=k, value=tuple(cast("list[TagValue]", v))) for k, v in tag_dict.items())
        return Tags(items=items)

    except (ValueError, mutagen.MutagenError) as e:
        logger.exception(f"[TagReader] Failed to read tags from {path_str}")
        msg = f"Failed to read tags: {e}"
        raise RuntimeError(msg) from e


def _extract_id3_tags(audio: mutagen.FileType, namespace: str) -> dict[str, list[str]]:
    """Extract namespaced tags from ID3v2 TXXX frames."""
    tags: dict[str, list[str]] = {}
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

        tags[clean_name] = list(values)

    return tags


def _extract_mp4_tags(audio: mutagen.FileType, namespace: str) -> dict[str, list[str]]:
    """Extract namespaced tags from MP4 freeform atoms."""
    tags: dict[str, list[str]] = {}
    if audio.tags is None or not hasattr(audio.tags, "items"):
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
                tags[clean_name] = decoded
            else:
                decoded_val = value.decode("utf-8") if isinstance(value, bytes) else str(value)
                tags[clean_name] = [decoded_val]
        except (UnicodeDecodeError, AttributeError, TypeError) as e:
            logger.warning("[TagReader] Failed to decode tag %s: %s", key, e)
            continue

    return tags


def _extract_vorbis_tags(audio: mutagen.FileType, namespace: str) -> dict[str, list[str]]:
    """Extract namespaced tags from Vorbis comments."""
    tags: dict[str, list[str]] = {}
    if not hasattr(audio, "tags") or not audio.tags:
        return tags

    # Convert namespace to uppercase with underscore for Vorbis format
    vorbis_prefix = f"{namespace.upper()}_"

    for key, values in audio.tags.items():
        if not isinstance(key, str) or not key.startswith(vorbis_prefix):
            continue

        clean_name = key[len(vorbis_prefix) :].lower().replace("_", "-")
        tags[clean_name] = list(values)

    return tags
