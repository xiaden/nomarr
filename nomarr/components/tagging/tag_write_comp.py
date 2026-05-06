"""Tag write and curation helpers extracted from legacy tag persistence."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, cast

from nomarr.components.tagging.tag_cleanup_comp import cleanup_orphaned_tags
from nomarr.helpers.dto.tag_curation_dto import RelinkResult
from nomarr.helpers.dto.tags_dto import TagValue

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def find_or_create_tag(db: Database, name: str, value: TagValue) -> str:
    """Find or create one tag vertex and return its ``_id``."""
    return cast("str", db.tags.upsert(name=name, value=value, fields={})[0])


def resolve_tag_ids(
    db: Database,
    pairs: Sequence[tuple[str, TagValue]],
) -> dict[tuple[str, TagValue], str]:
    """Batch-resolve tag ids for ``(name, value)`` pairs."""
    if not pairs:
        return {}

    resolved: dict[tuple[str, TagValue], str] = {}
    for name, value in dict.fromkeys(pairs):
        matches = cast("list[dict[str, Any]]", db.tags.get(name=name, value=value, limit=1))
        if not matches:
            continue
        tag_id = matches[0].get("_id")
        if tag_id is not None:
            resolved[(name, value)] = str(tag_id)
    return resolved


def _find_song_name_edge_ids(db: Database, song_id: str, name: str) -> list[str]:
    """Return ``song_has_tags`` edge ids for one song + name pair."""
    edge_ids: list[str] = []
    for edge in cast("list[dict[str, Any]]", db.song_has_tags.get(_from=song_id, limit=None)):
        tag_id = edge.get("_to")
        if tag_id is None:
            continue
        tag = db.tags.get(_id=str(tag_id))
        if not isinstance(tag, dict) or tag.get("name") != name:
            continue
        edge_id = edge.get("_id")
        if edge_id is not None:
            edge_ids.append(str(edge_id))
    return edge_ids


def set_song_tags(db: Database, song_id: str, name: str, values: list[TagValue]) -> None:
    """Replace all tags for one ``song_id`` + ``name`` pair."""
    edge_ids = _find_song_name_edge_ids(db, song_id, name)
    for edge_id in edge_ids:
        db.song_has_tags.delete(_id=edge_id)
    if not values:
        return

    tag_id_map = {value: find_or_create_tag(db, name, value) for value in values}
    edge_docs = [{"_from": song_id, "_to": tag_id_map[value]} for value in values if value in tag_id_map]
    for edge_doc in edge_docs:
        db.song_has_tags.upsert(_from=edge_doc["_from"], _to=edge_doc["_to"], fields={})


def set_song_tags_batch(db: Database, entries: list[dict[str, Any]]) -> None:
    """Replace tags for many ``(song_id, name)`` pairs as component composition.

    This supersedes the old persistence primitive from ADR-010. The operation is
    now expressed as component-layer coordination of constructor-backed verbs:
    targeted edge deletion, tag upsert, then edge upsert (idempotent).

    Args:
        db: Database handle used to replace tag edges and upsert referenced tags.
        entries: Batch entries to apply. Each entry must contain ``song_id`` for
            the song vertex id, ``name`` for the tag name being replaced, and
            ``values`` for the list of tag values to attach for that pair.
    """
    if not entries:
        return

    edge_ids: list[str] = []
    upsert_pairs: list[tuple[str, TagValue]] = []
    entry_pairs: list[tuple[str, str, list[TagValue]]] = []
    for entry in entries:
        song_id = str(entry["song_id"])
        name = str(entry["name"])
        values = [cast("TagValue", value) for value in entry["values"]]
        entry_pairs.append((song_id, name, values))
        edge_ids.extend(_find_song_name_edge_ids(db, song_id, name))
        upsert_pairs.extend((name, value) for value in values)

    for edge_id in edge_ids:
        db.song_has_tags.delete(_id=edge_id)

    if not upsert_pairs:
        return

    tag_ids = {(name, value): find_or_create_tag(db, name, value) for name, value in upsert_pairs}

    edge_docs: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str]] = set()
    for song_id, name, values in entry_pairs:
        for value in values:
            tag_id = tag_ids.get((name, value))
            if tag_id is not None:
                edge_key = (song_id, tag_id)
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    edge_docs.append({"_from": song_id, "_to": tag_id})
    for edge_doc in edge_docs:
        db.song_has_tags.upsert(_from=edge_doc["_from"], _to=edge_doc["_to"], fields={})


def add_song_tag(db: Database, song_id: str, name: str, value: TagValue) -> None:
    """Add one tag value to a song without replacing other values for the name."""
    tag_id = find_or_create_tag(db, name, value)
    db.song_has_tags.upsert(_from=song_id, _to=tag_id, fields={})


def delete_song_tags(db: Database, song_id: str) -> None:
    """Delete all tag edges for one song."""
    db.song_has_tags.delete(_from=song_id)


def relink_tag_edges(
    db: Database,
    source_tag_id: str,
    target_tag_id: str,
    song_ids: list[str] | None = None,
) -> RelinkResult:
    """Move ``song_has_tags`` edges from one tag vertex to another.

    This supersedes the old persistence primitive from ADR-014. The relink is a
    component composition of constructor verbs: get source edges, insert target
    edges, remove moved source edges, then cascade-delete the source tag when it
    becomes orphaned.

    Args:
        db: Database handle used to read, insert, and delete tag edges.
        source_tag_id: Tag vertex id whose outgoing song edges should be moved.
        target_tag_id: Tag vertex id that should receive moved song edges.
        song_ids: Optional song vertex ids to limit the relink scope. When ``None``,
            all songs linked to the source tag are considered. When provided,
            only source edges whose ``_from`` is in the list are relinked.

    Returns:
        A summary of the relink operation containing ``moved`` for the number of
        target edges inserted, ``skipped`` for source edges whose songs already
        had target edges, and ``source_orphaned`` indicating whether the source
        tag has no remaining ``song_has_tags`` edges after the relink.
    """
    source_edges = cast(
        "list[dict[str, Any]]",
        db.song_has_tags.get(_to=source_tag_id, limit=None),
    )
    if song_ids is not None:
        allowed = set(song_ids)
        source_edges = [edge for edge in source_edges if edge.get("_from") in allowed]
    if not source_edges:
        return {"moved": 0, "skipped": 0, "source_orphaned": False}

    target_existing = {
        str(edge.get("_from"))
        for edge in cast(
            "list[dict[str, Any]]",
            db.song_has_tags.get(_to=target_tag_id, limit=None),
        )
    }
    edges_to_insert = [
        {"_from": str(edge["_from"]), "_to": target_tag_id}
        for edge in source_edges
        if str(edge["_from"]) not in target_existing
    ]
    if edges_to_insert:
        db.song_has_tags.insert(edges_to_insert)

    moved_edge_ids = [str(edge["_id"]) for edge in source_edges if edge.get("_id")]
    for edge_id in moved_edge_ids:
        db.song_has_tags.delete(_id=edge_id)

    remaining_source_edges = cast(
        "list[dict[str, Any]]",
        db.song_has_tags.get(_to=source_tag_id, limit=None),
    )
    source_orphaned = len(remaining_source_edges) == 0
    if source_orphaned:
        cleanup_orphaned_tags(db)

    moved = len(edges_to_insert)
    skipped = len(source_edges) - moved
    return {"moved": moved, "skipped": skipped, "source_orphaned": source_orphaned}
