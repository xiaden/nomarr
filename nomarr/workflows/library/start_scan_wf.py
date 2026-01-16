"""
Workflow for starting library scans (orchestration layer).

This workflow handles the orchestration of scan initialization:
- Resolves library (by ID or default)
- Validates scan paths within library root
- Launches background scan task OR runs synchronously
- Calls scan_library_direct_workflow for actual scanning

Architecture:
- Pure workflow: takes all dependencies as parameters
- Does NOT import services/DI container
- Callers (typically services) provide Database, config, and BackgroundTaskService
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_root_comp import resolve_path_within_library
from nomarr.helpers.dto.library_dto import StartScanResult

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def start_scan_workflow(
    db: Database,
    background_tasks: Any | None,
    library_id: str | None = None,
    paths: list[str] | None = None,
    recursive: bool = True,
    clean_missing: bool = True,
) -> StartScanResult:
    """
    Start a library scan workflow.

    This orchestrates scan initialization:
    1. Resolves library (by ID or default)
    2. Validates scan paths are within library root
    3. Launches background task or runs synchronously
    4. Returns scan result DTO

    IMPORTANT: Libraries determine which roots to scan.
    All discovered files are GLOBAL (no library_id in library_files table).

    Args:
        db: Database instance
        background_tasks: BackgroundTaskService for async execution (or None for sync)
        library_id: Library to scan (None = use default library)
        paths: Paths to scan within library (None = scan entire library root)
        recursive: Scan subdirectories recursively
        clean_missing: Detect moved files and mark missing files invalid

    Returns:
        StartScanResult DTO with scan statistics and task_id

    Raises:
        ValueError: If library not found, scan already running, or paths invalid
    """
    # Resolve library_id
    if library_id is None:
        # Use default library
        library = db.libraries.get_default_library()
        if not library:
            # Try to create default library
            logger.info("[start_scan_workflow] No default library found, creating one may be needed")
            raise ValueError("No default library exists. Create a library first or configure library_root.")
        library_id = library["id"]
    else:
        # Validate specified library exists
        library = db.libraries.get_library(library_id)
        if not library:
            raise ValueError(f"Library not found: {library_id}")

    # Check if scan already running
    scan_status = library.get("scan_status")
    if scan_status == "scanning":
        raise ValueError(f"Library {library_id} is already being scanned")

    base_root = Path(library["root_path"])

    # Build scan paths for scanning
    # Libraries control which roots to scan, but the workflow operates globally
    if paths is None:
        # Scan entire library root
        scan_paths = [str(base_root)]
    else:
        # Validate each user path is within library root
        scan_paths = []
        for user_path in paths:
            resolved = resolve_path_within_library(
                library_root=str(base_root),
                user_path=user_path,
                must_exist=True,
                must_be_file=False,
            )
            scan_paths.append(str(resolved))

    from nomarr.workflows.library.scan_library_direct_wf import scan_library_direct_workflow

    logger.info(
        f"[start_scan_workflow] Starting scan for library {library_id} "
        f"({library['name']}) with {len(scan_paths)} path(s)"
    )

    # Launch background scan task if BackgroundTaskService available
    if background_tasks:
        task_id = f"scan_library_{library_id}"
        background_tasks.start_task(
            task_id=task_id,
            task_fn=scan_library_direct_workflow,
            db=db,
            library_id=library_id,
            paths=scan_paths,
            recursive=recursive,
            clean_missing=clean_missing,
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
            paths=scan_paths,
            recursive=recursive,
            clean_missing=clean_missing,
        )

        return StartScanResult(
            files_discovered=stats["files_discovered"],
            files_queued=0,  # Legacy field
            files_skipped=stats["files_skipped"],
            files_removed=stats["files_removed"],
            job_ids=[],  # No background task
        )
