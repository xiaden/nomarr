"""Component-owned persistence helpers for ML model registration.

This module absorbs all remaining ``db.ml_models.*`` and
``db.ml_model_outputs.*`` call patterns so workflows and services can stay on
the right side of the architecture boundary while the schema constructor owns
the public persistence facade.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, cast

from nomarr.components.ml.onnx.tag_model_output_comp import delete_tag_model_output_edges_for_outputs
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
    model_count = db.ml_models.count()
    if model_count <= 0:
        return []

    ids = [str(row["value"]) for row in db.ml_models.aggregate("_id", limit=model_count) if "value" in row]
    if not ids:
        return []

    docs = [cast("dict[str, Any] | None", db.ml_models.get(_id=model_id)) for model_id in ids]
    return [doc for doc in docs if doc is not None]


def get_registered_model_by_path(db: Database, path: str) -> dict[str, Any] | None:
    """Return the registered model document for ``path`` if present."""
    return cast("dict[str, Any] | None", db.ml_models.get(path=path))


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

    db.ml_models.upsert(path=path, fields={key: value for key, value in payload.items() if key != "path"})
    model_doc = get_registered_model_by_path(db, path)
    if model_doc is None:
        msg = f"Failed to load persisted ml_models document for path={path}"
        raise RuntimeError(msg)
    return model_doc


def mark_model_fully_configured(db: Database, model_id: str, value: bool) -> None:
    """Set the ``fully_configured`` flag on one registered model."""
    model_doc = cast("dict[str, Any] | None", db.ml_models.get(_id=model_id))
    if model_doc is None:
        return

    db.ml_models.upsert(
        path=cast("str", model_doc["path"]),
        fields={
            **{key: field for key, field in model_doc.items() if key not in {"_rev", "path"}},
            "fully_configured": value,
            "updated_at": now_ms().value,
        },
    )


def mark_model_known(db: Database, model_id: str, value: bool) -> None:
    """Set the ``is_known`` flag on one registered model."""
    model_doc = cast("dict[str, Any] | None", db.ml_models.get(_id=model_id))
    if model_doc is None:
        return

    db.ml_models.upsert(
        path=cast("str", model_doc["path"]),
        fields={
            **{key: field for key, field in model_doc.items() if key not in {"_rev", "path"}},
            "is_known": value,
            "updated_at": now_ms().value,
        },
    )


def delete_registered_model(db: Database, model_id: str) -> None:
    """Delete one registered model vertex by ``_id``."""
    db.ml_models.delete(_id=model_id)


def list_model_outputs_for_model(db: Database, model_id: str) -> list[dict[str, Any]]:
    """Return all output vertices attached to one model, ordered by index."""
    outputs = cast(
        "list[dict[str, Any]]",
        db.ml_models.model_has_output(model_id, limit=db.ml_model_outputs.count()),
    )
    return sorted(outputs, key=lambda doc: int(cast("int", doc.get("output_index", 0))))


def list_fully_labeled_model_outputs(db: Database, model_id: str) -> list[dict[str, Any]]:
    """Return only labeled output vertices for one model."""
    return [doc for doc in list_model_outputs_for_model(db, model_id) if bool(doc.get("fully_labeled"))]


def ensure_model_outputs(db: Database, model_id: str, output_count: int) -> list[dict[str, Any]]:
    """Ensure all expected output vertices and edges exist for a model."""
    for output_index in range(output_count):
        output_key = _output_key(model_id, output_index)
        if db.ml_model_outputs.get(_key=output_key) is None:
            db.ml_model_outputs.insert(
                [
                    {
                        "_key": output_key,
                        "output_index": output_index,
                        "label": None,
                        "fully_labeled": False,
                    }
                ]
            )

        db.model_has_output.upsert(_key=output_key, fields={"_from": model_id, "_to": f"ml_model_outputs/{output_key}"})

    return list_model_outputs_for_model(db, model_id)


def update_model_output_label(db: Database, output_id: str, label: str) -> None:
    """Write label metadata for one output vertex."""
    output_key = output_id.split("/", 1)[-1]
    db.ml_model_outputs.update(
        _key=output_key,
        fields={
            "label": label,
            "fully_labeled": True,
        },
    )


def build_model_output_id_map(db: Database) -> dict[str, dict[str, str]]:
    """Return ``{model_path: {label: output_id}}`` for labeled outputs."""
    result: dict[str, dict[str, str]] = {}
    for model_doc in list_registered_models(db):
        model_path = model_doc.get("path")
        model_id = model_doc.get("_id")
        if not isinstance(model_path, str) or not isinstance(model_id, str):
            continue
        for output_doc in list_model_outputs_for_model(db, model_id):
            label = output_doc.get("label")
            output_id = output_doc.get("_id")
            if isinstance(label, str) and isinstance(output_id, str):
                result.setdefault(model_path, {})[label] = output_id
    return result


def delete_model_outputs_for_model(db: Database, model_id: str) -> list[str]:
    """Delete all output vertices and model-output edges for one model."""
    outputs = list_model_outputs_for_model(db, model_id)
    if not outputs:
        return []

    output_ids = [cast("str", output_doc["_id"]) for output_doc in outputs if "_id" in output_doc]
    edge_ids = [
        f"model_has_output/{output_doc['_key']}" for output_doc in outputs if isinstance(output_doc.get("_key"), str)
    ]

    if edge_ids:
        db.model_has_output.delete.in_(_id=edge_ids)  # type: ignore[union-attr]
    db.ml_model_outputs.delete.in_(_id=output_ids)  # type: ignore[union-attr]
    return output_ids


def prune_registered_model(db: Database, model_id: str) -> dict[str, int | list[str]]:
    """Delete a stale model along with its outputs and tag edges.

    Args:
        db: Database instance
        model_id: ArangoDB ``_id`` of the model to delete.

    Returns:
        Summary containing ``output_ids`` for deleted output vertices and
        ``tag_model_output_edges_deleted`` for the number of removed tag edges.

    """
    output_ids = [cast("str", output_doc["_id"]) for output_doc in list_model_outputs_for_model(db, model_id)]
    edge_count = delete_tag_model_output_edges_for_outputs(db, output_ids) if output_ids else 0
    deleted_output_ids = delete_model_outputs_for_model(db, model_id)
    delete_registered_model(db, model_id)
    return {
        "output_ids": deleted_output_ids,
        "tag_model_output_edges_deleted": edge_count,
    }
