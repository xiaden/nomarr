"""File tags component - retrieve tag data for files."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_file_query_comp import get_file_by_id
from nomarr.components.tagging.tag_query_comp import get_song_tags

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def get_file_tags_with_path(db: Database, file_id: str, nomarr_only: bool = False) -> dict[str, Any] | None:
    """Get all tags for a file along with file path.

    Returns dict with 'path' and 'tags' keys, or None if file not found.
    """
    # Get file info from persistence
    file_record = get_file_by_id(db, file_id)
    if not file_record:
        return None

    # Get tags from the component-owned tag query helper
    tags = get_song_tags(db, file_id, nomarr_only=nomarr_only)

    # Transform to expected format for API compatibility
    # Expand each multi-valued Tag into individual entries
    tags_data = [
        {
            "key": tag.key,
            "name": tag.key,
            "value": single_value,
            "is_nomarr_tag": tag.key.startswith("nom:"),
        }
        for tag in tags
        for single_value in tag.value
    ]

    return {
        "path": file_record["path"],
        "tags": tags_data,
    }
