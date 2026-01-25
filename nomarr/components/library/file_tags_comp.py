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
        nomarr_only: If True, only return Nomarr-generated tags (rel starts with "nom:")

    Returns:
        Dict with 'path' and 'tags' keys, or None if file not found.
        'tags' is a list of dicts with 'rel', 'value', 'is_nomarr_tag'.
    """
    # Get file info from persistence
    file_record = db.library_files.get_file_by_id(file_id)
    if not file_record:
        return None

    # Get tags from unified TagOperations
    tags_raw = db.tags.get_song_tags(file_id, nomarr_only=nomarr_only)

    # Transform to expected format for API compatibility
    tags_data = [
        {
            "key": tag["rel"],  # API uses "key" for backward compat
            "rel": tag["rel"],
            "value": tag["value"],
            "is_nomarr_tag": tag["rel"].startswith("nom:"),
        }
        for tag in tags_raw
    ]

    return {
        "path": file_record["path"],
        "tags": tags_data,
    }
