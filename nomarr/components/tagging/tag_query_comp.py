"""Tag query helpers extracted from legacy tag persistence.

All reads route through the sealed intent-level tag facade (``LibraryTagsDb``)
using domain identities (``TagRef`` / ``SongIdentity``) and typed domain
results (``SongTagAssignment`` / ``Song`` / ``SongTagMatch`` / ``TagUsage``).
Numeric song handles are translated with the song-side identity bridge
(``db.library.resolve_song_identity(s)``); numeric tag handles come from the
root ``db.resolve_tag_identity`` (opaque external tag ids only).
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef
from nomarr.helpers.dataclasses.tags_dataclass import Tag, Tags, TagValue
from nomarr.helpers.dto.tag_curation_dto import TagSongItem

if TYPE_CHECKING:
    from collections.abc import Sequence

    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment
    from nomarr.persistence.db import Database


def _numeric_value(value: object) -> float | None:
    """Convert values to numeric form when possible for ordered comparisons."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _matches_tag_operator(tag_value: object, operator: str, value: TagValue) -> bool:
    """Evaluate a supported tag comparison in Python."""
    if operator in {"==", "="}:
        return bool(tag_value == value)
    if operator == "!=":
        return bool(tag_value != value)
    if operator == "CONTAINS":
        return str(value).lower() in str(tag_value).lower()
    if operator == "NOTCONTAINS":
        return str(value).lower() not in str(tag_value).lower()

    left_num = _numeric_value(tag_value)
    right_num = _numeric_value(value)
    if left_num is not None and right_num is not None:
        if operator == ">":
            return left_num > right_num
        if operator == "<":
            return left_num < right_num
        if operator == ">=":
            return left_num >= right_num
        if operator == "<=":
            return left_num <= right_num
        return bool(tag_value == value)

    left_cmp = str(tag_value)
    right_cmp = str(value)
    if operator == ">":
        return left_cmp > right_cmp
    if operator == "<":
        return left_cmp < right_cmp
    if operator == ">=":
        return left_cmp >= right_cmp
    if operator == "<=":
        return left_cmp <= right_cmp
    return bool(tag_value == value)


def _candidate_filter_values(value: str) -> list[TagValue]:
    """Generate exact-match candidates including numeric coercions."""
    candidates: list[TagValue] = [value]
    with contextlib.suppress(ValueError):
        candidates.append(int(value))
    try:
        float_value = float(value)
    except ValueError:
        return candidates
    if float_value not in candidates:
        candidates.append(float_value)
    return candidates


def _first_assignment_value(assignments: Sequence[SongTagAssignment], name: str) -> str:
    """Return the first string value for a tag name, or an empty string."""
    for assignment in assignments:
        if assignment.name != name:
            continue
        if isinstance(assignment.value, str):
            return assignment.value
    return ""


def _assignments_to_tags(assignments: Sequence[SongTagAssignment]) -> Tags:
    """Convert public ``SongTagAssignment`` domain values into a canonical ``Tags``.

    Component-local conversion over the public facade result (replaces the old
    persistence ``tags_from_tag_rows`` mapper dependency): only the assignment's
    ``name`` (tag_name) and ``value`` (tag_value) are carried into the domain
    ``Tags``, which is exactly the two-field subset the canonical ``Tags``
    contract represents. Persistence-only metadata (``source``, ``confidence``,
    ``namespace``) is deliberately absent from the domain value object and is
    never projected into storage-shaped rows here. Duplicate names are merged and
    per-name values preserve order with the same dedupe/sort behavior as before;
    empty input yields an empty ``Tags`` (which raises the canonical ``ValueError``).
    """
    aggregated: dict[str, list[TagValue]] = {}
    for assignment in assignments:
        # SongTagAssignment.value is typed ``object`` but is always a scalar
        # TagValue at runtime; ``Tag.__post_init__`` validates the type anyway.
        aggregated.setdefault(assignment.name, []).append(cast("TagValue", assignment.value))
    items = tuple(Tag(name=name, values=tuple(values)) for name, values in aggregated.items())
    return Tags(items=items)


def _library_song_ids(db: Database, library_id: int) -> set[int] | None:
    """Resolve a numeric library handle to its song-id set (or None if missing)."""
    library_identity = db.library.resolve_library_identity(library_id)
    if library_identity is None:
        return None
    library = db.library.get_library_by_name(library_identity.name)
    if library is None:
        return None
    return set(db.library.list_library_song_ids(library, limit=None))


