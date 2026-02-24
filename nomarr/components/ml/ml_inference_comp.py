"""ONNX model inference operations.

Handles embedding computation and batched processing using ONNX Runtime.
Mel spectrogram preprocessing and patch extraction are performed externally
via ml_preprocess_comp before each session call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable

_BACKBONE_BATCH_SIZE = 32
"""Number of mel patches per ONNX forward pass for backbone embedding models.

ONNX Runtime receives all patches as a single batch per call, so unbounded
batch sizes cause linear memory growth with track duration (and OOM for long
tracks). Fixed batches cap peak allocation regardless of input length.
"""


def _run_in_batches(
    predict_fn: Callable[[np.ndarray], np.ndarray],
    inputs: np.ndarray,
    batch_size: int,
) -> np.ndarray:
    """Run predict_fn over inputs in fixed-size batches and vstack results.

    Args:
        predict_fn: Callable accepting [batch, ...] and returning [batch, dim].
        inputs: Full input array, shape [n, ...].
        batch_size: Maximum number of rows per forward pass.

    Returns:
        Concatenated outputs, shape [n, dim].
    """
    all_results: list[np.ndarray] = []
    for i in range(0, inputs.shape[0], batch_size):
        batch = inputs[i : i + batch_size]
        result = np.asarray(predict_fn(batch), dtype=np.float32)
        if result.ndim == 1:
            result = result.reshape(1, -1)
        all_results.append(result)
    return np.vstack(all_results)
