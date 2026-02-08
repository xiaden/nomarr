"""Missing file detection component.

Identifies library files that no longer exist on disk using folder-aware
comparison.  Files in skipped (cached) folders are assumed present.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def detect_missing_files(
    existing_files: dict[str, dict[str, Any]],
    discovered_paths: set[str],
    scanned_folder_paths: set[str],
    all_on_disk_folder_paths: set[str],
) -> set[str]:
    """Identify files that are missing from disk after a scan.

    Uses folder-aware logic so files in folders that were **skipped** by the
    scan (because their cache was still valid) are not falsely flagged.

    A file is considered missing when:
    - Its parent folder *was* scanned and the file was not rediscovered, OR
    - Its parent folder no longer exists on disk at all.

    Files whose parent folder was *skipped* (cached, not scanned) are assumed
    present.

    Args:
        existing_files: Map of absolute-path -> file record for all known files.
        discovered_paths: Set of absolute paths found during this scan.
        scanned_folder_paths: Absolute paths of folders that **were** walked.
        all_on_disk_folder_paths: Absolute paths of **all** folders on disk
            (including skipped ones).

    Returns:
        Set of absolute file paths that should be treated as missing.

    """
    missing: set[str] = set()

    for existing_path in existing_files:
        from pathlib import Path

        parent_dir = str(Path(existing_path).parent)

        if parent_dir in scanned_folder_paths:
            # Folder was scanned — file must appear in discovered_paths
            if existing_path not in discovered_paths:
                missing.add(existing_path)
        elif parent_dir not in all_on_disk_folder_paths:
            # Folder doesn't even exist on disk anymore
            missing.add(existing_path)
        # else: folder exists but was skipped (cached) — assume file is fine

    if missing:
        logger.info("%d files missing from scanned folders", len(missing))

    return missing
