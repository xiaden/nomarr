"""Core ONNX model types and constants shared across the ML component layer.

This module is the single source of truth for:
- ``MODEL_SUITE_VERSION`` — the stable model-suite version string embedded in
  all tag keys.  Increment only when model weights change (new backbone,
  retraining, head replacement).  Switching inference runtimes (TF → ONNX)
  does NOT warrant a bump.
- ``Sidecar`` — wrapper around a co-located ``.json`` metadata file for any
  ONNX model (backbone embedding extractor or classification/regression head).

Kept separate from ``ml_discovery_comp`` (filesystem walking) to avoid the
circular import that arises when ONNX model classes need ``Sidecar`` while
discovery constructs those same classes.
"""

from __future__ import annotations

import os
from typing import Any

# Stable model-suite version embedded in all tag keys.
# Tracks the deployed model set, not the inference runtime.
# Increment this ("v1" -> "v2") only when the model weights themselves change
# in a way that alters numeric outputs (new backbone, retraining, head replacement).
# Changing the inference runtime (TF -> ONNX) does NOT warrant a version bump.
MODEL_SUITE_VERSION: str = "v1"


class Sidecar:
    """Represents a model sidecar JSON file (head or embedding extractor)."""

    def __init__(self, path: str, data: dict[str, Any]) -> None:
        self.path = path
        self.data = data
        self.infer = data.get("inference", {})
        self.schema = data.get("schema", {})
        self.inputs = self.schema.get("inputs", [])
        self.outputs = self.schema.get("outputs", [])

    @property
    def name(self) -> str:
        """Model name from sidecar."""
        return self.data.get("name") or self.data.get("head_name") or os.path.basename(self.path).rsplit(".", 1)[0]

    @property
    def labels(self) -> list[str]:
        """Class labels for classification heads."""
        return list(self.data.get("classes") or self.data.get("labels") or [])

    @property
    def sr(self) -> int:
        """Expected sample rate."""
        explicit = self.data.get("audio", {}).get("sample_rate") or self.infer.get("sample_rate")
        if explicit:
            return int(explicit)
        return 16000

    @property
    def segment_hop(self) -> tuple[float, float]:
        """Segment length and hop for windowed processing."""
        seg = self.data.get("segment", {})
        segment_s = float(seg.get("length_s", seg.get("length", 10.0)))
        hop_s = float(seg.get("hop_s", seg.get("hop", 5.0)))
        return (segment_s, hop_s)

    def graph_abs(self, models_dir: str) -> str | None:
        """Resolve absolute path to the graph file (same dir as JSON).

        Prefers ``.onnx`` when available; falls back to ``.pb`` for the
        transition period.  Returns ``None`` if neither file exists.
        """
        base = self.path.rsplit(".", 1)[0]
        onnx_path = base + ".onnx"
        if os.path.exists(onnx_path):
            return onnx_path
        pb_path = base + ".pb"
        return pb_path if os.path.exists(pb_path) else None

    def input_dim(self) -> int | None:
        """Expected embedding dimension for heads (from schema.inputs)."""
        try:
            if not self.inputs:
                return None
            shp = self.inputs[0].get("shape")
            if isinstance(shp, list):
                if len(shp) == 1 and isinstance(shp[0], int):
                    return shp[0]
                if len(shp) == 2 and isinstance(shp[1], int):
                    return shp[1]
        except Exception:
            pass
        return None

    def head_output_name(self) -> str | None:
        """Output node name for head predictions (from schema.outputs)."""
        try:
            if not self.outputs:
                return None
            for out in self.outputs:
                purpose = str(out.get("output_purpose") or "").lower()
                if purpose in ("predictions", "logits", "probabilities", "probs"):
                    return str(out.get("name"))
            return str(self.outputs[0].get("name"))
        except Exception:
            return None

    def head_input_name(self) -> str | None:
        """Input node name for head (from schema.inputs)."""
        try:
            if not self.inputs:
                return None
            return str(self.inputs[0].get("name"))
        except Exception:
            return None
