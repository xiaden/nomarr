"""Library components — song management, scanning, metadata, and queries.

Core library domain components covering song mutation/queries, folder
discovery, scan lifecycle, path reconciliation, metadata extraction,
chromaprint computation, song state transitions, and tag hydration.
"""

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
from .library_scan_file_ops_comp import (
    cleanup_stale_folders,
    get_cached_folders,
    remove_deleted_files,
    save_folder_record,
    snapshot_existing_files,
    upsert_scanned_files,
)
from .library_song_mutation_comp import get_song_library_key, set_chromaprint, upsert_library_song
from .library_song_query_comp import get_library_song
from .library_song_state_comp import bulk_set_not_hydrated
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
    get_library_scan_histories,
    get_scanning_library_ids,
    mark_scan_completed,
    mark_scan_started,
    resolve_library_for_scan,
    update_scan_progress,
)
from .search_files_comp import (
    get_unique_tag_values,
    search_songs,
)
from .song_sync_comp import mark_song_processed, save_song_tags
from .song_tags_comp import get_song_tags_with_path

__all__ = [
    "bulk_set_not_hydrated",
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
    "get_library_by_name",
    "get_library_record",
    "get_library_scan_histories",
    "get_library_song",
    "get_library_watch_config",
    "get_scanning_library_ids",
    "get_song_library_key",
    "get_song_tags_with_path",
    "get_unique_tag_values",
    "library_key_from_ref",
    "list_all_library_keys",
    "list_library_records",
    "list_watchable_libraries",
    "list_watchable_library_records",
    "mark_scan_completed",
    "mark_scan_started",
    "mark_song_processed",
    "normalize_library_id",
    "normalize_library_root",
    "remove_deleted_files",
    "resolve_artists",
    "resolve_library_for_scan",
    "resolve_path_within_library",
    "save_folder_record",
    "save_song_tags",
    "search_songs",
    "set_chromaprint",
    "snapshot_existing_files",
    "update_library_config_fields",
    "update_library_record",
    "update_scan_progress",
    "upsert_library_song",
    "upsert_scanned_files",
    "validate_library_root",
]
