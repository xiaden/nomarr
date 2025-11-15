"""
Library scanner for tracking music files and their metadata.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import mutagen
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3
from mutagen.mp4 import MP4

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


def scan_library(
    db: Database,
    library_path: str,
    namespace: str = "essentia",
    progress_callback: Callable[[int, int], None] | None = None,
    scan_id: int | None = None,
    auto_tag: bool = False,
    ignore_patterns: str = "",
) -> dict[str, Any]:
    """
    Scan a music library directory and update the database.

    Args:
        db: Database instance
        library_path: Root path to scan
        namespace: Tag namespace for essentia tags
        progress_callback: Optional callback(current, total)
        scan_id: Optional existing scan record ID (if None, creates new record)
        auto_tag: Whether to automatically enqueue untagged files for tagging
        ignore_patterns: Comma-separated path patterns to skip from auto-tagging

    Returns:
        Dict with scan statistics: files_scanned, files_added, files_updated, files_removed
    """
    logging.info(f"[library_scanner] Starting library scan: {library_path}")

    # Use existing scan record or create new one
    if scan_id is None:
        scan_id = db.create_library_scan()
    else:
        logging.info(f"[library_scanner] Using existing scan record: {scan_id}")

    stats = {
        "files_scanned": 0,
        "files_added": 0,
        "files_updated": 0,
        "files_removed": 0,
    }

    try:
        # Get list of existing files in database
        existing_files, _ = db.list_library_files(limit=1000000)  # Get all files
        existing_paths = {f["path"] for f in existing_files}
        seen_paths: set[str] = set()

        # Scan directory recursively
        audio_extensions = {".mp3", ".m4a", ".flac", ".ogg", ".opus"}
        files_to_scan = []

        for root, _dirs, files in os.walk(library_path):
            for file in files:
                ext = Path(file).suffix.lower()
                if ext in audio_extensions:
                    file_path = os.path.join(root, file)
                    files_to_scan.append(file_path)

        total_files = len(files_to_scan)
        logging.info(f"[library_scanner] Found {total_files} audio files to scan")

        # Scan each file
        for idx, file_path in enumerate(files_to_scan):
            try:
                # Get file stats for modification time check
                file_stat = os.stat(file_path)
                modified_time = int(file_stat.st_mtime * 1000)

                # Check if file needs updating
                existing_file = db.get_library_file(file_path)
                if existing_file and existing_file["modified_time"] == modified_time:
                    # File hasn't changed, skip
                    stats["files_scanned"] += 1
                    seen_paths.add(file_path)
                    continue

                # Update library database with file metadata and tags
                update_library_file_from_tags(db, file_path, namespace)

                # Auto-enqueue for tagging if enabled and file not already tagged
                if auto_tag:
                    file_record = db.get_library_file(file_path)
                    if file_record:
                        # Check if file needs tagging (not tagged, not skipped, not ignored by pattern)
                        needs_tag = (
                            not file_record.get("tagged")
                            and not file_record.get("skip_auto_tag")
                            and not _matches_ignore_pattern(file_path, ignore_patterns)
                        )
                        if needs_tag:
                            # Enqueue for tagging (don't force re-tag)
                            db.enqueue(file_path, force=False)
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

                # Update DB stats periodically for real-time UI updates
                if (idx + 1) % 10 == 0:
                    db.update_library_scan(
                        scan_id,
                        files_scanned=stats["files_scanned"],
                        files_added=stats["files_added"],
                        files_updated=stats["files_updated"],
                    )

            except Exception as e:
                logging.warning(f"[library_scanner] Failed to scan {file_path}: {e}")

        # Remove files that no longer exist
        removed_paths = existing_paths - seen_paths
        for path in removed_paths:
            db.delete_library_file(path)
            stats["files_removed"] += 1

        # Update scan record
        db.update_library_scan(
            scan_id,
            status="done",
            files_scanned=stats["files_scanned"],
            files_added=stats["files_added"],
            files_updated=stats["files_updated"],
            files_removed=stats["files_removed"],
        )

        logging.info(
            f"[library_scanner] Scan complete: scanned={stats['files_scanned']}, "
            f"added={stats['files_added']}, updated={stats['files_updated']}, removed={stats['files_removed']}"
        )

        return stats

    except Exception as e:
        logging.error(f"[library_scanner] Scan failed: {e}")
        db.update_library_scan(scan_id, status="error", error_message=str(e))
        raise


def update_library_file_from_tags(
    db: Database, file_path: str, namespace: str, tagged_version: str | None = None
) -> None:
    """
    Update library database with current file metadata and tags.

    This is the canonical way to sync a file's tags to the library database,
    used by both the library scanner and the processor after tagging.

    Args:
        db: Database instance
        file_path: Path to audio file
        namespace: Tag namespace (e.g., "nom" or "essentia")
        tagged_version: Optional tagger version to mark file as tagged
    """
    try:
        # Get file stats
        file_stat = os.stat(file_path)
        file_size = file_stat.st_size
        modified_time = int(file_stat.st_mtime * 1000)

        # Extract metadata from file
        metadata = _extract_metadata(file_path, namespace)

        # Upsert to library database
        db.upsert_library_file(
            path=file_path,
            file_size=file_size,
            modified_time=modified_time,
            duration_seconds=metadata.get("duration"),
            artist=metadata.get("artist"),
            album=metadata.get("album"),
            title=metadata.get("title"),
            genre=metadata.get("genre"),
            year=metadata.get("year"),
            track_number=metadata.get("track_number"),
            tags_json=json.dumps(metadata.get("all_tags", {})),
            nom_tags=json.dumps(metadata.get("nom_tags", {})),
        )

        # Get file ID and populate library_tags table
        file_record = db.get_library_file(file_path)
        if file_record and metadata.get("nom_tags"):
            nom_tags = metadata["nom_tags"]
            # Parse tag values to detect types
            parsed_tags = _parse_tag_values(nom_tags)
            db.upsert_file_tags(file_record["id"], parsed_tags)

        # Mark file as tagged if tagger version provided (called from processor)
        if tagged_version and file_record:
            from nomarr.persistence.db import now_ms

            db.conn.execute(
                "UPDATE library_files SET tagged=1, tagged_version=?, last_tagged_at=? WHERE path=?",
                (tagged_version, now_ms(), file_path),
            )
            db.conn.commit()

        logging.debug(f"[library_scanner] Updated library for {file_path}")
    except Exception as e:
        logging.warning(f"[library_scanner] Failed to update library for {file_path}: {e}")


def _extract_metadata(file_path: str, namespace: str) -> dict[str, Any]:
    """
    Extract metadata and tags from an audio file.

    Returns dict with:
        - duration: float (seconds)
        - artist, album, title, genre, year, track_number: str/int
        - all_tags: dict of all tags
        - nom_tags: dict of tags in the nom namespace (stored WITHOUT nom: prefix)
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
    """Get first value from tag dictionary, handling various formats."""
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
    Handles JSON arrays, floats, ints, and strings.

    Args:
        tags: Dict of tag_key -> tag_value (as strings from file)

    Returns:
        Dict with parsed values (arrays as lists, numbers as float/int)
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
