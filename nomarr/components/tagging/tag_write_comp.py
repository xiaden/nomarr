"""Tag write and curation helpers extracted from legacy tag persistence."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, cast

from nomarr.components.tagging.tag_cleanup_comp import cleanup_orphaned_tags
from nomarr.helpers.dto.tag_curation_dto import RelinkResult
from nomarr.helpers.dto.tags_dto import TagValue

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def find_or_create_tag(db: Database, rel: str, value: TagValue) -> str:
    """Find or create one tag vertex and return its ``_id``."""
    return db.tags.value.upsert([{"rel": rel, "value": value}], match_field=["rel", "value"])[0]


def resolve_tag_ids(
    db: Database,
    pairs: Sequence[tuple[str, TagValue]],
) -> dict[tuple[str, TagValue], str]:
    """Batch-resolve tag ids for ``(rel, value)`` pairs."""
    if not pairs:
        return {}

    resolved: dict[tuple[str, TagValue], str] = {}
    for rel, value in dict.fromkeys(pairs):
        matches = db.tags.get.many.by_filter({"rel": rel, "value": value}, limit=1)
        if not matches:
            continue
        tag_id = matches[0].get("_id")
        if tag_id is not None:
            resolved[(rel, value)] = str(tag_id)
    return resolved


def _find_song_rel_edge_ids(db: Database, song_id: str, rel: str) -> list[str]:
    """Return ``song_has_tags`` edge ids for one song + rel pair."""
    edge_ids: list[str] = []
    for edge in db.song_has_tags._from.get.many(song_id, limit=None):
        tag_id = edge.get("_to")
        if tag_id is None:
            continue
        tag = db.tags.get(str(tag_id))
        if tag is None or tag.get("rel") != rel:
            continue
        edge_id = edge.get("_id")
        if edge_id is not None:
            edge_ids.append(str(edge_id))
    return edge_ids


def set_song_tags(db: Database, song_id: str, rel: str, values: list[TagValue]) -> None:
    """Replace all tags for one ``song_id`` + ``rel`` pair."""
    edge_ids = _find_song_rel_edge_ids(db, song_id, rel)
    if edge_ids:
        db.song_has_tags.delete(edge_ids)
    if not values:
        return

    tag_id_map = {value: find_or_create_tag(db, rel, value) for value in values}
    edge_docs = [{"_from": song_id, "_to": tag_id_map[value]} for value in values if value in tag_id_map]
    if edge_docs:
        db.song_has_tags._to.upsert(edge_docs, match_field=["_from", "_to"])


def set_song_tags_batch(db: Database, entries: list[dict[str, Any]]) -> None:
    """Replace tags for many ``(song_id, rel)`` pairs as component composition.

    This supersedes the old persistence primitive from ADR-010. The operation is
    now expressed as component-layer coordination of constructor-backed verbs:
    targeted edge deletion, tag upsert, then edge upsert (idempotent).

    Args:
        db: Database handle used to replace tag edges and upsert referenced tags.
        entries: Batch entries to apply. Each entry must contain ``song_id`` for
            the song vertex id, ``rel`` for the tag relation being replaced, and
            ``values`` for the list of tag values to attach for that pair.
    """
    if not entries:
        return

    edge_ids: list[str] = []
    upsert_pairs: list[tuple[str, TagValue]] = []
    entry_pairs: list[tuple[str, str, list[TagValue]]] = []
    for entry in entries:
        song_id = str(entry["song_id"])
        rel = str(entry["rel"])
        values = [cast("TagValue", value) for value in entry["values"]]
        entry_pairs.append((song_id, rel, values))
        edge_ids.extend(_find_song_rel_edge_ids(db, song_id, rel))
        upsert_pairs.extend((rel, value) for value in values)

    if edge_ids:
        db.song_has_tags.delete(edge_ids)

    if not upsert_pairs:
        return

    tag_ids = {(rel, value): find_or_create_tag(db, rel, value) for rel, value in upsert_pairs}

    edge_docs: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str]] = set()
    for song_id, rel, values in entry_pairs:
        for value in values:
            tag_id = tag_ids.get((rel, value))
            if tag_id is not None:
                edge_key = (song_id, tag_id)
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    edge_docs.append({"_from": song_id, "_to": tag_id})
    if edge_docs:
        db.song_has_tags._to.upsert(edge_docs, match_field=["_from", "_to"])


def add_song_tag(db: Database, song_id: str, rel: str, value: TagValue) -> None:
    """Add one tag value to a song without replacing other values for the rel."""
    tag_id = find_or_create_tag(db, rel, value)
    db.song_has_tags._to.upsert([{"_from": song_id, "_to": tag_id}], match_field=["_from", "_to"])


def delete_song_tags(db: Database, song_id: str) -> None:
    """Delete all tag edges for one song."""
    db.song_has_tags._from.delete(song_id)


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
        db.song_has_tags._to.get.many(source_tag_id, limit=None),
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
            db.song_has_tags._to.get.many(target_tag_id, limit=None),
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
    if moved_edge_ids:
        db.song_has_tags.delete(moved_edge_ids)

    remaining_source_edges = cast(
        "list[dict[str, Any]]",
        db.song_has_tags._to.get.many(source_tag_id, limit=None),
    )
    source_orphaned = len(remaining_source_edges) == 0
    if source_orphaned:
        cleanup_orphaned_tags(db)

    moved = len(edges_to_insert)
    skipped = len(source_edges) - moved
    return {"moved": moved, "skipped": skipped, "source_orphaned": source_orphaned}
