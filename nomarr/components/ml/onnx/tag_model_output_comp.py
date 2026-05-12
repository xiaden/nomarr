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
    unique_tag_ids = sorted({tag_id for tag_id, _ in unique_edges})

    # Fetch all existing edges for all involved tags in one IN query.
    all_existing = cast("list[dict[str, Any]]", db.ml.get_tag_model_output_edges_for_tags(unique_tag_ids))
    existing_by_tag: dict[str, dict[str, dict[str, Any]]] = {}
    for edge in all_existing:
        if "_to" not in edge or "_from" not in edge:
            continue
        existing_by_tag.setdefault(str(edge["_from"]), {})[str(edge["_to"])] = edge

    docs_to_insert: list[dict[str, Any]] = []
    docs_to_update: list[dict[str, Any]] = []
    for (tag_id, output_id), score in unique_edges.items():
        edge_key = _edge_key(tag_id, output_id)
        existing = existing_by_tag.get(tag_id, {}).get(output_id)
        if existing is not None:
            docs_to_update.append({"_key": edge_key, "score": score, "updated_at": timestamp})
        else:
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

    if docs_to_update:
        db.ml.update_tag_model_output_edges_batch(docs_to_update)
    if docs_to_insert:
        db.ml.insert_tag_model_output_edges_batch(docs_to_insert)


def delete_tag_model_output_edges_for_tag(db: Database, tag_id: str) -> int:
    """Delete all outbound provenance edges for one tag vertex."""
    return db.ml.delete_tag_model_output_edges_for_tag(tag_id)


def tag_has_model_output_edges(db: Database, tag_id: str) -> bool:
    """Return whether the tag has any outbound provenance edges."""
    return db.ml.count_tag_model_output_edges_for_tag(tag_id) > 0


def delete_tag_model_output_edges_for_outputs(db: Database, output_ids: list[str]) -> int:
    """Delete all provenance edges that target the provided output vertices."""
    if not output_ids:
        return 0

    return db.ml.delete_tag_model_output_edges_for_outputs(output_ids)
