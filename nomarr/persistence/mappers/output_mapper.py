"""Persistence mappers for ML model-output records.

The repository returns storage DTOs, while the ML intent facade exposes the
small domain value object. Keeping this translation in the persistence layer
prevents table columns and row DTOs from becoming part of the facade contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.helpers.dataclasses.ml_model_output_dataclass import ModelOutput

if TYPE_CHECKING:
    from nomarr.helpers.dto.output_repo_dto import ModelOutputRecord

__all__ = ["model_output_from_record"]


def model_output_from_record(record: ModelOutputRecord) -> ModelOutput:
    """Translate one repository output row into its domain value object."""
    return ModelOutput(
        output_id=record["output_id"],
        output_index=record.get("output_index"),
        label=record.get("label"),
        fully_labeled=bool(record.get("fully_labeled", False)),
    )
