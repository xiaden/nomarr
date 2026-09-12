"""Tag query helpers extracted from legacy tag persistence.

All reads route through the public ``db.library`` tag forwarders (the intent-level
``LibraryTagsDb`` sub-facade is reached only via ``db.library``)
using domain identities (``TagRef`` / ``SongIdentity``) and typed domain
results (``SongTagAssignment`` / ``Song`` / ``SongTagMatch`` / ``TagUsage``).
Song handles are translated to semantic ``SongIdentity`` locators through the
public carrier projection (``locators_for_carriers``); results are keyed by
locators, never generated ids. Tag get/count/list-song paths accept complete
natural ``TagRef`` identities and never parse ``tag_id`` or convert a numeric
natural value into a storage tag primary key.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef
from nomarr.helpers.dataclasses.tags_dataclass import Tag, Tags, TagValue
from nomarr.helpers.dto.tag_curation_dto import TagSongItem
from nomarr.helpers.song_locator_codec import encode_song_locator

if TYPE_CHECKING:
    from collections.abc import Sequence

    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.helpers.dataclasses.song_dataclass import Song
    from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment
    from nomarr.persistence.db import Database


def _project_song_locators(db: Database, songs: Sequence[Song]) -> list[SongIdentity]:
    """Project bare semantic songs to their UUID-bearing locators in input order.

    Uses the Q3-C public projection :func:`locators_for_carriers`; a song whose
    owning library or row no longer resolves is skipped deterministically. No
    generated id, row, resolver, or physical-path heuristic participates.
    """
    if not songs:
        return []
    # Imported locally: the ``library`` package eagerly imports ``search_files_comp``,
    # which imports this module. A top-level import closes an order-dependent cycle
    # (tagging -> library -> search_files_comp -> tagging) that breaks standalone
    # collection. Both symbols are needed only at call time.
    from nomarr.components.library.library_song_query_comp import locators_for_carriers
    from nomarr.components.library.song_query_types import TrackSong

    carriers = [TrackSong(song=song, metadata={}, isrc=None) for song in songs]
    return [locator for locator in locators_for_carriers(db, carriers) if locator is not None]


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


def assignments_to_tags(assignments: Sequence[SongTagAssignment]) -> Tags:
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


def get_tag(db: Database, identity: TagRef) -> dict[str, Any] | None:
    """Resolve one complete natural tag identity to a tag document.

    Accepts a ``TagRef`` natural identity and returns a dict with ``name``,
    ``value`` and ``namespace``, or ``None`` when no tag carries that exact
    natural key. The lookup goes through ``db.library.get_tag`` (never the root
    tag-identity bridge or an integer tag facade). ``id`` mirrors the listing
    projection (``list_tags_by_name``) and carries the natural value.
    """
    resolved = db.library.get_tag(identity)
    if resolved is None:
        return None
    return {
        "id": resolved.value,
        "name": resolved.name,
        "value": resolved.value,
        "namespace": resolved.namespace,
    }


def count_songs_for_tag(db: Database, identity: TagRef) -> int:
    """Count files linked to one complete natural tag identity.

    Matches the exact ``(name, value, namespace)`` natural key via
    ``db.library.find_songs_with_tag``; a tag with no matching row yields 0.
    """
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

    # Complete natural identity is projected so the interface boundary can encode
    # a namespace-distinct opaque handle: two tags with identical (name, value) in
    # different namespaces must not collapse into one id. The storage primary key
    # stays inside persistence.
    return [
        {
            "id": usage.identity.value,
            "name": usage.identity.name,
            "value": usage.identity.value,
            "namespace": usage.identity.namespace,
            "song_count": usage.song_count,
        }
        for usage in usages
    ]


def count_tags_by_name(db: Database, name: str | None = None, search: str | None = None) -> int:
    """Count tags, optionally filtered by tag name and search text."""
    return db.library.count_tags_filtered(name=name, search=search)


def list_songs_for_tag(db: Database, identity: TagRef, limit: int = 100, offset: int = 0) -> list[SongIdentity]:
    """List song locators connected to one complete natural tag identity.

    Matches the exact ``(name, value, namespace)`` natural key via
    ``db.library.find_songs_with_tag`` and projects each semantic song to its
    UUID-bearing ``SongIdentity``; a tag with no matching row yields ``[]``.
    Input order is preserved and unresolved songs are skipped.
    """
    songs = db.library.find_songs_with_tag(identity, limit=limit, offset=offset)
    return _project_song_locators(db, songs)


def get_file_ids_matching_tag(db: Database, name: str, operator: str, value: TagValue) -> set[SongIdentity]:
    """Return song locators matching one tag comparison."""
    all_tags = (
        list(db.library.list_tags(name=name, limit=None))
        if name is not None
        else list(db.library.list_tags(limit=None))
    )
    matching_tags = [identity for identity in all_tags if _matches_tag_operator(identity.value, operator, value)]

    songs = [song for identity in matching_tags for song in db.library.find_songs_with_tag(identity, limit=None)]
    return set(_project_song_locators(db, songs))


def get_file_ids_for_tags(
    db: Database,
    tag_specs: list[tuple[str, str]],
    library: Library | None = None,
) -> dict[tuple[str, str], set[SongIdentity]]:
    """Get song-locator sets for many ``(name, value)`` tag specs.

    Library scope filters the projected locators on the owning
    ``LibraryIdentity.library_uuid`` rather than rebuilding an integer
    library-song-id bridge. ``None`` keeps global scope.
    """
    result: dict[tuple[str, str], set[SongIdentity]] = {}

    for name, value in tag_specs:
        tags = list(db.library.list_tags(name=name, limit=None))
        if value != "*":
            candidates = _candidate_filter_values(value)
            tags = [identity for identity in tags if identity.value in candidates]

        songs = [song for identity in tags for song in db.library.find_songs_with_tag(identity, limit=None)]
        locators = _project_song_locators(db, songs)
        if library is not None:
            locators = [locator for locator in locators if locator.library.library_uuid == library.library_uuid]
        result[(name, value)] = set(locators)

    return result


def get_file_ids_for_mood_tags(
    db: Database,
    mood_values: list[str],
    mood_tier: str = "mood-strict",
    library: Library | None = None,
) -> dict[str, set[SongIdentity]]:
    """Return song-locator sets for mood values using CONTAINS array matching."""
    result: dict[str, set[SongIdentity]] = {}
    name = f"nom:{mood_tier}" if not mood_tier.startswith("nom:") else mood_tier

    for mood_value in mood_values:
        identity = TagRef(name=name, value=mood_value, namespace="nom")
        songs = db.library.find_songs_with_tag_contains(identity, limit=None)
        locators = _project_song_locators(db, songs)
        if library is not None:
            locators = [locator for locator in locators if locator.library.library_uuid == library.library_uuid]
        result[mood_value] = set(locators)

    return result


def get_unique_mood_values(db: Database, mood_tier: str = "mood-strict", limit: int = 100) -> list[str]:
    """Return unique mood values for one tier."""
    name = f"nom:{mood_tier}" if not mood_tier.startswith("nom:") else mood_tier
    tags = list_tags_by_name(db, name=name, limit=limit, offset=0)
    values = sorted({str(tag["value"]) for tag in tags})
    return values[:limit]


def get_distinct_tag_values_for_files(db: Database, locators: Sequence[SongIdentity], name: str) -> list[str]:
    """Return distinct string values for one tag name across many song locators."""
    if not locators:
        return []

    by_identity = db.library.list_song_tags_for_songs(list(locators))
    values = {
        str(assignment.value)
        for assignments in by_identity.values()
        for assignment in assignments
        if assignment.name == name and isinstance(assignment.value, str)
    }
    return sorted(values)


def get_tag_values_grouped_by_file(
    db: Database, locators: Sequence[SongIdentity], name: str
) -> dict[SongIdentity, set[str]]:
    """Return string tag values grouped by song locator for one tag name."""
    if not locators:
        return {}

    by_identity = db.library.list_song_tags_for_songs(list(locators))
    result: dict[SongIdentity, set[str]] = {}
    for identity, assignments in by_identity.items():
        for assignment in assignments:
            if assignment.name != name or not isinstance(assignment.value, str):
                continue
            result.setdefault(identity, set()).add(assignment.value)
    return result


def get_tag_songs_with_metadata(db: Database, identity: TagRef, limit: int = 50, offset: int = 0) -> list[TagSongItem]:
    """Return song rows for a tag with basic file metadata.

    ``file_id`` is the opaque ``nom1`` SongLocator token of the song; no
    generated integer id crosses this projection.
    """
    result: list[TagSongItem] = []
    for locator in list_songs_for_tag(db, identity, limit=limit, offset=offset):
        song = db.library.get_song(locator)
        if song is None:
            continue
        assignments = db.library.list_tags_for_song(locator)
        result.append(
            TagSongItem(
                file_id=encode_song_locator(locator),
                title=_first_assignment_value(assignments, "title"),
                artist=_first_assignment_value(assignments, "artist"),
                album=_first_assignment_value(assignments, "album"),
                path=song.path,
            ),
        )
    return result
