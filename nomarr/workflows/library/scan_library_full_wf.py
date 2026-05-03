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
from nomarr.components.library.folder_analysis_comp import discover_library_folders
from nomarr.components.library.library_file_state_comp import transition_file_state
from nomarr.components.library.library_root_comp import validate_library_root
from nomarr.components.library.move_detection_comp import (
    apply_detected_moves,
    detect_file_moves,
)
from nomarr.components.library.scan_lifecycle_comp import (
    cleanup_stale_folders,
    count_library_files,
    get_files_for_folder,
    get_files_for_folders,
    get_folder_rel_paths,
    library_has_tagged_files,
    mark_scan_completed,
    mark_scan_started,
    remove_deleted_files,
    resolve_library_for_scan,
    save_folder_record,
    transition_pipeline_state,
    update_scan_progress,
    upsert_scanned_files,
)
from nomarr.components.library.validate_scan_state_comp import validate_unchanged_files
from nomarr.components.metadata import seed_entities_for_scan_batch
from nomarr.helpers.constants.file_states import (
    STATE_ERRORED,
    STATE_NOT_ERRORED,
    STATE_NOT_SCANNED,
    STATE_SCANNED,
)
from nomarr.helpers.constants.pipeline_states import PIPELINE_IDLE
from nomarr.helpers.time_helper import internal_ms, now_ms
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
    min_duration_s: int | None = None,
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
        min_duration_s: Minimum duration for ML tagging. Files shorter
            than this are marked ``needs_tagging=False`` at scan time.

    Returns:
        Dict with scan statistics (files_discovered, files_added,
        files_updated, files_moved, files_removed, files_failed,
        files_skipped, scan_duration_s, warnings, scan_id)

    Raises:
        ValueError: If library not found
        OSError: If library root is inaccessible

    """
    start_time = internal_ms()
    stats: dict[str, int] = defaultdict(int)
    warnings: list[str] = []
    scan_id = f"{library_id}_{now_ms()}"

    # Step 1 — Resolve library and validate root
    library = resolve_library_for_scan(db, library_id)
    library_root = Path(library["root_path"]).resolve()
    validate_library_root(library_root)
    mark_scan_started(db, library_id, scan_type="full")

    try:
        # Step 2 — Pre-scan DB lookups (no global file snapshot)
        db_folder_paths = get_folder_rel_paths(db, library_id)
        has_tagged_files = library_has_tagged_files(db, library_id)
        file_count = count_library_files(db, library_id)

        # Step 3 — Discover folders on disk
        all_folders = discover_library_folders(library_root, [library_root])
        discovered_folder_paths = {f.rel_path for f in all_folders}

        stats["folders_scanned"] = len(all_folders)
        stats["folders_skipped"] = 0
        stats["files_discovered"] = sum(f.file_count for f in all_folders)
        update_scan_progress(db, library_id, total=file_count or stats["files_discovered"])

        # Step 4 — Seed missing_docs from vanished folders (in DB but absent on disk)
        vanished_folder_paths = db_folder_paths - discovered_folder_paths
        missing_docs_map: dict[str, dict[str, Any]] = {}
        if vanished_folder_paths:
            missing_docs_map.update(
                get_files_for_folders(
                    db,
                    library_id,
                    list(vanished_folder_paths),
                ),
            )

        unmatched_new: list[dict[str, Any]] = []
        unmatched_new_metadata: dict[str, dict[str, Any]] = {}
        unmatched_edge_bootstraps: list[dict[str, Any]] = []
        all_discovered_paths: set[str] = set()
        all_metadata: dict[str, dict[str, Any]] = {}

        # Step 5 — Per-folder scan with incremental move detection
        for folder in all_folders:
            for attempt in range(2):
                try:
                    # Fetch only this folder's files from DB
                    existing_for_folder = get_files_for_folder(
                        db,
                        library_id,
                        folder.rel_path,
                    )
                    batch = scan_folder_files(
                        folder_path=Path(folder.abs_path),
                        folder_rel_path=folder.rel_path,
                        library_root=library_root,
                        library_id=library_id,
                        existing_files=existing_for_folder,
                        tagger_version=tagger_version,
                        db=db,
                        min_duration_s=min_duration_s,
                    )

                    stats["files_updated"] += batch.stats["files_updated"]
                    stats["files_failed"] += batch.stats["files_failed"]
                    stats["files_skipped"] += batch.stats.get("files_skipped", 0)
                    warnings.extend(batch.warnings)
                    all_discovered_paths.update(batch.discovered_paths)
                    all_metadata.update(batch.metadata_map)

                    # Files in DB for this folder that are no longer on disk → could be moves
                    missing_docs_map.update(
                        {path: doc for path, doc in existing_for_folder.items() if path not in batch.discovered_paths}
                    )

                    # Split entries: updated (DB knows them) vs new to this folder
                    updated_entries = [e for e in batch.file_entries if e["path"] in existing_for_folder]
                    new_entries = [e for e in batch.file_entries if e["path"] not in existing_for_folder]

                    # Upsert updated entries immediately
                    if updated_entries:
                        file_ids = upsert_scanned_files(db, updated_entries, batch.edge_bootstraps)
                        transition_file_state(db, file_ids, STATE_NOT_SCANNED, STATE_SCANNED)
                        transition_file_state(db, file_ids, STATE_ERRORED, STATE_NOT_ERRORED)
                        metadata_by_id = {
                            fid: batch.metadata_map[entry["path"]]
                            for fid, entry in zip(file_ids, updated_entries, strict=True)
                            if entry["path"] in batch.metadata_map
                        }
                        seed_entities_for_scan_batch(db, file_ids, metadata_by_id)

                    # Incremental move detection for new entries
                    if has_tagged_files and new_entries:
                        move_result = detect_file_moves(
                            list(missing_docs_map.values()),
                            new_entries,
                            db,
                        )
                        if move_result.moves:
                            apply_detected_moves(
                                move_result.moves,
                                all_metadata,
                                db,
                                library_root,
                            )
                            stats["files_moved"] += move_result.files_moved_count
                            for m in move_result.moves:
                                missing_docs_map.pop(m.old_path, None)
                        matched_new_paths = {m.new_path for m in move_result.moves}
                        folder_unmatched = [e for e in new_entries if e["path"] not in matched_new_paths]
                        unmatched_new.extend(folder_unmatched)
                        unmatched_edge_bootstraps.extend(batch.edge_bootstraps)
                        for e in folder_unmatched:
                            if e["path"] in batch.metadata_map:
                                unmatched_new_metadata[e["path"]] = batch.metadata_map[e["path"]]
                    elif new_entries:
                        # No tagged files — upsert new entries immediately
                        file_ids = upsert_scanned_files(db, new_entries, batch.edge_bootstraps)
                        transition_file_state(db, file_ids, STATE_NOT_SCANNED, STATE_SCANNED)
                        transition_file_state(db, file_ids, STATE_ERRORED, STATE_NOT_ERRORED)
                        stats["files_added"] += len(new_entries)
                        metadata_by_id = {
                            fid: batch.metadata_map[entry["path"]]
                            for fid, entry in zip(file_ids, new_entries, strict=True)
                            if entry["path"] in batch.metadata_map
                        }
                        seed_entities_for_scan_batch(db, file_ids, metadata_by_id)

                    save_folder_record(
                        db,
                        library_id,
                        folder.rel_path,
                        folder.mtime,
                        folder.file_count,
                    )
                    break  # Folder processed successfully

                except Exception as e:
                    if attempt == 0:
                        logger.warning(
                            "Folder %r scan attempt 1 failed, retrying: %s",
                            folder.rel_path,
                            e,
                        )
                    else:
                        logger.error(
                            "Folder %r failed after retry, skipping: %s",
                            folder.rel_path,
                            e,
                        )
                        stats["files_failed"] += folder.file_count
                        warnings.append(f"Folder {folder.rel_path!r} skipped after error: {e}")

            update_scan_progress(db, library_id, progress=len(all_discovered_paths))

        # Step 6 — Final move detection pass for unmatched new files
        truly_new: list[dict[str, Any]] = []
        if unmatched_new and has_tagged_files:
            final_move_result = detect_file_moves(
                list(missing_docs_map.values()),
                unmatched_new,
                db,
            )
            if final_move_result.moves:
                apply_detected_moves(
                    final_move_result.moves,
                    all_metadata,
                    db,
                    library_root,
                )
                stats["files_moved"] += final_move_result.files_moved_count
                for m in final_move_result.moves:
                    missing_docs_map.pop(m.old_path, None)
                moved_new_paths = {m.new_path for m in final_move_result.moves}
                truly_new = [e for e in unmatched_new if e["path"] not in moved_new_paths]
            else:
                truly_new = unmatched_new

        if truly_new:
            file_ids = upsert_scanned_files(db, truly_new, unmatched_edge_bootstraps)
            transition_file_state(db, file_ids, STATE_NOT_SCANNED, STATE_SCANNED)
            transition_file_state(db, file_ids, STATE_ERRORED, STATE_NOT_ERRORED)
            stats["files_added"] += len(truly_new)
            metadata_by_id = {
                fid: unmatched_new_metadata[entry["path"]]
                for fid, entry in zip(file_ids, truly_new, strict=True)
                if entry["path"] in unmatched_new_metadata
            }
            seed_entities_for_scan_batch(db, file_ids, metadata_by_id)

        # Step 7 — Remove truly deleted files
        if missing_docs_map:
            stats["files_removed"] += remove_deleted_files(db, list(missing_docs_map.keys()))

        # Step 8 — Clean up stale folder records
        cleanup_stale_folders(db, library_id, discovered_folder_paths)

        # Step 9 — Entity graph cleanup
        try:
            cleanup_orphaned_entities_workflow(db, dry_run=False)
        except Exception as e:
            logger.warning("Entity cleanup failed: %s", e)

        # Step 9b — Tag graph validation (optional, requires models_dir)
        if models_dir:
            try:
                validation = validate_library_tags_workflow(
                    db,
                    models_dir,
                    library_id=library_id,
                    namespace=namespace,
                    auto_repair=True,
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
                        "Tag validation found %d incomplete files (repaired %d), missing names: %s",
                        validation["incomplete_files"],
                        validation["files_repaired"],
                        validation.get("missing_names_summary", {}),
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

        # Step 9c — Validate scan state for unchanged files (heal short files)
        if min_duration_s is not None:
            try:
                validation_stats = validate_unchanged_files(db, library_id, min_duration_s)
                stats["short_files_healed"] = validation_stats.short_files_healed
            except Exception as e:
                logger.warning("Scan state validation failed: %s", e)

        # Step 10 — Finalize
        scan_duration = internal_ms().value - start_time.value
        mark_scan_completed(db, library_id)
        update_scan_progress(
            db,
            library_id,
            progress=stats["files_discovered"],
            scan_error=None,
        )

        logger.info(
            "Full scan complete in %.1fms: "
            "folders=%d, added=%d, updated=%d, skipped=%d, moved=%d, removed=%d, failed=%d",
            scan_duration,
            stats["folders_scanned"],
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
        update_scan_progress(db, library_id, scan_error=str(e))
        try:
            transition_pipeline_state(db, library_id, PIPELINE_IDLE)
        except Exception:
            logger.exception(
                "Failed to reset pipeline state to IDLE after scan failure for library %s",
                library_id,
            )
        raise
