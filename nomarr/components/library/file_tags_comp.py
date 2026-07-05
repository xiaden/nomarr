"""File tags component - retrieve tag data for files."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class _FileTagItem(TypedDict):
    """Internal shape of each tag dict returned to service callers."""

    key: str
    rel: str
    value: str | int | float | bool | list[str | int | float | bool]
    type: str
    is_nomarr_tag: bool


def get_file_tags_with_path(db: Database, file_id: str, nomarr_only: bool = False) -> dict[str, Any] | None:
    """Get all tags for a file along with file path.

    Returns dict with 'path' and 'tags' keys, or None if file not found.
    'tags' is a list of ``_FileTagItem`` dicts.
    """
    file_record = db.library_files.get_file_by_id(file_id)
    if not file_record:
        return None

    # Get tags from unified TagOperations
    tags = db.tags.get_song_tags(file_id, nomarr_only=nomarr_only)

    # Transform Tags DTO to API-compatible dict format.
    # Flatten single-value tuples for API consumers.
    tags_data: list[_FileTagItem] = [
        {
            "key": tag.key,
            "rel": tag.key,
            "value": tag.value[0] if len(tag.value) == 1 else list(tag.value),
            "type": "nomarr" if tag.key.startswith("nom:") else "user",
            "is_nomarr_tag": tag.key.startswith("nom:"),
        }
        for tag in tags
    ]

    return {
        "path": file_record["path"],
        "tags": tags_data,
    }
