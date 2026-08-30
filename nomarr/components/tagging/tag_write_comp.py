"""Tag write and curation helpers extracted from legacy tag persistence.

All writes route through the sealed tag facade (``LibraryTagsDb``) using
domain identities (``SongIdentity`` / ``TagRef``) and typed assignment
commands (``SongTagAssignment``). Numeric song handles are translated with the
song-side identity bridge (``db.library.resolve_song_identity(s)`` /
``resolve_song_identities``); tag relink uses the facade ``relink_tags`` intent
and consumes the typed ``RelinkResult``. No integer tag resolution, raw
replacement dictionaries, edge scans, or manual collision/orphan bookkeeping
remains at this layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.helpers.dataclasses.song_tag_dataclass import RelinkResult, SongTagAssignment, TagRef

if TYPE_CHECKING:
    from collections.abc import Sequence

    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.helpers.dataclasses.tags_dataclass import TagValue
    from nomarr.persistence.db import Database


def _merge_replaced_assignments(
    existing_tags: Sequence[SongTagAssignment],
    *,
    replacements_by_name: dict[str, list[TagValue]],
) -> list[SongTagAssignment]:
    """Merge existing assignments, replacing every value for the given names."""
    replaced_names = set(replacements_by_name)
    merged_tags = [assignment for assignment in existing_tags if assignment.name not in replaced_names]
    for name, values in replacements_by_name.items():
        merged_tags.extend(SongTagAssignment(name=name, value=value) for value in dict.fromkeys(values))
    return merged_tags


def set_song_tags(db: Database, song_id: int, name: str, values: list[TagValue]) -> None:
    """Replace all tags for one ``song_id`` + ``name`` pair."""
    song_identity = db.library.resolve_song_identity(song_id)
    if song_identity is None:
        return
    existing_tags = db.library.list_tags_for_song(song_identity)
    db.library.replace_song_tags(
        song_identity,
        _merge_replaced_assignments(existing_tags, replacements_by_name={name: values}),
    )


def _validate_tag_value(value: object) -> TagValue:
    """Runtime validation that a value is an acceptable tag value type."""
    if isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"Invalid tag value type: {type(value).__name__}")


def set_song_tags_batch(db: Database, entries: list[dict[str, Any]]) -> None:
    """Replace tags for many ``(song_id, name)`` pairs using intent-level file-tag writes."""
    if not entries:
        return

    replacements_by_song: dict[int, dict[str, list[TagValue]]] = {}
    for entry in entries:
        song_id = int(entry["song_id"])
        name = str(entry["name"])
        values = [_validate_tag_value(value) for value in entry["values"]]
        song_replacements = replacements_by_song.setdefault(song_id, {})
        song_replacements.setdefault(name, []).extend(values)

    identity_map = db.library.resolve_song_identities(list(replacements_by_song))
    existing_tags_by_song = db.library.list_song_tags_for_songs(list(identity_map.values()))
    for song_id, replacements_by_name in replacements_by_song.items():
        song_identity = identity_map.get(song_id)
        if song_identity is None:
            continue
        db.library.replace_song_tags(
            song_identity,
            _merge_replaced_assignments(
                existing_tags_by_song.get(song_identity, ()),
                replacements_by_name=replacements_by_name,
            ),
        )


def add_song_tag(db: Database, song_id: int, name: str, value: TagValue) -> None:
    """Add one tag value to a song without replacing other values for the name."""
    song_identity = db.library.resolve_song_identity(song_id)
    if song_identity is None:
        return
    existing_tags = db.library.list_tags_for_song(song_identity)
    db.library.replace_song_tags(
        song_identity,
        [*existing_tags, SongTagAssignment(name=name, value=value)],
    )


def delete_song_tags(db: Database, song_id: int) -> None:
    """Delete all tag edges for one song."""
    song_identity = db.library.resolve_song_identity(song_id)
    if song_identity is None:
        return
    db.library.remove_song_tags(song_identity)


def relink_tag_edges(
    db: Database,
    source: TagRef,
    target: TagRef,
    song_identities: Sequence[SongIdentity] | None = None,
) -> RelinkResult:
    """Relink source edges to target via the sealed duplicate-safe relink intent.

    Returns the facade's typed ``RelinkResult``. A no-op source==target or a
    source tag that does not exist yields ``RelinkResult(0, 0, 0)``.
    """
    if source == target:
        return RelinkResult(moved=0, skipped=0, source_orphaned=0)
    return db.library.relink_tags(source, target, songs=song_identities)
