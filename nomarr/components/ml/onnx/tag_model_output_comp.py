"""Component-owned helpers for tag → model-output provenance edges."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def _edge_key(tag_id: str, output_id: str) -> str:
    """Return the stable `_key` used for one provenance edge."""
    return hashlib.sha256(f"{tag_id}:{output_id}".encode()).hexdigest()[:16]


def write_tag_model_output_edge(db: Database, tag_id: str, output_id: str, score: float) -> None:
    """Insert or update one tag → output provenance edge."""
    write_tag_model_output_edges_batch(db, [(tag_id, output_id, score)])


def write_tag_model_output_edges_batch(db: Database, edges: list[tuple[str, str, float]]) -> None:
    """Insert or update a batch of tag → output provenance edges."""
    if not edges:
        return

    timestamp = now_ms().value
    unique_edges = {(tag_id, output_id): score for tag_id, output_id, score in edges}
    edge_count = db.tag_model_output.count()
    existing_by_tag: dict[str, dict[str, dict[str, Any]]] = {}

    for tag_id, _output_id in unique_edges:
        if tag_id in existing_by_tag:
            continue
        existing_edges = cast(
            "list[dict[str, Any]]",
            db.tag_model_output._from.get.many(tag_id, limit=edge_count or None),
        )
        existing_by_tag[tag_id] = {str(edge["_to"]): edge for edge in existing_edges if "_to" in edge}

    docs_to_insert: list[dict[str, Any]] = []
    for (tag_id, output_id), score in unique_edges.items():
        edge_key = _edge_key(tag_id, output_id)
        existing = existing_by_tag[tag_id].get(output_id)
        if existing is not None:
            db.tag_model_output._key.update(edge_key, {"score": score, "updated_at": timestamp})
            continue
        docs_to_insert.append(
            {
                "_key": edge_key,
                "_from": tag_id,
                "_to": output_id,
                "score": score,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        )

    if docs_to_insert:
        db.tag_model_output.insert(docs_to_insert)


def delete_tag_model_output_edges_for_tag(db: Database, tag_id: str) -> int:
    """Delete all outbound provenance edges for one tag vertex."""
    return int(db.tag_model_output._from.delete(tag_id))


def tag_has_model_output_edges(db: Database, tag_id: str) -> bool:
    """Return whether the tag has any outbound provenance edges."""
    return bool(cast("list[dict[str, Any]]", db.tag_model_output._from.get.many(tag_id, limit=1)))


def delete_tag_model_output_edges_for_outputs(db: Database, output_ids: list[str]) -> int:
    """Delete all provenance edges that target the provided output vertices."""
    deleted = 0
    for output_id in output_ids:
        deleted += int(db.tag_model_output._to.delete(output_id))
    return deleted
