"""Full library scan workflow.

Walks every folder in the library regardless of cached mtime/file_count.
All files are re-examined for disk-level changes (mtime, size).

Pass 1 of the two-pass scan: fast disk walk → upsert files to DB + seed state edges.
Pass 2 (audio tag extraction + entity seeding) runs in the background tag extraction worker.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nomarr.components.library.file_batch_scanner_comp import scan_folder_files
from nomarr.components.library.folder_analysis_comp import discover_library_folders
from nomarr.components.library.library_file_query_comp import (
    get_files_for_folder,
    get_folder_rel_paths,
)
from nomarr.components.library.library_file_state_comp import transition_file_state
from nomarr.components.library.library_root_comp import validate_library_root
from nomarr.components.library.scan_lifecycle_comp import (
    cleanup_stale_folders,
    count_library_files,
    get_cached_folders,
    mark_scan_completed,
    mark_scan_started,
    remove_deleted_files,
    resolve_library_for_scan,
    save_folder_record,
    transition_pipeline_state,
    update_scan_progress,
    upsert_scanned_files,
)
from nomarr.helpers.constants.file_states import (
    STATE_ERRORED,
    STATE_NOT_ERRORED,
    STATE_NOT_SCANNED,
    STATE_SCANNED,
    STATE_TAGS_EXTRACTED,
    STATE_TAGS_NOT_EXTRACTED,
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
) -> dict[str, Any]:
    """Run a full library scan (ignores folder cache).

    Walks every folder in the library regardless of cached mtime/file_count.
    All files are re-examined for disk-level changes.

    Pass 1: fast disk walk — upsert files to DB, seed initial state edges.
    Pass 2: background tag extraction worker reads audio tags and seeds entities.

    Args:
        db: Database instance
        library_id: Library document ``_id``
        tagger_version: Model suite hash for version comparison
        models_dir: Path to ML models (enables tag validation when provided)
        namespace: Tag namespace (default ``"nom"``)

    Returns:
        Dict with scan statistics (files_discovered, files_added,
        files_updated, files_removed, files_failed,
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
        # Step 2 — Pre-scan DB lookups
        db_folder_paths = get_folder_rel_paths(db, library_id)
        file_count = count_library_files(db, library_id)
        cached_folders = get_cached_folders(db, library_id)

        # Step 3 — Discover folders on disk
        all_folders = discover_library_folders(library_root, [library_root])
        discovered_folder_paths = {f.rel_path for f in all_folders}

        estimated_total = sum(f.file_count for f in all_folders)
        update_scan_progress(db, library_id, total=file_count or estimated_total)

        # Step 4 — Track which folders vanished so their files can be deleted after the loop
        vanished_folder_paths = db_folder_paths - discovered_folder_paths
        all_discovered_paths: set[str] = set()

        # Step 5 — Per-folder scan
        for folder in all_folders:
            stats["folders_scanned"] += 1
            for attempt in range(2):
                try:
                    existing_for_folder = get_files_for_folder(db, library_id, folder.rel_path)
                    batch = scan_folder_files(
                        folder_path=Path(folder.abs_path),
                        folder_rel_path=folder.rel_path,
                        library_root=library_root,
                        library_id=library_id,
                        existing_files=existing_for_folder,
                        tagger_version=tagger_version,
                        db=db,
                    )

                    stats["files_updated"] += batch.stats["files_updated"]
                    stats["files_failed"] += batch.stats["files_failed"]
                    stats["files_skipped"] += batch.stats.get("files_skipped", 0)
                    stats["files_discovered"] += len(batch.discovered_paths)
                    warnings.extend(batch.warnings)
                    all_discovered_paths.update(batch.discovered_paths)

                    # Upsert all discovered files immediately
                    if batch.file_entries:
                        new_paths = batch.discovered_paths - set(existing_for_folder)
                        file_ids = upsert_scanned_files(db, batch.file_entries, batch.edge_bootstraps)
                        transition_file_state(db, file_ids, STATE_NOT_SCANNED, STATE_SCANNED)
                        transition_file_state(db, file_ids, STATE_ERRORED, STATE_NOT_ERRORED)
                        # Reset tags_extracted → tags_not_extracted for modified files
                        # so the tag extraction worker re-extracts their audio tags.
                        # New files already get tags_not_extracted from state bootstrap.
                        modified_file_ids = [
                            fid
                            for fid, e in zip(file_ids, batch.file_entries, strict=True)
                            if e["path"] not in new_paths
                        ]
                        if modified_file_ids:
                            transition_file_state(db, modified_file_ids, STATE_TAGS_EXTRACTED, STATE_TAGS_NOT_EXTRACTED)
                        new_file_ids = [
                            fid for fid, e in zip(file_ids, batch.file_entries, strict=True) if e["path"] in new_paths
                        ]
                        stats["files_added"] += len(new_file_ids)

                    # Files in DB for this folder no longer on disk → delete
                    deleted_paths = [p for p in existing_for_folder if p not in batch.discovered_paths]
                    if deleted_paths:
                        stats["files_removed"] += remove_deleted_files(db, deleted_paths)

                    cached_folder = cached_folders.get(folder.rel_path)
                    save_folder_record(
                        db,
                        library_id,
                        folder.rel_path,
                        folder.mtime,
                        folder.file_count,
                        existing_folder_id=str(cached_folder["_id"]) if cached_folder is not None else None,
                    )
                    break

                except Exception as e:
                    if attempt == 0:
                        logger.debug(
                            "Folder %r failed on first attempt, retrying: %s",
                            folder.rel_path,
                            e,
                            exc_info=True,
                        )
                    else:
                        logger.error("Folder %r failed after retry, skipping: %s", folder.rel_path, e)
                        stats["files_failed"] += folder.file_count
                        warnings.append(f"Folder {folder.rel_path!r} skipped after error: {e}")

            update_scan_progress(db, library_id, progress=len(all_discovered_paths))

        # Step 6 — Delete files from folders that vanished entirely from disk
        for folder_rel_path in vanished_folder_paths:
            vanished_files = get_files_for_folder(db, library_id, folder_rel_path)
            if vanished_files:
                stats["files_removed"] += remove_deleted_files(db, list(vanished_files.keys()))

        # Step 7 — Clean up stale folder records
        cleanup_stale_folders(db, library_id, discovered_folder_paths)

        # Step 9 — Entity graph cleanup
        try:
            cleanup_orphaned_entities_workflow(db, dry_run=False)
        except Exception as e:
            logger.warning("Entity cleanup failed: %s", e, exc_info=True)

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
                logger.warning("Tag validation failed: %s", e, exc_info=True)
                warnings.append(f"Tag validation error: {e}")

        # Step 10 — Finalize
        scan_duration = internal_ms().value - start_time.value
        mark_scan_completed(db, library_id)
        update_scan_progress(
            db,
            library_id,
            progress=stats["files_discovered"],
            total=stats["files_discovered"],
            scan_error=None,
        )

        logger.info(
            "Full scan complete in %.1fms: folders=%d, added=%d, updated=%d, skipped=%d, removed=%d, failed=%d",
            scan_duration,
            stats["folders_scanned"],
            stats["files_added"],
            stats["files_updated"],
            stats["files_skipped"],
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
