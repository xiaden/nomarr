"""Compute unified work status for the system.

Pure domain logic: takes raw data from DB queries, computes scanning status,
processing velocity, and ETA.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from nomarr.helpers.dto.info_dto import LibraryPipelineInfo, ScanningLibraryInfo, WorkStatusResult

if TYPE_CHECKING:
    from nomarr.helpers.dto.library_dto import LibraryDict, LibraryStatsResult


class _LibrarySnapshot(TypedDict):
    """Shape of a library document consumed by ``compute_work_status``."""

    id: int
    name: str
    scan_status: str | None
    scan_progress: int | None
    scan_total: int | None


def compute_work_status(
    libraries: list[LibraryDict],
    stats: LibraryStatsResult,
    recently_tagged_count: int,
    pipeline_states: dict[str, dict[str, str]] | None = None,
    velocity_window_seconds: int = 300,
    library_docs: list[LibraryDict] | None = None,
) -> WorkStatusResult:
    """Compute unified work status from raw data.

    Args:
        libraries: All library domain objects (with scan_status, scan_progress, etc.)
        stats: Aggregated library stats (total_files, needs_tagging_count, etc.)
        recently_tagged_count: Number of files tagged in the velocity window.
        pipeline_states: Per-library pipeline states (``{lib_id: {state_fields}}``).
        velocity_window_seconds: Window size for velocity calculation (default 5 min).
        library_docs: Alternative library docs used for pipeline_libraries building.

    Returns:
        WorkStatusResult DTO with scanning, processing, and velocity info.

    """
    scanning_libraries = [
        ScanningLibraryInfo(
            library_id=lib.id,
            name=lib.name or "Unknown",
            progress=lib.scan_progress or 0,
            total=lib.scan_total or 0,
        )
        for lib in libraries
        if lib.scan_status == "scanning"
        or (
            pipeline_states
            and str(lib.id) in pipeline_states
            and pipeline_states[str(lib.id)].get("scan_state") == "scanning"
        )
    ]
    is_scanning = len(scanning_libraries) > 0

    # Build pipeline libraries
    pipeline_libraries: list[LibraryPipelineInfo] = []
    pipeline_source = library_docs if library_docs is not None else libraries
    pipeline_states = pipeline_states or {}
    for lib in pipeline_source:
        lib_id = lib.id
        lib_state = pipeline_states.get(str(lib_id), {})
        state = _derive_pipeline_state(lib_state)
        pipeline_libraries.append(
            LibraryPipelineInfo(
                library_id=lib_id,
                name=lib.name or "Unknown",
                state=state,
                library_auto_write=bool(lib.library_auto_write),
            )
        )

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


def _derive_pipeline_state(axis_state: dict[str, str]) -> str:
    """Derive a single pipeline state string from axis-level states.

    Maps the four pipeline axes to a unified state label.
    An axis that is in a non-terminal state (not_completed, in_progress)
    means that phase of the pipeline needs work.
    Returns the first incomplete axis found; if all axes are terminal → ``"done"``.
    """
    if not axis_state:
        return "idle"

    # "scanning" is distinct from "scan_ready": an active scan vs. needing one.
    scan_val = axis_state.get("scan_state", "")
    if scan_val == "scanning":
        return "scanning"

    # Map axis field → pipeline label when axis needs work.  These labels are
    # the public states consumed by the frontend, not the raw axis values.
    axis_map: list[tuple[str, str]] = [
        ("scan_state", "scan_ready"),
        ("ml_state", "ml_ready"),
        ("calibration_state", "cal_ready"),
        ("tag_write_state", "write_ready"),
    ]
    active_labels = {
        "not_scanned": "scan_ready",
        "not_ML_processed": "ml_ready",
        "ML_processing": "ml_running",
        "not_calibrated": "awaiting_calibration",
        "calibrating": "calibrating",
        "not_written": "write_ready",
        "writing": "writing",
    }
    terminal_values = {"scanned", "ML_processed", "calibrated", "written", ""}

    for key, label in axis_map:
        val = axis_state.get(key, "")
        if val in active_labels:
            return active_labels[val]
        if val and val not in terminal_values:
            return label

    return "done"
