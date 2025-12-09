"""Library components for file search and management."""

from nomarr.components.library.metadata_extraction_comp import extract_metadata
from nomarr.components.library.search_files_comp import (
    get_unique_tag_keys,
    search_library_files,
)
from nomarr.components.library.tag_normalization_comp import (
    normalize_id3_tags,
    normalize_mp4_tags,
    normalize_vorbis_tags,
)

__all__ = [
    "extract_metadata",
    "get_unique_tag_keys",
    "normalize_id3_tags",
    "normalize_mp4_tags",
    "normalize_vorbis_tags",
    "search_library_files",
]
