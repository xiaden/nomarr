"""
Workflow for starting library scans (orchestration layer).

This workflow handles the orchestration of scan initialization:
- Resolves library (by ID or default)
- Constructs ScanTarget list (defaults to full library scan)
- Launches background scan task OR runs synchronously
- Calls scan_library_direct_workflow for actual scanning

Architecture:
- Pure workflow: takes all dependencies as parameters
- Does NOT import services/DI container
- Callers (typically services) provide Database, config, and BackgroundTaskService
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto import ScanTarget
from nomarr.helpers.dto.library_dto import StartScanResult

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def start_scan_workflow(
    db: Database,
    background_tasks: Any | None,
    library_id: str | None = None,
    scan_targets: list[ScanTarget] | None = None,
    batch_size: int = 200,
    force_rescan: bool = False,
) -> StartScanResult:
    """
    Start a library scan workflow.

    Supports both full library scans and targeted/incremental scans.

    This orchestrates scan initialization:
    1. Resolves library (by ID or default)
    2. Constructs scan_targets if not provided (defaults to full scan)
    3. Launches background task or runs synchronously
    4. Returns scan result DTO

    IMPORTANT: Libraries determine which roots to scan.
    Files are stored with (library_id, normalized_path) identity.

    Args:
        db: Database instance
        background_tasks: BackgroundTaskService for async execution (or None for sync)
        library_id: Library to scan (None = use default library)
        scan_targets: List of folders to scan (None = full library scan)
        batch_size: Number of files to accumulate before DB write (default 200)
        force_rescan: If True, skip unchanged files detection (rescan all files)

    Returns:
        StartScanResult DTO with scan statistics and task_id

    Raises:
        ValueError: If library not found or scan already running
    """
    # Resolve library_id
    if library_id is None:
        # Use default library
        library = db.libraries.get_default_library()
        if not library:
            # Try to create default library
            logger.info("[start_scan_workflow] No default library found, creating one may be needed")
            raise ValueError("No default library exists. Create a library first or configure library_root.")
        library_id = library["_id"]
    else:
        # Validate specified library exists
        library = db.libraries.get_library(library_id)
        if not library:
            raise ValueError(f"Library not found: {library_id}")

    # Check if scan already running
    scan_status = library.get("scan_status")
    if scan_status == "scanning":
        raise ValueError(f"Library {library_id} is already being scanned")

    # Construct scan_targets if not provided (default to full library scan)
    if not scan_targets:
        scan_targets = [ScanTarget(library_id=library_id, folder_path="")]
        logger.info("[start_scan_workflow] No scan_targets provided - defaulting to full library scan")

    # Check for interrupted scan
    interrupted, was_full = db.libraries.check_interrupted_scan(library_id)
    if interrupted:
        logger.warning(
            f"[start_scan_workflow] Detected interrupted {'full' if was_full else 'targeted'} scan "
            f"for library {library['name']} - continuing with new scan"
        )

    from nomarr.workflows.library.scan_library_direct_wf import scan_library_direct_workflow

    logger.info(
        f"[start_scan_workflow] Starting scan for library {library_id} ({library['name']}) "
        f"with {len(scan_targets)} target(s)"
    )

    # Launch background scan task if BackgroundTaskService available
    if background_tasks:
        task_id = f"scan_library_{library_id}"
        background_tasks.start_task(
            task_id=task_id,
            task_fn=scan_library_direct_workflow,
            db=db,
            library_id=library_id,
            scan_targets=scan_targets,
            batch_size=batch_size,
            force_rescan=force_rescan,
        )

        logger.info(f"[start_scan_workflow] Scan task launched: {task_id}")

        return StartScanResult(
            files_discovered=0,  # Will be updated by workflow
            files_queued=0,  # Legacy field (no queue anymore)
            files_skipped=0,
            files_removed=0,
            job_ids=[task_id] if task_id else [],  # Task ID is str
        )
    else:
        # Synchronous execution (for testing or no background service)
        stats = scan_library_direct_workflow(
            db=db,
            library_id=library_id,
            scan_targets=scan_targets,
            batch_size=batch_size,
            force_rescan=force_rescan,
        )

        return StartScanResult(
            files_discovered=stats["files_discovered"],
            files_queued=0,  # Legacy field
            files_skipped=stats["files_skipped"],
            files_removed=stats["files_removed"],
            job_ids=[],  # No background task
        )
