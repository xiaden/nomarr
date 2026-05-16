"""Component-owned persistence helpers for ML model registration.

This module centralizes ML model and model-output persistence access so
workflows and services stay on the right side of the architecture boundary
while the schema constructor owns the public persistence facade.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def _model_key(path: str) -> str:
    """Return the stable document key used for one registered model path."""
    return hashlib.sha256(path.encode()).hexdigest()[:16]


def _output_key(model_id: str, output_index: int) -> str:
    """Return the stable document key used for one model output vertex."""
    return hashlib.sha256(f"{model_id}:{output_index}".encode()).hexdigest()[:16]


def list_registered_models(db: Database) -> list[dict[str, Any]]:
    """Return every registered ML model document."""
    return cast("list[dict[str, Any]]", db.ml.list_models())


def get_registered_model_by_path(db: Database, path: str) -> dict[str, Any] | None:
    """Return the registered model document for ``path`` if present."""
    return cast("dict[str, Any] | None", db.ml.get_model_by_path(path))


def upsert_registered_model(
    db: Database,
    *,
    path: str,
    backbone: str,
    head_type: str,
    model_stem: str,
    output_count: int,
    source: str = "discovered",
    head_release_date: str = "",
    embedder_release_date: str = "",
) -> dict[str, Any]:
    """Insert or update one registered model via constructor verbs.

    Args:
        db: Database instance
        path: Model file path used as the registry identity.
        backbone: Backbone name associated with the model.
        head_type: Head type produced by the model.
        model_stem: Stem name used to group related model artifacts.
        output_count: Number of output vertices expected for the model.
        source: Registration source label.
        head_release_date: Release date recorded for the head artifact.
        embedder_release_date: Release date recorded for the embedder artifact.

    Returns:
        Persisted ``ml_models`` document, including ArangoDB fields such as
        ``_id`` and ``_key`` plus the registered model metadata.

    """
    existing = get_registered_model_by_path(db, path)
    timestamp = now_ms().value
    payload: dict[str, Any] = {
        "_key": _model_key(path),
        "path": path,
        "backbone": backbone,
        "head_type": head_type,
        "model_stem": model_stem,
        "output_count": output_count,
        "source": source,
        "head_release_date": head_release_date,
        "embedder_release_date": embedder_release_date,
        "updated_at": timestamp,
    }
    if existing is None:
        payload.update(
            {
                "fully_configured": False,
                "is_known": False,
                "registered_at": timestamp,
            }
        )
    else:
        payload.update(
            {
                "fully_configured": existing.get("fully_configured", False),
                "is_known": existing.get("is_known", False),
                "registered_at": existing.get("registered_at", timestamp),
            }
        )

    try:
        return cast("dict[str, Any]", db.ml.add_model(payload))
    except RuntimeError as exc:
        msg = f"Failed to load persisted ml_models document for path={path}"
        raise RuntimeError(msg) from exc


def mark_model_fully_configured(db: Database, model_id: str, value: bool) -> None:
    """Set the ``fully_configured`` flag on one registered model."""
    model_doc = cast("dict[str, Any] | None", db.ml.get_model(model_id))
    if model_doc is None:
        return

    db.ml.update_model(
        model_id,
        {
            "fully_configured": value,
            "updated_at": now_ms().value,
        },
    )


def mark_model_known(db: Database, model_id: str, value: bool) -> None:
    """Set the ``is_known`` flag on one registered model."""
    model_doc = cast("dict[str, Any] | None", db.ml.get_model(model_id))
    if model_doc is None:
        return

    db.ml.update_model(
        model_id,
        {
            "is_known": value,
            "updated_at": now_ms().value,
        },
    )


def delete_registered_model(db: Database, model_id: str) -> None:
    """Delete one registered model vertex by ``_id``."""
    db.ml.remove_model(model_id)


def list_model_outputs_for_model(db: Database, model_id: str) -> list[dict[str, Any]]:
    """Return all output vertices attached to one model, ordered by index."""
    return cast("list[dict[str, Any]]", db.ml.list_model_outputs(model_id))


def list_fully_labeled_model_outputs(db: Database, model_id: str) -> list[dict[str, Any]]:
    """Return only labeled output vertices for one model."""
    return [doc for doc in list_model_outputs_for_model(db, model_id) if bool(doc.get("fully_labeled"))]


def ensure_model_outputs(db: Database, model_id: str, output_count: int) -> list[dict[str, Any]]:
    """Ensure all expected output vertices and edges exist for a model."""
    for output_index in range(output_count):
        output_key = _output_key(model_id, output_index)
        output_id = f"ml_model_outputs/{output_key}"
        existing_output = cast("dict[str, Any] | None", db.ml.get_model_output(output_id))
        payload = {
            "_key": output_key,
            "output_index": output_index,
            "label": None,
            "fully_labeled": False,
        }
        if existing_output is not None:
            payload["label"] = existing_output.get("label")
            payload["fully_labeled"] = existing_output.get("fully_labeled", False)

        db.ml.replace_model_output(model_id, output_key, payload)

    return list_model_outputs_for_model(db, model_id)


def update_model_output_label(db: Database, model_id: str, output_id: str, label: str) -> None:
    """Write label metadata for one output vertex."""
    existing_output = cast("dict[str, Any] | None", db.ml.get_model_output(output_id))
    if existing_output is None:
        return

    db.ml.replace_model_output(
        model_id,
        output_id.split("/", 1)[-1],
        {
            "_key": output_id.split("/", 1)[-1],
            "output_index": existing_output.get("output_index"),
            "label": label,
            "fully_labeled": True,
        },
    )


def build_model_output_index_map(db: Database) -> dict[str, dict[int, str]]:
    """Return ``{model_path: {output_index: output_id}}`` for registered outputs."""
    result: dict[str, dict[int, str]] = {}
    for model_doc in list_registered_models(db):
        model_path = model_doc.get("path")
        model_id = model_doc.get("_id")
        if not isinstance(model_path, str) or not isinstance(model_id, str):
            continue
        for output_doc in list_model_outputs_for_model(db, model_id):
            output_index = output_doc.get("output_index")
            output_id = output_doc.get("_id")
            if isinstance(output_index, int) and isinstance(output_id, str):
                result.setdefault(model_path, {})[output_index] = output_id
    return result


def delete_model_outputs_for_model(db: Database, model_id: str) -> list[str]:
    """Delete all output vertices and model-output edges for one model."""
    return cast("list[str]", db.ml.remove_model_outputs_for_model(model_id))


def prune_registered_model(db: Database, model_id: str) -> dict[str, list[str]]:
    """Delete a stale model along with its outputs.

    Args:
        db: Database instance
        model_id: ArangoDB ``_id`` of the model to delete.

    Returns:
        Summary containing ``output_ids`` for deleted output vertices.

    """
    deleted_output_ids = delete_model_outputs_for_model(db, model_id)
    delete_registered_model(db, model_id)
    return {
        "output_ids": deleted_output_ids,
    }
