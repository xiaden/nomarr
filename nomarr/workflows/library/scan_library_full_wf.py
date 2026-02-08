"""Full library scan workflow.

Walks every folder in the library regardless of cached mtime/file_count.
All files are re-examined for metadata changes.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nomarr.components.library.file_batch_scanner_comp import scan_folder_files
from nomarr.components.library.folder_analysis_comp import discover_library_folders, plan_full_scan
from nomarr.components.library.library_root_comp import validate_library_root
from nomarr.components.library.missing_file_detection_comp import detect_missing_files
from nomarr.components.library.move_detection_comp import (
    apply_detected_moves,
    detect_file_moves,
)
from nomarr.components.library.scan_lifecycle_comp import (
    cleanup_stale_folders,
    mark_scan_completed,
    mark_scan_started,
    remove_deleted_files,
    resolve_library_for_scan,
    save_folder_record,
    snapshot_existing_files,
    update_scan_progress,
    upsert_scanned_files,
)
from nomarr.components.metadata import seed_entities_for_scan_batch
from nomarr.helpers.time_helper import internal_s, now_ms
from nomarr.workflows.metadata.cleanup_orphaned_entities_wf import cleanup_orphaned_entities_workflow

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def scan_library_full_workflow(
    db: Database,
    library_id: str,
    tagger_version: str,
) -> dict[str, Any]:
    """Run a full library scan (ignores folder cache).

    Walks every folder in the library regardless of cached mtime/file_count.
    All files are re-examined for metadata changes.

    Args:
        db: Database instance
        library_id: Library document ``_id``
        tagger_version: Model suite hash for version comparison

    Returns:
        Dict with scan statistics (files_discovered, files_added,
        files_updated, files_moved, files_removed, files_failed,
        scan_duration_s, warnings, scan_id)

    Raises:
        ValueError: If library not found
        OSError: If library root is inaccessible

    """
    start_time = internal_s()
    stats: dict[str, int] = defaultdict(int)
    warnings: list[str] = []
    scan_id = f"{library_id}_{now_ms()}"

    # Step 1 — Resolve library and validate root
    library = resolve_library_for_scan(db, library_id)
    library_root = Path(library["root_path"]).resolve()
    validate_library_root(library_root)
    mark_scan_started(db, library_id, scan_type="full")

    try:
        # Step 2 — Discover folders, then plan full scan (no cache)
        all_folders = discover_library_folders(library_root, [library_root])
        folder_plan = plan_full_scan(all_folders)
        stats["folders_scanned"] = len(folder_plan.folders_to_scan)
        stats["folders_skipped"] = folder_plan.folders_skipped
        stats["files_discovered"] = folder_plan.total_files_to_scan
        update_scan_progress(db, library_id, total=folder_plan.total_files_to_scan)

        # Step 3 — Snapshot existing files for comparison
        existing_files_dict, has_tagged_files = snapshot_existing_files(db, library_id)

        all_discovered_paths: set[str] = set()
        new_file_entries_for_move_detection: list[dict[str, Any]] = []
        all_metadata: dict[str, dict[str, Any]] = {}

        # Step 4 — Scan files folder-by-folder, upsert + seed entities
        for folder in folder_plan.folders_to_scan:
            batch = scan_folder_files(
                folder_path=Path(folder.abs_path),
                folder_rel_path=folder.rel_path,
                library_root=library_root,
                library_id=library_id,
                existing_files=existing_files_dict,
                tagger_version=tagger_version,
                db=db,
            )

            stats["files_updated"] += batch.stats["files_updated"]
            stats["files_failed"] += batch.stats["files_failed"]
            warnings.extend(batch.warnings)
            all_discovered_paths.update(batch.discovered_paths)
            all_metadata.update(batch.metadata_map)

            if has_tagged_files:
                new_file_entries_for_move_detection.extend(
                    e for e in batch.file_entries if e["path"] in batch.new_file_paths
                )

            if batch.file_entries:
                upsert_scanned_files(db, batch.file_entries)
                stats["files_added"] += sum(
                    1 for e in batch.file_entries if e["path"] not in existing_files_dict
                )
                seed_entities_for_scan_batch(
                    db,
                    [e["path"] for e in batch.file_entries],
                    batch.metadata_map,
                )

            save_folder_record(
                db, library_id, folder.rel_path, folder.mtime, folder.file_count,
            )
            update_scan_progress(db, library_id, progress=len(all_discovered_paths))

        # Step 5 — Detect missing files (folder-aware)
        scanned_folder_paths = {f.abs_path for f in folder_plan.folders_to_scan}
        all_on_disk_folder_paths = {f.abs_path for f in folder_plan.all_folders}

        missing_paths = detect_missing_files(
            existing_files=existing_files_dict,
            discovered_paths=all_discovered_paths,
            scanned_folder_paths=scanned_folder_paths,
            all_on_disk_folder_paths=all_on_disk_folder_paths,
        )

        # Step 6 — Move detection + delete unmatched
        if missing_paths:
            files_to_remove = [existing_files_dict[p] for p in missing_paths]

            if has_tagged_files:
                move_result = detect_file_moves(files_to_remove, new_file_entries_for_move_detection, db)
                stats["files_moved"] = move_result.files_moved_count
                apply_detected_moves(move_result.moves, all_metadata, db)
                unmatched = missing_paths - {m.old_path for m in move_result.moves}
            else:
                unmatched = missing_paths

            if unmatched:
                stats["files_removed"] += remove_deleted_files(db, list(unmatched))

        # Step 7 — Clean up stale folder records
        existing_folder_rel_paths = {f.rel_path for f in folder_plan.all_folders}
        cleanup_stale_folders(db, library_id, existing_folder_rel_paths)

        # Step 8 — Entity graph cleanup
        try:
            cleanup_orphaned_entities_workflow(db, dry_run=False)
        except Exception as e:
            logger.warning("Entity cleanup failed: %s", e)

        # Step 9 — Finalize
        scan_duration = internal_s().value - start_time.value
        mark_scan_completed(db, library_id)
        update_scan_progress(
            db, library_id, status="complete", progress=stats["files_discovered"], scan_error=None,
        )

        logger.info(
            "Full scan complete in %.1fs: folders=%d/%d, added=%d, updated=%d, moved=%d, removed=%d, failed=%d",
            scan_duration,
            stats["folders_scanned"],
            stats["folders_scanned"] + stats["folders_skipped"],
            stats["files_added"],
            stats["files_updated"],
            stats["files_moved"],
            stats["files_removed"],
            stats["files_failed"],
        )

        return {**stats, "scan_duration_s": scan_duration, "warnings": warnings, "scan_id": scan_id}

    except Exception as e:
        logger.error("Full scan crashed: %s", e, exc_info=True)
        update_scan_progress(db, library_id, status="error", scan_error=str(e))
        raise
