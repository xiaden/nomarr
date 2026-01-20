"""
Direct library scan workflow without worker/queue overhead.

Implements fast, read-only metadata extraction. Move detection happens during
ML processing when chromaprint is computed.

Supports targeted/incremental scanning via scan_targets parameter.
Uses folder-level caching for quick scans (skips unchanged folders entirely).
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nomarr.components.infrastructure.path_comp import build_library_path_from_input
from nomarr.components.library.metadata_extraction_comp import extract_metadata
from nomarr.components.metadata import rebuild_song_metadata_cache, seed_song_entities_from_tags
from nomarr.helpers.dto import ScanTarget
from nomarr.helpers.files_helper import collect_audio_files, is_audio_file
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def _seed_and_rebuild_batch(
    db: Database, file_batch: list[dict[str, Any]], metadata_map: dict[str, dict[str, Any]]
) -> None:
    """Seed entities and rebuild metadata caches for a batch of files.

    Args:
        db: Database instance
        file_batch: List of file entries that were just upserted
        metadata_map: Map of file_path -> metadata dict
    """
    for file_entry in file_batch:
        file_path = file_entry["path"]
        metadata = metadata_map.get(file_path)
        if not metadata:
            continue

        # Get file_id from database
        file_record = db.library_files.get_library_file(file_path)
        if not file_record:
            logger.warning(f"File not found after upsert: {file_path}")
            continue

        file_id = file_record["_id"]

        try:
            # Seed entity vertices and edges from metadata
            entity_tags = {
                "artist": metadata.get("artist"),
                "artists": metadata.get("artists"),
                "album": metadata.get("album"),
                "label": metadata.get("label"),
                "genre": metadata.get("genre"),
                "year": metadata.get("year"),
            }
            seed_song_entities_from_tags(db, file_id, entity_tags)

            # Rebuild cache fields (artist, album, etc.) from edges
            rebuild_song_metadata_cache(db, file_id)

        except Exception as e:
            logger.warning(f"Failed to seed entities for {file_path}: {e}")


def _compute_normalized_path(absolute_path: Path, library_root: Path) -> str:
    """
    Compute normalized POSIX-style path relative to library root.

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


