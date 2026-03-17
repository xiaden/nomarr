"""Core ONNX model types and constants shared across the ML component layer.

This module is the single source of truth for:
- ``MODEL_SUITE_VERSION`` — the stable model-suite version string embedded in
  all tag keys.  Increment only when model weights change (new backbone,
  retraining, head replacement).  Switching inference runtimes (TF → ONNX)
  does NOT warrant a bump.
"""

from __future__ import annotations

# Stable model-suite version embedded in all tag keys.
# Tracks the deployed model set, not the inference runtime.
# Increment this ("v1" -> "v2") only when the model weights themselves change
# in a way that alters numeric outputs (new backbone, retraining, head replacement).
# Changing the inference runtime (TF -> ONNX) does NOT warrant a version bump.
MODEL_SUITE_VERSION: str = "v1"
