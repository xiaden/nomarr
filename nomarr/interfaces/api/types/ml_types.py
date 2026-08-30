"""ML model management API types.

Pydantic models for ML model configuration endpoints:
listing models, reading/updating output labels, and marking models as configured.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.ml_model_dataclass import RegisteredModel
    from nomarr.helpers.dataclasses.ml_model_output_dataclass import ModelOutput


class MlModelResponse(BaseModel):
    """Response model for a registered ML model vertex.

    ``id`` is the raw stable model key (16-hex sha256 of the model path) —
    ML ids are strings, not int-encoded persistence PKs.
    """

    id: str
    backbone: str
    head_type: str
    model_stem: str
    output_count: int
    fully_configured: bool
    is_known: bool
    source: str

    @classmethod
    def from_model(cls, model: RegisteredModel) -> MlModelResponse:
        """Build response from a domain :class:`RegisteredModel`."""
        return cls(
            id=model.id,
            backbone=model.backbone,
            head_type=model.head_type,
            model_stem=model.model_stem,
            output_count=model.output_count,
            fully_configured=model.fully_configured,
            is_known=model.is_known,
            source=model.source,
        )


class MlModelOutputResponse(BaseModel):
    """Response model for a single model output activation.

    ``output_id`` is the stable natural identity (sha256 ``_output_key``) —
    it is the key the UI uses to address label edits.
    """

    output_id: str
    output_index: int | None
    label: str | None
    fully_labeled: bool

    @classmethod
    def from_domain(cls, output: ModelOutput) -> MlModelOutputResponse:
        """Build response from a domain :class:`ModelOutput`."""
        return cls(
            output_id=output.output_id,
            output_index=output.output_index,
            label=output.label,
            fully_labeled=output.fully_labeled,
        )


class UpdateOutputLabelRequest(BaseModel):
    """Request body for PATCH /api/web/machine-learning/model/{model_id}/output/{output_id}."""

    label: str


class MarkConfiguredRequest(BaseModel):
    """Request body for POST /api/web/machine-learning/model/{model_id}/mark-configured."""

    value: bool
