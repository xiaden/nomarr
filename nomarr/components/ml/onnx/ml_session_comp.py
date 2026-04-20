"""ONNX Runtime inference backend.

Provides session creation with CUDAExecutionProvider / CPUExecutionProvider
selection, and the standard is_available / require / get_version contract
used by the ML component layer.

VRAM budgeting
--------------
Each GPU session accepts an explicit ``vram_limit_bytes`` at creation time.
The value comes from per-model VRAM probe measurements stored in meta
(see ml_vram_probe_comp.py / Plan A).  When not provided, no explicit
``gpu_mem_limit`` is set and ONNX Runtime allocates as needed.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import numpy as np

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

    import onnxruntime as ort

try:
    import onnxruntime as _ort
except ImportError:
    _ort = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_available() -> bool:
    """Return True if onnxruntime is installed and importable.

    Example:
        if not is_available():
            print("ONNX Runtime not available - skipping ML operations")
            return
    """
    return _ort is not None


def require() -> None:
    """Raise a clear RuntimeError if onnxruntime is not installed.

    Raises:
        RuntimeError: If onnxruntime is not installed.

    Example:
        require()  # fails fast if ONNX Runtime missing
        # proceed with ML operations
    """
    if _ort is None:
        msg = "onnxruntime is not installed. Install onnxruntime-gpu for GPU support or onnxruntime for CPU-only."
        raise RuntimeError(msg)


def get_version() -> str:
    """Return the onnxruntime version string, or 'unknown' if not installed.

    Example:
        version = get_version()
        print(f"Using ONNX Runtime {version}")
    """
    if _ort is None:
        return "unknown"
    return str(_ort.__version__)


def create_session(
    model_path: str,
    device: str = "cpu",
    vram_limit_bytes: int | None = None,
) -> ort.InferenceSession:
    """Create an ONNX Runtime InferenceSession for the given model file.

    Selects CUDAExecutionProvider when device=="gpu" (falls back to CPU if
    CUDA is unavailable on this machine).  Always appends
    CPUExecutionProvider as the final fallback.

    When creating a GPU session with *vram_limit_bytes* provided, the CUDA
    provider is given an explicit ``gpu_mem_limit`` equal to that value.
    When not provided, no explicit memory limit is set.

    Args:
        model_path: Absolute path to the .onnx model file.
        device: ``"gpu"`` or ``"cpu"``.  Any other value is treated as ``"cpu"``.
        vram_limit_bytes: Optional explicit GPU memory limit in bytes.  When
            provided and *device* is ``"gpu"``, applied directly as
            ``gpu_mem_limit`` in the CUDA provider options.

    Returns:
        A ready-to-use ``onnxruntime.InferenceSession``.

    Raises:
        RuntimeError: If onnxruntime is not installed.
        FileNotFoundError: If *model_path* does not exist.
    """
    require()

    if not os.path.exists(model_path):
        msg = f"ONNX model file not found: {model_path}"
        raise FileNotFoundError(msg)

    providers: list[str | tuple[str, dict[str, object]]] = []

    if device == "gpu":
        available = _ort.get_available_providers()  # type: ignore[union-attr]
        if "CUDAExecutionProvider" in available:
            cuda_opts = _build_cuda_provider_options(vram_limit_bytes)
            providers.append(("CUDAExecutionProvider", cuda_opts))
            if vram_limit_bytes is not None:
                logger.debug(
                    "[onnx] Using CUDAExecutionProvider for %s (gpu_mem_limit=%dMB)",
                    model_path,
                    vram_limit_bytes // (1024 * 1024),
                )
            else:
                logger.debug(
                    "[onnx] Using CUDAExecutionProvider for %s (no explicit limit)",
                    model_path,
                )
        else:
            logger.warning(
                "[onnx] GPU requested but CUDAExecutionProvider not available; falling back to CPU for %s",
                model_path,
            )

    providers.append("CPUExecutionProvider")

    sess_options = _ort.SessionOptions()  # type: ignore[union-attr]
    sess_options.log_severity_level = 3  # ERROR only — suppress ONNX RT info/warnings
    # Cap thread pools per session.  Head models are tiny (< 1MB) and gain
    # nothing from parallelism; backbone runs on GPU so CPU threads are idle.
    # Without limits, ORT spawns one pool per session x nproc threads, which
    # balloons thread-stack RSS into the gigabytes (nproc x sessions).
    sess_options.intra_op_num_threads = 2
    sess_options.inter_op_num_threads = 1

    session: ort.InferenceSession = _ort.InferenceSession(  # type: ignore[union-attr]
        model_path,
        sess_options=sess_options,
        providers=providers,
    )

    logger.debug(
        "[onnx] Session created: %s (providers=%s)",
        model_path,
        session.get_providers(),
    )
    return session


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_cuda_provider_options(vram_limit_bytes: int | None) -> dict[str, object]:
    """Build CUDA provider options dict.

    When *vram_limit_bytes* is provided (normal warmup): caps the arena and
    uses ``kSameAsRequested`` so the arena only holds what is currently live.

    When *vram_limit_bytes* is None (probe mode): returns an empty dict so ORT
    uses its default ``kNextPowerOfTwo`` arena strategy, which retains all peak
    allocations after ``run()`` returns.  This makes the post-run nvidia-smi
    snapshot reflect the true inference peak (weights + max activation workspace)
    rather than just the settled weight footprint.

    Args:
        vram_limit_bytes: Optional explicit GPU memory limit in bytes.

    Returns:
        Dict suitable for ``("CUDAExecutionProvider", opts)``.
    """
    if vram_limit_bytes is None:
        # Probe mode: let ORT use default kNextPowerOfTwo so peak is retained
        return {}
    return {
        # Don't double the arena on each extension — only take what we need
        "arena_extend_strategy": "kSameAsRequested",
        "gpu_mem_limit": vram_limit_bytes,
    }


# ---------------------------------------------------------------------------
# Batch inference helpers
# (consolidated from ml_inference_comp — consumed by ml_backbone.py / ml_head.py)
# ---------------------------------------------------------------------------

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
