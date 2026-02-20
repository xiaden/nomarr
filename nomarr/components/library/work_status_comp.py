"""Compute unified work status for the system.

Pure domain logic: takes raw data from DB queries, computes scanning status,
processing velocity, and ETA.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.info_dto import ScanningLibraryInfo, WorkStatusResult

if TYPE_CHECKING:
    from nomarr.helpers.dto.library_dto import LibraryStatsResult


def compute_work_status(
    libraries: list[dict[str, Any]],
    stats: LibraryStatsResult,
    recently_tagged_count: int,
    velocity_window_seconds: int = 300,
) -> WorkStatusResult:
    """Compute unified work status from raw data.

    Args:
        libraries: All library documents (with scan_status, scan_progress, etc.)
        stats: Aggregated library stats (total_files, needs_tagging_count, etc.)
        recently_tagged_count: Number of files tagged in the velocity window.
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
        if lib.get("scan_status") == "scanning"
    ]
    is_scanning = len(scanning_libraries) > 0

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
        is_processing=is_processing,
        pending_files=pending,
        processed_files=processed,
        total_files=stats.total_files,
        files_per_minute=files_per_minute,
        estimated_minutes_remaining=estimated_minutes_remaining,
        is_busy=is_scanning or is_processing,
    )
