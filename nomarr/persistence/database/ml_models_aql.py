"""Operations for the ml_models collection.

ml_models stores one vertex document per ONNX head model file.
Each document records the filesystem path, structural metadata derived
from the path convention, the output dimension count introspected from
the ONNX session, and a ``fully_configured`` flag that gates inference:
only models where every output dimension has a user-assigned label will
be returned by discovery.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, cast

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)


def _model_key(path: str) -> str:
    """Compute a stable, ArangoDB-safe document key for a model path.

    Uses the first 16 hex digits of SHA-256 so the key is always valid
    and deterministic across restarts.

    Args:
        path: Absolute path to the ONNX model file.

    Returns:
        16-character lowercase hex string.

    """
    return hashlib.sha256(path.encode()).hexdigest()[:16]


class MLModelsOperations:
    """Operations for the ml_models collection."""

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
        self.collection = db.collection("ml_models")

    def upsert_model(
        self,
        path: str,
        backbone: str,
        head_type: str,
        model_stem: str,
        output_count: int,
        source: str = "discovered",
        head_release_date: str = "",
        embedder_release_date: str = "",
    ) -> dict[str, Any]:
        """Insert or update a model vertex document.

        Preserves ``fully_configured``, ``is_known``, and ``registered_at`` on
        update so that re-running at startup does not clobber user configuration.

        Args:
            path: Absolute path to the ONNX file.
            backbone: Backbone identifier (e.g. ``"effnet"``).
            head_type: Head activation type directory (e.g. ``"sigmoid"``).
            model_stem: Filename stem (e.g. ``"mood_happy"``).
            output_count: Number of output activations from the ONNX session.
            source: Origin string — ``"known"``, ``"user"``, or ``"discovered"``.
            head_release_date: ISO date from the head sidecar JSON
                (e.g. ``"2022-08-25"``).  Stored verbatim for tag-key
                generation.
            embedder_release_date: ISO date from the backbone sidecar JSON
                (e.g. ``"2021-06-04"``).  Stored verbatim for tag-key
                generation.

        Returns:
            The upserted document as stored in ArangoDB.

        """
        _key = _model_key(path)
        ts = now_ms().value

        existing = self.collection.get(_key)  # type: ignore[union-attr]
        if existing is not None:
            update: dict[str, Any] = {
                "_key": _key,
                "path": path,
                "backbone": backbone,
                "head_type": head_type,
                "model_stem": model_stem,
                "output_count": output_count,
                "source": source,
                "head_release_date": head_release_date,
                "embedder_release_date": embedder_release_date,
                "updated_at": ts,
            }
            self.collection.update(update)  # type: ignore[union-attr]
            return dict(self.collection.get(_key))  # type: ignore[union-attr, arg-type]

        doc: dict[str, Any] = {
            "_key": _key,
            "path": path,
            "backbone": backbone,
            "head_type": head_type,
            "model_stem": model_stem,
            "output_count": output_count,
            "fully_configured": False,
            "is_known": False,
            "source": source,
            "head_release_date": head_release_date,
            "embedder_release_date": embedder_release_date,
            "registered_at": ts,
            "updated_at": ts,
        }
        self.collection.insert(doc)  # type: ignore[union-attr]
        return dict(self.collection.get(_key))  # type: ignore[union-attr, arg-type]

    def get_model_by_path(self, path: str) -> dict[str, Any] | None:
        """Return the model vertex for *path*, or ``None`` if not registered.

        Args:
            path: Absolute path to the ONNX file.

        Returns:
            Model document or ``None``.

        """
        _key = _model_key(path)
        result = self.collection.get(_key)  # type: ignore[union-attr]
        return dict(result) if result is not None else None  # type: ignore[union-attr, arg-type]

    def list_models(self) -> list[dict[str, Any]]:
        """Return all registered model documents.

        Returns:
            List of model documents, unsorted.

        """
        cursor = cast("Any", self.db.aql.execute("FOR m IN ml_models RETURN m"))
        return [dict(doc) for doc in cursor]

    def set_fully_configured(self, model_id: str, value: bool) -> None:
        """Update the ``fully_configured`` flag for a model.

        Args:
            model_id: ArangoDB ``_id`` of the model vertex
                (e.g. ``"ml_models/abc1234567890123"``).
            value: New fully-configured state.

        """
        _key = model_id.split("/", 1)[-1]
        self.collection.update({"_key": _key, "fully_configured": value, "updated_at": now_ms().value})  # type: ignore[union-attr]

    def set_is_known(self, model_id: str, value: bool) -> None:
        """Update the ``is_known`` flag for a model.

        Args:
            model_id: ArangoDB ``_id`` of the model vertex.
            value: New is-known state.

        """
        _key = model_id.split("/", 1)[-1]
        self.collection.update({"_key": _key, "is_known": value, "updated_at": now_ms().value})  # type: ignore[union-attr]

    def delete_model(self, model_id: str) -> None:
        """Delete the *ml_models* vertex for *model_id*.

        Callers are responsible for removing child ``ml_model_outputs``
        vertices **and** all inbound/outbound ``tag_model_output`` edges
        before calling this method so that the graph is left consistent.

        Args:
            model_id: ArangoDB ``_id`` of the model vertex
                (e.g. ``"ml_models/abc1234567890123"``).

        """
        _key = model_id.split("/", 1)[-1]
        self.collection.delete(_key, ignore_missing=True)  # type: ignore[union-attr]
