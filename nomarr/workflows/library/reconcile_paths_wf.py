"""Reconcile library paths workflow - validate all library paths against current config."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.library.reconcile_paths_comp import ReconcilePolicy, reconcile_library_paths

if TYPE_CHECKING:
    from nomarr.helpers.dto.library_dto import ReconcileResult
    from nomarr.persistence.db import Database


def reconcile_library_paths_workflow(
    db: Database,
    library_root: str | None,
    policy: ReconcilePolicy = "mark_invalid",
    batch_size: int = 1000,
) -> ReconcileResult:
    """Re-validate all library paths against current configuration.

    This checks all files in library_files table to detect paths that have
    become invalid due to config changes (library root moves, deletions, etc.).
    Useful after modifying library configurations or recovering from filesystem changes.

    Args:
        db: Database instance
        library_root: Library root configuration (must be set)
        policy: What to do with invalid paths:
            - "dry_run": Only report, don't modify database
            - "mark_invalid": Keep files but log warnings (default)
            - "delete_invalid": Remove invalid files from database
        batch_size: Number of files to process per batch (default: 1000)

    Returns:
        ReconcileResult with statistics:
            - total_files: Total files checked
            - valid_files: Files that passed validation
            - invalid_config: Files outside current library roots
            - not_found: Files that don't exist on disk
            - unknown_status: Files with other validation issues
            - deleted_files: Files removed (if policy="delete_invalid")
            - errors: Validation errors

    Raises:
        ValueError: If library_root not configured or invalid policy

    """
    # Validate configuration
    if not library_root:
        msg = "Library root not configured"
        raise ValueError(msg)

    # Validate policy
    valid_policies: set[ReconcilePolicy] = {"dry_run", "mark_invalid", "delete_invalid"}
    if policy not in valid_policies:
        msg = f"Invalid policy '{policy}'. Must be one of: {valid_policies}"
        raise ValueError(msg)

    logging.info(f"[reconcile_paths] Starting reconciliation: policy={policy}, batch_size={batch_size}")

    # Call component to perform reconciliation
    result = reconcile_library_paths(
        db=db,
        policy=policy,
        batch_size=batch_size,
    )

    logging.info(
        f"[reconcile_paths] Reconciliation complete: {result['total_files']} files checked, "
        f"{result['valid_files']} valid, {result['deleted_files']} deleted",
    )

    return result
