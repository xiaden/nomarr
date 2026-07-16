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


async def list_registered_models(db: Database) -> list[dict[str, Any]]:
    """Return every registered ML model document."""
    result = await db.ml.list_models()
    return cast("list[dict[str, Any]]", result if isinstance(result, list) else [])


async def get_registered_model_by_path(db: Database, path: str) -> dict[str, Any] | None:
    """Return the registered model document for ``path`` if present."""
    result = await db.ml.get_model_by_type(path)
    return cast("dict[str, Any] | None", result if isinstance(result, dict) else None)


async def upsert_registered_model(
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
        Persisted ``ml_models`` document, including database fields such as
        primary key plus the registered model metadata.

    """
    existing = await get_registered_model_by_path(db, path)
    timestamp = now_ms().value
    payload: dict[str, Any] = {
        "id": _model_key(path),
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
        result = await db.ml.add_model(payload)
        if not isinstance(result, dict):
            raise RuntimeError(f"Failed to load persisted ml_models document for path={path}")
        return result
    except RuntimeError as exc:
        msg = f"Failed to load persisted ml_models document for path={path}"
        raise RuntimeError(msg) from exc


async def mark_model_fully_configured(db: Database, model_id: str, value: bool) -> None:
    """Set the ``fully_configured`` flag on one registered model."""
    model_doc = await db.ml.get_model(model_id)
    if not isinstance(model_doc, dict):
        return

    await db.ml.update_model(
        model_id,
        {
            "fully_configured": value,
            "updated_at": now_ms().value,
        },
    )


async def mark_model_known(db: Database, model_id: str, value: bool) -> None:
    """Set the ``is_known`` flag on one registered model."""
    model_doc = await db.ml.get_model(model_id)
    if not isinstance(model_doc, dict):
        return

    await db.ml.update_model(
        model_id,
        {
            "is_known": value,
            "updated_at": now_ms().value,
        },
    )


async def delete_registered_model(db: Database, model_id: str) -> None:
    """Delete one registered model vertex by ID."""
    await db.ml.remove_model(model_id)


async def list_model_outputs_for_model(db: Database, model_id: str) -> list[dict[str, Any]]:
    """Return all output vertices attached to one model, ordered by index."""
    result = await db.ml.list_model_outputs(model_id)
    return cast("list[dict[str, Any]]", result if isinstance(result, list) else [])


async def list_fully_labeled_model_outputs(db: Database, model_id: str) -> list[dict[str, Any]]:
    """Return only labeled output vertices for one model."""
    return [doc for doc in await list_model_outputs_for_model(db, model_id) if bool(doc.get("fully_labeled"))]


async def ensure_model_outputs(db: Database, model_id: str, output_count: int) -> list[dict[str, Any]]:
    """Ensure all expected output vertices exist for a model."""
    for output_index in range(output_count):
        output_key = _output_key(model_id, output_index)
        existing = await db.ml.get_model_output(output_index)
        payload = {
            "id": output_key,
            "output_index": output_index,
            "label": None,
            "fully_labeled": False,
        }
        if isinstance(existing, dict):
            payload["label"] = existing.get("label")
            payload["fully_labeled"] = existing.get("fully_labeled", False)

        await db.ml.replace_model_output(model_id, output_key, payload)

    return await list_model_outputs_for_model(db, model_id)


async def update_model_output_label(db: Database, model_id: str, output_id: str, label: str) -> None:
    """Write label metadata for one output vertex."""
    existing_output = await db.ml.get_model_output(output_id)  # type: ignore[arg-type]
    if not isinstance(existing_output, dict):
        return

    await db.ml.replace_model_output(
        model_id,
        output_id,
        {
            "id": output_id,
            "output_index": existing_output.get("output_index"),
            "label": label,
            "fully_labeled": True,
        },
    )


async def build_model_output_index_map(db: Database) -> dict[str, dict[int, str]]:
    """Return ``{model_path: {output_index: output_id}}`` for registered outputs."""
    result: dict[str, dict[int, str]] = {}
    for model_doc in await list_registered_models(db):
        model_path = model_doc.get("path")
        model_id = model_doc.get("id")
        if not isinstance(model_path, str) or not isinstance(model_id, str):
            continue
        for output_doc in await list_model_outputs_for_model(db, model_id):
            output_index = output_doc.get("output_index")
            output_id_key = output_doc.get("id")
            if isinstance(output_index, int) and isinstance(output_id_key, str):
                result.setdefault(model_path, {})[output_index] = output_id_key
    return result


async def delete_model_outputs_for_model(db: Database, model_id: str) -> list[str]:
    """Delete all output vertices for one model."""
    result = await db.ml.remove_model_outputs_for_model(model_id)  # type: ignore[attr-defined]
    if isinstance(result, list):
        return [str(r) for r in result]
    return []


async def prune_registered_model(db: Database, model_id: str) -> dict[str, list[str]]:
    """Delete a stale model along with its outputs.
    Args:
        db: Database instance
        model_id: String ID of the model to delete.
    Returns:
        Summary containing ``output_ids`` for deleted output vertices.
    """
    deleted_output_ids = await delete_model_outputs_for_model(db, model_id)
    await delete_registered_model(db, model_id)
    return {
        "output_ids": deleted_output_ids,
    }
