"""
Library file search component.

Provides search functionality for library files with tag filtering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def search_library_files(
    db: Database,
    query_text: str = "",
    artist: str | None = None,
    album: str | None = None,
    tag_key: str | None = None,
    tag_value: str | None = None,
    tagged_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """
    Search library files with optional filtering.

    Args:
        db: Database instance
        query_text: Text search query for artist/album/title
        artist: Filter by artist name
        album: Filter by album name
        tag_key: Filter by files that have this tag key
        tag_value: Filter by files with this specific tag key=value
        tagged_only: Only return tagged files
        limit: Maximum number of results
        offset: Pagination offset

    Returns:
        Tuple of (files list with tags, total count)
    """
    # Use joined queries for efficient file+tag retrieval
    return db.library_files.search_library_files_with_tags(
        q=query_text,
        artist=artist,
        album=album,
        tag_key=tag_key,
        tag_value=tag_value,
        tagged_only=tagged_only,
        limit=limit,
        offset=offset,
    )


def get_unique_tag_keys(db: Database, nomarr_only: bool = False) -> list[str]:
    """
    Get list of unique tag keys (rel values).

    Args:
        db: Database instance
        nomarr_only: Only return Nomarr tags (rel starts with "nom:")

    Returns:
        List of unique tag keys (rel values)
    """
    return db.tags.get_unique_rels(nomarr_only=nomarr_only)


def get_unique_tag_values(db: Database, tag_key: str, nomarr_only: bool = False) -> list[str]:
    """
    Get list of unique values for a specific tag key (rel).

    Args:
        db: Database instance
        tag_key: The tag rel to get values for
        nomarr_only: Ignored (key already determines if it's nomarr)

    Returns:
        List of unique tag values
    """
    # Get all tags for this rel (limited to reasonable count)
    tags = db.tags.list_tags_by_rel(tag_key, limit=10000)
    return [str(t["value"]) for t in tags]
