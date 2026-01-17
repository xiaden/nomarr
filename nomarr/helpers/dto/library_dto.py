"""
DTOs for library-related operations.

Cross-layer data contracts for library service operations (used by services and interfaces).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict


class ReconcileResult(TypedDict):
    """Statistics from library path reconciliation operation."""

    total_files: int
    valid_files: int
    invalid_config: int
    not_found: int
    unknown_status: int
    deleted_files: int
    errors: int


@dataclass
class LibraryScanStatusResult:
    """Result from library_service.get_status."""

    configured: bool
    library_path: str | None
    enabled: bool
    pending_jobs: int  # Legacy (deprecated, always 0)
    running_jobs: int  # Legacy (deprecated, 1 if scanning else 0)
    scan_status: str | None = None  # "idle", "scanning", "complete", "error"
    scan_progress: int | None = None  # Number of files processed
    scan_total: int | None = None  # Total files to process
    scanned_at: int | None = None  # Timestamp (ms) of last scan completion
    scan_error: str | None = None  # Error message if scan_status == "error"


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

    _id: str  # ArangoDB _id (e.g., "libraries/12345")
    _key: str  # ArangoDB _key (e.g., "12345")
    _rev: str  # ArangoDB _rev (revision)
    name: str
    root_path: str
    is_enabled: bool
    is_default: bool
    created_at: str | int  # Can be ISO string or Unix timestamp (ms)
    updated_at: str | int  # Can be ISO string or Unix timestamp (ms)
    scan_status: str | None = None
    scan_progress: int | None = None
    scan_total: int | None = None
    scanned_at: int | None = None
    scan_error: str | None = None


@dataclass
class StartScanResult:
    """Result from library_service.start_scan or start_scan_for_library."""

    files_discovered: int
    files_queued: int
    files_skipped: int
    files_removed: int
    job_ids: list[int] | list[str]  # Can be int (legacy queue IDs) or str (task IDs)


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
    library_id: str | None
    version_tag_key: str  # Key for version tag (e.g., "nomarr_version")
    tagger_version: str  # Current tagger version (e.g., "1.2")


@dataclass
class ScanLibraryWorkflowParams:
    """Parameters for workflows/library/scan_library_wf.py::scan_library_workflow."""

    library_path: str
    namespace: str
    progress_callback: Any  # Callable[[int, int], None] | None
    auto_tag: bool
    ignore_patterns: str  # Comma-separated patterns like "*/Audiobooks/*,*.wav"


@dataclass
@dataclass
class UpdateLibraryFromTagsParams:
    """Parameters for components/library/library_update_comp.py::update_library_from_tags."""

    file_path: str
    metadata: dict[str, Any]
    namespace: str
    tagged_version: str | None
    calibration: dict[str, str] | None = None
    library_id: int | None = None


@dataclass
class FileTag:
    """Single tag for a library file."""

    key: str
    value: str
    type: str
    is_nomarr: bool


@dataclass
class LibraryFileWithTags:
    """Library file with its tags."""

    id: str  # ArangoDB _id
    path: str
    library_id: str  # ArangoDB _id
    file_size: int | None
    modified_time: int | None
    duration_seconds: float | None
    artist: str | None
    album: str | None
    title: str | None
    calibration: str | None
    scanned_at: int | None
    last_tagged_at: int | None
    tagged: int
    tagged_version: str | None
    skip_auto_tag: int
    created_at: str | None
    updated_at: str | None
    tags: list[FileTag]


@dataclass
class SearchFilesResult:
    """Result from library_service.search_files."""

    files: list[LibraryFileWithTags]
    total: int
    limit: int
    offset: int


@dataclass
class UniqueTagKeysResult:
    """Result from library_service.get_unique_tag_keys."""

    tag_keys: list[str]
    count: int
    calibration: dict[str, str] | None
    library_id: int | None


@dataclass
class TagCleanupResult:
    """Result from library_service.cleanup_orphaned_tags."""

    orphaned_count: int
    deleted_count: int


@dataclass
class FileTagsResult:
    """Result from library_service.get_file_tags."""

    file_id: str  # ArangoDB _id
    path: str
    tags: list[FileTag]


__all__ = [
    "FileTag",
    "FileTagsResult",
    "LibraryDict",
    "LibraryFileWithTags",
    "LibraryScanStatusResult",
    "LibraryStatsResult",
    "ScanLibraryWorkflowParams",
    "ScanSingleFileWorkflowParams",
    "SearchFilesResult",
    "StartLibraryScanWorkflowParams",
    "StartScanResult",
    "TagCleanupResult",
    "UniqueTagKeysResult",
    "UpdateLibraryFromTagsParams",
]