def get_tag(db: Database, tag_id: int) -> dict[str, Any] | None:
    """Resolve one opaque external tag id to a tag document.

    Returns a dict with ``id`` (the external tag id), ``name``, ``value`` and
    ``namespace`` so the caller-facing dict shape is preserved while the lookup
    goes through the root tag-identity bridge (never an integer tag facade).
    """
    identity = db.resolve_tag_identity(tag_id)
    if identity is None:
        return None
    return {
        "id": tag_id,
        "name": identity.name,
        "value": identity.value,
        "namespace": identity.namespace,
    }


def count_songs_for_tag(db: Database, tag_id: int) -> int:
    """Count files linked to one opaque external tag id."""
    identity = db.resolve_tag_identity(tag_id)
    if identity is None:
        return 0
    return len(db.library.find_songs_with_tag(identity, limit=None))


def list_tags_by_name(
    db: Database,
    name: str | None = None,
    limit: int = 100,
    offset: int = 0,
    search: str | None = None,
    sort_by_count: bool = False,
) -> list[dict[str, Any]]:
    """List tag values, optionally filtered by tag name and search text.

    Tag ``id`` is the natural tag value. Tag storage primary keys stay inside
    persistence and are not exposed through the domain browse contract.
    """
    if sort_by_count:
        # Fetch all matching usages sorted by count desc, then page in Python.
        total = db.library.count_tags_filtered(name=name, search=search)
        usages = list(db.library.list_tags_with_song_count(name=name, search=search, limit=total, offset=0))
        usages.sort(key=lambda usage: (-usage.song_count, str(usage.identity.value).lower()))
        usages = usages[offset : offset + limit]
    else:
        # Default path: sort by value, paginated server-side
        usages = list(db.library.list_tags_with_song_count(name=name, search=search, limit=limit, offset=offset))

    return [
        {
            "id": usage.identity.value,
            "name": usage.identity.name,
            "value": usage.identity.value,
            "song_count": usage.song_count,
        }
        for usage in usages
    ]


def count_tags_by_name(db: Database, name: str | None = None, search: str | None = None) -> int:
    """Count tags, optionally filtered by tag name and search text."""
    return db.library.count_tags_filtered(name=name, search=search)


def get_song_tags(db: Database, song_id: int, name: str | None = None, nomarr_only: bool = False) -> Tags | None:
    """Return tags for one song as a ``Tags`` DTO, or ``None`` if no tags match."""
    song_identity = db.library.resolve_song_identity(song_id)
    if song_identity is None:
        return None
    assignments = db.library.list_tags_for_song(song_identity)
    matching = [
        assignment
        for assignment in assignments
        if (name is None or assignment.name == name) and (not nomarr_only or assignment.namespace == "nom")
    ]
    if not matching:
        return None
    return _assignments_to_tags(matching)


def get_nomarr_tags_bulk(db: Database, file_ids: list[int]) -> dict[int, Tags]:
    """Return Nomarr-prefixed tags for many files in one query."""
    if not file_ids:
        return {}

    identity_map = db.library.resolve_song_identities(file_ids)
    if not identity_map:
        return {}
    id_to_identity = {identity: song_id for song_id, identity in identity_map.items()}
    by_identity = db.library.list_song_tags_for_songs(list(identity_map.values()), name_starts_with="nom:")

    result: dict[int, Tags] = {}
    for identity, assignments in by_identity.items():
        song_id = id_to_identity.get(identity)
        if song_id is None:
            continue
        if not assignments:
            continue
        result[song_id] = _assignments_to_tags(assignments)
    return result


def list_songs_for_tag(db: Database, tag_id: int, limit: int = 100, offset: int = 0) -> list[int]:
    """List song ids connected to one opaque external tag id."""
    identity = db.resolve_tag_identity(tag_id)
    if identity is None:
        return []
    return [song.song_id for song in db.library.find_songs_with_tag(identity, limit=limit, offset=offset)]


def get_file_ids_matching_tag(db: Database, name: str, operator: str, value: TagValue) -> set[int]:
    """Return file ids matching one tag comparison."""
    all_tags = (
        list(db.library.list_tags(name=name, limit=None))
        if name is not None
        else list(db.library.list_tags(limit=None))
    )
    matching_tags = [identity for identity in all_tags if _matches_tag_operator(identity.value, operator, value)]

    file_ids: set[int] = set()
    for identity in matching_tags:
        for song in db.library.find_songs_with_tag(identity, limit=None):
            file_ids.add(song.song_id)
    return file_ids


