"""
DTOs for library-related operations.

Cross-layer data contracts for library service operations (used by services and interfaces).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class LibraryScanStatusResult:
    """Result from library_service.get_status."""

    configured: bool
    library_path: str | None
    enabled: bool
    pending_jobs: int
    running_jobs: int


@dataclass
class ScanJobResult:
    """Single scan job from library_service.get_scan_history."""

    id: int
    path: str
    status: str
    force: bool
    started_at: str | None
    completed_at: str | None
    error_message: str | None


@dataclass
class LibraryStatsResult:
    """Result from library_service.get_library_stats."""

    total_files: int
    total_artists: int
    total_albums: int
    total_duration: float | None
    total_size: int | None


@dataclass
class LibraryDict:
    """Single library record from library_service.list_libraries or get_library."""

    id: int
    name: str
    root_path: str
    is_enabled: bool
    is_default: bool
    created_at: str
    updated_at: str


@dataclass
class StartScanResult:
    """Result from library_service.start_scan or start_scan_for_library."""

    files_discovered: int
    files_queued: int
    files_skipped: int
    files_removed: int
    job_ids: list[int]


@dataclass
class RecalibrateFileWorkflowParams:
    """Parameters for workflows/calibration/recalibrate_file_wf.py::recalibrate_file_workflow."""

    file_path: str
    models_dir: str
    namespace: str
    version_tag_key: str
    calibrate_heads: bool


@dataclass
class StartLibraryScanWorkflowParams:
    """Parameters for workflows/library/start_library_scan_wf.py::start_library_scan_workflow."""

    root_paths: list[str]
    recursive: bool
    force: bool
    auto_tag: bool
    ignore_patterns: str  # Comma-separated patterns like "*/Audiobooks/*,*.wav"
    clean_missing: bool


@dataclass
class ScanSingleFileWorkflowParams:
    """Parameters for workflows/library/scan_single_file_wf.py::scan_single_file_workflow."""

    file_path: str
    namespace: str
    force: bool
    auto_tag: bool
    ignore_patterns: str  # Comma-separated patterns like "*/Audiobooks/*,*.wav"
    library_id: int | None


@dataclass
class ScanLibraryWorkflowParams:
    """Parameters for workflows/library/scan_library_wf.py::scan_library_workflow."""

    library_path: str
    namespace: str
    progress_callback: Any  # Callable[[int, int], None] | None
    auto_tag: bool
    ignore_patterns: str  # Comma-separated patterns like "*/Audiobooks/*,*.wav"


@dataclass
class UpdateLibraryFileFromTagsParams:
    """Parameters for workflows/library/scan_library_wf.py::update_library_file_from_tags."""

    file_path: str
    namespace: str
    tagged_version: str | None
    calibration: dict[str, str] | None
    library_id: int | None


__all__ = [
    "LibraryDict",
    "LibraryScanStatusResult",
    "LibraryStatsResult",
    "RecalibrateFileWorkflowParams",
    "ScanJobResult",
    "ScanLibraryWorkflowParams",
    "ScanSingleFileWorkflowParams",
    "StartLibraryScanWorkflowParams",
    "StartScanResult",
    "UpdateLibraryFileFromTagsParams",
]
