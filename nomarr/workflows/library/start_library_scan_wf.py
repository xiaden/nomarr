"""Dispatcher workflow for library scanning.

Routes to the appropriate scan workflow based on scan_type. Handles
common pre-scan validation (library exists, not already scanning) and
launches the scan as a background task when a BackgroundTaskService is
available.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from nomarr.components.library.scan_lifecycle_comp import (
    check_interrupted_scan,
    resolve_library_for_scan,
    update_scan_progress,
)
from nomarr.helpers.dto.library_dto import StartScanResult
from nomarr.workflows.library.scan_library_full_wf import scan_library_full_workflow
from nomarr.workflows.library.scan_library_quick_wf import scan_library_quick_workflow

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

_SCAN_WORKFLOWS: dict[str, Any] = {
    "quick": scan_library_quick_workflow,
    "full": scan_library_full_workflow,
}


def start_library_scan_workflow(
    db: Database,
    background_tasks: Any | None,
    tagger_version: str,
    library_id: str,
    scan_type: Literal["quick", "full"] = "quick",
    models_dir: str | None = None,
    namespace: str = "nom",
) -> StartScanResult:
    """Start a library scan, dispatching to the correct workflow.

    1. Validates the library exists and is not already scanning.
    2. Sets ``scan_status`` to ``'scanning'``.
    3. Dispatches to ``scan_library_quick_workflow`` or
       ``scan_library_full_workflow`` via background task (or synchronously).
    4. Returns a :class:`StartScanResult`.

    Args:
        db: Database instance.
        background_tasks: ``BackgroundTaskService`` for async execution,
            or ``None`` for synchronous mode.
        tagger_version: Model-suite hash for version comparison.
        library_id: Library document ``_id``.
        scan_type: ``"quick"`` (incremental, folder-cache aware) or
            ``"full"`` (rescan everything).
        models_dir: Path to ML models directory (enables tag validation
            in full scans when provided).
        namespace: Tag namespace (default ``"nom"``).

    Returns:
        StartScanResult with initial counters and optional task id.

    Raises:
        ValueError: If library not found, already scanning, or
            ``scan_type`` is invalid.

    """
    # --- resolve scan workflow ---
    workflow_fn = _SCAN_WORKFLOWS.get(scan_type)
    if workflow_fn is None:
        msg = f"Invalid scan_type: {scan_type!r}. Must be 'quick' or 'full'."
        raise ValueError(msg)

    # --- validate library ---
    library = resolve_library_for_scan(db, library_id)

    if library.get("scan_status") == "scanning":
        msg = f"Library {library_id} is already being scanned"
        raise ValueError(msg)

    # Check for interrupted scan (log only)
    interrupted, prev_scan_type = check_interrupted_scan(db, library_id)
    if interrupted:
        logger.warning(
            "Detected interrupted %s scan for library %s — continuing with new scan",
            prev_scan_type or "unknown",
            library["name"],
        )

    logger.info(
        "Starting %s scan for library %s (%s)",
        scan_type,
        library_id,
        library["name"],
    )

    # Set scan_status BEFORE background launch so frontend sees it immediately
    update_scan_progress(db, library_id, status="scanning", progress=0, total=0)

    # --- dispatch ---
    # Build extra kwargs for full scans (tag validation)
    extra_kwargs: dict[str, Any] = {}
    if scan_type == "full" and models_dir:
        extra_kwargs["models_dir"] = models_dir
        extra_kwargs["namespace"] = namespace

    if background_tasks:
        task_id = f"scan_library_{library_id}"
        background_tasks.start_task(
            task_id=task_id,
            task_fn=workflow_fn,
            db=db,
            library_id=library_id,
            tagger_version=tagger_version,
            **extra_kwargs,
        )
        logger.info("Scan task launched: %s", task_id)

        return StartScanResult(
            files_discovered=0,
            files_queued=0,
            files_skipped=0,
            files_removed=0,
            job_ids=[task_id],
        )

    # Synchronous fallback (testing / no background service)
    stats = workflow_fn(
        db=db,
        library_id=library_id,
        tagger_version=tagger_version,
        **extra_kwargs,
    )

    return StartScanResult(
        files_discovered=stats.get("files_discovered", 0),
        files_queued=0,
        files_skipped=stats.get("files_skipped", 0),
        files_removed=stats.get("files_removed", 0),
        job_ids=[],
    )
