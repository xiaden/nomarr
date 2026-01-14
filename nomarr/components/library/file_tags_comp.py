"""File tags component - retrieve tag data for files."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def get_file_tags_with_path(db: Database, file_id: str, nomarr_only: bool = False) -> dict[str, Any] | None:
    """
    Get all tags for a file along with file path.

    Args:
        db: Database instance
        file_id: Library file ID
        nomarr_only: If True, only return Nomarr-generated tags

    Returns:
        Dict with 'path' and 'tags' keys, or None if file not found.
        'tags' is a list of dicts with 'key', 'value', 'type', 'is_nomarr_tag'.
    """
    # Get file info from persistence
    file_record = db.library_files.get_file_by_id(file_id)
    if not file_record:
        return None

    # Get tags from persistence
    tags_data = db.file_tags.get_file_tags_with_metadata(file_id, nomarr_only=nomarr_only)

    return {
        "path": file_record["path"],
        "tags": tags_data,
    }
