"""
Direct library scan workflow without worker/queue overhead.

Implements fast, read-only metadata extraction. Move detection happens during
ML processing when chromaprint is computed.
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from nomarr.components.infrastructure.path_comp import build_library_path_from_input
from nomarr.components.library.metadata_extraction_comp import extract_metadata
from nomarr.helpers.files_helper import collect_audio_files, is_audio_file
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def scan_library_direct_workflow(
    db: Database,
    library_id: str,
    paths: list[str] | None = None,
    recursive: bool = True,
    clean_missing: bool = True,
) -> dict[str, Any]:
    """
    Scan library by walking filesystem and writing directly to database.

    This is a read-only operation - no files are modified, only metadata is extracted
    and stored in the database. Content hashes are computed and stored for move detection,
    but not written to files until ML tagging occurs.

    Args:
        db: Database instance
        library_id: Library to scan
        paths: Specific paths to scan (or None for entire library root)
        recursive: Recursively scan subdirectories
        clean_missing: Mark missing files as invalid, detect moved files via hash matching

    Returns:
        Dict with scan results:
        - files_discovered: int (total audio files found)
        - files_added: int (new files)
        - files_updated: int (changed files)
        - files_moved: int (detected via chromaprint comparison to removed files)
        - files_removed: int (marked invalid)
        - files_skipped: int (unchanged, not rescanned)
        - files_failed: int (extraction errors)
        - scan_duration_s: float
        - warnings: list[str]

    Notes:
        - Batches DB writes by folder for crash recovery
        - Move detection: new files with chromaprint matching removed files are moves
        - Chromaprint computed for new files if not in DB (requires audio load)
        - Crashes intentionally on fatal errors (loud failure for Docker)
        - Progress tracked via library.scan_progress column
    """
    start_time = time.time()
    stats: dict[str, int] = defaultdict(int)
    warnings: list[str] = []

    # Get library record
    library = db.libraries.get_library(library_id)
    if not library:
        raise ValueError(f"Library {library_id} not found")

    scan_paths = paths or [library["root_path"]]

    # Update library status to 'scanning'
    db.libraries.update_scan_status(library_id, status="scanning", progress=0, total=0)

    try:
        # PHASE 1: Count total files (fast walk for progress tracking)
        logger.info(f"[scan_library] Counting files in {len(scan_paths)} path(s)...")
        total_files = 0
        for root_path in scan_paths:
            total_files += count_audio_files(root_path, recursive=recursive)

        db.libraries.update_scan_status(library_id, total=total_files)
        stats["files_discovered"] = total_files
        logger.info(f"[scan_library] Found {total_files} audio files")

        # PHASE 2: Check if move detection is needed
        # Only detect moves if library has tagged files (preserves ML work)
        has_tagged_files = db.library_files.library_has_tagged_files(library_id)
        enable_move_detection = has_tagged_files and clean_missing

        if enable_move_detection:
            logger.info("[scan_library] Move detection enabled (library has tagged files)")
        else:
            logger.info("[scan_library] Fast mode (no tagged files, simple add/remove)")

        # Snapshot existing DB paths and hashes for this library
        # Note: list_library_files returns all files (no library_id filter in current schema)
        existing_files_tuple = db.library_files.list_library_files(limit=1000000, offset=0)
        existing_files = existing_files_tuple[0]  # Get list from (list, count) tuple
        existing_paths = {f["path"] for f in existing_files}
        existing_files_dict = {f["path"]: f for f in existing_files}
        discovered_paths: set[str] = set()

        # Only track for move detection if needed
        files_to_remove: list[dict] = [] if enable_move_detection else []
        new_files: list[dict] = [] if enable_move_detection else []

        # PHASE 3: Walk filesystem and process files (batched by folder)
        logger.info("[scan_library] Walking filesystem...")
        current_file = 0

        for root_path in scan_paths:
            # Walk directory tree, batched by folder to avoid RAM bloat
            for _folder_path, files in walk_audio_files_batched(root_path, recursive):
                folder_batch: list[dict] = []  # Batch writes for this folder

                for file_path in files:
                    current_file += 1

                    try:
                        # Validate path
                        library_path = build_library_path_from_input(file_path, db)
                        if not library_path.is_valid():
                            warnings.append(f"Invalid path: {file_path} - {library_path.reason}")
                            stats["files_failed"] += 1
                            continue

                        file_path_str = str(library_path.absolute)
                        discovered_paths.add(file_path_str)

                        # Check if file exists in DB
                        existing_file = existing_files_dict.get(file_path_str)
                        file_stat = os.stat(file_path_str)
                        modified_time = int(file_stat.st_mtime * 1000)
                        file_size = file_stat.st_size

                        # Skip unchanged files
                        if existing_file and existing_file.get("modified_time") == modified_time:
                            stats["files_skipped"] += 1
                            continue

                        # Extract metadata + tags (component call)
                        metadata = extract_metadata(library_path, namespace="nom")

                        # Check if file needs tagging
                        existing_version = metadata.get("nom_tags", {}).get("nom_version")
                        tagger_version = metadata.get("nom_tags", {}).get("tagger_version", "unknown")
                        needs_tagging = (
                            existing_file is None
                            or not existing_file.get("tagged")
                            or existing_version != tagger_version
                        )

                        # Prepare batch entry
                        file_entry = {
                            "path": file_path_str,
                            "library_id": library_id,
                            "metadata": metadata,
                            "file_size": file_size,
                            "modified_time": modified_time,
                            "needs_tagging": needs_tagging,
                            "is_valid": True,
                            "scanned_at": now_ms(),
                        }
                        folder_batch.append(file_entry)

                        # Track new files for move detection (if enabled)
                        if existing_file is None:
                            if enable_move_detection:
                                new_files.append(file_entry)
                        else:
                            stats["files_updated"] += 1

                    except Exception as e:
                        logger.error(f"Failed to process {file_path}: {e}")
                        stats["files_failed"] += 1
                        warnings.append(f"Extraction failed: {file_path} - {str(e)[:100]}")
                        continue

                # Batch write folder files to DB (with collision handling)
                if folder_batch:
                    try:
                        db.library_files.batch_upsert_library_files(folder_batch)
                        stats["files_added"] += len([f for f in folder_batch if f["path"] not in existing_paths])
                    except Exception as e:
                        # Batch insert failed - process individually for better error visibility
                        logger.warning(f"Batch insert failed, processing individually: {e}")
                        for file_entry in folder_batch:
                            try:
                                db.library_files.batch_upsert_library_files([file_entry])
                                if file_entry["path"] not in existing_paths:
                                    stats["files_added"] += 1
                            except Exception as insert_error:
                                logger.error(f"Failed to insert {file_entry['path']}: {insert_error}")
                                warnings.append(f"Failed to insert: {file_entry['path']}")
                                stats["files_failed"] += 1

                # Update progress every folder
                db.libraries.update_scan_status(library_id, progress=current_file)

        # PHASE 4: Identify missing files (only if move detection enabled)
        if enable_move_detection:
            missing_paths = existing_paths - discovered_paths
            logger.info(f"[scan_library] Found {len(missing_paths)} missing files")

            for missing_path in missing_paths:
                missing_file = existing_files_dict.get(missing_path)
                if missing_file:
                    files_to_remove.append(missing_file)
        elif clean_missing:
            # Fast mode: just mark missing files invalid, no move detection
            missing_paths = existing_paths - discovered_paths
            if missing_paths:
                logger.info(f"[scan_library] Fast mode: marking {len(missing_paths)} missing files invalid")
                db.library_files.bulk_mark_invalid(list(missing_paths))
                stats["files_removed"] += len(missing_paths)

        # PHASE 5: Move detection (conditional on chromaprint availability)
        if enable_move_detection and files_to_remove:
            # Check if any chromaprints exist in this library (indicates ML has run)
            has_chromaprints = any(f.get("chromaprint") for f in files_to_remove)

            if not has_chromaprints:
                # Fast path: No chromaprints in DB yet, can't do move detection
                # Just mark missing files as invalid
                logger.info(
                    f"[scan_library] No chromaprints found in library - "
                    f"skipping move detection, removing {len(files_to_remove)} files"
                )
                paths_to_remove = [f["path"] for f in files_to_remove]
                db.library_files.bulk_mark_invalid(paths_to_remove)
                stats["files_removed"] += len(files_to_remove)
            else:
                # Chromaprints exist - do full move detection
                from nomarr.components.library.metadata_extraction_comp import compute_chromaprint_for_file

                logger.info(
                    f"[scan_library] Chromaprints found - checking {len(new_files)} new files for moves "
                    f"against {len(files_to_remove)} removed files..."
                )

                # Sort removed files by ID for deterministic matching when duplicates exist
                files_to_remove.sort(key=lambda f: f["id"])

                matched_moves: set[int] = set()

                for new_file in new_files:
                    new_path = new_file["path"]

                    # Compute chromaprint for new file
                    try:
                        library_path_for_audio = build_library_path_from_input(new_path, db)
                        if not library_path_for_audio.is_valid():
                            continue

                        new_chromaprint = compute_chromaprint_for_file(library_path_for_audio)

                        # Check if chromaprint matches any removed file
                        for idx, removed_file in enumerate(files_to_remove):
                            if idx in matched_moves:
                                continue

                            removed_chromaprint = removed_file.get("chromaprint")
                            if new_chromaprint and removed_chromaprint and removed_chromaprint == new_chromaprint:
                                # Chromaprint matches - verify duration to catch edge cases
                                removed_duration = removed_file.get("duration_seconds")
                                new_duration = new_file.get("duration_seconds")

                                # Verify duration matches (allow 1 second tolerance)
                                duration_matches = (
                                    removed_duration is None
                                    or new_duration is None
                                    or abs(removed_duration - new_duration) <= 1.0
                                )

                                if duration_matches:
                                    # Match confirmed - update all metadata except ML tags
                                    # (chromaprint + duration match = same audio = same ML output)
                                    logger.info(f"[scan_library] File moved: {removed_file['path']} → {new_path}")
                                    metadata = new_file.get("metadata", {})
                                    db.library_files.update_file_path(
                                        file_id=removed_file["id"],
                                        new_path=new_path,
                                        file_size=new_file["file_size"],
                                        modified_time=new_file["modified_time"],
                                        artist=metadata.get("artist"),
                                        album=metadata.get("album"),
                                        title=metadata.get("title"),
                                        duration_seconds=new_duration,
                                    )
                                    stats["files_moved"] += 1
                                    matched_moves.add(idx)
                                    break
                                else:
                                    # Chromaprint collision - different songs with same fingerprint
                                    logger.warning(
                                        f"[scan_library] Chromaprint collision detected: "
                                        f"{removed_file['path']} vs {new_path} "
                                        f"(duration: {removed_duration}s vs {new_duration}s)"
                                    )
                    except Exception as e:
                        logger.warning(f"[scan_library] Failed to compute chromaprint for {new_path}: {e}")
                        continue

                # PHASE 6: Bulk remove remaining unmatched missing files
                unmatched_removed = [f for idx, f in enumerate(files_to_remove) if idx not in matched_moves]
                if unmatched_removed:
                    logger.info(f"[scan_library] Removing {len(unmatched_removed)} deleted files from library")
                    paths_to_remove = [f["path"] for f in unmatched_removed]
                    db.library_files.bulk_mark_invalid(paths_to_remove)
                    stats["files_removed"] += len(unmatched_removed)
                paths_to_remove = [f["path"] for f in unmatched_removed]
                db.library_files.bulk_mark_invalid(paths_to_remove)
                stats["files_removed"] += len(unmatched_removed)

        # PHASE 7: Finalize scan
        scan_duration = time.time() - start_time

        # Verify count matches (warning only for dev/alpha visibility)
        expected = stats["files_added"] + stats["files_updated"] + stats["files_skipped"] + stats["files_failed"]
        if expected != total_files:
            warning = (
                f"File count mismatch: discovered={total_files}, "
                f"processed={expected} (added={stats['files_added']}, "
                f"updated={stats['files_updated']}, skipped={stats['files_skipped']}, "
                f"failed={stats['files_failed']}). Filesystem may have changed during scan."
            )
            warnings.append(warning)
            logger.warning(f"[scan_library] {warning}")

        # Mark scan complete
        db.libraries.update_scan_status(
            library_id,
            status="complete",
            progress=total_files,
            scan_error=None,
        )

        logger.info(
            f"[scan_library] Scan complete in {scan_duration:.1f}s: "
            f"added={stats['files_added']}, updated={stats['files_updated']}, "
            f"moved={stats['files_moved']}, removed={stats['files_removed']}, "
            f"skipped={stats['files_skipped']}, failed={stats['files_failed']}"
        )

        return {
            **stats,
            "scan_duration_s": scan_duration,
            "warnings": warnings,
        }

    except Exception as e:
        # Crash is intentional - loud failure in Docker container
        logger.error(f"[scan_library] Scan crashed: {e}", exc_info=True)
        db.libraries.update_scan_status(
            library_id,
            status="error",
            scan_error=str(e),
        )
        # Re-raise to crash container (preferred behavior for alpha)
        raise


def count_audio_files(root_path: str, recursive: bool) -> int:
    """
    Fast count of audio files for progress tracking.

    Args:
        root_path: Directory to count files in
        recursive: Whether to recurse into subdirectories

    Returns:
        Total number of audio files found
    """
    files = collect_audio_files(root_path, recursive=recursive)
    return len(files)


def walk_audio_files_batched(root_path: str, recursive: bool):
    """
    Walk filesystem and yield (folder_path, audio_files) batches.

    This prevents loading all file paths into RAM at once.

    Args:
        root_path: Directory to walk
        recursive: Whether to recurse into subdirectories

    Yields:
        tuple[str, list[str]]: (folder_path, list of audio file paths in that folder)
    """
    if recursive:
        for dirpath, _dirnames, filenames in os.walk(root_path):
            audio_files = [os.path.join(dirpath, f) for f in filenames if is_audio_file(f)]
            if audio_files:
                yield (dirpath, audio_files)
    else:
        # Non-recursive: only scan root directory
        try:
            filenames = os.listdir(root_path)
            audio_files = [
                os.path.join(root_path, f)
                for f in filenames
                if os.path.isfile(os.path.join(root_path, f)) and is_audio_file(f)
            ]
            if audio_files:
                yield (root_path, audio_files)
        except OSError as e:
            logger.error(f"Error reading directory {root_path}: {e}")
