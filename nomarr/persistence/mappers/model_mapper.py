"""Persistence-layer mappers for the ML model registry surface.

Ownership (per ADR-032/ADR-041): ``RegisteredModel`` (in
``nomarr/helpers/dataclasses/ml_model_dataclass.py``) is the domain object for
one registered ML model.  This module lives in the persistence layer and owns
the row-to-domain and domain-to-storage conversions.  It imports helpers
dataclasses/DTOs only — never components, services, workflows, or interfaces.

Storage aliases that stay inside persistence and are translated here:

- The model's stable identity ``id`` is derived from the natural registration
  identity ``path`` (``sha256(path).hexdigest()[:16]``).
- ``model_type`` / ``backbone_id`` are NOT NULL storage columns but redundant
  with the domain ``head_type`` / ``backbone``; they are derived here
  (``model_type = head_type``, ``backbone_id = backbone``) so callers never
  reason about them.
- ``fully_configured`` / ``is_known`` are integer flags in storage and bools on
  the domain object.
- ``enabled``, ``created_at``, ``updated_at``, and ``registered_at`` are storage
  bookkeeping fields and never cross this module's public boundary.  (The
  generated ``id`` is the one exception — it is a *stable content key*, not a
  surrogate, and is exposed so callers can address a model's outputs and
  calibration state.)
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from nomarr.helpers.dataclasses.ml_model_dataclass import RegisteredModel

if TYPE_CHECKING:
    from nomarr.helpers.dto.model_repo_dto import ModelRecord

__all__ = [
    "model_key_from_path",
    "registered_model_from_record",
    "registered_model_insert_payload",
]


def model_key_from_path(path: str) -> str:
    """Return the stable model identity for one registered model path."""
    return hashlib.sha256(path.encode()).hexdigest()[:16]


def registered_model_from_record(record: ModelRecord) -> RegisteredModel:
    """Map a storage ``ModelRecord`` row to a domain ``RegisteredModel``.

    Translation decisions:
    - ``enabled`` / ``created_at`` / ``updated_at`` / ``registered_at`` are dropped.
    - integer flag columns become booleans.
    - nullable string columns fall back to empty strings.
    """
    return RegisteredModel(
        id=record["id"],
        path=record.get("path") or "",
        model_type=record["model_type"],
        backbone_id=record["backbone_id"],
        backbone=record.get("backbone") or "",
        head_type=record.get("head_type") or "",
        model_stem=record.get("model_stem") or "",
        output_count=int(record.get("output_count") or 0),
        fully_configured=bool(record.get("fully_configured") or 0),
        is_known=bool(record.get("is_known") or 0),
        source=record.get("source") or "discovered",
        head_release_date=record.get("head_release_date") or "",
        embedder_release_date=record.get("embedder_release_date") or "",
    )


def registered_model_insert_payload(
    *,
    path: str,
    model_id: str | None = None,
    backbone: str,
    head_type: str,
    model_stem: str,
    output_count: int,
    source: str,
    head_release_date: str,
    embedder_release_date: str,
    fully_configured: bool,
    is_known: bool,
    registered_at: int | None,
) -> dict[str, Any]:
    """Translate registration inputs into the ``ml_models`` upsert payload.

    Storage-side derivations: ``id`` from ``path``, ``model_type`` from
    ``head_type``, ``backbone_id`` from ``backbone``.  ``registered_at`` is
    passed through as the caller supplied it; ``created_at``/``updated_at`` are
    owned by the repository (``ModelRepo.upsert_model`` stamps them).
    """
    return {
        "id": model_id or model_key_from_path(path),
        "path": path,
        "model_type": head_type,
        "backbone_id": backbone,
        "backbone": backbone,
        "head_type": head_type,
        "model_stem": model_stem,
        "output_count": output_count,
        "fully_configured": int(fully_configured),
        "is_known": int(is_known),
        "source": source,
        "head_release_date": head_release_date,
        "embedder_release_date": embedder_release_date,
        "registered_at": registered_at,
    }
