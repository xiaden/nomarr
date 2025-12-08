"""
Workflow for planning library scans by discovering files and enqueueing them.

This workflow orchestrates the PLANNING phase of library scanning:
- Discovers audio files in specified paths
- Enqueues each file individually to the library_queue via queue components
- Returns statistics about files queued

The EXECUTION phase is handled by LibraryScanWorker, which processes
one file at a time from the queue.

ARCHITECTURE:
- This is a PURE WORKFLOW that takes all dependencies as parameters
- Does NOT import or use services, DI container, or application object
- Callers (typically services) must provide Database instance and config values

EXPECTED DEPENDENCIES:
- db: Database instance (provides library_files accessor)
- Queue components from nomarr.components.queue (for enqueueing)

USAGE:
    from nomarr.workflows.library.start_library_scan_wf import start_library_scan_workflow

    stats = start_library_scan_workflow(
        db=database_instance,
        params=StartLibraryScanWorkflowParams(...)
    )
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, TypedDict

from nomarr.components.queue.queue_enqueue_comp import enqueue_file
from nomarr.helpers.dto.library_dto import StartLibraryScanWorkflowParams

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class LibraryScanStats(TypedDict):
    """Statistics from library scan workflow."""

    files_discovered: int
    files_queued: int
    files_skipped: int
    files_removed: int
    job_ids: list[int]


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


def start_library_scan_workflow(
    db: Database,
    params: StartLibraryScanWorkflowParams,
) -> LibraryScanStats:
    """
    Plan a library scan by discovering files and enqueueing them.

    This workflow:
    1. Discovers audio files under root_paths
    2. Optionally checks if files need scanning (modification time check)
    3. Enqueues files via db.library_queue
    4. Optionally removes deleted files from database
    5. Returns statistics about files queued

    Args:
        db: Database instance (provides library_files and library_queue accessors)
        params: StartLibraryScanWorkflowParams with root_paths, recursive, force, auto_tag, ignore_patterns, clean_missing

    Returns:
        Dict with scan statistics:
        - files_discovered: int (total audio files found)
        - files_queued: int (files enqueued for scanning)
        - files_skipped: int (files skipped due to no changes)
        - files_removed: int (deleted files removed from DB)
        - job_ids: list[int] (IDs of enqueued jobs)

    Note:
        This workflow only PLANS the scan by enqueueing jobs.
        LibraryScanWorker executes the actual scanning asynchronously.
    """
    # Extract parameters (only the ones we use in this workflow)
    root_paths = params.root_paths
    recursive = params.recursive
    force = params.force
    clean_missing = params.clean_missing
    # Note: auto_tag and ignore_patterns are passed to workers via queue, not used here

    logging.info(f"[start_library_scan] Planning library scan for {len(root_paths)} path(s)")

    stats: LibraryScanStats = {
        "files_discovered": 0,
        "files_queued": 0,
        "files_skipped": 0,
        "files_removed": 0,
        "job_ids": [],
    }

    # Discover all audio files using helpers.files
    from nomarr.helpers.files_helper import collect_audio_files

    all_files: set[str] = set()
    for root_path in root_paths:
        if not os.path.exists(root_path):
            logging.warning(f"[start_library_scan] Path does not exist: {root_path}")
            continue

        files = collect_audio_files(root_path, recursive=recursive)
        all_files.update(files)

    stats["files_discovered"] = len(all_files)
    logging.info(f"[start_library_scan] Discovered {stats['files_discovered']} audio files")

    # Batch optimization: Load all existing file mtimes from DB in one query
    files_to_enqueue = all_files
    if not force:
        logging.info("[start_library_scan] Batch-checking file changes...")
        existing_mtimes = db.library_files.get_file_modified_times()

        files_to_check = []
        for file_path in all_files:
            try:
                file_stat = os.stat(file_path)
                current_mtime = int(file_stat.st_mtime * 1000)
                db_mtime = existing_mtimes.get(file_path)

                if db_mtime == current_mtime:
                    # File unchanged, skip
                    stats["files_skipped"] += 1
                else:
                    # File new or changed, needs scanning
                    files_to_check.append(file_path)
            except Exception as e:
                logging.warning(f"[start_library_scan] Failed to stat {file_path}: {e}")
                # If we can't stat it, enqueue anyway (worker will handle error)
                files_to_check.append(file_path)

        files_to_enqueue = set(files_to_check)
        logging.info(f"[start_library_scan] Batch check complete: {len(files_to_enqueue)} files need scanning")

    # Enqueue files that need scanning
    for file_path in files_to_enqueue:
        try:
            enqueue_file(db, file_path, force=force, queue_type="library")
            stats["files_queued"] += 1
        except Exception as e:
            logging.warning(f"[start_library_scan] Failed to enqueue {file_path}: {e}")

    logging.info(
        f"[start_library_scan] Queued {stats['files_queued']} files (skipped {stats['files_skipped']} unchanged)"
    )

    # Optionally clean up deleted files
    if clean_missing:
        try:
            # Get all files in database
            existing_files, _ = db.library_files.list_library_files(limit=1000000)
            existing_paths = {f["path"] for f in existing_files}

            # Find files that no longer exist
            removed_paths = existing_paths - all_files

            # Remove them from database
            for path in removed_paths:
                db.library_files.delete_library_file(path)
                stats["files_removed"] += 1

            if stats["files_removed"] > 0:
                logging.info(f"[start_library_scan] Removed {stats['files_removed']} deleted files from database")

        except Exception as e:
            logging.warning(f"[start_library_scan] Failed to clean missing files: {e}")

    logging.info(
        f"[start_library_scan] Scan planning complete: "
        f"discovered={stats['files_discovered']}, queued={stats['files_queued']}, "
        f"skipped={stats['files_skipped']}, removed={stats['files_removed']}"
    )

    return stats
