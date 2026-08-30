"""Component-owned persistence helpers for ML model-output registration.

This module centralizes ML model-output persistence access so workflows and
services stay on the right side of the architecture boundary while the schema
constructor owns the public persistence facade.

Model registration itself lives on ``db.ml`` (see ``nomarr.persistence.api.ml``)
and returns domain ``RegisteredModel`` objects.  This module retains only the
output-vertex helpers (``ml_model_outputs``), which are model-scoped metadata.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.ml_model_output_dataclass import ModelOutput
    from nomarr.persistence.db import Database


def _output_key(model_id: str, output_index: int) -> str:
    """Return the stable document key used for one model output vertex."""
    return hashlib.sha256(f"{model_id}:{output_index}".encode()).hexdigest()[:16]


def list_model_outputs_for_model(db: Database, model_id: str) -> list[ModelOutput]:
    """Return all output vertices attached to one model, ordered by index."""
    return db.ml.list_model_outputs(model_id)


def list_fully_labeled_model_outputs(db: Database, model_id: str) -> list[ModelOutput]:
    """Return only labeled output vertices for one model."""
    return [doc for doc in list_model_outputs_for_model(db, model_id) if doc.fully_labeled]


def ensure_model_outputs(db: Database, model_id: str, output_count: int) -> list[ModelOutput]:
    """Ensure all expected output vertices exist for a model.

    Model outputs are model-scoped metadata: no song context is involved.
    """
    for output_index in range(output_count):
        output_key = _output_key(model_id, output_index)
        existing = db.ml.get_model_output(output_key)
        label: str | None = None
        fully_labeled = False
        if existing is not None:
            label = existing.label
            fully_labeled = existing.fully_labeled

        db.ml.replace_model_output(
            model_id,
            output_key,
            output_index=output_index,
            label=label,
            fully_labeled=fully_labeled,
        )

    return list_model_outputs_for_model(db, model_id)


def update_model_output_label(db: Database, model_id: str, output_id: str, label: str) -> None:
    """Write label metadata for one output vertex."""
    existing_output = db.ml.get_model_output(output_id)
    if existing_output is None:
        return

    db.ml.replace_model_output(
        model_id,
        output_id,
        output_index=existing_output.output_index,
        label=label,
        fully_labeled=True,
    )
