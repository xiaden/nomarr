"""Library components for file search and management."""

from nomarr.components.library.metadata_extraction_comp import extract_metadata
from nomarr.components.library.search_files_comp import (
    get_unique_tag_keys,
    search_library_files,
)

__all__ = [
    "extract_metadata",
    "get_unique_tag_keys",
    "search_library_files",
]
