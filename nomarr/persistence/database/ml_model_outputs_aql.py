"""Operations for the ml_model_outputs collection.

ml_model_outputs stores one vertex document per output activation of an
ONNX head model.  Documents are keyed by a stable hash of
``(model_id, output_index)`` so upserts are idempotent.

Each output document carries the human-readable ``label`` string that
displays in the UI, a ``is_positive`` flag (``True`` means higher score
→ more matching), and an optional ``display_hint`` — all editable by
the user at runtime.  The ``fully_labeled`` flag is recomputed on every
label write and mirrors whether *both* ``label`` and ``is_positive`` have
been set for this activation.
"""

from __future__ import annotations

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
        and ``is_positive`` settings survive a restart. New documents are
        inserted with ``fully_labeled=False``.

        Args:
            model_id: ArangoDB ``_id`` of the parent model vertex
                (e.g. ``"ml_models/abc1234567890123"``).
            output_count: Number of output activations to ensure.

        Returns:
            All output documents for the model after the upsert, sorted
            ascending by ``output_index``.

        """
        ts = now_ms().value
        for i in range(output_count):
            _key = _output_key(model_id, i)
            existing = self.collection.get(_key)  # type: ignore[union-attr]
            if existing is None:
                doc: dict[str, Any] = {
                    "_key": _key,
                    "model_id": model_id,
                    "output_index": i,
                    "label": None,
                    "is_positive": None,
                    "display_hint": None,
                    "fully_labeled": False,
                    "created_at": ts,
                    "updated_at": ts,
                }
                self.collection.insert(doc)  # type: ignore[union-attr]
        return self.get_outputs_for_model(model_id)

    def update_label(
        self,
        output_id: str,
        label: str,
        is_positive: bool,
        display_hint: str | None = None,
    ) -> None:
        """Write label metadata for a single output vertex.

        Also sets ``fully_labeled=True`` on the document because both
        required fields are being supplied.

        Args:
            output_id: ArangoDB ``_id`` of the output vertex
                (e.g. ``"ml_model_outputs/abc1234567890123"``).
            label: Human-readable tag name for this activation.
            is_positive: Whether higher activation score means "more matching".
            display_hint: Optional rendering hint for the UI.

        """
        _key = output_id.split("/", 1)[-1]
        self.collection.update(  # type: ignore[union-attr]
            {
                "_key": _key,
                "label": label,
                "is_positive": is_positive,
                "display_hint": display_hint,
                "fully_labeled": True,
                "updated_at": now_ms().value,
            }
        )

    def get_outputs_for_model(self, model_id: str) -> list[dict[str, Any]]:
        """Return all output vertices for a model, ordered by ``output_index``.

        Args:
            model_id: ArangoDB ``_id`` of the parent model vertex.

        Returns:
            List of output documents sorted ascending by ``output_index``.

        """
        query = """
            FOR o IN ml_model_outputs
                FILTER o.model_id == @model_id
                SORT o.output_index ASC
                RETURN o
        """
        cursor = cast("Any", self.db.aql.execute(query, bind_vars={"model_id": model_id}))
        return [dict(doc) for doc in cursor]

    def get_fully_labeled_outputs(self, model_id: str) -> list[dict[str, Any]]:
        """Return only fully-labeled output vertices for a model.

        Used by the inference pipeline to build the label vector that maps
        activation indices to tag names.

        Args:
            model_id: ArangoDB ``_id`` of the parent model vertex.

        Returns:
            Labeled output documents sorted ascending by ``output_index``.

        """
        query = """
            FOR o IN ml_model_outputs
                FILTER o.model_id == @model_id
                FILTER o.fully_labeled == true
                SORT o.output_index ASC
                RETURN o
        """
        cursor = cast("Any", self.db.aql.execute(query, bind_vars={"model_id": model_id}))
        return [dict(doc) for doc in cursor]


    def get_output_id_map(self) -> dict[str, dict[str, str]]:
        """Build a mapping of model ONNX path to {label: output_id}.

        Joins ``ml_models`` with ``ml_model_outputs`` to produce a
        nested lookup that the inference pipeline uses to resolve
        ``tag_model_output`` edge targets.

        Only outputs with a non-null ``label`` are included.

        Returns:
            ``{model_path: {label: output_id}}`` for every labeled output.

        """
        query = """
            FOR m IN ml_models
                FOR o IN ml_model_outputs
                    FILTER o.model_id == m._id
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
            LET removed = (
                FOR o IN ml_model_outputs
                    FILTER o.model_id == @model_id
                    REMOVE o IN ml_model_outputs
                    RETURN OLD._id
            )
            RETURN removed
        """
        cursor = cast("Any", self.db.aql.execute(query, bind_vars={"model_id": model_id}))
        result = list(cursor)
        return list(result[0]) if result else []
