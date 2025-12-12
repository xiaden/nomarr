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
    created_at: str | int  # Can be ISO string or Unix timestamp (ms)
    updated_at: str | int  # Can be ISO string or Unix timestamp (ms)


@dataclass
class StartScanResult:
    """Result from library_service.start_scan or start_scan_for_library."""

    files_discovered: int
    files_queued: int
    files_skipped: int
    files_removed: int
    job_ids: list[int]


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

    id: int
    path: str
    library_id: int
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

    file_id: int
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
