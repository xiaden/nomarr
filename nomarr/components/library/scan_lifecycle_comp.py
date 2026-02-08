"""Scan lifecycle component — persistence operations for library scanning.

Wraps all db.libraries.*, db.library_files.*, and db.library_folders.* calls
needed by the scan workflows.  Workflows call these functions instead of
accessing persistence directly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Library resolution
# ---------------------------------------------------------------------------


def resolve_library_for_scan(db: Database, library_id: str) -> dict[str, Any]:
    """Fetch a library document, raising if not found.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    Returns:
        Library dict

    Raises:
        ValueError: If library not found

    """
    library = db.libraries.get_library(library_id)
    if not library:
        msg = f"Library {library_id} not found"
        raise ValueError(msg)
    return library


def check_interrupted_scan(db: Database, library_id: str) -> tuple[bool, str | None]:
    """Check whether a previous scan was interrupted.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    Returns:
        Tuple of (was_interrupted, scan_type).  *scan_type* is ``"quick"``
        or ``"full"`` when interrupted, ``None`` otherwise.

    """
    return db.libraries.check_interrupted_scan(library_id)


# ---------------------------------------------------------------------------
# Scan status tracking
# ---------------------------------------------------------------------------


def mark_scan_started(db: Database, library_id: str, scan_type: str) -> None:
    """Record that a scan has started.

    Args:
        db: Database instance
        library_id: Library document ``_id``
        scan_type: ``"quick"`` or ``"full"``

    """
    db.libraries.mark_scan_started(library_id, scan_type=scan_type)


def mark_scan_completed(db: Database, library_id: str) -> None:
    """Record that a scan has completed successfully.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    """
    db.libraries.mark_scan_completed(library_id)


def update_scan_progress(
    db: Database,
    library_id: str,
    *,
    status: str | None = None,
    progress: int | None = None,
    total: int | None = None,
    scan_error: str | None = None,
) -> None:
    """Update scan progress counters and/or status.

    Only updates fields that are explicitly provided.

    Args:
        db: Database instance
        library_id: Library document ``_id``
        status: Scan status (``'idle'``, ``'scanning'``, ``'complete'``, ``'error'``)
        progress: Files processed so far
        total: Total files to scan
        scan_error: Error message (only when ``status='error'``)

    """
    db.libraries.update_scan_status(
        library_id, status=status, progress=progress, total=total, scan_error=scan_error,
    )


# ---------------------------------------------------------------------------
# File snapshots
# ---------------------------------------------------------------------------


def snapshot_existing_files(
    db: Database, library_id: str,
) -> tuple[dict[str, dict[str, Any]], bool]:
    """Load all existing library files and check for tagged files.

    Returns a snapshot of what the DB knows before scanning, used for
    comparison during the scan loop.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    Returns:
        Tuple of (existing_files_dict, has_tagged_files) where
        *existing_files_dict* maps file path → file document.

    """
    files_tuple = db.library_files.list_library_files(limit=1_000_000, offset=0)
    existing_files_dict: dict[str, dict[str, Any]] = {
        f["path"]: f for f in files_tuple[0]
    }
    has_tagged_files = db.library_files.library_has_tagged_files(library_id)
    return existing_files_dict, has_tagged_files


# ---------------------------------------------------------------------------
# Batch file operations
# ---------------------------------------------------------------------------


def upsert_scanned_files(db: Database, file_entries: list[dict[str, Any]]) -> int:
    """Batch-upsert scanned file documents.

    Args:
        db: Database instance
        file_entries: File documents to upsert

    Returns:
        Number of documents processed

    """
    return db.library_files.upsert_batch(file_entries)


def remove_deleted_files(db: Database, paths: list[str]) -> int:
    """Bulk-delete files that are no longer on disk.

    Args:
        db: Database instance
        paths: Absolute file paths to remove

    Returns:
        Number of files deleted

    """
    return db.library_files.bulk_delete_files(paths)


# ---------------------------------------------------------------------------
# Folder cache
# ---------------------------------------------------------------------------


def get_cached_folders(
    db: Database, library_id: str,
) -> dict[str, dict[str, Any]]:
    """Load all cached folder records for a library.

    Args:
        db: Database instance
        library_id: Library document ``_id``

    Returns:
        Dict mapping relative folder path → folder record

    """
    return db.library_folders.get_all_folders_for_library(library_id)


def save_folder_record(
    db: Database,
    library_id: str,
    rel_path: str,
    mtime: int,
    file_count: int,
) -> None:
    """Upsert a single folder cache record.

    Args:
        db: Database instance
        library_id: Library document ``_id``
        rel_path: Folder path relative to library root (POSIX-style)
        mtime: Folder modification time
        file_count: Number of audio files in the folder

    """
    db.library_folders.upsert_folder(library_id, rel_path, mtime, file_count)


def cleanup_stale_folders(
    db: Database,
    library_id: str,
    existing_folder_rel_paths: set[str],
) -> None:
    """Delete folder records that no longer exist on disk.

    Logs a warning on failure instead of propagating.

    Args:
        db: Database instance
        library_id: Library document ``_id``
        existing_folder_rel_paths: Set of folder relative paths still on disk

    """
    try:
        db.library_folders.delete_missing_folders(library_id, existing_folder_rel_paths)
    except Exception as e:
        logger.warning("Failed to clean up folder records: %s", e)
