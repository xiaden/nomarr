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
from nomarr.workflows.library.validate_library_tags_wf import validate_library_tags_workflow
from nomarr.workflows.metadata.cleanup_orphaned_entities_wf import cleanup_orphaned_entities_workflow

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def scan_library_full_workflow(
    db: Database,
    library_id: str,
    tagger_version: str,
    models_dir: str | None = None,
    namespace: str = "nom",
) -> dict[str, Any]:
    """Run a full library scan (ignores folder cache).

    Walks every folder in the library regardless of cached mtime/file_count.
    All files are re-examined for metadata changes.

    Args:
        db: Database instance
        library_id: Library document ``_id``
        tagger_version: Model suite hash for version comparison
        models_dir: Path to ML models (enables tag validation when provided)
        namespace: Tag namespace (default ``"nom"``)

    Returns:
        Dict with scan statistics (files_discovered, files_added,
        files_updated, files_moved, files_removed, files_failed,
        files_skipped, scan_duration_s, warnings, scan_id)

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
        deferred_new_entries: list[dict[str, Any]] = []
        deferred_new_metadata: dict[str, dict[str, Any]] = {}
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
            stats["files_skipped"] += batch.stats.get("files_skipped", 0)
            warnings.extend(batch.warnings)
            all_discovered_paths.update(batch.discovered_paths)
            all_metadata.update(batch.metadata_map)

            # Split into updated (existing path) vs new entries
            updated_entries = [
                e for e in batch.file_entries if e["path"] in existing_files_dict
            ]
            new_entries = [
                e for e in batch.file_entries if e["path"] not in existing_files_dict
            ]

            # Defer new entries for move detection (if library has chromaprints)
            if has_tagged_files and new_entries:
                deferred_new_entries.extend(new_entries)
                for e in new_entries:
                    if e["path"] in batch.metadata_map:
                        deferred_new_metadata[e["path"]] = batch.metadata_map[e["path"]]

            # Upsert only updated entries immediately (new entries deferred)
            if updated_entries:
                file_ids = upsert_scanned_files(db, updated_entries)
                # Build metadata map keyed by file_id
                metadata_by_id = {
                    file_id: batch.metadata_map[entry["path"]]
                    for file_id, entry in zip(file_ids, updated_entries, strict=True)
                    if entry["path"] in batch.metadata_map
                }
                seed_entities_for_scan_batch(db, file_ids, metadata_by_id)

            # If no tagged files, upsert new entries immediately (no move detection)
            if not has_tagged_files and new_entries:
                file_ids = upsert_scanned_files(db, new_entries)
                stats["files_added"] += len(new_entries)
                metadata_by_id = {
                    file_id: batch.metadata_map[entry["path"]]
                    for file_id, entry in zip(file_ids, new_entries, strict=True)
                    if entry["path"] in batch.metadata_map
                }
                seed_entities_for_scan_batch(db, file_ids, metadata_by_id)

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

        # Step 6 — Move detection + upsert remaining new files + delete unmatched missing
        moved_new_paths: set[str] = set()
        if missing_paths and has_tagged_files:
            files_to_remove = [existing_files_dict[p] for p in missing_paths]
            move_result = detect_file_moves(files_to_remove, deferred_new_entries, db)
            stats["files_moved"] = move_result.files_moved_count
            apply_detected_moves(move_result.moves, all_metadata, db, library_root)
            moved_new_paths = {m.new_path for m in move_result.moves}
            unmatched = missing_paths - {m.old_path for m in move_result.moves}
            if unmatched:
                stats["files_removed"] += remove_deleted_files(db, list(unmatched))
        elif missing_paths:
            # No tagged files - just remove missing
            stats["files_removed"] += remove_deleted_files(db, list(missing_paths))

        # Upsert remaining deferred new entries (not consumed by move detection)
        if has_tagged_files and deferred_new_entries:
            remaining_new_entries = [
                e for e in deferred_new_entries if e["path"] not in moved_new_paths
            ]
            if remaining_new_entries:
                file_ids = upsert_scanned_files(db, remaining_new_entries)
                stats["files_added"] += len(remaining_new_entries)
                metadata_by_id = {
                    file_id: deferred_new_metadata[entry["path"]]
                    for file_id, entry in zip(file_ids, remaining_new_entries, strict=True)
                    if entry["path"] in deferred_new_metadata
                }
                seed_entities_for_scan_batch(db, file_ids, metadata_by_id)

        # Step 7 — Clean up stale folder records
        existing_folder_rel_paths = {f.rel_path for f in folder_plan.all_folders}
        cleanup_stale_folders(db, library_id, existing_folder_rel_paths)

        # Step 8 — Entity graph cleanup
        try:
            cleanup_orphaned_entities_workflow(db, dry_run=False)
        except Exception as e:
            logger.warning("Entity cleanup failed: %s", e)

        # Step 8b — Tag graph validation (optional, requires models_dir)
        if models_dir:
            try:
                validation = validate_library_tags_workflow(
                    db, models_dir, library_id=library_id, namespace=namespace, auto_repair=True,
                )
                stats["validation_checked"] = validation["files_checked"]
                stats["validation_incomplete"] = validation["incomplete_files"]
                stats["validation_repaired"] = validation["files_repaired"]
                if validation["incomplete_files"]:
                    warnings.append(
                        f"Tag validation: {validation['incomplete_files']}/{validation['files_checked']} "
                        f"files incomplete ({validation['files_repaired']} auto-repaired)"
                    )
                    logger.warning(
                        "Tag validation found %d incomplete files (repaired %d), missing rels: %s",
                        validation["incomplete_files"],
                        validation["files_repaired"],
                        validation.get("missing_rels_summary", {}),
                    )
                else:
                    logger.info(
                        "Tag validation: all %d files complete (%d heads)",
                        validation["files_checked"],
                        validation["expected_heads"],
                    )
            except Exception as e:
                logger.warning("Tag validation failed: %s", e)
                warnings.append(f"Tag validation error: {e}")

        # Step 9 — Finalize
        scan_duration = internal_s().value - start_time.value
        mark_scan_completed(db, library_id)
        update_scan_progress(
            db, library_id, status="complete", progress=stats["files_discovered"], scan_error=None,
        )

        logger.info(
            "Full scan complete in %.1fs: folders=%d/%d, added=%d, updated=%d, skipped=%d, moved=%d, removed=%d, failed=%d",
            scan_duration,
            stats["folders_scanned"],
            stats["folders_scanned"] + stats["folders_skipped"],
            stats["files_added"],
            stats["files_updated"],
            stats["files_skipped"],
            stats["files_moved"],
            stats["files_removed"],
            stats["files_failed"],
        )

        return {**stats, "scan_duration_s": scan_duration, "warnings": warnings, "scan_id": scan_id}

    except Exception as e:
        logger.error("Full scan crashed: %s", e, exc_info=True)
        update_scan_progress(db, library_id, status="error", scan_error=str(e))
        raise
