"""
Metadata extraction component for audio files.

Handles format-specific tag extraction for MP4/M4A, FLAC, MP3, and other audio formats.
Uses mutagen library for low-level tag access.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import mutagen  # type: ignore[import-untyped]
from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.mp4 import MP4

from nomarr.components.library.tag_normalization_comp import (
    normalize_id3_tags,
    normalize_mp4_tags,
    normalize_vorbis_tags,
)


def extract_metadata(file_path: str, namespace: str = "nom") -> dict[str, Any]:
    """
    Extract metadata and tags from an audio file.

    Handles format-specific tag extraction based on file extension.
    Extracts both standard metadata (artist, album, etc.) and namespace-specific
    tags (e.g., nom:* or ab:* tags).

    Namespace tags are stored WITHOUT the namespace prefix in the returned dict.
    For example, "nom:mood-strict" becomes "mood-strict" in nom_tags.

    Args:
        file_path: Absolute path to audio file
        namespace: Tag namespace to extract (default: "nom")

    Returns:
        Dict with:
        - duration: float | None (seconds)
        - artist: str | None
        - album: str | None
        - title: str | None
        - genre: str | None
        - year: int | None
        - track_number: int | None
        - all_tags: dict[str, str] (all tags as strings)
        - nom_tags: dict[str, str] (namespace tags WITHOUT prefix)

    Note:
        Handles MP3 (ID3), M4A/MP4, FLAC, and other mutagen-supported formats.
        Multi-value tags in MP3/FLAC are stored as JSON array strings.
    """
    metadata: dict[str, Any] = {
        "duration": None,
        "artist": None,
        "album": None,
        "title": None,
        "genre": None,
        "year": None,
        "track_number": None,
        "all_tags": {},
        "nom_tags": {},
    }

    # Get file extension to determine tag format
    file_ext = os.path.splitext(file_path)[1].lower()

    try:
        audio = mutagen.File(file_path)  # type: ignore[attr-defined]
        if audio is None:
            return metadata

        # Get duration (format-agnostic)
        if hasattr(audio.info, "length"):
            metadata["duration"] = audio.info.length

        # Extract tags based on file extension
        if file_ext in (".m4a", ".mp4", ".m4p", ".m4b"):
            # M4A/MP4 files - use MP4 atoms
            _extract_mp4_metadata(audio, metadata, namespace)

        elif file_ext == ".flac":
            # FLAC files - use Vorbis comments
            _extract_flac_metadata(audio, metadata, namespace)

        elif file_ext in (".mp3", ".mp2", ".aac"):
            # MP3 and similar - use ID3 tags
            _extract_mp3_metadata(file_path, metadata, namespace)

    except Exception as e:
        logging.debug(f"[metadata_extraction] Failed to extract metadata from {file_path}: {e}")

    return metadata


def _extract_mp4_metadata(audio: Any, metadata: dict[str, Any], namespace: str) -> None:
    """Extract metadata from M4A/MP4 files using MP4 atoms."""
    if not isinstance(audio, MP4) or not audio.tags:
        return

    # Standard metadata (extract directly for library_files table)
    metadata["artist"] = _get_first(audio.tags, "\xa9ART")
    metadata["album"] = _get_first(audio.tags, "\xa9alb")
    metadata["title"] = _get_first(audio.tags, "\xa9nam")
    metadata["genre"] = _get_first(audio.tags, "\xa9gen")
    year_str = _get_first(audio.tags, "\xa9day")
    if year_str:
        try:
            metadata["year"] = int(year_str[:4])
        except (ValueError, IndexError):
            pass
    track = _get_first(audio.tags, "trkn")
    if track and isinstance(track, tuple) and len(track) > 0:
        metadata["track_number"] = track[0]

    # Normalize ALL tags to common names (for file_tags table)
    metadata["all_tags"] = normalize_mp4_tags(audio.tags)

    # Extract namespace tags (nom:*, ab:*, etc.) - store WITHOUT namespace prefix
    nom_tags: dict[str, str] = {}
    for key, value in metadata["all_tags"].items():
        if ":" in key and key.startswith(f"{namespace}:"):
            tag_key = key[len(namespace) + 1 :]  # Remove "nom:" prefix
            nom_tags[tag_key] = value
    metadata["nom_tags"] = nom_tags


def _extract_flac_metadata(audio: Any, metadata: dict[str, Any], namespace: str) -> None:
    """Extract metadata from FLAC files using Vorbis comments."""
    if not isinstance(audio, FLAC):
        return

    # Standard metadata (extract directly for library_files table)
    metadata["artist"] = _get_first(audio, "ARTIST")
    metadata["album"] = _get_first(audio, "ALBUM")
    metadata["title"] = _get_first(audio, "TITLE")
    metadata["genre"] = _get_first(audio, "GENRE")
    year_str = _get_first(audio, "DATE")
    if year_str:
        try:
            metadata["year"] = int(year_str[:4])
        except (ValueError, IndexError):
            pass
    track_str = _get_first(audio, "TRACKNUMBER")
    if track_str:
        try:
            metadata["track_number"] = int(track_str.split("/")[0])
        except (ValueError, IndexError):
            pass

    # Normalize ALL tags to common names (for file_tags table)
    metadata["all_tags"] = normalize_vorbis_tags(dict(audio))

    # Extract namespace tags (nom:*, ab:*, etc.) - store WITHOUT namespace prefix
    nom_tags: dict[str, str] = {}
    for key, value in metadata["all_tags"].items():
        if ":" in key and key.lower().startswith(f"{namespace.lower()}:"):
            tag_key = key[len(namespace) + 1 :]  # Remove "nom:" prefix
            nom_tags[tag_key] = value
    metadata["nom_tags"] = nom_tags


def _extract_mp3_metadata(file_path: str, metadata: dict[str, Any], namespace: str) -> None:
    """Extract metadata from MP3 files using ID3 tags."""
    # Try EasyID3 for standard metadata (for library_files table)
    try:
        easy = EasyID3(file_path)
        metadata["artist"] = _get_first(easy, "artist")
        metadata["album"] = _get_first(easy, "album")
        metadata["title"] = _get_first(easy, "title")
        metadata["genre"] = _get_first(easy, "genre")
        year_str = _get_first(easy, "date")
        if year_str:
            try:
                metadata["year"] = int(year_str[:4])
            except (ValueError, IndexError):
                pass
        track_str = _get_first(easy, "tracknumber")
        if track_str:
            try:
                metadata["track_number"] = int(track_str.split("/")[0])
            except (ValueError, IndexError):
                pass
    except Exception:
        pass

    # Try ID3 for detailed tags - normalize ALL tags to common names (for file_tags table)
    try:
        id3 = ID3(file_path)
        metadata["all_tags"] = normalize_id3_tags(dict(id3))

        # Extract namespace tags (nom:*, ab:*, etc.) - store WITHOUT namespace prefix
        nom_tags: dict[str, str] = {}
        for key, value in metadata["all_tags"].items():
            if ":" in key and key.startswith(f"{namespace}:"):
                tag_key = key[len(namespace) + 1 :]  # Remove "nom:" prefix
                nom_tags[tag_key] = value
        metadata["nom_tags"] = nom_tags
    except Exception:
        pass


def _get_first(tags: Any, key: str) -> str | None:
    """
    Get first value from a tag dict.

    Handles both mutagen tag dicts (which store values as lists) and regular dicts.

    Args:
        tags: Tag dictionary (supports .get() method)
        key: Tag key

    Returns:
        First value as string, or None if not found
    """
    value = tags.get(key)
    if value is None:
        return None
    if isinstance(value, list) and len(value) > 0:
        return str(value[0])
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


def _serialize_mutagen_value(value: Any) -> str:
    """
    Serialize a mutagen tag value to a string.

    Handles various mutagen types:
    - MP4FreeForm: Extract bytes and decode
    - Lists: Process all elements, JSON-encode if multiple values
    - Bytes: Decode to UTF-8
    - Everything else: str()

    Multi-value tags are JSON-encoded as arrays. The _parse_tag_values()
    function will parse them back to lists when storing in the database.

    Args:
        value: Mutagen tag value

    Returns:
        String representation of the value
    """
    # Handle MP4FreeForm values (bytes wrapped in a list-like object)
    if hasattr(value, "__iter__") and not isinstance(value, (str, bytes)):
        try:
            items = list(value)
            if len(items) == 0:
                return ""
            # If single item, unwrap and serialize it
            if len(items) == 1:
                item = items[0]
                if isinstance(item, bytes):
                    return item.decode("utf-8", errors="replace")
                return str(item)
            # Multiple items - JSON encode
            decoded = []
            for item in items:
                if isinstance(item, bytes):
                    decoded.append(item.decode("utf-8", errors="replace"))
                else:
                    decoded.append(str(item))
            return json.dumps(decoded, ensure_ascii=False)
        except Exception:
            return str(value)

    # Handle bytes directly
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    # Everything else
    return str(value)
