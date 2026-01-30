"""Direct library scan workflow without worker/queue overhead.

Implements fast, read-only metadata extraction. Move detection happens during
ML processing when chromaprint is computed.

Supports targeted/incremental scanning via scan_targets parameter.
Uses folder-level caching for quick scans (skips unchanged folders entirely).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nomarr.components.library.file_batch_scanner_comp import scan_folder_files
from nomarr.components.library.folder_analysis_comp import analyze_folders_for_scan
from nomarr.components.library.move_detection_comp import detect_file_moves
from nomarr.components.library.scan_target_validator_comp import validate_scan_targets
from nomarr.components.metadata import rebuild_song_metadata_cache, seed_song_entities_from_tags
from nomarr.helpers.time_helper import internal_s, now_ms
from nomarr.workflows.metadata.cleanup_orphaned_entities_wf import cleanup_orphaned_entities_workflow

if TYPE_CHECKING:
    from nomarr.helpers.dto import ScanTarget
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def _seed_and_rebuild_batch(db: Database, file_paths: list[str], metadata_map: dict[str, dict[str, Any]]) -> None:
    """Seed entities and rebuild metadata caches for a batch of files.

    Workflow helper for entity seeding after file upsert.

    Args:
        db: Database instance
        file_paths: List of file paths that were just upserted
        metadata_map: Map of file_path -> metadata dict

    """
    for file_path in file_paths:
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


# Exported for tests
def _compute_normalized_path(absolute_path: Path, library_root: Path) -> str:
    """Compute normalized POSIX-style path relative to library root.

    Note: Kept in workflow for test compatibility.
    Component version exists in file_batch_scanner_comp.

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


