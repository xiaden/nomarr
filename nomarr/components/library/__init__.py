"""Library package."""

from .file_sync_comp import (
    find_library_for_file,
    get_library_file,
    mark_file_tagged,
    save_file_tags,
    set_chromaprint,
    upsert_library_file,
)
from .file_tags_comp import get_file_tags_with_path
from .library_root_comp import (
    ensure_no_overlapping_library_root,
    get_base_library_root,
    normalize_library_root,
    resolve_path_within_library,
    validate_library_root,
)
from .metadata_extraction_comp import (
    compute_chromaprint_for_file,
    extract_metadata,
    resolve_artists,
)
from .reconcile_paths_comp import reconcile_library_paths
from .scan_lifecycle_comp import (
    check_interrupted_scan,
    cleanup_stale_folders,
    get_cached_folders,
    mark_scan_completed,
    mark_scan_started,
    remove_deleted_files,
    resolve_library_for_scan,
    save_folder_record,
    snapshot_existing_files,
    update_scan_progress,
    upsert_scanned_files,
)
from .search_files_comp import (
    get_unique_tag_keys,
    get_unique_tag_values,
    search_library_files,
)
from .tag_cleanup_comp import cleanup_orphaned_tags, get_orphaned_tag_count

__all__ = [
    "check_interrupted_scan",
    "cleanup_orphaned_tags",
    "cleanup_stale_folders",
    "compute_chromaprint_for_file",
    "ensure_no_overlapping_library_root",
    "extract_metadata",
    "find_library_for_file",
    "get_base_library_root",
    "get_cached_folders",
    "get_file_tags_with_path",
    "get_library_file",
    "get_orphaned_tag_count",
    "get_unique_tag_keys",
    "get_unique_tag_values",
    "mark_file_tagged",
    "mark_scan_completed",
    "mark_scan_started",
    "normalize_library_root",
    "reconcile_library_paths",
    "remove_deleted_files",
    "resolve_artists",
    "resolve_library_for_scan",
    "resolve_path_within_library",
    "save_file_tags",
    "save_folder_record",
    "search_library_files",
    "set_chromaprint",
    "snapshot_existing_files",
    "update_scan_progress",
    "upsert_library_file",
    "upsert_scanned_files",
    "validate_library_root",
]
