"""
Metadata extraction component for audio files.

Handles format-specific tag extraction for MP4/M4A, FLAC, MP3, and other audio formats.
Uses mutagen library for low-level tag access.
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any

import mutagen  # type: ignore[import-untyped]
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.mp4 import MP4

from nomarr.components.tagging.tag_normalization_comp import (
    normalize_id3_tags,
    normalize_mp4_tags,
    normalize_vorbis_tags,
)

if TYPE_CHECKING:
    from nomarr.helpers.dto.path_dto import LibraryPath


def resolve_artists(all_tags: dict[str, str]) -> tuple[str | None, str | None]:
    """
    Resolve artist and artists tags with deduplication and fallback logic.

    Resolution rules:
    - If BOTH exist: Keep artist as single value, artists as multi-value list
    - If ONLY artists exists: Extract first as artist, keep full list as artists
    - If ONLY artist exists: Use same value for both
    - If neither exists: Return (None, None)

    Args:
        all_tags: Dict of normalized tags (may contain "artist" and/or "artists")

    Returns:
        Tuple of (artist_value, artists_value) - both strings or None
    """
    artist_value = all_tags.get("artist")
    artists_value = all_tags.get("artists")

    # Neither exists - return None for both
    if not artist_value and not artists_value:
        return (None, None)

    # Process artists field - split, deduplicate, rejoin
    if artists_value:
        # Split on common separators
        artists_list = []
        for sep in (";", ",", "/", " / "):
            if sep in artists_value:
                artists_list = [a.strip() for a in artists_value.split(sep)]
                break
        else:
            # No separator found - single value
            artists_list = [artists_value.strip()]

        # Deduplicate while preserving order
        seen = set()
        deduplicated = []
        for a in artists_list:
            if a and a not in seen:
                seen.add(a)
                deduplicated.append(a)

        artists_value = "; ".join(deduplicated) if deduplicated else None

    # Case 1: Both exist - keep both as-is
    if artist_value and artists_value:
        return (artist_value, artists_value)

    # Case 2: Only artists exists - extract first as artist
    if artists_value:
        first_artist = artists_value.split(";")[0].strip() if ";" in artists_value else artists_value
        return (first_artist, artists_value)

    # Case 3: Only artist exists - use for both
    if artist_value:
        return (artist_value, artist_value)

    return (None, None)


def extract_metadata(file_path: LibraryPath, namespace: str = "nom") -> dict[str, Any]:
    """
    Extract metadata and tags from an audio file.

    Handles format-specific tag extraction based on file extension.
    Extracts both standard metadata (artist, album, etc.) and namespace-specific
    tags (e.g., nom:* or ab:* tags).

    Namespace tags are stored WITHOUT the namespace prefix in the returned dict.
    For example, "nom:mood-strict" becomes "mood-strict" in nom_tags.

    Args:
        file_path: LibraryPath to audio file (must be valid)
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

    Raises:
        ValueError: If path is invalid

    Note:
        Handles MP3 (ID3), M4A/MP4, FLAC, and other mutagen-supported formats.
        Multi-value tags in MP3/FLAC are stored as JSON array strings.
    """
    # Enforce validation before file operations
    if not file_path.is_valid():
        raise ValueError(
            f"Cannot extract metadata from invalid path ({file_path.status}): {file_path.absolute} - {file_path.reason}"
        )

    path_str = str(file_path.absolute)

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
    file_ext = os.path.splitext(path_str)[1].lower()

    try:
        audio = mutagen.File(path_str)  # type: ignore[attr-defined]
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

    # Normalize ALL tags to canonical names first (for file_tags table)
    metadata["all_tags"] = normalize_mp4_tags(audio.tags)

    # Resolve artist/artists with deduplication
    artist_value, artists_value = resolve_artists(metadata["all_tags"])

    # Set standard metadata for library_files table
    metadata["title"] = metadata["all_tags"].get("title")
    metadata["artist"] = artist_value
    metadata["album"] = metadata["all_tags"].get("album")
    metadata["genre"] = metadata["all_tags"].get("genre")

    # Parse year from date
    year_str = metadata["all_tags"].get("year") or metadata["all_tags"].get("date")
    if year_str:
        try:
            metadata["year"] = int(year_str[:4])
        except (ValueError, IndexError):
            pass

    # Parse track number (may be "10/10" format from normalized tags)
    track_str = metadata["all_tags"].get("tracknumber")
    if track_str:
        try:
            metadata["track_number"] = int(track_str.split("/")[0])
        except (ValueError, IndexError):
            pass

    # Update all_tags with resolved artist/artists
    if artist_value:
        metadata["all_tags"]["artist"] = artist_value
    if artists_value:
        metadata["all_tags"]["artists"] = artists_value

    # Extract namespace tags (nom:*) - store WITHOUT namespace prefix
    # and REMOVE from all_tags to prevent duplication
    nom_tags: dict[str, str] = {}
    keys_to_remove = []
    for key, value in metadata["all_tags"].items():
        if isinstance(key, str) and key.lower().startswith(f"{namespace.lower()}:"):
            tag_key = key[len(namespace) + 1 :]  # Remove "nom:" prefix
            nom_tags[tag_key] = value
            keys_to_remove.append(key)

    # Remove namespace tags from all_tags
    for key in keys_to_remove:
        del metadata["all_tags"][key]

    metadata["nom_tags"] = nom_tags


def _extract_flac_metadata(audio: Any, metadata: dict[str, Any], namespace: str) -> None:
    """Extract metadata from FLAC files using Vorbis comments."""
    if not isinstance(audio, FLAC):
        return

    # Normalize ALL tags to canonical names first (for file_tags table)
    metadata["all_tags"] = normalize_vorbis_tags(dict(audio))

    # Resolve artist/artists with deduplication
    artist_value, artists_value = resolve_artists(metadata["all_tags"])

    # Set standard metadata for library_files table
    metadata["title"] = metadata["all_tags"].get("title")
    metadata["artist"] = artist_value
    metadata["album"] = metadata["all_tags"].get("album")
    metadata["genre"] = metadata["all_tags"].get("genre")

    # Parse year from date
    year_str = metadata["all_tags"].get("year") or metadata["all_tags"].get("date")
    if year_str:
        try:
            metadata["year"] = int(year_str[:4])
        except (ValueError, IndexError):
            pass

    # Parse track number
    track_str = metadata["all_tags"].get("tracknumber")
    if track_str:
        try:
            metadata["track_number"] = int(track_str.split("/")[0])
        except (ValueError, IndexError):
            pass

    # Update all_tags with resolved artist/artists
    if artist_value:
        metadata["all_tags"]["artist"] = artist_value
    if artists_value:
        metadata["all_tags"]["artists"] = artists_value

    # Extract namespace tags (nom:*) - store WITHOUT namespace prefix
    # and REMOVE from all_tags to prevent duplication
    nom_tags: dict[str, str] = {}
    keys_to_remove = []
    for key, value in metadata["all_tags"].items():
        if isinstance(key, str) and key.lower().startswith(f"{namespace.lower()}:"):
            tag_key = key[len(namespace) + 1 :]  # Remove "nom:" prefix
            nom_tags[tag_key] = value
            keys_to_remove.append(key)

    # Remove namespace tags from all_tags
    for key in keys_to_remove:
        del metadata["all_tags"][key]

    metadata["nom_tags"] = nom_tags


def _extract_mp3_metadata(file_path: LibraryPath, metadata: dict[str, Any], namespace: str) -> None:
    """Extract metadata from MP3 files using ID3 tags."""
    # Use ID3 for detailed tags - normalize to canonical names (for file_tags table)
    try:
        id3 = ID3(str(file_path.absolute))
        metadata["all_tags"] = normalize_id3_tags(dict(id3))

        # Resolve artist/artists with deduplication
        artist_value, artists_value = resolve_artists(metadata["all_tags"])

        # Set standard metadata for library_files table
        metadata["title"] = metadata["all_tags"].get("title")
        metadata["artist"] = artist_value
        metadata["album"] = metadata["all_tags"].get("album")
        metadata["genre"] = metadata["all_tags"].get("genre")

        # Parse year from date
        year_str = metadata["all_tags"].get("year") or metadata["all_tags"].get("date")
        if year_str:
            try:
                metadata["year"] = int(year_str[:4])
            except (ValueError, IndexError):
                pass

        # Parse track number
        track_str = metadata["all_tags"].get("tracknumber")
        if track_str:
            try:
                metadata["track_number"] = int(track_str.split("/")[0])
            except (ValueError, IndexError):
                pass

        # Update all_tags with resolved artist/artists
        if artist_value:
            metadata["all_tags"]["artist"] = artist_value
        if artists_value:
            metadata["all_tags"]["artists"] = artists_value

        # Extract namespace tags (nom:*) - store WITHOUT namespace prefix
        # and REMOVE from all_tags to prevent duplication
        nom_tags: dict[str, str] = {}
        keys_to_remove = []
        for key, value in metadata["all_tags"].items():
            if isinstance(key, str) and key.lower().startswith(f"{namespace.lower()}:"):
                tag_key = key[len(namespace) + 1 :]  # Remove "nom:" prefix
                nom_tags[tag_key] = value
                keys_to_remove.append(key)

        # Remove namespace tags from all_tags
        for key in keys_to_remove:
            del metadata["all_tags"][key]

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
