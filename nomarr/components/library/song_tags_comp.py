"""Song tags component — retrieve tag data for songs.

Reads route through the sealed tag facade (``db.library``). A song is addressed
by a semantic ``SongIdentity`` locator; tags are read via
``db.library.list_tags_for_song(SongIdentity)``, filtered by ``namespace ==
"nom"`` when ``nomarr_only`` is set, and projected to the library/API
``FileTag`` contract by ``tag_mapping_comp.file_tag_from_tag_row``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.components.library.tag_mapping_comp import file_tag_from_tag_row

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.helpers.dto.library_dto import FileTag
    from nomarr.persistence.db import Database


def get_song_tags_with_path(
    db: Database, song_identity: SongIdentity, nomarr_only: bool = False
) -> dict[str, Any] | None:
    """Get all tags for a song along with its file path.

    Args:
        db: Persistence facade.
        song_identity: Semantic ``SongIdentity`` locator addressing the song;
            the underlying storage id is never accepted or returned.
        nomarr_only: When true, restrict the result to ``nom``-namespace
            (Nomarr-owned) tags.

    Returns:
        A dict with ``path`` and ``tags`` keys, or ``None`` if the song is not
        found. ``tags`` is a list of library-owned ``FileTag`` objects produced
        by the shared row-to-``FileTag`` mapper (``tag_mapping_comp``).

    """
    file_record = db.library.get_song(song_identity)
    if not file_record:
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
