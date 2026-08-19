"""Song tags component — retrieve tag data for songs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class _FileTagItem(TypedDict):
    """Internal shape of each tag dict returned to service callers."""

    key: str
    value: str | int | float | bool | list[str | int | float | bool]
    type: str
    is_nomarr: bool


def get_song_tags_with_path(db: Database, song_id: int, nomarr_only: bool = False) -> dict[str, Any] | None:
    """Get all tags for a song along with its file path.

    Returns dict with 'path' and 'tags' keys, or None if the song is not found.
    'tags' is a list of ``_FileTagItem`` dicts.
    """
    file_record = db.library.get_song(song_id)
    if not file_record:
        return None

    # Get tags from library facade and filter if needed
    all_tags = db.library.list_tags_for_song(song_id)
    if nomarr_only:
        tags = [tag for tag in all_tags if tag.get("namespace") == "nom"]
    else:
        tags = all_tags

    # Transform TagRow to the canonical tag row shape used by tag consumers.
    tags_data: list[_FileTagItem] = [
        {
            "key": tag["name"],
            "value": tag["value"],
            "type": "float"
            if isinstance(tag["value"], (int, float)) and not isinstance(tag["value"], bool)
            else "string",
            "is_nomarr": tag.get("namespace") == "nom",
        }
        for tag in tags
    ]

    return {
        "path": file_record["path"],
        "tags": tags_data,
    }