def _compute_folder_path(absolute_folder: Path, library_root: Path) -> str:
    """Compute POSIX-style relative folder path from library root.

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


def scan_library_direct_workflow(
    db: Database,
    library_id: str,
    scan_targets: list[ScanTarget],
    batch_size: int = 200,
    force_rescan: bool = False,
) -> dict[str, Any]:
    """
    Scan specific folders within a library.

    Supports both full library scans and targeted/incremental scans.
    - Full scan: single ScanTarget with folder_path=""
    - Targeted scan: one or more ScanTargets with specific folder_path values

    This is a read-only operation - no files are modified, only metadata is extracted
    and stored in the database. Content hashes are computed and stored for move detection,
    but not written to files until ML tagging occurs.

    Args:
        db: Database instance
        library_id: Library to scan
        scan_targets: List of folders to scan (empty folder_path = full library)
        batch_size: Number of files to accumulate before writing to DB
        force_rescan: If True, skip unchanged files detection (rescan all files)

    Returns:
        Dict with scan results:
        - files_discovered: int (total audio files found)
        - files_added: int (new files)
        - files_updated: int (changed files)
        - files_moved: int (detected via chromaprint comparison to removed files)
        - files_removed: int (marked invalid, ONLY for full scans)
        - files_skipped: int (unchanged, not rescanned)
        - files_failed: int (extraction errors)
        - scan_duration_s: float
        - warnings: list[str]
        - scan_id: str (identifier for this scan)

    Notes:
        - Batches DB writes by folder for crash recovery
        - Move detection: new files with chromaprint matching removed files are moves
        - Chromaprint computed for new files if not in DB (requires audio load)
        - Crashes intentionally on fatal errors (loud failure for Docker)
        - Progress tracked via library.scan_progress column
        - Files marked missing ONLY for full scans (single target with folder_path="")
        - Identity model: files keyed by (library_id, normalized_path)
        - normalized_path is POSIX-style relative to library root
    """
    start_time = time.time()
    stats: dict[str, int] = defaultdict(int)
    warnings: list[str] = []

    # Generate scan_id for tracking files seen in this scan
    scan_id = f"{library_id}_{now_ms()}"

    # Get library record
    library = db.libraries.get_library(library_id)
    if not library:
        raise ValueError(f"Library {library_id} not found")

    library_root = Path(library["root_path"]).resolve()

    # Determine if this is a full scan (for missing file detection)
    is_full_scan = len(scan_targets) == 1 and scan_targets[0].folder_path == ""

    # Mark scan started
    db.libraries.mark_scan_started(library_id, full_scan=is_full_scan)

    # Update library status to 'scanning'
    db.libraries.update_scan_status(library_id, status="scanning", progress=0, total=0)

    try:
        # PHASE 1: Determine scan paths from targets
        scan_paths: list[Path] = []
        for target in scan_targets:
            if target.folder_path:
                # Targeted scan: scan specific subfolder
                target_path = library_root / target.folder_path
            else:
                # Full library scan
                target_path = library_root

            if not target_path.exists():
                warning = f"Scan target does not exist: {target_path}"
                warnings.append(warning)
                logger.warning(f"[scan_library] {warning}")
                continue

            scan_paths.append(target_path)

        if not scan_paths:
            raise ValueError("No valid scan paths found in scan_targets")

        # PHASE 2: Folder-based scan optimization
        # For quick scans, we check folder mtime + file_count to skip unchanged folders
        # For full scans, we scan all folders regardless of cache

        # Get cached folder data from DB
        cached_folders = db.library_folders.get_all_folders_for_library(library_id)

        # Walk folders and determine which need scanning
        folders_to_scan: list[tuple[str, str, int, int]] = []  # (abs_path, rel_path, mtime, file_count)
        folders_skipped = 0
        all_folder_data: list[tuple[str, str, int, int]] = []  # For updating DB later

        for scan_path in scan_paths:
            for dirpath, _dirnames, _filenames in os.walk(str(scan_path)):
                try:
                    folder_mtime = _get_folder_mtime(dirpath)
                    folder_file_count = _count_audio_files_in_folder(dirpath)
                except OSError as e:
                    logger.warning(f"[scan_library] Cannot access folder {dirpath}: {e}")
                    continue

                # Skip folders with no audio files
                if folder_file_count == 0:
                    continue

                # Compute relative path for DB lookup
                folder_rel_path = _compute_folder_path(Path(dirpath), library_root)
                all_folder_data.append((dirpath, folder_rel_path, folder_mtime, folder_file_count))

                # Check if folder needs scanning (skip unchanged folders for quick scan)
                if not force_rescan:
                    cached = cached_folders.get(folder_rel_path)
                    if cached and cached["mtime"] == folder_mtime and cached["file_count"] == folder_file_count:
                        folders_skipped += 1
                        logger.debug(f"[scan_library] Skipping unchanged folder: {folder_rel_path}")
                        continue

                folders_to_scan.append((dirpath, folder_rel_path, folder_mtime, folder_file_count))

        # Log folder scan stats
        total_folders = len(all_folder_data)
        scan_folder_count = len(folders_to_scan)
        if force_rescan:
            logger.info(f"[scan_library] Full scan: {total_folders} folders to scan")
        else:
            logger.info(
                f"[scan_library] Quick scan: {scan_folder_count}/{total_folders} folders "
                f"need scanning ({folders_skipped} unchanged)"
            )
        stats["folders_scanned"] = scan_folder_count
        stats["folders_skipped"] = folders_skipped

        # Count files in folders to scan (for progress)
        total_files = sum(fc for _, _, _, fc in folders_to_scan)
        db.libraries.update_scan_status(library_id, total=total_files)
        stats["files_discovered"] = total_files
        logger.info(f"[scan_library] {total_files} files to scan in {scan_folder_count} folders")

        # PHASE 3: Check if move detection is needed
        # Only detect moves if library has tagged files (preserves ML work)
        has_tagged_files = db.library_files.library_has_tagged_files(library_id)
        enable_move_detection = has_tagged_files

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

        # Track metadata for entity seeding after upsert
        files_metadata: dict[str, dict[str, Any]] = {}

        # PHASE 4: Scan files in selected folders only
        logger.info("[scan_library] Scanning files in selected folders...")
        current_file = 0

        # Iterate over folders to scan (not all folders)
        for folder_abs_path, folder_rel_path, folder_mtime, _folder_file_count in folders_to_scan:
            folder_batch: list[dict] = []  # Batch writes for this folder

            # Get audio files in this folder (non-recursive)
            try:
                filenames = os.listdir(folder_abs_path)
                files = [
                    os.path.join(folder_abs_path, f)
                    for f in filenames
                    if is_audio_file(f) and os.path.isfile(os.path.join(folder_abs_path, f))
                ]
            except OSError as e:
                logger.error(f"[scan_library] Cannot read folder {folder_abs_path}: {e}")
                continue

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

                    # Compute normalized_path: POSIX-style relative to library root
                    try:
                        normalized_path = _compute_normalized_path(Path(file_path_str), library_root)
                    except ValueError:
                        warning = f"File outside library root: {file_path_str}"
                        warnings.append(warning)
                        logger.warning(f"[scan_library] {warning}")
                        stats["files_failed"] += 1
                        continue

                    discovered_paths.add(file_path_str)

                    # Check if file exists in DB
                    existing_file = existing_files_dict.get(file_path_str)
                    file_stat = os.stat(file_path_str)
                    modified_time = int(file_stat.st_mtime * 1000)
                    file_size = file_stat.st_size

                    # Note: For quick scans, we already filtered at folder level.
                    # We still process all files in changed folders since folder mtime changed.

                    # Extract metadata + tags (component call)
                    metadata = extract_metadata(library_path, namespace="nom")

                    # Check if file needs tagging
                    existing_version = metadata.get("nom_tags", {}).get("nom_version")
                    tagger_version = metadata.get("nom_tags", {}).get("tagger_version", "unknown")
                    needs_tagging = (
                        existing_file is None or not existing_file.get("tagged") or existing_version != tagger_version
                    )

                    # Prepare batch entry with normalized_path for identity
                    # NOTE: artist/album/title are cache fields derived from entity graph
                    # They will be populated after upsert via seed_song_entities + rebuild_cache
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
                        "scanned_at": now_ms(),
                        "last_seen_scan_id": scan_id,  # Mark as seen in this scan
                    }
                    folder_batch.append(file_entry)

                    # Store metadata for immediate post-upsert entity seeding
                    # Store path as key for looking up file_id after upsert
                    files_metadata[file_path_str] = metadata

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

            # Batch write folder files to DB
            if folder_batch and len(folder_batch) >= batch_size:
                db.library_files.upsert_batch(folder_batch)
                stats["files_added"] += len([f for f in folder_batch if f["path"] not in existing_paths])

                # Immediately seed entities and rebuild caches for upserted files
                _seed_and_rebuild_batch(db, folder_batch, files_metadata)

                folder_batch.clear()

            # Write remaining batch at end of folder
            if folder_batch:
                db.library_files.upsert_batch(folder_batch)
                stats["files_added"] += len([f for f in folder_batch if f["path"] not in existing_paths])

                # Immediately seed entities and rebuild caches for final batch
                _seed_and_rebuild_batch(db, folder_batch, files_metadata)

            # Update folder record after scanning
            db.library_folders.upsert_folder(library_id, folder_rel_path, folder_mtime, len(files))

            # Update progress every folder
            db.libraries.update_scan_status(library_id, progress=current_file)
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
                files_to_remove.sort(key=lambda f: f["_id"])

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
                                    # Match confirmed - update path and re-read metadata
                                    # Preserve: ML tags (chromaprint, calibration, tagged status)
                                    # Update: artist/album/title/genre from new file location
                                    logger.info(f"[scan_library] File moved: {removed_file['path']} → {new_path}")

                                    # Update path and filesystem metadata (preserves ML fields)
                                    db.library_files.update_file_path(
                                        file_id=removed_file["_id"],
                                        new_path=new_path,
                                        file_size=new_file["file_size"],
                                        modified_time=new_file["modified_time"],
                                        duration_seconds=new_duration,
                                    )

                                    # Re-seed entities and rebuild cache from new file's metadata
                                    # This updates artist/album/genre if tags were edited
                                    new_metadata = files_metadata.get(new_path)
                                    if new_metadata:
                                        try:
                                            entity_tags = {
                                                "artist": new_metadata.get("artist"),
                                                "artists": new_metadata.get("artists"),
                                                "album": new_metadata.get("album"),
                                                "label": new_metadata.get("label"),
                                                "genre": new_metadata.get("genre"),
                                                "year": new_metadata.get("year"),
                                            }
                                            seed_song_entities_from_tags(db, removed_file["_id"], entity_tags)
                                            rebuild_song_metadata_cache(db, removed_file["_id"])
                                        except Exception as entity_error:
                                            logger.warning(
                                                f"Failed to update entities for moved file {new_path}: {entity_error}"
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

        # PHASE 5: Mark missing files (ONLY for full scans)
        if is_full_scan:
            logger.info("[scan_library] Full scan complete - marking missing files")
            try:
                missing_count = db.library_files.mark_missing_for_library(library_id, scan_id)
                if missing_count > 0:
                    logger.info(f"[scan_library] Marked {missing_count} missing files as invalid")
                    stats["files_removed"] += missing_count
            except Exception as e:
                logger.error(f"[scan_library] Failed to mark missing files: {e}")
                warnings.append(f"Failed to mark missing files: {str(e)[:100]}")

            # Clean up folder records for deleted folders
            existing_folder_paths = {rel_path for _, rel_path, _, _ in all_folder_data}
            try:
                deleted_folders = db.library_folders.delete_missing_folders(library_id, existing_folder_paths)
                if deleted_folders > 0:
                    logger.info(f"[scan_library] Removed {deleted_folders} deleted folder records")
            except Exception as e:
                logger.warning(f"[scan_library] Failed to clean up folder records: {e}")
        else:
            logger.info("[scan_library] Targeted scan - skipping missing file detection")

        # PHASE 6: Entity graph cleanup after scan
        try:
            from nomarr.workflows.metadata.cleanup_orphaned_entities_wf import cleanup_orphaned_entities_workflow

            cleanup_result = cleanup_orphaned_entities_workflow(db, dry_run=False)
            total_deleted = cleanup_result.get("total_deleted", 0)
            if total_deleted:
                logger.info(f"[scan_library] Entity cleanup removed {total_deleted} orphaned entities")
        except Exception as e:
            logger.warning(f"[scan_library] Entity cleanup failed: {e}")

        # PHASE 7: Finalize scan
        scan_duration = time.time() - start_time

        # Note: For quick scans, files in skipped folders aren't counted in total_files
        # So we only verify count for files we actually attempted to process
        expected = stats["files_added"] + stats["files_updated"] + stats["files_failed"]
        if expected != total_files and force_rescan:
            # Only warn for full scans where we expect all files to be processed
            warning = (
                f"File count mismatch: discovered={total_files}, "
                f"processed={expected} (added={stats['files_added']}, "
                f"updated={stats['files_updated']}, "
                f"failed={stats['files_failed']}). Filesystem may have changed during scan."
            )
            warnings.append(warning)
            logger.warning(f"[scan_library] {warning}")

        # Mark scan complete
        db.libraries.mark_scan_completed(library_id)
        db.libraries.update_scan_status(
            library_id,
            status="complete",
            progress=total_files,
            scan_error=None,
        )

        logger.info(
            f"[scan_library] Scan complete in {scan_duration:.1f}s: "
            f"folders={stats['folders_scanned']}/{stats['folders_scanned'] + stats['folders_skipped']} scanned, "
            f"files: added={stats['files_added']}, updated={stats['files_updated']}, "
            f"moved={stats['files_moved']}, removed={stats['files_removed']}, "
            f"failed={stats['files_failed']}"
        )

        return {
            **stats,
            "scan_duration_s": scan_duration,
            "warnings": warnings,
            "scan_id": scan_id,
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
