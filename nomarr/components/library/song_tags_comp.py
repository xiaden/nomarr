"""Song tags component — retrieve tag data for songs.

Reads route through the sealed tag facade (``db.library``). A numeric song
handle is translated to its natural ``SongIdentity`` with the identity bridge
(``db.library.resolve_song_identity``); tags are read via
``db.library.list_tags_for_song(SongIdentity)``, filtered by ``namespace ==
"nom"`` when ``nomarr_only`` is set, and projected to the library/API
``FileTag`` contract by ``tag_mapping_comp.file_tag_from_tag_row``.
"""

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
    # Physical song is used only for its absolute path.
    file_record = db.library.get_song(song_id)
    if not file_record:
        return None

    # Resolve the numeric song handle to a domain SongIdentity before the sealed
    # tag call (the tag facade never accepts an integer song id).
    song_identity = db.library.resolve_song_identity(song_id)
    if song_identity is None:
        return None

    # Get tags from library facade and filter if needed
    assignments = db.library.list_tags_for_song(song_identity)
    filtered_assignments = (
        [assignment for assignment in assignments if assignment.namespace == "nom"]
        if nomarr_only
        else list(assignments)
    )

    # Transform SongTagAssignment to the library FileTag contract via the shared mapper.
    tags_data: list[FileTag] = [
        file_tag_from_tag_row({"name": assignment.name, "value": assignment.value, "namespace": assignment.namespace})
        for assignment in filtered_assignments
    ]

    return {
        "path": file_record.path,
        "tags": tags_data,
    }
