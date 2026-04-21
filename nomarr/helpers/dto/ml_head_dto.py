"""ML head metadata DTOs shared across layers.

This module defines pure metadata contracts used by discovery, inference,
workflows, and services. It must remain free of component/service/workflow
dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class HeadInfo:
    """Metadata for a discovered head model.

    Sources:
    - DB-backed discovery via ``ml_models`` / ``ml_model_outputs``
    - Filesystem-only discovery with synthesized empty labels

    JSON sidecar files are not part of the ONNX runtime discovery path.
    """

    name: str
    labels: list[str]
    backbone: str
    head_type: str
    model_stem: str
    model_path: str
    embedding_graph: str
    is_regression_head: bool = False

    def __post_init__(self) -> None:
        """Defensively copy labels to avoid aliasing caller-owned lists."""
        self.labels = list(self.labels)

    @property
    def kind(self) -> str:
        """Return head kind: regression, multilabel, or multiclass."""
        head_type_lower = self.head_type.lower()
        if "regression" in head_type_lower:
            return "regression"
        if "multilabel" in head_type_lower:
            return "multilabel"
        if "multiclass" in head_type_lower or "classification" in head_type_lower:
            return "multiclass"
        return "multiclass"

    def build_versioned_tag_key(
        self,
        label: str,
        calib_method: str = "none",
        calib_version: int = 0,
    ) -> tuple[str, str]:
        """Build a deterministic model tag key and calibration identifier."""
        model_key = f"{label}_{self.backbone}_{self.model_stem}"
        calibration_id = f"{calib_method}_{calib_version}"
        return (model_key, calibration_id)
