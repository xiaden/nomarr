"""Song tags component — retrieve tag data for songs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.components.library.tag_mapping_comp import file_tag_from_tag_row

if TYPE_CHECKING:
    from nomarr.helpers.dto.library_dto import FileTag
    from nomarr.persistence.db import Database


def get_song_tags_with_path(db: Database, song_id: int, nomarr_only: bool = False) -> dict[str, Any] | None:
    """Get all tags for a song along with its file path.

    Returns dict with 'path' and 'tags' keys, or None if the song is not found.
    'tags' is a list of library-owned ``FileTag`` objects produced by the shared
    row-to-``FileTag`` mapper (``tag_mapping_comp``).
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

    # Transform TagRow to the library FileTag contract via the shared mapper.
    tags_data: list[FileTag] = [file_tag_from_tag_row(tag) for tag in tags]

    return {
        "path": file_record["path"],
        "tags": tags_data,
    }
