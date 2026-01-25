"""
Folder analysis component for library scanning.

Analyzes folders to determine which need scanning based on cache comparison.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from nomarr.helpers.files_helper import is_audio_file

logger = logging.getLogger(__name__)


# Component-local DTOs (not promoted to helpers/dto)
@dataclass
class FolderMetadata:
    """Metadata for a single folder in the library."""

    abs_path: str
    rel_path: str  # POSIX relative to library root
    mtime: int  # Modification time in milliseconds
    file_count: int  # Number of audio files
    needs_scan: bool  # False if cached and unchanged


@dataclass
class FolderScanPlan:
    """Plan describing which folders need scanning."""

    all_folders: list[FolderMetadata]  # All folders with audio files
    folders_to_scan: list[FolderMetadata]  # Folders that need scanning
    folders_skipped: int  # Count of folders skipped due to cache
    total_files_to_scan: int  # Total audio files in folders_to_scan


def analyze_folders_for_scan(
    library_root: Path,
    scan_paths: list[Path],
    cached_folders: dict[str, dict],
    force_rescan: bool = False,
) -> FolderScanPlan:
    """
    Analyze folders to determine which need scanning.

    Walks the filesystem, computes folder metadata, and compares against
    cached folder data to identify unchanged folders that can be skipped.

    Args:
        library_root: Absolute path to library root
        scan_paths: Paths to scan (from scan targets)
        cached_folders: Existing folder cache from DB (rel_path -> dict with mtime/file_count)
        force_rescan: If True, skip cache checks and scan all folders

    Returns:
        FolderScanPlan with folders to scan and statistics
    """
    all_folders: list[FolderMetadata] = []
    folders_to_scan: list[FolderMetadata] = []
    folders_skipped = 0

    # Walk all scan paths
    for scan_path in scan_paths:
        for dirpath, _dirnames, _filenames in os.walk(str(scan_path)):
            try:
                folder_mtime = _get_folder_mtime(dirpath)
                folder_file_count = _count_audio_files_in_folder(dirpath)
            except OSError as e:
                logger.warning(f"Cannot access folder {dirpath}: {e}")
                continue

            # Skip folders with no audio files
            if folder_file_count == 0:
                continue

            # Compute relative path for DB lookup
            folder_rel_path = _compute_folder_path(Path(dirpath), library_root)

            # Determine if folder needs scanning
            needs_scan = True
            if not force_rescan:
                cached = cached_folders.get(folder_rel_path)
                if cached and cached["mtime"] == folder_mtime and cached["file_count"] == folder_file_count:
                    needs_scan = False
                    folders_skipped += 1
                    logger.debug(f"Skipping unchanged folder: {folder_rel_path}")

            folder_meta = FolderMetadata(
                abs_path=dirpath,
                rel_path=folder_rel_path,
                mtime=folder_mtime,
                file_count=folder_file_count,
                needs_scan=needs_scan,
            )

            all_folders.append(folder_meta)
            if needs_scan:
                folders_to_scan.append(folder_meta)

    # Compute total files to scan
    total_files_to_scan = sum(f.file_count for f in folders_to_scan)

    return FolderScanPlan(
        all_folders=all_folders,
        folders_to_scan=folders_to_scan,
        folders_skipped=folders_skipped,
        total_files_to_scan=total_files_to_scan,
    )


# Helper functions (component-private)
def _get_folder_mtime(folder_path: str) -> int:
    """Get folder modification time in milliseconds."""
    return int(os.stat(folder_path).st_mtime * 1000)


def _count_audio_files_in_folder(folder_path: str) -> int:
    """Count audio files in a single folder (non-recursive)."""
    try:
        return sum(
            1 for f in os.listdir(folder_path) if is_audio_file(f) and os.path.isfile(os.path.join(folder_path, f))
        )
    except OSError:
        return 0


def _compute_folder_path(absolute_folder: Path, library_root: Path) -> str:
    """
    Compute POSIX-style relative folder path from library root.

    Args:
        absolute_folder: Absolute folder path
        library_root: Library root path

    Returns:
        POSIX-style relative path (e.g., "Rock/Beatles"), or "" for root
    """
    if absolute_folder == library_root:
        return ""
    relative = absolute_folder.relative_to(library_root)
    return relative.as_posix()
