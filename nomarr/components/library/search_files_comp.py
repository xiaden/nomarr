"""Library file search component.

Provides search functionality for library files with tag filtering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_file_query_comp import search_library_files_with_tags
from nomarr.components.tagging.tag_query_comp import list_tags_by_rel
from nomarr.components.tagging.tag_stats_comp import get_unique_rels
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


def get_unique_tag_keys(db: Database, nomarr_only: bool = False) -> list[str]:
    """Get list of unique tag keys (rel values).

    Args:
        db: Database instance
        nomarr_only: Only return Nomarr tags (rel starts with "nom:")

    Returns:
        List of unique tag keys (rel values)

    """
    return get_unique_rels(db, nomarr_only=nomarr_only)


def get_unique_tag_values(db: Database, tag_key: str, nomarr_only: bool = False) -> list[str]:
    """Get list of unique values for a specific tag key (rel).

    Args:
        db: Database instance
        tag_key: The tag rel to get values for
        nomarr_only: Ignored (key already determines if it's nomarr)

    Returns:
        List of unique tag values

    """
    # Get all tags for this rel (limited to reasonable count)
    tags = list_tags_by_rel(db, tag_key, limit=10000, sort_by_count=True)
    return [str(t["value"]) for t in tags]
