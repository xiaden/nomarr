"""File batch scanner component for library scanning.

Scans a single folder and returns batch-ready file data for DB upsert.
Pass 1 of the two-pass scan: fast disk walk only — no metadata extraction.
Audio tag extraction is handled by the background tag extraction worker.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nomarr.components.infrastructure.path_comp import build_library_path_from_input
from nomarr.helpers.files_helper import is_audio_file
from nomarr.helpers.time_helper import now_ms
from nomarr.persistence import Database

logger = logging.getLogger(__name__)


@dataclass
class FileBatchResult:
    """Result of scanning a single folder."""

    file_entries: list[dict[str, Any]]  # Ready for DB upsert (no state fields)
    discovered_paths: set[str]  # All paths found
    new_file_paths: set[str]  # Paths that are new (not in existing_files)
    stats: dict[str, int]  # files_updated, files_failed, files_skipped
    warnings: list[str]
    edge_bootstraps: list[dict[str, Any]] = field(default_factory=list)  # Post-upsert edge creation metadata


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

    Pass 1 of the two-pass scan: fast disk walk only. No audio tag extraction.
    The background tag extraction worker handles Pass 2.

    Args:
        folder_path: Absolute folder path to scan
        folder_rel_path: POSIX relative path for this folder
        library_root: Library root for normalization
        library_id: Library identifier
        existing_files: Path → existing file dict (for determining if file is new/updated)
        tagger_version: Current model suite hash (used for ml-tagged bootstrap)
        db: Database instance (for build_library_path_from_input)

    Returns:
        FileBatchResult with file entries ready for upsert

    """
    file_entries: list[dict[str, Any]] = []
    discovered_paths: set[str] = set()
    new_file_paths: set[str] = set()
    stats: dict[str, int] = {"files_updated": 0, "files_failed": 0, "files_skipped": 0}
    warnings: list[str] = []
    edge_bootstraps: list[dict[str, Any]] = []

    try:
        filenames = os.listdir(str(folder_path))
        files = [
            os.path.join(str(folder_path), f)
            for f in filenames
            if is_audio_file(f) and os.path.isfile(os.path.join(str(folder_path), f))
        ]
    except OSError as e:
        logger.exception("Cannot read folder %s: %s", folder_path, e)
        return FileBatchResult(
            file_entries=file_entries,
            discovered_paths=discovered_paths,
            new_file_paths=new_file_paths,
            stats=stats,
            warnings=warnings,
            edge_bootstraps=edge_bootstraps,
        )

    for file_path in files:
        try:
            library_path = build_library_path_from_input(file_path, db)
            if not library_path.is_valid():
                warnings.append(f"Invalid path: {file_path} - {library_path.reason}")
                stats["files_failed"] += 1
                continue

            file_path_str = str(library_path.absolute)

            try:
                normalized_path = _compute_normalized_path(Path(file_path_str), library_root)
            except ValueError:
                warning = f"File outside library root: {file_path_str}"
                warnings.append(warning)
                logger.warning(warning)
                stats["files_failed"] += 1
                continue

            discovered_paths.add(file_path_str)

            existing_file = existing_files.get(file_path_str)
            file_stat = os.stat(file_path_str)
            modified_time = int(file_stat.st_mtime * 1000)
            file_size = file_stat.st_size

            if existing_file is not None and existing_file.get("modified_time") == modified_time:
                stats["files_skipped"] += 1
                continue

            if existing_file is not None and existing_file.get("has_tagged_state"):
                file_version = existing_file.get("tagger_version")
                if file_version == tagger_version:
                    edge_bootstraps.append(
                        {
                            "normalized_path": normalized_path,
                            "type": "ml_tagged",
                            "version": tagger_version,
                        }
                    )

            file_entry = {
                "path": file_path_str,
                "normalized_path": normalized_path,
                "library_id": library_id,
                "file_size": file_size,
                "modified_time": modified_time,
                "scanned_at": now_ms().value,
            }
            file_entries.append(file_entry)

            if existing_file is None:
                new_file_paths.add(file_path_str)
            else:
                stats["files_updated"] += 1

        except Exception as e:
            logger.exception("Failed to process %s: %s", file_path, e)
            stats["files_failed"] += 1
            warnings.append(f"Scan failed: {file_path} - {str(e)[:100]}")
            continue

    return FileBatchResult(
        file_entries=file_entries,
        discovered_paths=discovered_paths,
        new_file_paths=new_file_paths,
        stats=stats,
        warnings=warnings,
        edge_bootstraps=edge_bootstraps,
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
