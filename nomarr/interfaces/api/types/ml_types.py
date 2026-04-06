"""ML model management API types.

Pydantic models for ML model configuration endpoints:
listing models, reading/updating output labels, and marking models as configured.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from nomarr.interfaces.api.id_codec import encode_id


class MlModelResponse(BaseModel):
    """Response model for a registered ML model vertex."""

    id: str
    backbone: str
    head_type: str
    model_stem: str
    output_count: int
    fully_configured: bool
    is_known: bool
    source: str

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> MlModelResponse:
        """Build response from an ml_models ArangoDB document."""
        return cls(
            id=encode_id(doc["_id"]),
            backbone=doc["backbone"],
            head_type=doc["head_type"],
            model_stem=doc["model_stem"],
            output_count=doc["output_count"],
            fully_configured=doc.get("fully_configured", False),
            is_known=doc.get("is_known", False),
            source=doc.get("source", "discovered"),
        )


class MlModelOutputResponse(BaseModel):
    """Response model for a single model output activation."""

    id: str
    output_index: int
    label: str | None
    fully_labeled: bool

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> MlModelOutputResponse:
        """Build response from an ml_model_outputs ArangoDB document."""
        return cls(
            id=encode_id(doc["_id"]),
            output_index=doc["output_index"],
            label=doc.get("label"),
            fully_labeled=doc.get("fully_labeled", False),
        )


class UpdateOutputLabelRequest(BaseModel):
    """Request body for PATCH /api/web/machine-learning/model/{model_id}/output/{output_id}."""

    label: str


class MarkConfiguredRequest(BaseModel):
    """Request body for POST /api/web/machine-learning/model/{model_id}/mark-configured."""

    value: bool
