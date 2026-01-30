"""Component for reconciling library paths after configuration changes.

This component re-validates all paths in the library_files table against
the current library configuration. It detects paths that have become invalid
due to config changes (library root moves, library deletions, etc.).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from nomarr.components.infrastructure.path_comp import build_library_path_from_db

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.helpers.dto.library_dto import ReconcileResult
    from nomarr.helpers.dto.path_dto import LibraryPath
    from nomarr.persistence.db import Database
ReconcilePolicy = Literal["mark_invalid", "delete_invalid", "dry_run"]

def reconcile_library_paths(db: Database, policy: ReconcilePolicy="mark_invalid", batch_size: int=1000) -> ReconcileResult:
    """Re-validate all library paths against current configuration.

    This component scans the library_files table and re-validates each path
    using build_library_path_from_db() to check against current config.
    Useful after library root changes or library deletions.

    Args:
        db: Database instance
        policy: What to do with invalid paths:
            - "dry_run": Only report, don't modify database
            - "mark_invalid": Keep files but log warnings
            - "delete_invalid": Remove invalid files from database
        batch_size: Number of files to process per batch (default: 1000)

    Returns:
        ReconcileResult with counts of valid/invalid files

    Example:
        # After changing library root in config
        from nomarr.components.library import reconcile_library_paths

        result = reconcile_library_paths(
            db=db,
            policy="delete_invalid",
            batch_size=500
        )
        print(f"Cleaned up {result['deleted_files']} invalid files")

    """
    logger.info(f"[reconcile_library_paths] Starting reconciliation with policy={policy}")
    result: ReconcileResult = {"total_files": 0, "valid_files": 0, "invalid_config": 0, "not_found": 0, "unknown_status": 0, "deleted_files": 0, "errors": 0}
    stats = db.library_files.get_library_stats()
    total_count = stats.get("total_files", 0)
    logger.info(f"[reconcile_library_paths] Found {total_count} files to validate")
    offset = 0
    while True:
        files, _ = db.library_files.list_library_files(limit=batch_size, offset=offset)
        if not files:
            break
        logger.debug(f"[reconcile_library_paths] Processing batch at offset {offset} ({len(files)} files)")
        for file_record in files:
            result["total_files"] += 1
            file_path = file_record["path"]
            library_id = file_record.get("library_id")
            try:
                library_path = build_library_path_from_db(stored_path=file_path, db=db, library_id=library_id, check_disk=True)
                if library_path.is_valid():
                    result["valid_files"] += 1
                elif library_path.status == "invalid_config":
                    result["invalid_config"] += 1
                    _handle_invalid_path(db, file_path, library_path, policy, result)
                elif library_path.status == "not_found":
                    result["not_found"] += 1
                    _handle_invalid_path(db, file_path, library_path, policy, result)
                elif library_path.status == "unknown":
                    result["unknown_status"] += 1
                    logger.warning(f"[reconcile_library_paths] Unknown status for {file_path}: {library_path.reason}")
            except Exception as e:
                result["errors"] += 1
                logger.exception(f"[reconcile_library_paths] Error validating {file_path}: {e}")
        offset += len(files)
        if offset % (batch_size * 5) == 0:
            logger.info(f"[reconcile_library_paths] Progress: {offset}/{total_count} (valid={result['valid_files']}, invalid={result['invalid_config'] + result['not_found']})")
    total_invalid = result["invalid_config"] + result["not_found"]
    logger.info(f"[reconcile_library_paths] Reconciliation complete: total={result['total_files']}, valid={result['valid_files']}, invalid_config={result['invalid_config']}, not_found={result['not_found']}, deleted={result['deleted_files']}, errors={result['errors']}")
    if policy == "dry_run":
        logger.info(f"[reconcile_library_paths] DRY RUN: Would have affected {total_invalid} files (use policy='delete_invalid' to actually remove them)")
    return result

def _handle_invalid_path(db: Database, file_path: str, library_path: LibraryPath, policy: ReconcilePolicy, result: ReconcileResult) -> None:
    """Handle an invalid path based on policy.

    Args:
        db: Database instance
        file_path: Absolute path from database
        library_path: Re-validated LibraryPath with status
        policy: Reconciliation policy
        result: Result dict to update

    """
    reason = library_path.reason or "unknown"
    status = library_path.status
    if policy == "dry_run":
        logger.info(f"[reconcile_library_paths] DRY RUN: Would handle {status} path: {file_path} ({reason})")
    elif policy == "mark_invalid":
        logger.warning(f"[reconcile_library_paths] Invalid path ({status}): {file_path} - {reason}")
    elif policy == "delete_invalid":
        try:
            db.library_files.delete_library_file(file_path)
            result["deleted_files"] += 1
            logger.info(f"[reconcile_library_paths] Deleted invalid path ({status}): {file_path} - {reason}")
        except Exception as e:
            logger.exception(f"[reconcile_library_paths] Failed to delete {file_path}: {e}")
            result["errors"] += 1
