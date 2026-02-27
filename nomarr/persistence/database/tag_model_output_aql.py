"""Operations for the tag_model_output edge collection.

tag_model_output stores directed edges from a ``tags`` vertex to an
``ml_model_outputs`` vertex.  Each edge represents the fact that a
particular tag is *produced* by a specific output activation of a
registered ML model.

Edge keys are stable SHA-256 hashes of ``(tag_id, output_id)`` so that
upserts are idempotent and duplicate edges cannot be created.

The orphan-tag cleanup query (``tags_aql/cleanup.py``) must also consult
this collection to determine whether a tag is still in use.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, cast

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)


def _edge_key(tag_id: str, output_id: str) -> str:
    """Compute a stable edge key for *(tag_id, output_id)*.

    Args:
        tag_id: ArangoDB ``_id`` of the tag vertex (e.g. ``"tags/abc123"``).
        output_id: ArangoDB ``_id`` of the output vertex
            (e.g. ``"ml_model_outputs/abc123"``).

    Returns:
        16-character lowercase hex string.

    """
    return hashlib.sha256(f"{tag_id}:{output_id}".encode()).hexdigest()[:16]


class TagModelOutputOperations:
    """Operations for the tag_model_output edge collection."""

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
        self.collection = db.collection("tag_model_output")

    def write_edge(
        self,
        tag_id: str,
        output_id: str,
        score: float,
    ) -> None:
        """Insert or update a tag→output edge.

        This is idempotent: calling it multiple times with the same
        *(tag_id, output_id)* pair updates ``score`` and ``updated_at`` in
        place rather than creating duplicate edges.

        Args:
            tag_id: ArangoDB ``_id`` of the source tag vertex.
            output_id: ArangoDB ``_id`` of the destination output vertex.
            score: Activation score that triggered this edge (0.0 - 1.0).

        """
        _key = _edge_key(tag_id, output_id)
        ts = now_ms().value
        existing = self.collection.get(_key)  # type: ignore[union-attr]
        if existing is not None:
            self.collection.update({"_key": _key, "score": score, "updated_at": ts})  # type: ignore[union-attr]
        else:
            doc: dict[str, Any] = {
                "_key": _key,
                "_from": tag_id,
                "_to": output_id,
                "score": score,
                "created_at": ts,
                "updated_at": ts,
            }
            self.collection.insert(doc)  # type: ignore[union-attr]

    def write_edges_batch(
        self,
        edges: list[tuple[str, str, float]],
    ) -> None:
        """Batch-upsert tag→output edges in a single AQL round-trip.

        Each edge is ``(tag_id, output_id, score)``. Idempotent: existing
        edges are updated in place.

        Args:
            edges: List of ``(tag_id, output_id, score)`` tuples.

        """
        if not edges:
            return
        ts = now_ms().value
        bind_edges = [
            {
                "_key": _edge_key(tag_id, output_id),
                "_from": tag_id,
                "_to": output_id,
                "score": score,
            }
            for tag_id, output_id, score in edges
        ]
        self.db.aql.execute(
            """
            FOR e IN @edges
                UPSERT { _key: e._key }
                INSERT { _key: e._key, _from: e._from, _to: e._to,
                         score: e.score, created_at: @ts, updated_at: @ts }
                UPDATE { score: e.score, updated_at: @ts }
                IN tag_model_output
            """,
            bind_vars=cast("dict[str, Any]", {"edges": bind_edges, "ts": ts}),
        )
    def delete_edges_for_tag(self, tag_id: str) -> int:
        """Remove all outbound edges from *tag_id*.

        Used when a tag is deleted or re-assigned so that stale provenance
        edges do not accumulate.

        Args:
            tag_id: ArangoDB ``_id`` of the tag vertex.

        Returns:
            Number of edge documents removed.

        """
        query = """
            LET removed = (
                FOR edge IN tag_model_output
                    FILTER edge._from == @tag_id
                    REMOVE edge IN tag_model_output
                    RETURN 1
            )
            RETURN LENGTH(removed)
        """
        cursor = cast("Any", self.db.aql.execute(query, bind_vars={"tag_id": tag_id}))
        result = list(cursor)
        return int(result[0]) if result else 0

    def has_any_edge(self, tag_id: str) -> bool:
        """Return ``True`` if *tag_id* has at least one outbound edge.

        Used by the orphan-tag cleanup to determine whether a tag produced
        by an ML model is still considered "in use".

        Args:
            tag_id: ArangoDB ``_id`` of the tag vertex.

        Returns:
            ``True`` if at least one tag→output edge exists for *tag_id*.

        """
        query = """
            RETURN LENGTH(
                FOR edge IN tag_model_output
                    FILTER edge._from == @tag_id
                    LIMIT 1
                    RETURN 1
            ) > 0
        """
        cursor = cast("Any", self.db.aql.execute(query, bind_vars={"tag_id": tag_id}))
        result = list(cursor)
        return bool(result[0]) if result else False


    def delete_edges_for_outputs(self, output_ids: list[str]) -> int:
        """Bulk-delete all edges whose ``_to`` is in *output_ids*.

        Called when ``ml_model_outputs`` vertices are removed so that
        stale provenance edges do not accumulate in the graph.

        Args:
            output_ids: List of ArangoDB ``_id`` values of the output
                vertices being removed
                (e.g. ``["ml_model_outputs/abc123", ...]``).

        Returns:
            Number of edge documents removed.

        """
        if not output_ids:
            return 0
        query = """
            LET removed = (
                FOR edge IN tag_model_output
                    FILTER edge._to IN @output_ids
                    REMOVE edge IN tag_model_output
                    RETURN 1
            )
            RETURN LENGTH(removed)
        """
        cursor = cast("Any", self.db.aql.execute(query, bind_vars={"output_ids": output_ids}))
        result = list(cursor)
        return int(result[0]) if result else 0
