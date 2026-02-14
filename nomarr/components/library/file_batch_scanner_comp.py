"""File batch scanner component for library scanning.

Scans a single folder and returns batch-ready file data for DB upsert.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nomarr.components.infrastructure.path_comp import build_library_path_from_input
from nomarr.components.library.metadata_extraction_comp import extract_metadata
from nomarr.components.tagging.tagging_reader_comp import infer_write_mode_from_tags
from nomarr.helpers.files_helper import is_audio_file
from nomarr.helpers.time_helper import now_ms
from nomarr.persistence import Database

logger = logging.getLogger(__name__)


# Component-local DTOs (not promoted to helpers/dto)
@dataclass
class FileBatchResult:
    """Result of scanning a single folder."""

    file_entries: list[dict[str, Any]]  # Ready for DB upsert
    metadata_map: dict[str, dict[str, Any]]  # path → full metadata for entity seeding
    discovered_paths: set[str]  # All paths found
    new_file_paths: set[str]  # Paths that are new (not in existing_files)
    stats: dict[str, int]  # files_updated, files_failed, files_skipped
    warnings: list[str]


def scan_folder_files(
    folder_path: Path,
    folder_rel_path: str,
    library_root: Path,
    library_id: str,
    existing_files: dict[str, dict],
    tagger_version: str,
    db: Database,
) -> FileBatchResult:
    """Scan all files in a single folder and return batch-ready data.

    Args:
        folder_path: Absolute folder path to scan
        folder_rel_path: POSIX relative path for this folder
        library_root: Library root for normalization
        library_id: Library identifier
        existing_files: Path → existing file dict (for determining if file is new/updated)
        tagger_version: Current model suite hash
        db: Database instance (for build_library_path_from_input)

    Returns:
        FileBatchResult with file entries ready for upsert and metadata

    """
    file_entries: list[dict[str, Any]] = []
    metadata_map: dict[str, dict[str, Any]] = {}
    discovered_paths: set[str] = set()
    new_file_paths: set[str] = set()
    stats: dict[str, int] = {"files_updated": 0, "files_failed": 0, "files_skipped": 0}
    warnings: list[str] = []

    # Get audio files in this folder (non-recursive)
    try:
        filenames = os.listdir(str(folder_path))
        files = [
            os.path.join(str(folder_path), f)
            for f in filenames
            if is_audio_file(f) and os.path.isfile(os.path.join(str(folder_path), f))
        ]
    except OSError as e:
        logger.exception(f"Cannot read folder {folder_path}: {e}")
        return FileBatchResult(
            file_entries=file_entries,
            metadata_map=metadata_map,
            discovered_paths=discovered_paths,
            new_file_paths=new_file_paths,
            stats=stats,
            warnings=warnings,
        )

    # Process each file
    for file_path in files:
        try:
            # Validate path
            library_path = build_library_path_from_input(file_path, db)
            if not library_path.is_valid():
                warnings.append(f"Invalid path: {file_path} - {library_path.reason}")
                stats["files_failed"] += 1
                continue

            file_path_str = str(library_path.absolute)

            # Compute normalized_path: POSIX-style relative to library root
            try:
                normalized_path = _compute_normalized_path(Path(file_path_str), library_root)
            except ValueError:
                warning = f"File outside library root: {file_path_str}"
                warnings.append(warning)
                logger.warning(warning)
                stats["files_failed"] += 1
                continue

            discovered_paths.add(file_path_str)

            # Check if file exists in DB and get disk mtime
            existing_file = existing_files.get(file_path_str)
            file_stat = os.stat(file_path_str)
            modified_time = int(file_stat.st_mtime * 1000)
            file_size = file_stat.st_size

            # Skip unchanged files: if file exists in DB and mtime matches,
            # no need to re-parse metadata or update entities
            if existing_file is not None and existing_file.get("modified_time") == modified_time:
                stats["files_skipped"] += 1
                continue

            # Extract metadata + tags (only for new or changed files)
            metadata = extract_metadata(library_path, namespace="nom")

            # Check if file needs ML tagging
            # Compare file's nom_version tag against current tagger_version (model suite hash)
            file_version = metadata.get("nom_tags", {}).get("nom_version")
            needs_tagging = (
                existing_file is None  # New file
                or not existing_file.get("tagged")  # Not yet tagged in DB
                or file_version != tagger_version  # Tagged with different model suite
            )

            # Compute namespace tracking fields
            nom_tags = metadata.get("nom_tags", {})
            has_nomarr_namespace = bool(nom_tags)
            last_written_mode = infer_write_mode_from_tags(set(nom_tags.keys())) if has_nomarr_namespace else None

            # Prepare batch entry with normalized_path for identity
            file_entry = {
                "path": file_path_str,  # Absolute path for access
                "normalized_path": normalized_path,  # POSIX relative path for identity
                "library_id": library_id,
                "file_size": file_size,
                "modified_time": modified_time,
                "duration_seconds": metadata.get("duration"),
                "title": metadata.get("title"),  # Title is direct metadata, not derived
                "needs_tagging": needs_tagging,
                "is_valid": True,
                "scanned_at": now_ms().value,
                "has_nomarr_namespace": has_nomarr_namespace,
                "last_written_mode": last_written_mode,
            }
            file_entries.append(file_entry)

            # Store metadata for entity seeding
            metadata_map[file_path_str] = metadata

            # Track new files and updated files
            if existing_file is None:
                new_file_paths.add(file_path_str)
            else:
                stats["files_updated"] += 1

        except Exception as e:
            logger.exception(f"Failed to process {file_path}: {e}")
            stats["files_failed"] += 1
            warnings.append(f"Extraction failed: {file_path} - {str(e)[:100]}")
            continue

    return FileBatchResult(
        file_entries=file_entries,
        metadata_map=metadata_map,
        discovered_paths=discovered_paths,
        new_file_paths=new_file_paths,
        stats=stats,
        warnings=warnings,
    )


# Helper function (component-private)
def _compute_normalized_path(absolute_path: Path, library_root: Path) -> str:
    """Compute normalized POSIX-style path relative to library root.

    Args:
        absolute_path: Absolute file path
        library_root: Absolute library root path

    Returns:
        POSIX-style relative path (e.g., "Rock/Beatles/track.mp3")

    Raises:
        ValueError: If absolute_path is not under library_root

    """
    relative = absolute_path.relative_to(library_root)
    return relative.as_posix()
