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

# Standard MP4 atoms to include (filtering out MusicBrainz/Picard spam)
ALLOWED_MP4_TAGS = {
    "\xa9nam",  # Title
    "\xa9ART",  # Artist
    "\xa9alb",  # Album
    "\xa9gen",  # Genre
    "\xa9day",  # Year
    "trkn",  # Track number
    "disk",  # Disc number
    "aART",  # Album artist
    "\xa9wrt",  # Composer
    "\xa9cmt",  # Comment
    "cprt",  # Copyright
    "\xa9lyr",  # Lyrics
    "tmpo",  # BPM
    "covr",  # Cover art
}

# Standard ID3 frames to include (filtering out MusicBrainz/Picard spam)
ALLOWED_ID3_FRAMES = {
    "TIT2",  # Title
    "TPE1",  # Artist
    "TALB",  # Album
    "TCON",  # Genre
    "TDRC",  # Year
    "TRCK",  # Track number
    "TPOS",  # Disc number
    "TPE2",  # Album artist
    "TCOM",  # Composer
    "COMM",  # Comment
    "USLT",  # Lyrics
    "TBPM",  # BPM
    "APIC",  # Cover art
}


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
        audio = mutagen.File(file_path)
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

    # Standard metadata
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

    # Filter tags (standard music metadata + namespace tags)
    filtered_tags = {}
    for k, v in audio.tags.items():
        # Include namespace tags (----:com.apple.iTunes:nom:*, etc.)
        # Only include freeform tags if they have a namespace prefix (colon after prefix removal)
        if isinstance(k, str) and k.startswith("----:com.apple.iTunes:"):
            tag_name = k.replace("----:com.apple.iTunes:", "")
            if ":" in tag_name:  # Must have namespace prefix (nom:, ab:, etc.)
                filtered_tags[k] = v
        # Include standard music metadata atoms from whitelist
        elif k in ALLOWED_MP4_TAGS:
            filtered_tags[k] = v
    metadata["all_tags"] = {k: _serialize_mutagen_value(v) for k, v in filtered_tags.items()}

    # Extract namespace tags (freeform) - store WITHOUT namespace prefix
    nom_tags: dict[str, str] = {}
    for key in audio.tags:
        if key.startswith("----:com.apple.iTunes:"):
            tag_name = key.replace("----:com.apple.iTunes:", "")
            if tag_name.startswith(f"{namespace}:"):
                value = audio.tags[key]
                if value:
                    raw_value = value[0]
                    tag_key = tag_name[len(namespace) + 1 :]
                    if isinstance(raw_value, bytes):
                        nom_tags[tag_key] = raw_value.decode("utf-8")
                    else:
                        nom_tags[tag_key] = str(raw_value)
    metadata["nom_tags"] = nom_tags


def _extract_flac_metadata(audio: Any, metadata: dict[str, Any], namespace: str) -> None:
    """Extract metadata from FLAC files using Vorbis comments."""
    if not isinstance(audio, FLAC):
        return

    # Standard metadata (Vorbis comments use uppercase keys)
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

    # FLAC stores all tags in Vorbis comment format (case-insensitive keys)
    # Include namespace tags and standard metadata only
    filtered_tags = {}
    nom_tags: dict[str, str] = {}
    for k, v in audio.items():
        key_upper = k.upper()
        # Namespace tags (nom:*, ab:*, etc.)
        if ":" in k:
            filtered_tags[k] = v
            # Extract namespace tags - store WITHOUT namespace prefix
            if k.lower().startswith(f"{namespace.lower()}:"):
                tag_key = k[len(namespace) + 1 :]
                # Vorbis values are lists
                if isinstance(v, list) and len(v) > 0:
                    if len(v) > 1:
                        nom_tags[tag_key] = json.dumps(v, ensure_ascii=False)
                    else:
                        nom_tags[tag_key] = v[0]
        # Standard music metadata (whitelist common Vorbis fields)
        elif key_upper in {
            "ARTIST",
            "ALBUM",
            "TITLE",
            "GENRE",
            "DATE",
            "TRACKNUMBER",
            "DISCNUMBER",
            "ALBUMARTIST",
            "COMPOSER",
            "PERFORMER",
        }:
            filtered_tags[k] = v

    metadata["all_tags"] = {k: _serialize_mutagen_value(v) for k, v in filtered_tags.items()}
    metadata["nom_tags"] = nom_tags


def _extract_mp3_metadata(file_path: str, metadata: dict[str, Any], namespace: str) -> None:
    """Extract metadata from MP3 files using ID3 tags."""
    # Try EasyID3 for standard metadata
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

    # Try ID3 for detailed tags
    try:
        id3 = ID3(file_path)
        # Filter tags (standard ID3 frames + TXXX namespace tags)
        filtered_tags = {}
        for k, v in id3.items():
            if (k.startswith("TXXX:") and ":" in k[5:]) or k[:4] in ALLOWED_ID3_FRAMES:
                filtered_tags[k] = v
        metadata["all_tags"] = {str(k): _serialize_mutagen_value(v) for k, v in filtered_tags.items()}

        # Extract namespace tags from TXXX frames - store WITHOUT namespace prefix
        nom_tags = {}
        for frame in id3.getall("TXXX"):
            if frame.desc.startswith(f"{namespace}:"):
                tag_key = frame.desc[len(namespace) + 1 :]
                if len(frame.text) > 1:
                    nom_tags[tag_key] = json.dumps(frame.text, ensure_ascii=False)
                elif len(frame.text) == 1:
                    nom_tags[tag_key] = frame.text[0]
                else:
                    nom_tags[tag_key] = ""
        metadata["nom_tags"] = nom_tags
    except Exception:
        pass


def _get_first(tags: dict, key: str) -> str | None:
    """
    Get first value from a tag dict.

    Handles both mutagen tag dicts (which store values as lists) and regular dicts.

    Args:
        tags: Tag dictionary
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
