"""
Library scanner workflow for tracking music files and their metadata.

This is a PURE WORKFLOW module that orchestrates:
- Filesystem scanning for audio files
- Database persistence (library_files, file_tags)
- Queue management (auto-enqueue untagged files)
- Tag extraction and normalization

ARCHITECTURE:
- This workflow is domain logic that takes all dependencies as parameters.
- It does NOT import or use the DI container, services, or application object.
- Callers (typically services) must provide a Database instance and all config values.

EXPECTED DATABASE INTERFACE:
The `db` parameter must provide these methods:
- db.library_files.list_library_files(limit) -> tuple[list[dict], int]
- db.library_files.get_library_file(path) -> dict | None
- db.library_files.delete_library_file(path) -> None
- db.library_files.upsert_library_file(path, **metadata) -> None
- db.library_files.mark_file_tagged(path, version) -> None
- db.file_tags.upsert_file_tags_mixed(file_id, external_tags, nomarr_tags) -> None
- db.tag_queue.enqueue(path, force) -> None
- db.conn (for raw SQL updates in update_library_file_from_tags)

USAGE:
    from nomarr.workflows.library.scan_library_wf import scan_library_workflow

    stats = scan_library_workflow(
        db=database_instance,
        library_path="/path/to/music",
        namespace="nom",
        progress_callback=my_progress_fn,
        auto_tag=True,
        ignore_patterns="*/Audiobooks/*,*.wav"
    )
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import mutagen
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3
from mutagen.mp4 import MP4

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def _matches_ignore_pattern(file_path: str, patterns: str) -> bool:
    """
    Check if file path matches any ignore pattern.

    Args:
        file_path: Absolute file path
        patterns: Comma-separated patterns (supports * wildcards and */ for directory matching)

    Returns:
        True if file should be ignored

    Examples:
        "*/Audiobooks/*" matches any file in Audiobooks directory
        "*.wav" matches all WAV files
    """
    if not patterns:
        return False

    import fnmatch

    # Normalize path separators
    normalized_path = file_path.replace("\\", "/")

    for pattern in patterns.split(","):
        pattern = pattern.strip()
        if not pattern:
            continue

        # Normalize pattern separators
        pattern = pattern.replace("\\", "/")

        # Check if pattern matches
        if fnmatch.fnmatch(normalized_path, pattern):
            return True

    return False


def scan_library_workflow(
    db: Database,
    library_path: str,
    namespace: str,
    progress_callback: Callable[[int, int], None] | None = None,
    auto_tag: bool = False,
    ignore_patterns: str = "",
) -> dict[str, Any]:
    """
    Scan a music library directory and update the database.

    This is the main workflow entrypoint for library scanning. It orchestrates:
    1. Filesystem traversal to find audio files
    2. Metadata extraction and database updates
    3. Optional auto-enqueue of untagged files
    4. Removal of deleted files from database

    Args:
        db: Database instance (must provide library, tags, and queue accessors)
        library_path: Root path to scan for audio files
        namespace: Tag namespace for tag extraction and database tracking (must be provided by service)
        progress_callback: Optional callback(current, total) for progress updates
        auto_tag: Whether to automatically enqueue untagged files for tagging
        ignore_patterns: Comma-separated path patterns to skip from auto-tagging
                        (supports * wildcards and */ for directory matching)

    Returns:
        Dict with scan statistics:
        - files_scanned: int
        - files_added: int
        - files_updated: int
        - files_removed: int

    Raises:
        Exception: On scan failure
    """
    logging.info(f"[library_scanner] Starting library scan: {library_path}")

    stats = {
        "files_scanned": 0,
        "files_added": 0,
        "files_updated": 0,
        "files_removed": 0,
    }

    try:
        # Get list of existing files in database
        existing_files, _ = db.library_files.list_library_files(limit=1000000)  # Get all files
        existing_paths = {f["path"] for f in existing_files}
        seen_paths: set[str] = set()

        # Discover all audio files using helpers.files (secure, handles existence/filtering/traversal)
        from nomarr.helpers.files_helper import collect_audio_files

        files_to_scan = collect_audio_files(library_path, recursive=True)

        total_files = len(files_to_scan)
        logging.info(f"[library_scanner] Found {total_files} audio files to scan")

        # Scan each file
        for idx, file_path in enumerate(files_to_scan):
            try:
                # Get file stats for modification time check
                file_stat = os.stat(file_path)
                modified_time = int(file_stat.st_mtime * 1000)

                # Check if file needs updating
                existing_file = db.library_files.get_library_file(file_path)
                if existing_file and existing_file["modified_time"] == modified_time:
                    # File hasn't changed, skip
                    stats["files_scanned"] += 1
                    seen_paths.add(file_path)
                    continue

                # Update library database with file metadata and tags
                update_library_file_from_tags(db, file_path, namespace)

                # Auto-enqueue for tagging if enabled and file not already tagged
                if auto_tag:
                    file_record = db.library_files.get_library_file(file_path)
                    if file_record:
                        # Check if file needs tagging (not tagged, not skipped, not ignored by pattern)
                        needs_tag = (
                            not file_record.get("tagged")
                            and not file_record.get("skip_auto_tag")
                            and not _matches_ignore_pattern(file_path, ignore_patterns)
                        )
                        if needs_tag:
                            # Enqueue for tagging (don't force re-tag)
                            db.tag_queue.enqueue(file_path, force=False)
                            logging.info(f"[library_scanner] Auto-queued untagged file: {file_path}")

                if existing_file:
                    stats["files_updated"] += 1
                else:
                    stats["files_added"] += 1

                stats["files_scanned"] += 1
                seen_paths.add(file_path)

                # Check for cancellation on every file for faster response
                if progress_callback:
                    try:
                        # Call with 0 to just check for cancel without updating progress
                        progress_callback(idx + 1, total_files)
                    except KeyboardInterrupt:
                        raise  # Re-raise to abort scan

            except Exception as e:
                logging.warning(f"[library_scanner] Failed to scan {file_path}: {e}")

        # Remove files that no longer exist
        removed_paths = existing_paths - seen_paths
        for path in removed_paths:
            db.library_files.delete_library_file(path)
            stats["files_removed"] += 1

        logging.info(
            f"[library_scanner] Scan complete: scanned={stats['files_scanned']}, "
            f"added={stats['files_added']}, updated={stats['files_updated']}, removed={stats['files_removed']}"
        )

        return stats

    except Exception as e:
        logging.error(f"[library_scanner] Scan failed: {e}")
        raise


def update_library_file_from_tags(
    db: Database,
    file_path: str,
    namespace: str,
    tagged_version: str | None = None,
    calibration: dict[str, str] | None = None,
    library_id: int | None = None,
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
        file_path: Absolute path to audio file
        namespace: Tag namespace (e.g., "nom" or "essentia")
        tagged_version: Optional tagger version to mark file as tagged
                       (only set when called from processor after tagging)
        calibration: Optional calibration metadata dict (model_key -> calibration_id)
        library_id: Library ID (if None, will be auto-determined from file path)

    Returns:
        None (updates database in-place)

    Raises:
        Logs warnings on failure but does not raise exceptions
    """
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
                metadata["all_tags"] = {k: str(v) for k, v in audio.tags.items()}

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
                metadata["all_tags"] = {str(k): str(v) for k, v in id3.items()}

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
