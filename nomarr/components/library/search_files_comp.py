"""Library file search component.

Provides search functionality for library files with tag filtering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_file_query_comp import search_library_files_with_tags
from nomarr.components.tagging.tag_query_comp import list_tags_by_name
from nomarr.helpers.dto.library_dto import SearchFilesQuery

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def search_library_files(
    db: Database,
    query: SearchFilesQuery,
) -> tuple[list[dict[str, Any]], int]:
    """Search library files with optional filtering.

    Args:
        db: Database instance
        query: Search/filter parameters

    Returns:
        Tuple of (files list with tags, total count)

    """
    # Use joined queries for efficient file+tag retrieval
    return search_library_files_with_tags(
        db,
        query_text=query.query_text,
        artist=query.artist,
        album=query.album,
        tag_key=query.tag_key,
        tag_value=query.tag_value,
        tagged_only=query.tagged_only,
        limit=query.limit,
        offset=query.offset,
    )


def get_unique_tag_values(db: Database, tag_key: str, nomarr_only: bool = False) -> list[str]:
    """Get list of unique values for a specific tag key (name).

    Args:
        db: Database instance
        tag_key: The tag name to get values for
        nomarr_only: Ignored (key already determines if it's nomarr)

    Returns:
        List of unique tag values

    """
    # Get all tags for this name (limited to reasonable count)
    tags = list_tags_by_name(db, tag_key, limit=10000, sort_by_count=True)
    return [str(t["value"]) for t in tags]
