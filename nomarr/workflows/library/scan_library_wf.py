"""
Library file update workflow for tracking music files and their metadata.

TODO: LEGACY CODE CLEANUP
This file contains a legacy monolithic workflow `scan_library_workflow()` that is UNUSED.
The current architecture uses:
- start_library_scan_wf.py (PLANNING: discover files, enqueue to library_queue)
- scan_single_file_wf.py (EXECUTION: process each file from queue)

The only actively used function is `update_library_file_from_tags()`, which syncs
a file's metadata and tags to the library database. It's called by:
- scan_single_file_wf.py (after scanning)
- process_file_wf.py (after tagging)

REFACTOR PLAN:
1. Extract `update_library_file_from_tags()` and helpers to a standalone module
2. Delete the unused `scan_library_workflow()` and `_matches_ignore_pattern()`
3. Update imports in scan_single_file_wf.py and process_file_wf.py

ARCHITECTURE:
- This workflow is domain logic that takes all dependencies as parameters.
- It does NOT import or use the DI container, services, or application object.
- Callers (typically services) must provide a Database instance and all config values.

EXPECTED DATABASE INTERFACE:
The `db` parameter must provide these methods:
- db.library_files.get_library_file(path) -> dict | None
- db.library_files.upsert_library_file(path, **metadata) -> None
- db.library_files.mark_file_tagged(path, version) -> None
- db.file_tags.upsert_file_tags_mixed(file_id, external_tags, nomarr_tags) -> None
- db.libraries.find_library_containing_path(path) -> dict | None
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any

import mutagen  # type: ignore[import-untyped]
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3
from mutagen.mp4 import MP4

from nomarr.helpers.dto.library_dto import UpdateLibraryFileFromTagsParams

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


# TODO: DELETE - Unused legacy function from monolithic scan_library_workflow
# def _matches_ignore_pattern(file_path: str, patterns: str) -> bool:
#     """Check if file path matches any ignore pattern."""
#     ...


# TODO: DELETE - Unused legacy monolithic workflow
# The current architecture uses start_library_scan_wf.py + scan_single_file_wf.py instead
# def scan_library_workflow(db: Database, params: ScanLibraryWorkflowParams) -> dict[str, Any]:
#     """
#     Legacy monolithic workflow - UNUSED - DELETE THIS
#
#     This was the original single-function approach that did both planning and execution.
#     It has been replaced by:
#     - start_library_scan_wf.py (PLANNING: discover files, enqueue to library_queue)
#     - scan_single_file_wf.py (EXECUTION: process each file from queue)
#     """
#     ...


def update_library_file_from_tags(
    db: Database,
    params: UpdateLibraryFileFromTagsParams,
) -> None:
    """
    Update library database with current file metadata and tags.

    This is the canonical way to sync a file's tags to the library database,
    used by both the library scanner and the processor after tagging.

    This workflow function:
    1. Extracts metadata from the audio file (duration, artist, album, etc.)
    2. Extracts all tags and namespace-specific tags (e.g., nom:* tags)
    3. Upserts to library_files table
    4. Populates file_tags table with parsed tag values:
       - External tags (from file metadata) with is_nomarr_tag=False
       - Nomarr-generated tags (nom:*) with is_nomarr_tag=True
    5. Optionally marks file as tagged with tagger version
    6. Stores calibration metadata (model_key -> calibration_id mapping)

    Args:
        db: Database instance (must provide library and tags accessors)
        params: UpdateLibraryFileFromTagsParams with file_path, namespace, tagged_version, calibration, library_id

    Returns:
        None (updates database in-place)

    Raises:
        Logs warnings on failure but does not raise exceptions
    """
    # Extract parameters
    file_path = params.file_path
    namespace = params.namespace
    tagged_version = params.tagged_version
    calibration = params.calibration
    library_id = params.library_id
    try:
        # Determine library_id if not provided
        if library_id is None:
            library = db.libraries.find_library_containing_path(file_path)
            if not library:
                logging.warning(f"[update_library_file_from_tags] File path not in any library: {file_path}")
                return
            library_id = library["id"]

        # At this point library_id is guaranteed to be int
        assert library_id is not None  # Type narrowing for mypy

        # Get file stats
        file_stat = os.stat(file_path)
        file_size = file_stat.st_size
        modified_time = int(file_stat.st_mtime * 1000)

        # Extract metadata from file
        metadata = _extract_metadata(file_path, namespace)

        # Serialize calibration metadata to JSON
        calibration_json = json.dumps(calibration) if calibration else None

        # Upsert to library database
        db.library_files.upsert_library_file(
            path=file_path,
            library_id=library_id,
            file_size=file_size,
            modified_time=modified_time,
            duration_seconds=metadata.get("duration"),
            artist=metadata.get("artist"),
            album=metadata.get("album"),
            title=metadata.get("title"),
            genre=metadata.get("genre"),
            year=metadata.get("year"),
            track_number=metadata.get("track_number"),
            calibration=calibration_json,
        )

        # Get file ID and populate file_tags table
        file_record = db.library_files.get_library_file(file_path)
        if file_record:
            # Parse all_tags (external metadata) and nom_tags (Nomarr-generated)
            all_tags = metadata.get("all_tags", {})
            nom_tags = metadata.get("nom_tags", {})

            parsed_all_tags = _parse_tag_values(all_tags) if all_tags else {}
            parsed_nom_tags = _parse_tag_values(nom_tags) if nom_tags else {}

            # Insert both sets of tags with appropriate is_nomarr_tag flags
            db.file_tags.upsert_file_tags_mixed(
                file_record["id"],
                external_tags=parsed_all_tags,
                nomarr_tags=parsed_nom_tags,
            )

        # Mark file as tagged if tagger version provided (called from processor)
        if tagged_version and file_record:
            db.library_files.mark_file_tagged(file_path, tagged_version)

        logging.debug(f"[library_scanner] Updated library for {file_path}")
    except Exception as e:
        logging.warning(f"[library_scanner] Failed to update library for {file_path}: {e}")


