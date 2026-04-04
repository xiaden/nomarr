"""Operations for the ml_model_outputs collection.

ml_model_outputs stores one vertex document per output activation of an
ONNX head model.  Documents are keyed by a stable hash of
``(model_id, output_index)`` so upserts are idempotent.

Each output document carries the human-readable ``label`` string that
displays in the UI, editable by the user at runtime.  The
``fully_labeled`` flag mirrors whether a ``label`` has been set for this
activation.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
from typing import Any, cast

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)


def _output_key(model_id: str, output_index: int) -> str:
    """Compute a stable, ArangoDB-safe document key for a model output.

    Args:
        model_id: ArangoDB ``_id`` of the parent model vertex.
        output_index: Zero-based index of the activation.

    Returns:
        16-character lowercase hex string.

    """
    return hashlib.sha256(f"{model_id}:{output_index}".encode()).hexdigest()[:16]


class MLModelOutputsOperations:
    """Operations for the ml_model_outputs collection."""

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
        self.collection = db.collection("ml_model_outputs")

    def upsert_outputs(self, model_id: str, output_count: int) -> list[dict[str, Any]]:
        """Ensure *output_count* output vertices exist for *model_id*.

        Existing documents are left untouched so that user-assigned labels
        survive a restart. New documents are inserted with
        ``fully_labeled=False``.

        Creates ``model_has_output`` edges linking the model vertex to each
        output vertex.

        Args:
            model_id: ArangoDB ``_id`` of the parent model vertex
                (e.g. ``"ml_models/abc1234567890123"``).
            output_count: Number of output activations to ensure.

        Returns:
            All output documents for the model after the upsert, sorted
            ascending by ``output_index``.

        """
        edge_collection = cast("Any", self.db.collection("model_has_output"))
        for i in range(output_count):
            _key = _output_key(model_id, i)
            existing = self.collection.get(_key)  # type: ignore[union-attr]
            if existing is None:
                doc: dict[str, Any] = {
                    "_key": _key,
                    "output_index": i,
                    "label": None,
                    "fully_labeled": False,
                }
                self.collection.insert(doc)  # type: ignore[union-attr]
            # UPSERT edge: model -> output
            output_id = f"ml_model_outputs/{_key}"
            edge_key = _key  # Same key for idempotent edge
            edge_doc = {"_key": edge_key, "_from": model_id, "_to": output_id}
            with contextlib.suppress(Exception):
                edge_collection.insert(edge_doc)  # Ignore if edge exists
        return self.get_outputs_for_model(model_id)

    def update_label(
        self,
        output_id: str,
        label: str,
    ) -> None:
        """Write label metadata for a single output vertex.

        Also sets ``fully_labeled=True`` on the document.

        Args:
            output_id: ArangoDB ``_id`` of the output vertex
                (e.g. ``"ml_model_outputs/abc1234567890123"``).
            label: Human-readable tag name for this activation.

        """
        _key = output_id.split("/", 1)[-1]
        self.collection.update(  # type: ignore[union-attr]
            {
                "_key": _key,
                "label": label,
                "fully_labeled": True,
                "updated_at": now_ms().value,
            }
        )

    def get_outputs_for_model(self, model_id: str) -> list[dict[str, Any]]:
        """Return all output vertices for a model, ordered by ``output_index``.

        Uses ``model_has_output`` edge traversal from the model vertex.

        Args:
            model_id: ArangoDB ``_id`` of the parent model vertex.

        Returns:
            List of output documents sorted ascending by ``output_index``.

        """
        query = """
            FOR o IN OUTBOUND @model_id model_has_output
                SORT o.output_index ASC
                RETURN o
        """
        cursor = cast("Any", self.db.aql.execute(query, bind_vars={"model_id": model_id}))
        return [dict(doc) for doc in cursor]

    def get_fully_labeled_outputs(self, model_id: str) -> list[dict[str, Any]]:
        """Return only fully-labeled output vertices for a model.

        Uses ``model_has_output`` edge traversal from the model vertex.

        Used by the inference pipeline to build the label vector that maps
        activation indices to tag names.

        Args:
            model_id: ArangoDB ``_id`` of the parent model vertex.

        Returns:
            Labeled output documents sorted ascending by ``output_index``.

        """
        query = """
            FOR o IN OUTBOUND @model_id model_has_output
                FILTER o.fully_labeled == true
                SORT o.output_index ASC
                RETURN o
        """
        cursor = cast("Any", self.db.aql.execute(query, bind_vars={"model_id": model_id}))
        return [dict(doc) for doc in cursor]

    def get_output_id_map(self) -> dict[str, dict[str, str]]:
        """Build a mapping of model ONNX path to {label: output_id}.

        Uses ``model_has_output`` edge traversal to join models with outputs.

        Only outputs with a non-null ``label`` are included.

        Returns:
            ``{model_path: {label: output_id}}`` for every labeled output.

        """
        query = """
            FOR m IN ml_models
                FOR o IN OUTBOUND m model_has_output
                    FILTER o.label != null
                    RETURN {path: m.path, label: o.label, output_id: o._id}
        """
        cursor = cast("Any", self.db.aql.execute(query))
        result: dict[str, dict[str, str]] = {}
        for doc in cursor:
            result.setdefault(doc["path"], {})[doc["label"]] = doc["output_id"]
        return result

    def delete_outputs_for_model(self, model_id: str) -> list[str]:
        """Delete all output vertices for *model_id* and return their ids.

        Also removes ``model_has_output`` edges linking the model to its outputs.

        Callers must cascade-delete all ``tag_model_output`` edges
        whose ``_to`` points to the returned ids **before** removing
        the parent ``ml_models`` vertex.

        Args:
            model_id: ArangoDB ``_id`` of the parent model vertex
                (e.g. ``"ml_models/abc1234567890123"``).

        Returns:
            List of ``_id`` values of the deleted output vertices.

        """
        query = """
            LET outputs = (
                FOR o IN OUTBOUND @model_id model_has_output
                    RETURN o._id
            )
            LET _edge_del = (
                FOR e IN model_has_output
                    FILTER e._from == @model_id
                    REMOVE e IN model_has_output
            )
            LET _output_del = (
                FOR oid IN outputs
                    REMOVE PARSE_IDENTIFIER(oid).key IN ml_model_outputs
            )
            RETURN outputs
        """
        cursor = cast("Any", self.db.aql.execute(query, bind_vars={"model_id": model_id}))
        result = list(cursor)
        return list(result[0]) if result else []