def scan_library_direct_workflow(
    db: Database,
    library_id: str,
    scan_targets: list[ScanTarget],
    tagger_version: str,
    batch_size: int = 200,
    force_rescan: bool = False,
) -> dict[str, Any]:
    """Scan specific folders within a library.

    Orchestrates component calls for folder analysis, file scanning, and move detection.

    Args:
        db: Database instance
        library_id: Library to scan
        scan_targets: List of folders to scan (empty folder_path = full library)
        tagger_version: Model suite hash for version comparison (determines needs_tagging)
        batch_size: Number of files to accumulate before writing to DB (unused, kept for API compat)
        force_rescan: If True, skip unchanged files detection (rescan all files)

    Returns:
        Dict with scan results (files_discovered, files_added, files_updated, files_moved,
        files_removed, files_failed, scan_duration_s, warnings, scan_id)

    """
    start_time = internal_s()
    stats: dict[str, int] = defaultdict(int)
    warnings: list[str] = []
    scan_id = f"{library_id}_{now_ms()}"

    # Setup
    library = db.libraries.get_library(library_id)
    if not library:
        msg = f"Library {library_id} not found"
        raise ValueError(msg)

    library_root = Path(library["root_path"]).resolve()
    is_full_scan = len(scan_targets) == 1 and scan_targets[0].folder_path == ""

    db.libraries.mark_scan_started(library_id, full_scan=is_full_scan)

    try:
        # PHASE 1: Validate scan targets - COMPONENT CALL
        scan_paths = validate_scan_targets(scan_targets, library_root)

        if not scan_paths:
            msg = "No valid scan paths found in scan_targets"
            raise ValueError(msg)

        # PHASE 2: Analyze folders - COMPONENT CALL
        cached_folders = db.library_folders.get_all_folders_for_library(library_id)
        folder_plan = analyze_folders_for_scan(
            library_root=library_root,
            scan_paths=scan_paths,
            cached_folders=cached_folders,
            force_rescan=force_rescan,
        )

        stats["folders_scanned"] = len(folder_plan.folders_to_scan)
        stats["folders_skipped"] = folder_plan.folders_skipped
        stats["files_discovered"] = folder_plan.total_files_to_scan

        db.libraries.update_scan_status(library_id, total=folder_plan.total_files_to_scan)

        logger.info(
            f"[scan_library] {stats['folders_scanned']}/{len(folder_plan.all_folders)} folders need scanning "
            f"({folder_plan.total_files_to_scan} files)",
        )

        # PHASE 3: Determine if move detection is needed
        has_tagged_files = db.library_files.library_has_tagged_files(library_id)
        enable_move_detection = has_tagged_files

        logger.info(f"[scan_library] Move detection: {'enabled' if enable_move_detection else 'disabled'}")

        # Get existing files for comparison
        existing_files_tuple = db.library_files.list_library_files(limit=1000000, offset=0)
        existing_files = existing_files_tuple[0]
        existing_files_dict = {f["path"]: f for f in existing_files}
        existing_paths = set(existing_files_dict.keys())

        all_discovered_paths: set[str] = set()
        new_file_entries_for_move_detection: list[dict] = []
        all_metadata: dict[str, dict[str, Any]] = {}

        # PHASE 4: Scan files folder-by-folder - ITERATE + COMPONENT CALL
        for folder in folder_plan.folders_to_scan:
            batch_result = scan_folder_files(
                folder_path=Path(folder.abs_path),
                folder_rel_path=folder.rel_path,
                library_root=library_root,
                library_id=library_id,
                existing_files=existing_files_dict,
                tagger_version=tagger_version,
                scan_id=scan_id,
                db=db,
            )

            # Update stats and warnings from batch
            stats["files_updated"] += batch_result.stats["files_updated"]
            stats["files_failed"] += batch_result.stats["files_failed"]
            warnings.extend(batch_result.warnings)
            all_discovered_paths.update(batch_result.discovered_paths)
            all_metadata.update(batch_result.metadata_map)

            # Track new files for move detection
            if enable_move_detection:
                new_entries = [
                    entry for entry in batch_result.file_entries if entry["path"] in batch_result.new_file_paths
                ]
                new_file_entries_for_move_detection.extend(new_entries)

            # UPSERT BATCH TO DB (crash recovery per folder)
            if batch_result.file_entries:
                db.library_files.upsert_batch(batch_result.file_entries)

                # Count new files
                for entry in batch_result.file_entries:
                    if entry["path"] not in existing_paths:
                        stats["files_added"] += 1

                # Seed entities immediately after upsert
                file_paths = [entry["path"] for entry in batch_result.file_entries]
                _seed_and_rebuild_batch(db, file_paths, batch_result.metadata_map)

            # Update folder cache
            db.library_folders.upsert_folder(library_id, folder.rel_path, folder.mtime, folder.file_count)

            # Update progress
            db.libraries.update_scan_status(library_id, progress=len(all_discovered_paths))

        # PHASE 5: Move detection - COMPONENT CALL (if enabled)
        if enable_move_detection:
            missing_paths = existing_paths - all_discovered_paths
            files_to_remove = [existing_files_dict[p] for p in missing_paths]

            move_result = detect_file_moves(
                files_to_remove=files_to_remove,
                new_file_entries=new_file_entries_for_move_detection,
                db=db,
            )

            # Apply moves to DB
            for move in move_result.moves:
                db.library_files.update_file_path(
                    file_id=move.file_id,
                    new_path=move.new_path,
                    file_size=move.new_file_size,
                    modified_time=move.new_modified_time,
                    duration_seconds=move.new_duration,
                )

                # Re-seed entities for moved file
                new_metadata = all_metadata.get(move.new_path)
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
                        seed_song_entities_from_tags(db, move.file_id, entity_tags)
                        rebuild_song_metadata_cache(db, move.file_id)
                    except Exception as entity_error:
                        logger.warning(f"Failed to update entities for moved file {move.new_path}: {entity_error}")

            stats["files_moved"] = move_result.files_moved_count

            # Delete unmatched files (move detection failed or truly deleted)
            unmatched_paths = missing_paths - {move.old_path for move in move_result.moves}
            if unmatched_paths:
                deleted = db.library_files.bulk_delete_files(list(unmatched_paths))
                logger.info(f"[scan_library] Deleted {deleted} files from library")
                stats["files_removed"] += deleted

        # PHASE 6: Delete missing files (ONLY for full scans)
        if is_full_scan:
            logger.info("[scan_library] Full scan complete - deleting missing files")
            try:
                deleted = db.library_files.delete_missing_for_library(library_id, scan_id)
                if deleted > 0:
                    logger.info(f"[scan_library] Deleted {deleted} missing files")
                    stats["files_removed"] += deleted
            except Exception as e:
                logger.exception(f"[scan_library] Failed to delete missing files: {e}")
                warnings.append(f"Failed to delete missing files: {str(e)[:100]}")

            # Clean up folder records for deleted folders
            existing_folder_paths = {f.rel_path for f in folder_plan.all_folders}
            try:
                deleted_folders = db.library_folders.delete_missing_folders(library_id, existing_folder_paths)
                if deleted_folders > 0:
                    logger.info(f"[scan_library] Removed {deleted_folders} deleted folder records")
            except Exception as e:
                logger.warning(f"[scan_library] Failed to clean up folder records: {e}")

        # PHASE 7: Entity graph cleanup
        try:
            cleanup_result = cleanup_orphaned_entities_workflow(db, dry_run=False)
            total_deleted = cleanup_result.get("total_deleted", 0)
            if total_deleted:
                logger.info(f"[scan_library] Entity cleanup removed {total_deleted} orphaned entities")
        except Exception as e:
            logger.warning(f"[scan_library] Entity cleanup failed: {e}")

        # PHASE 8: Finalize scan
        scan_duration = internal_s().value - start_time.value

        db.libraries.mark_scan_completed(library_id)
        db.libraries.update_scan_status(
            library_id,
            status="complete",
            progress=stats["files_discovered"],
            scan_error=None,
        )

        logger.info(
            f"[scan_library] Scan complete in {scan_duration:.1f}s: "
            f"folders={stats['folders_scanned']}/{stats['folders_scanned'] + stats['folders_skipped']} scanned, "
            f"files: added={stats['files_added']}, updated={stats['files_updated']}, "
            f"moved={stats['files_moved']}, removed={stats['files_removed']}, "
            f"failed={stats['files_failed']}",
        )

        return {
            **stats,
            "scan_duration_s": scan_duration,
            "warnings": warnings,
            "scan_id": scan_id,
        }

    except Exception as e:
        logger.error(f"[scan_library] Scan crashed: {e}", exc_info=True)
        db.libraries.update_scan_status(
            library_id,
            status="error",
            scan_error=str(e),
        )
        raise