def get_file_ids_for_tags(
    db: Database,
    tag_specs: list[tuple[str, str]],
    library: Library | None = None,
) -> dict[tuple[str, str], set[int]]:
    """Get file-id sets for many ``(name, value)`` tag specs."""
    result: dict[tuple[str, str], set[int]] = {}

    # Resolve library-scoped file ids when a library is provided
    library_ids: set[int] | None = (
        {song.song_id for song in db.library.list_songs(library, limit=None)} if library is not None else None
    )

    for name, value in tag_specs:
        tags = list(db.library.list_tags(name=name, limit=None))
        if value != "*":
            candidates = _candidate_filter_values(value)
            tags = [identity for identity in tags if identity.value in candidates]

        file_ids: set[int] = set()
        for identity in tags:
            for song in db.library.find_songs_with_tag(identity, limit=None):
                file_ids.add(song.song_id)

        if library_ids is not None:
            file_ids &= library_ids
        result[(name, value)] = file_ids

    return result


def get_file_ids_for_mood_tags(
    db: Database,
    mood_values: list[str],
    mood_tier: str = "mood-strict",
    library: Library | None = None,
) -> dict[str, set[int]]:
    """Return file-id sets for mood values using CONTAINS array matching."""
    result: dict[str, set[int]] = {}
    name = f"nom:{mood_tier}" if not mood_tier.startswith("nom:") else mood_tier

    library_ids: set[int] | None = (
        {song.song_id for song in db.library.list_songs(library, limit=None)} if library is not None else None
    )

    for mood_value in mood_values:
        identity = TagRef(name=name, value=mood_value, namespace="nom")
        songs = db.library.find_songs_with_tag_contains(identity, limit=None)
        file_ids: set[int] = {song.song_id for song in songs}
        if library_ids is not None:
            file_ids &= library_ids
        result[mood_value] = file_ids

    return result


def get_unique_mood_values(db: Database, mood_tier: str = "mood-strict", limit: int = 100) -> list[str]:
    """Return unique mood values for one tier."""
    name = f"nom:{mood_tier}" if not mood_tier.startswith("nom:") else mood_tier
    tags = list_tags_by_name(db, name=name, limit=limit, offset=0)
    values = sorted({str(tag["value"]) for tag in tags})
    return values[:limit]


def get_distinct_tag_values_for_files(db: Database, file_ids: list[int], name: str) -> list[str]:
    """Return distinct values for one tag name across many files."""
    if not file_ids:
        return []

    identity_map = db.library.resolve_song_identities(file_ids)
    if not identity_map:
        return []
    by_identity = db.library.list_song_tags_for_songs(list(identity_map.values()))
    values = {
        str(assignment.value)
        for assignments in by_identity.values()
        for assignment in assignments
        if assignment.name == name and isinstance(assignment.value, str)
    }
    return sorted(values)


def get_tag_values_grouped_by_file(db: Database, file_ids: list[int], name: str) -> dict[int, set[str]]:
    """Return tag values grouped by file for one tag name."""
    if not file_ids:
        return {}

    identity_map = db.library.resolve_song_identities(file_ids)
    if not identity_map:
        return {}
    id_to_identity = {identity: song_id for song_id, identity in identity_map.items()}
    by_identity = db.library.list_song_tags_for_songs(list(identity_map.values()))
    result: dict[int, set[str]] = {}
    for identity, assignments in by_identity.items():
        song_id = id_to_identity.get(identity)
        if song_id is None:
            continue
        for assignment in assignments:
            if assignment.name != name or not isinstance(assignment.value, str):
                continue
            result.setdefault(song_id, set()).add(assignment.value)
    return result


def get_tag_songs_with_metadata(db: Database, tag_id: int, limit: int = 50, offset: int = 0) -> list[TagSongItem]:
    """Return song rows for a tag with basic file metadata."""
    result: list[TagSongItem] = []
    for song_id in list_songs_for_tag(db, tag_id, limit=limit, offset=offset):
        song = db.library.get_song(song_id)
        if song is None:
            continue
        song_identity = db.library.resolve_song_identity(song_id)
        if song_identity is None:
            continue
        assignments = db.library.list_tags_for_song(song_identity)
        result.append(
            TagSongItem(
                file_id=song_id,
                title=_first_assignment_value(assignments, "title"),
                artist=_first_assignment_value(assignments, "artist"),
                album=_first_assignment_value(assignments, "album"),
                path=song.path,
            ),
        )
    return result
