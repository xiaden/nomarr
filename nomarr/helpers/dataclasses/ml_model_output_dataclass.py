"""Domain value object for a persisted ML model output vertex.

This type is the contract at the ML persistence intent boundary for the
``ml_model_outputs`` metadata registry.  It carries only the stable output
identity and the human-facing metadata a caller needs; the integer primary key,
the raw ``output_data`` JSONB blob, the owning model foreign key, and the
creation timestamp remain persistence concerns.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelOutput:
    """Metadata for one ML model output vertex exposed by the ML intent facade.

    ``output_id`` is the stable natural identity (sha256 ``_output_key`` from
    the model registry).  ``output_index`` may be ``None`` for legacy rows.
    """

    output_id: str
    output_index: int | None = None
    label: str | None = None
    fully_labeled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.output_id, str) or not self.output_id.strip():
            raise ValueError("ModelOutput.output_id must not be blank")
        if self.output_index is not None and not isinstance(self.output_index, int):
            raise TypeError("ModelOutput.output_index must be an int or None")
        if self.label is not None and not isinstance(self.label, str):
            raise TypeError("ModelOutput.label must be a str or None")


__all__ = ["ModelOutput"]
