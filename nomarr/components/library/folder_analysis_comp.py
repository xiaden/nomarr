"""Folder analysis components for library scanning.

Provides filesystem discovery and scan planning as separate concerns:

- ``discover_library_folders`` — pure filesystem walk
- ``plan_incremental_scan`` — cache-aware planning (skip unchanged folders)
- ``plan_full_scan`` — plan that scans every folder
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


@dataclass
class FolderScanPlan:
    """Plan describing which folders need scanning."""

    all_folders: list[FolderMetadata]  # All folders with audio files
    folders_to_scan: list[FolderMetadata]  # Folders that need scanning
    folders_skipped: int  # Count of folders skipped due to cache
    total_files_to_scan: int  # Total audio files in folders_to_scan


def discover_library_folders(
    library_root: Path,
    scan_paths: list[Path],
) -> list[FolderMetadata]:
    """Walk the filesystem and discover all folders containing audio files.

    Pure discovery — no cache comparison, no scan policy decisions.

    Args:
        library_root: Absolute path to library root
        scan_paths: Paths to walk (typically ``[library_root]``)

    Returns:
        List of :class:`FolderMetadata` for every folder with at least
        one audio file.

    """
    folders: list[FolderMetadata] = []

    for scan_path in scan_paths:
        for dirpath, _dirnames, _filenames in os.walk(str(scan_path)):
            try:
                folder_mtime = _get_folder_mtime(dirpath)
                folder_file_count = _count_audio_files_in_folder(dirpath)
            except OSError as e:
                logger.warning("Cannot access folder %s: %s", dirpath, e)
                continue

            if folder_file_count == 0:
                continue

            folder_rel_path = _compute_folder_path(Path(dirpath), library_root)

            folders.append(
                FolderMetadata(
                    abs_path=dirpath,
                    rel_path=folder_rel_path,
                    mtime=folder_mtime,
                    file_count=folder_file_count,
                ),
            )

    return folders


def plan_incremental_scan(
    all_folders: list[FolderMetadata],
    cached_folders: dict[str, dict],
) -> FolderScanPlan:
    """Build a scan plan that skips unchanged folders.

    Compares each discovered folder's mtime and file_count against the
    DB cache.  Folders whose cache entry matches are skipped.

    Args:
        all_folders: Discovered folders from :func:`discover_library_folders`
        cached_folders: DB cache — ``rel_path -> {mtime, file_count}``

    Returns:
        :class:`FolderScanPlan` with changed folders in ``folders_to_scan``
        and unchanged folders counted in ``folders_skipped``.

    """
    folders_to_scan: list[FolderMetadata] = []
    folders_skipped = 0

    for folder in all_folders:
        cached = cached_folders.get(folder.rel_path)
        if cached and cached["mtime"] == folder.mtime and cached["file_count"] == folder.file_count:
            folders_skipped += 1
            logger.debug("Skipping unchanged folder: %s", folder.rel_path)
        else:
            folders_to_scan.append(folder)

    return FolderScanPlan(
        all_folders=all_folders,
        folders_to_scan=folders_to_scan,
        folders_skipped=folders_skipped,
        total_files_to_scan=sum(f.file_count for f in folders_to_scan),
    )


def plan_full_scan(
    all_folders: list[FolderMetadata],
) -> FolderScanPlan:
    """Build a scan plan that includes every folder.

    No cache comparison — all discovered folders are marked for scanning.

    Args:
        all_folders: Discovered folders from :func:`discover_library_folders`

    Returns:
        :class:`FolderScanPlan` with all folders in ``folders_to_scan``
        and ``folders_skipped == 0``.

    """
    return FolderScanPlan(
        all_folders=all_folders,
        folders_to_scan=list(all_folders),
        folders_skipped=0,
        total_files_to_scan=sum(f.file_count for f in all_folders),
    )


# Component-private helpers
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
    """Compute POSIX-style relative folder path from library root.

    Args:
        absolute_folder: Absolute folder path
        library_root: Library root path

    Returns:
        POSIX-style relative path (e.g., ``"Rock/Beatles"``), or ``""`` for root

    """
    if absolute_folder == library_root:
        return ""
    relative = absolute_folder.relative_to(library_root)
    return relative.as_posix()