def _extract_metadata(file_path: str, namespace: str) -> dict[str, Any]:
    """
    Extract metadata and tags from an audio file.

    This is a pure helper function that reads audio file metadata using mutagen
    and extracts both standard metadata (artist, album, etc.) and namespace-specific
    tags (e.g., nom:* or essentia:* tags).

    Namespace tags are stored WITHOUT the namespace prefix in the returned dict.
    For example, "nom:mood-strict" becomes "mood-strict" in nom_tags.

    Args:
        file_path: Absolute path to audio file
        namespace: Tag namespace to extract (e.g., "nom" or "essentia")

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
        Handles MP3 (ID3), M4A/MP4, and other mutagen-supported formats.
        Multi-value tags in MP3 are stored as JSON array strings.
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

    try:
        audio = mutagen.File(file_path)
        if audio is None:
            return metadata

        # Get duration
        if hasattr(audio.info, "length"):
            metadata["duration"] = audio.info.length

        # Extract standard tags
        if isinstance(audio, MP4):
            # M4A/MP4 files
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

            # Get all tags
            if audio.tags:
                metadata["all_tags"] = {k: _serialize_mutagen_value(v) for k, v in audio.tags.items()}

            # Extract nom namespace tags (freeform) - store WITHOUT namespace prefix
            nom_tags: dict[str, str] = {}
            if audio.tags:
                for key in audio.tags:
                    if key.startswith("----:com.apple.iTunes:"):
                        tag_name = key.replace("----:com.apple.iTunes:", "")
                        if tag_name.startswith(f"{namespace}:"):
                            value = audio.tags[key]
                            if value:
                                # MP4FreeForm values are bytes - decode them properly
                                raw_value = value[0]
                                # Strip namespace prefix for storage
                                tag_key = tag_name[len(namespace) + 1 :]
                                if isinstance(raw_value, bytes):
                                    nom_tags[tag_key] = raw_value.decode("utf-8")
                                else:
                                    nom_tags[tag_key] = str(raw_value)
            metadata["nom_tags"] = nom_tags

        else:
            # MP3 and other formats
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
                        # Handle "1/12" format
                        metadata["track_number"] = int(track_str.split("/")[0])
                    except (ValueError, IndexError):
                        pass
            except Exception:
                pass

            # Get all tags including TXXX frames
            try:
                id3 = ID3(file_path)
                metadata["all_tags"] = {str(k): _serialize_mutagen_value(v) for k, v in id3.items()}

                # Extract nom namespace tags from TXXX frames - store WITHOUT namespace prefix
                nom_tags = {}
                for frame in id3.getall("TXXX"):
                    if frame.desc.startswith(f"{namespace}:"):
                        # Strip namespace prefix for storage
                        tag_key = frame.desc[len(namespace) + 1 :]
                        # Handle multi-value tags (frame.text is always a list)
                        if len(frame.text) > 1:
                            # Multi-value tag - store as JSON array string
                            nom_tags[tag_key] = json.dumps(frame.text, ensure_ascii=False)
                        elif len(frame.text) == 1:
                            # Single value - store as string
                            nom_tags[tag_key] = frame.text[0]
                        else:
                            nom_tags[tag_key] = ""
                metadata["nom_tags"] = nom_tags
            except Exception:
                pass

    except Exception as e:
        logging.debug(f"[library_scanner] Failed to extract metadata from {file_path}: {e}")

    return metadata


def _serialize_mutagen_value(value: Any) -> str | list[str]:
    """
    Serialize a mutagen tag value to a string or list of strings.

    Handles various mutagen types:
    - MP4FreeForm: Extract bytes and decode (returns single value or list)
    - Lists: Process all elements, return list if multiple values
    - Bytes: Decode to UTF-8
    - Everything else: str()

    Multi-value tags are returned as lists, which the persistence layer
    will JSON-encode with type="array".

    Args:
        value: Mutagen tag value

    Returns:
        Serialized string value or list of strings for multi-value tags
    """
    # Handle MP4FreeForm objects (which are list-like)
    if hasattr(value, "__class__") and value.__class__.__name__ == "MP4FreeForm":
        # MP4FreeForm is iterable, process all values
        decoded_values = []
        for item in value:
            if isinstance(item, bytes):
                decoded_values.append(item.decode("utf-8", errors="replace"))
            else:
                decoded_values.append(str(item))
        # Return single value if only one, otherwise return list
        return decoded_values[0] if len(decoded_values) == 1 else decoded_values

    # Handle lists
    if isinstance(value, list):
        if len(value) == 0:
            return ""
        # Decode each element
        decoded_values = []
        for item in value:
            if isinstance(item, bytes):
                decoded_values.append(item.decode("utf-8", errors="replace"))
            else:
                decoded_values.append(str(item))
        # Return single value if only one, otherwise return list
        return decoded_values[0] if len(decoded_values) == 1 else decoded_values

    # Handle bytes
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    # Everything else
    return str(value)


def _get_first(tags: Any, key: str) -> str | None:
    """
    Get first value from tag dictionary, handling various formats.

    Pure helper for extracting single values from mutagen tag containers,
    which may be lists, strings, or other types.

    Args:
        tags: Tag dictionary from mutagen (EasyID3, MP4, etc.)
        key: Tag key to extract

    Returns:
        First value as string, or None if key not found
    """
    if tags is None or key not in tags:
        return None
    value = tags[key]
    if isinstance(value, list) and len(value) > 0:
        return str(value[0])
    if isinstance(value, str):
        return value
    return str(value) if value else None


def _parse_tag_values(tags: dict[str, str]) -> dict[str, Any]:
    """
    Parse tag values from strings to appropriate types.

    Pure helper that converts string tag values to their proper types:
    - JSON arrays (e.g., "[\"value1\", \"value2\"]") -> list
    - Floats (e.g., "0.95") -> float
    - Integers (e.g., "120") -> int
    - Everything else -> str

    This is used when populating library_tags table with typed values.

    Args:
        tags: Dict of tag_key -> tag_value (as strings from file)

    Returns:
        Dict with parsed values (arrays as lists, numbers as float/int, rest as str)

    Example:
        >>> _parse_tag_values({"tempo": "120", "score": "0.95", "tags": '["pop", "upbeat"]'})
        {"tempo": 120, "score": 0.95, "tags": ["pop", "upbeat"]}
    """
    parsed: dict[str, Any] = {}

    for key, value in tags.items():
        if not value:
            continue

        # Try to parse as JSON (for arrays)
        if value.startswith("[") and value.endswith("]"):
            try:
                parsed_value = json.loads(value)
                if isinstance(parsed_value, list):
                    parsed[key] = parsed_value
                    continue
            except json.JSONDecodeError:
                pass

        # Try to parse as float
        try:
            if "." in value:
                parsed[key] = float(value)
                continue
        except ValueError:
            pass

        # Try to parse as int
        try:
            parsed[key] = int(value)
            continue
        except ValueError:
            pass

        # Keep as string
        parsed[key] = value

    return parsed
