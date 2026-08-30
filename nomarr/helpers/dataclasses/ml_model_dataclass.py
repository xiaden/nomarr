"""Domain value object for a registered ML model.

``RegisteredModel`` is the contract at the ML model persistence intent boundary.
It carries the model's stable identity and architecture metadata only; the
storage row id format, database timestamps, and the ``enabled`` storage flag
remain persistence concerns and are intentionally omitted.

``id`` is the stable model identity (16-hex sha256 of the model ``path``) that
cross-references ``ml_model_outputs`` / ``calibration_states`` rows.  ``path`` is
the human-facing natural registration identity (the ONNX file path).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RegisteredModel:
    """A registered ML head model exposed by the ML intent facade.

    ``id`` is the stable string model key; it is never an int-encoded
    persistence PK.  ``path`` is the natural registration identity.  Row
    metadata (``created_at``/``updated_at``/``registered_at``/``enabled``)
    never crosses this boundary.
    """

    id: str
    path: str
    model_type: str
    backbone_id: str
    backbone: str
    head_type: str
    model_stem: str
    output_count: int
    fully_configured: bool
    is_known: bool
    source: str
    head_release_date: str
    embedder_release_date: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("RegisteredModel.id must not be blank")
        if not isinstance(self.path, str) or not self.path.strip():
            raise ValueError("RegisteredModel.path must not be blank")
        if not isinstance(self.output_count, int):
            raise TypeError("RegisteredModel.output_count must be an int")


__all__ = ["RegisteredModel"]
