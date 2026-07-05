"""Tag removal operations - remove namespaced tags from audio files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, cast

import mutagen
from mutagen import MutagenError
from mutagen.flac import FLAC
from mutagen.id3 import ID3, ID3NoHeaderError
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

if TYPE_CHECKING:
    from nomarr.helpers.dto.path_dto import LibraryPath

logger = logging.getLogger(__name__)


def remove_tags_from_file(path: LibraryPath, namespace: str) -> int:
    """Remove all namespaced tags from an audio file."""
    if not path.is_valid():
        msg = f"Cannot remove tags from invalid path ({path.status}): {path.absolute} - {path.reason}"
        raise ValueError(msg)

    try:
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

    except (OSError, ValueError, MutagenError, RuntimeError) as e:
        logger.exception("[tagging] Failed to remove tags from %s", path_str)
        msg = f"Failed to remove tags: {e}"
        raise RuntimeError(msg) from e


def _remove_id3_tags(path: str, namespace: str) -> int:
    """Remove namespaced TXXX frames from ID3v2 (MP3)."""
    try:
        audio = ID3(path)
    except ID3NoHeaderError:
        return 0

    txxx_prefix = f"{namespace}:"
    keys_to_remove = [key for key in audio if key.startswith("TXXX:") and key[5:].startswith(txxx_prefix)]

    for key in keys_to_remove:
        del audio[key]

    if keys_to_remove:
        audio.save()
        logger.info("[tagging] Removed %s ID3 tags from %s", len(keys_to_remove), path)

    return len(keys_to_remove)


def _remove_mp4_tags(path: str, namespace: str) -> int:
    """Remove namespaced freeform atoms from MP4/M4A."""
    try:
        audio = MP4(path)
        if audio.tags is None:
            return 0

        atom_prefix = f"----:com.apple.iTunes:{namespace}:"
        keys_to_remove = [key for key in audio.tags if isinstance(key, str) and key.startswith(atom_prefix)]

        for key in keys_to_remove:
            del audio.tags[key]

        if keys_to_remove:
            audio.save()
            logger.info("[tagging] Removed %s MP4 tags from %s", len(keys_to_remove), path)

        return len(keys_to_remove)

    except (OSError, MutagenError) as e:
        msg = f"MP4 tag removal failed: {e}"
        raise RuntimeError(msg) from e


def _remove_vorbis_tags(path: str, namespace: str) -> int:
    """Remove namespaced tags from Vorbis comments (FLAC, OGG, Opus)."""
    try:
        ext = Path(path).suffix.lower()
        if ext == ".flac":
            audio: mutagen.FileType = FLAC(path)
        elif ext == ".ogg":
            audio = OggVorbis(path)
        elif ext == ".opus":
            audio = OggOpus(path)
        else:
            msg = f"Unexpected extension for Vorbis format: {ext}"
            raise ValueError(msg)

        if audio.tags is None:
            return 0

        vorbis_prefix = f"{namespace.upper()}_"
        if not isinstance(audio.tags, dict):
            return 0
        audio_tags = cast("dict[str, list[str]]", audio.tags)
        keys_to_remove = [
            key for key, _ in audio_tags.items() if isinstance(key, str) and key.startswith(vorbis_prefix)
        ]

        for key in keys_to_remove:
            del audio_tags[key]

        if keys_to_remove:
            audio.save()
            logger.info("[tagging] Removed %s Vorbis tags from %s", len(keys_to_remove), path)

        return len(keys_to_remove)

    except (OSError, MutagenError) as e:
        msg = f"Vorbis tag removal failed: {e}"
        raise RuntimeError(msg) from e
