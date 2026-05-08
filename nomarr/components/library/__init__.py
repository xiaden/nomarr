"""Library package."""

from .file_sync_comp import mark_file_tagged, save_file_tags
from .file_tags_comp import get_file_tags_with_path
from .library_file_mutation_comp import get_file_library_key, set_chromaprint, upsert_library_file
from .library_file_query_comp import get_library_file
from .library_id_comp import library_key_from_ref, normalize_library_id
from .library_records_comp import (
    create_library_record,
    find_library_containing_path,
    find_ml_complete_libraries,
    get_library_by_name,
    get_library_record,
    list_all_library_keys,
    list_library_records,
    list_watchable_library_records,
    update_library_config_fields,
    update_library_record,
)
from .library_root_comp import (
    ensure_no_overlapping_library_root,
    get_base_library_root,
    normalize_library_root,
    resolve_path_within_library,
    validate_library_root,
)
from .library_watch_config_comp import (
    get_library_watch_config,
    list_watchable_libraries,
)
from .metadata_extraction_comp import (
    compute_chromaprint_for_file,
    extract_metadata,
    resolve_artists,
)
from .scan_lifecycle_comp import (
    check_interrupted_scan,
    cleanup_stale_folders,
    get_cached_folders,
    get_library_scan_histories,
    get_scanning_library_ids,
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
    get_unique_tag_values,
    search_library_files,
)

__all__ = [
    "check_interrupted_scan",
    "cleanup_stale_folders",
    "compute_chromaprint_for_file",
    "create_library_record",
    "ensure_no_overlapping_library_root",
    "extract_metadata",
    "find_library_containing_path",
    "find_ml_complete_libraries",
    "get_base_library_root",
    "get_cached_folders",
    "get_file_library_key",
    "get_file_tags_with_path",
    "get_library_by_name",
    "get_library_file",
    "get_library_record",
    "get_library_scan_histories",
    "get_library_watch_config",
    "get_scanning_library_ids",
    "get_unique_tag_values",
    "library_key_from_ref",
    "list_all_library_keys",
    "list_library_records",
    "list_watchable_libraries",
    "list_watchable_library_records",
    "mark_file_tagged",
    "mark_scan_completed",
    "mark_scan_started",
    "normalize_library_id",
    "normalize_library_root",
    "remove_deleted_files",
    "resolve_artists",
    "resolve_library_for_scan",
    "resolve_path_within_library",
    "save_file_tags",
    "save_folder_record",
    "search_library_files",
    "set_chromaprint",
    "snapshot_existing_files",
    "update_library_config_fields",
    "update_library_record",
    "update_scan_progress",
    "upsert_library_file",
    "upsert_scanned_files",
    "validate_library_root",
]
