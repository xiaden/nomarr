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
    q: str = "",
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
        q: Text search query for artist/album/title
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
        q=q,
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
    Get list of unique tag keys.

    Args:
        db: Database instance
        nomarr_only: Only return Nomarr tags

    Returns:
        List of unique tag keys
    """
    return db.file_tags.get_unique_tag_keys(nomarr_only=nomarr_only)


def get_unique_tag_values(db: Database, tag_key: str, nomarr_only: bool = False) -> list[str]:
    """
    Get list of unique values for a specific tag key.

    Args:
        db: Database instance
        tag_key: The tag key to get values for
        nomarr_only: Only return values from Nomarr tags (NOTE: not yet supported)

    Returns:
        List of unique tag values
    """
    # NOTE: file_tags.get_unique_tag_values doesn't support nomarr_only yet
    # TODO: Add filtering support in persistence layer
    return db.file_tags.get_unique_tag_values(tag_key)
