"""Compute unified work status for the system.

Pure domain logic: takes raw data from DB queries, computes scanning status,
processing velocity, and ETA.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.info_dto import LibraryPipelineInfo, ScanningLibraryInfo, WorkStatusResult

if TYPE_CHECKING:
    from nomarr.helpers.dto.library_dto import LibraryStatsResult


def compute_work_status(
    libraries: list[dict[str, Any]],
    stats: LibraryStatsResult,
    recently_tagged_count: int,
    pipeline_states: dict[str, dict[str, str]],
    library_docs: list[dict[str, Any]] | None = None,
    velocity_window_seconds: int = 300,
) -> WorkStatusResult:
    """Compute unified work status from raw data.

    Args:
        libraries: All library documents (with scan_status, scan_progress, etc.)
        stats: Aggregated library stats (total_files, needs_tagging_count, etc.)
        recently_tagged_count: Number of files tagged in the velocity window.
        pipeline_states: Library document IDs mapped to per-axis pipeline state dicts.
        library_docs: Library documents used to populate pipeline library metadata.
        velocity_window_seconds: Window size for velocity calculation (default 5 min).

    Returns:
        WorkStatusResult DTO with scanning, processing, and velocity info.

    """
    scanning_libraries = [
        ScanningLibraryInfo(
            library_id=lib["_id"],
            name=lib.get("name", "Unknown"),
            progress=lib.get("scan_progress") or 0,
            total=lib.get("scan_total") or 0,
        )
        for lib in libraries
        if pipeline_states.get(lib["_id"], {}).get("scan_state") == "scanning"
    ]
    is_scanning = len(scanning_libraries) > 0

    pipeline_source_docs = library_docs if library_docs is not None else libraries
    pipeline_libraries = [
        LibraryPipelineInfo(
            library_id=lib["_id"],
            name=lib.get("name", "Unknown"),
            state=_derive_legacy_state(pipeline_states.get(lib["_id"])),
            library_auto_write=bool(lib.get("library_auto_write", False)),
        )
        for lib in pipeline_source_docs
    ]

    pending = stats.needs_tagging_count or 0
    processed = stats.total_files - pending
    is_processing = pending > 0

    window_minutes = velocity_window_seconds / 60
    files_per_minute = round(recently_tagged_count / window_minutes, 1) if window_minutes > 0 else 0.0

    estimated_minutes_remaining: float | None = None
    if pending > 0 and files_per_minute > 0:
        estimated_minutes_remaining = round(pending / files_per_minute, 1)

    return WorkStatusResult(
        is_scanning=is_scanning,
        scanning_libraries=scanning_libraries,
        pipeline_libraries=pipeline_libraries,
        is_processing=is_processing,
        pending_files=pending,
        processed_files=processed,
        total_files=stats.total_files,
        files_per_minute=files_per_minute,
        estimated_minutes_remaining=estimated_minutes_remaining,
        is_busy=is_scanning or is_processing,
    )


def _derive_legacy_state(axis_states: dict[str, str] | None) -> str:
    """Derive a single legacy state string from per-axis states.

    Maps the four-axis model to the old linear state for API compatibility.
    The frontend will eventually migrate to showing per-axis badges.
    """
    if axis_states is None:
        return "idle"

    scan = axis_states.get("scan_state", "not_scanned")
    ml = axis_states.get("ml_state", "not_ML_processed")
    cal = axis_states.get("calibration_state", "not_calibrated")
    tw = axis_states.get("tag_write_state", "not_written")

    if scan == "scanning":
        return "scanning"
    if scan == "not_scanned":
        return "idle"
    if ml == "ML_in_progress":
        return "ml_running"
    if ml == "not_ML_processed":
        return "idle"
    if cal == "calibration_in_progress":
        return "calibrating"
    if cal == "not_calibrated":
        return "awaiting_calibration"
    if tw == "write_in_progress":
        return "writing"
    if tw == "not_written":
        return "write_ready"
    if tw == "written":
        return "done"

    return "idle"
