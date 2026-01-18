"""
Library package.
"""

from .file_tags_comp import get_file_tags_with_path
from .library_root_comp import (
    ensure_no_overlapping_library_root,
    get_base_library_root,
    normalize_library_root,
    resolve_path_within_library,
)
from .metadata_extraction_comp import (
    compute_chromaprint_for_file,
    extract_metadata,
    resolve_artists,
)
from .reconcile_paths_comp import reconcile_library_paths
from .search_files_comp import (
    get_unique_tag_keys,
    get_unique_tag_values,
    search_library_files,
)
from .tag_cleanup_comp import cleanup_orphaned_tags, get_orphaned_tag_count

__all__ = [
    "cleanup_orphaned_tags",
    "compute_chromaprint_for_file",
    "ensure_no_overlapping_library_root",
    "extract_metadata",
    "get_base_library_root",
    "get_file_tags_with_path",
    "get_orphaned_tag_count",
    "get_unique_tag_keys",
    "get_unique_tag_values",
    "normalize_library_root",
    "reconcile_library_paths",
    "resolve_artists",
    "resolve_path_within_library",
    "search_library_files",
]
