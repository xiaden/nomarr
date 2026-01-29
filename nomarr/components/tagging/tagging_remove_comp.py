"""Tag removal operations - remove namespaced tags from audio files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mutagen.flac import FLAC  # type: ignore[import-untyped]
from mutagen.id3 import ID3, ID3NoHeaderError  # type: ignore[import-untyped]
from mutagen.mp4 import MP4  # type: ignore[import-untyped]
from mutagen.oggopus import OggOpus  # type: ignore[import-untyped]
from mutagen.oggvorbis import OggVorbis  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from nomarr.helpers.dto.path_dto import LibraryPath

logger = logging.getLogger(__name__)


def remove_tags_from_file(path: LibraryPath, namespace: str) -> int:
    """Remove all namespaced tags from an audio file.

    Args:
        path: LibraryPath to audio file (must be valid)
        namespace: Tag namespace to remove (e.g., "nom", "essentia")

    Returns:
        Number of tags removed

    Raises:
        ValueError: If path is invalid or file format is unsupported
        RuntimeError: If file cannot be modified

    """
    # Enforce validation before file operations
    if not path.is_valid():
        msg = f"Cannot remove tags from invalid path ({path.status}): {path.absolute} - {path.reason}"
        raise ValueError(msg)

    try:
        # Infer format from file extension
        path_str = str(path.absolute)
        ext = Path(path_str).suffix.lower()

        if ext == ".mp3":
            return _remove_id3_tags(path_str, namespace)
        if ext in (".m4a", ".mp4", ".m4b", ".m4p"):
            return _remove_mp4_tags(path_str, namespace)
        if ext in (".flac", ".ogg", ".opus"):
            return _remove_vorbis_tags(path_str, namespace)
        msg = f"Unsupported audio format: {ext}"
        raise ValueError(msg)

    except Exception as e:
        logger.exception(f"[TagRemover] Failed to remove tags from {path_str}")
        msg = f"Failed to remove tags: {e}"
        raise RuntimeError(msg) from e


def _remove_id3_tags(path: str, namespace: str) -> int:
    """Remove namespaced tags from ID3v2 format (MP3).

    Removes all TXXX frames that start with namespace prefix.
    """
    try:
        audio = ID3(path)
    except ID3NoHeaderError:
        # No ID3 tags at all - nothing to remove
        return 0

    txxx_prefix = f"{namespace}:"
    keys_to_remove = [key for key in audio if key.startswith("TXXX:") and key[5:].startswith(txxx_prefix)]

    for key in keys_to_remove:
        del audio[key]

    if keys_to_remove:
        audio.save()
        logger.info(f"[TagRemover] Removed {len(keys_to_remove)} ID3 tags from {path}")

    return len(keys_to_remove)


def _remove_mp4_tags(path: str, namespace: str) -> int:
    """Remove namespaced tags from MP4/M4A format.

    Removes all iTunes freeform atoms that start with namespace prefix.
    """
    try:
        audio = MP4(path)
        if audio.tags is None:
            # No tags at all - nothing to remove
            return 0

        atom_prefix = f"----:com.apple.iTunes:{namespace}:"
        keys_to_remove = [key for key in audio.tags if isinstance(key, str) and key.startswith(atom_prefix)]

        for key in keys_to_remove:
            del audio.tags[key]

        if keys_to_remove:
            audio.save()
            logger.info(f"[TagRemover] Removed {len(keys_to_remove)} MP4 tags from {path}")

        return len(keys_to_remove)

    except Exception as e:
        msg = f"MP4 tag removal failed: {e}"
        raise RuntimeError(msg) from e


def _remove_vorbis_tags(path: str, namespace: str) -> int:
    """Remove namespaced tags from Vorbis comments format (FLAC, OGG, Opus).

    Vorbis tags use uppercase keys with underscores.
    """
    try:
        ext = Path(path).suffix.lower()
        if ext == ".flac":
            audio: Any = FLAC(path)
        elif ext == ".ogg":
            audio = OggVorbis(path)
        elif ext == ".opus":
            audio = OggOpus(path)
        else:
            msg = f"Unexpected extension for Vorbis format: {ext}"
            raise ValueError(msg)

        if audio.tags is None:
            return 0

        # Vorbis tags are uppercase with underscores
        vorbis_prefix = f"{namespace.upper()}_"
        keys_to_remove = [
            key for key, _ in audio.tags.items() if isinstance(key, str) and key.startswith(vorbis_prefix)
        ]  # type: ignore[attr-defined]

        for key in keys_to_remove:
            del audio.tags[key]  # type: ignore[attr-defined]

        if keys_to_remove:
            audio.save()
            logger.info(f"[TagRemover] Removed {len(keys_to_remove)} Vorbis tags from {path}")

        return len(keys_to_remove)

    except Exception as e:
        msg = f"Vorbis tag removal failed: {e}"
        raise RuntimeError(msg) from e
