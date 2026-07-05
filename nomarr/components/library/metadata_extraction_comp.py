"""Metadata extraction component for audio files.

Handles format-specific tag extraction for MP4/M4A, FLAC, MP3, and other audio formats.
Uses mutagen library for low-level tag access.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from typing import TYPE_CHECKING, Any

import mutagen
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.mp4 import MP4

from nomarr.components.ml.audio.ml_audio_comp import load_audio_mono
from nomarr.components.ml.audio.ml_chromaprint_comp import compute_chromaprint
from nomarr.components.tagging.tag_normalization_comp import (
    normalize_id3_tags,
    normalize_mp4_tags,
    normalize_vorbis_tags,
)

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.helpers.dto.path_dto import LibraryPath


def _parse_single_value(value: str | None) -> str | None:
    """Parse a tag value that may be a JSON array, returning the first element."""
    if not value:
        return None
    if value.startswith("[") and value.endswith("]"):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list) and parsed:
                return str(parsed[0])
        except json.JSONDecodeError:
            pass  # Not valid JSON; fall through to return value as-is
    return value


def _parse_multi_values(value: str | None) -> list[str]:
    """Parse a tag value into a list of individual values.

    Handles JSON arrays, semicolon-delimited strings, and single values.
    """
    if not value:
        return []

    # Try to parse as JSON array first
    raw_values: list[str] = []
    if value.startswith("[") and value.endswith("]"):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                raw_values = [str(v) for v in parsed if v]
            else:
                raw_values = [value]
        except json.JSONDecodeError:
            raw_values = [value]
    else:
        raw_values = [value]

    # Split each value by semicolons and flatten
    genres: list[str] = []
    for v in raw_values:
        for part in v.split(";"):
            stripped = part.strip()
            if stripped:
                genres.append(stripped)

    return genres


def _parse_tag_value(value: str | None) -> str | list[str] | None:
    """Parse a tag value that may be a JSON array or plain string.

    Returns None if empty, list[str] for JSON arrays, str otherwise.
    """
    if not value:
        return None
    if value.startswith("[") and value.endswith("]"):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed if v]
        except json.JSONDecodeError:
            pass  # Not valid JSON; fall through to return value as plain string
    return value


def _extract_artist_string(artist_raw: str | list[str] | None) -> str | None:
    """Extract single artist string from raw value."""
    if isinstance(artist_raw, list):
        return artist_raw[0] if artist_raw else None
    return artist_raw


def _build_artists_list(artists_raw: str | list[str] | None) -> list[str]:
    """Build and deduplicate artists list from raw value."""
    if isinstance(artists_raw, list):
        artists_list = artists_raw
    elif artists_raw:
        for sep in (";", ",", "/", " / "):
            if sep in artists_raw:
                artists_list = [artist.strip() for artist in artists_raw.split(sep) if artist.strip()]
                break
        else:
            artists_list = [artists_raw.strip()] if artists_raw.strip() else []
    else:
        artists_list = []
    seen: set[str] = set()
    deduplicated: list[str] = []
    for artist in artists_list:
        if artist and artist not in seen:
            seen.add(artist)
            deduplicated.append(artist)
    return deduplicated


def resolve_artists(all_tags: dict[str, str]) -> tuple[str | None, list[str] | None]:
    """Resolve artist and artists tags with deduplication and fallback logic.

    Handles JSON array values from normalization. Resolution rules:
    - Both exist: artist as single, artists as deduplicated list
    - Only artists: extract first as artist, keep full list
    - Only artist: same value for both
    - Neither: return (None, None)
    """
    artist_raw = _parse_tag_value(all_tags.get("artist"))
    artists_raw = _parse_tag_value(all_tags.get("artists"))
    if not artist_raw and (not artists_raw):
        return (None, None)
    artist_str = _extract_artist_string(artist_raw)
    deduplicated = _build_artists_list(artists_raw)
    if not artist_str and deduplicated:
        artist_str = deduplicated[0]
    elif artist_str and (not deduplicated):
        deduplicated = [artist_str]
    return (artist_str, deduplicated or None)


def extract_metadata(file_path: LibraryPath, namespace: str = "nom") -> dict[str, Any]:
    """Extract metadata and tags from an audio file.

    Handles format-specific tag extraction for MP3 (ID3), M4A/MP4, FLAC, and
    other mutagen-supported formats. Namespace tags (e.g. nom:mood-strict) are
    stored without the prefix in nom_tags.
    """
    if not file_path.is_valid():
        msg = (
            f"Cannot extract metadata from invalid path ({file_path.status}): {file_path.absolute} - {file_path.reason}"
        )
        raise ValueError(msg)
    path_str = str(file_path.absolute)
    metadata: dict[str, Any] = {
        "duration": None,
        "artist": None,
        "album": None,
        "title": None,
        "genre": [],
        "year": None,
        "track_number": None,
        "all_tags": {},
        "nom_tags": {},
    }
    file_ext = os.path.splitext(path_str)[1].lower()
    try:
        audio = mutagen.File(path_str)  # pyright: ignore[reportPrivateImportUsage]
        if audio is None:
            return metadata
        if hasattr(audio.info, "length"):
            metadata["duration"] = audio.info.length
        if file_ext in (".m4a", ".mp4", ".m4p", ".m4b"):
            _extract_mp4_metadata(audio, metadata, namespace)
        elif file_ext == ".flac":
            _extract_flac_metadata(audio, metadata, namespace)
        elif file_ext in (".mp3", ".mp2", ".aac"):
            _extract_mp3_metadata(file_path, metadata, namespace)
    # Broad: mutagen raises diverse exceptions for corrupt files; always return partial metadata
    except Exception as e:
        logger.warning("[metadata_extraction] Failed to extract metadata from %s: %s", file_path, e, exc_info=True)
    return metadata


def _apply_common_tag_fields(metadata: dict[str, Any], namespace: str) -> None:
    """Populate standard metadata fields and nom_tags from all_tags. Mutates metadata in place."""
    artist_value, artists_value = resolve_artists(metadata["all_tags"])
    metadata["title"] = _parse_single_value(metadata["all_tags"].get("title"))
    metadata["artist"] = artist_value
    metadata["artists"] = artists_value
    metadata["album"] = _parse_single_value(metadata["all_tags"].get("album"))
    metadata["genre"] = _parse_multi_values(metadata["all_tags"].get("genre"))
    year_str = _parse_single_value(metadata["all_tags"].get("year")) or _parse_single_value(
        metadata["all_tags"].get("date"),
    )
    if year_str:
        with contextlib.suppress(ValueError, IndexError):
            metadata["year"] = int(year_str[:4])
    track_str = _parse_single_value(metadata["all_tags"].get("tracknumber"))
    if track_str:
        with contextlib.suppress(ValueError, IndexError):
            metadata["track_number"] = int(track_str.split("/")[0])
    if artist_value:
        metadata["all_tags"]["artist"] = json.dumps([artist_value], ensure_ascii=False)
    if artists_value:
        metadata["all_tags"]["artists"] = json.dumps(artists_value, ensure_ascii=False)
    nom_tags: dict[str, str] = {}
    keys_to_remove = []
    for key, value in metadata["all_tags"].items():
        if isinstance(key, str) and key.lower().startswith(f"{namespace.lower()}:"):
            tag_key = key[len(namespace) + 1 :]
            nom_tags[tag_key] = value
            keys_to_remove.append(key)
    for key in keys_to_remove:
        del metadata["all_tags"][key]
    metadata["nom_tags"] = nom_tags


def _extract_mp4_metadata(audio: mutagen.FileType, metadata: dict[str, Any], namespace: str) -> None:
    """Extract metadata from M4A/MP4 files using MP4 atoms."""
    if not isinstance(audio, MP4) or not audio.tags:
        return
    metadata["all_tags"] = normalize_mp4_tags(audio.tags)
    _apply_common_tag_fields(metadata, namespace)


def _extract_flac_metadata(audio: mutagen.FileType, metadata: dict[str, Any], namespace: str) -> None:
    """Extract metadata from FLAC files using Vorbis comments."""
    if not isinstance(audio, FLAC):
        return
    metadata["all_tags"] = normalize_vorbis_tags(dict(audio))
    _apply_common_tag_fields(metadata, namespace)


def _extract_mp3_metadata(file_path: LibraryPath, metadata: dict[str, Any], namespace: str) -> None:
    """Extract metadata from MP3 files using ID3 tags."""
    try:
        id3 = ID3(str(file_path.absolute))
        metadata["all_tags"] = normalize_id3_tags(dict(id3))
        _apply_common_tag_fields(metadata, namespace)
    except Exception as e:  # Corrupt ID3 tags raise diverse mutagen exceptions; caller tolerates partial metadata
        logger.warning("[metadata_extraction] Failed to extract MP3 tags from %s: %s", file_path, e, exc_info=True)


def _get_first(tags: dict[str, Any], key: str) -> str | None:
    """Get first value from a tag dict. Handles mutagen list-valued tags."""
    value = tags.get(key)
    if value is None:
        return None
    if isinstance(value, list) and len(value) > 0:
        return str(value[0])
    if isinstance(value, str | int | float):
        return str(value)
    return None


def compute_chromaprint_for_file(path: LibraryPath) -> str:
    """Compute chromaprint for an audio file at 16kHz sample rate."""
    result = load_audio_mono(path, target_sr=16000)
    return compute_chromaprint(result.waveform, result.sample_rate)
