"""ONNX Runtime inference backend.

Provides session creation with CUDAExecutionProvider / CPUExecutionProvider
selection, and the standard is_available / require / get_version contract
used by the ML component layer.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import onnxruntime as ort

try:
    import onnxruntime as _ort
except ImportError:
    _ort = None  # type: ignore[assignment]


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
        msg = (
            "onnxruntime is not installed. "
            "Install onnxruntime-gpu for GPU support or onnxruntime for CPU-only."
        )
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
) -> ort.InferenceSession:
    """Create an ONNX Runtime InferenceSession for the given model file.

    Selects CUDAExecutionProvider when device=="gpu" (falls back to CPU if
    CUDA is unavailable on this machine).  Always appends
    CPUExecutionProvider as the final fallback.

    Args:
        model_path: Absolute path to the .onnx model file.
        device: ``"gpu"`` or ``"cpu"``.  Any other value is treated as ``"cpu"``.

    Returns:
        A ready-to-use ``onnxruntime.InferenceSession``.

    Raises:
        RuntimeError: If onnxruntime is not installed.
        FileNotFoundError: If *model_path* does not exist.
    """
    require()

    import os

    if not os.path.exists(model_path):
        msg = f"ONNX model file not found: {model_path}"
        raise FileNotFoundError(msg)

    providers: list[str] = []

    if device == "gpu":
        available = _ort.get_available_providers()  # type: ignore[union-attr]
        if "CUDAExecutionProvider" in available:
            providers.append("CUDAExecutionProvider")
            logger.debug("[onnx] Using CUDAExecutionProvider for %s", model_path)
        else:
            logger.warning(
                "[onnx] GPU requested but CUDAExecutionProvider not available; "
                "falling back to CPU for %s",
                model_path,
            )

    providers.append("CPUExecutionProvider")

    sess_options = _ort.SessionOptions()  # type: ignore[union-attr]
    sess_options.log_severity_level = 3  # ERROR only — suppress ONNX RT info/warnings

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
