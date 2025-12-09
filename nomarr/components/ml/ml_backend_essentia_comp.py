"""
Essentia Backend Import Layer

This module provides a single, safe import layer for Essentia dependencies.
All Essentia imports in the ML layer must go through this module.

The backend is optional during development (Windows doesn't have PyPI packages).
Runtime errors only occur when ML inference is actually invoked, not at import time.

Usage:
    from nomarr.components.ml.backend_essentia import essentia_tf, is_available, require

    if is_available():
        # Use essentia_tf safely
        predictor = essentia_tf.TensorflowPredict2D(...)
    else:
        # Handle unavailability
        raise RuntimeError("Essentia required but not available")

    # Or just require it (raises clear error if missing)
    require()
    predictor = essentia_tf.TensorflowPredict2D(...)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

    # Type hints for when Essentia is available (Any to avoid union-attr errors)
    essentia_tf: Any

# Single guarded import point for Essentia
try:
    import essentia.standard as essentia_tf  # type: ignore[import-not-found,no-redef]
except ImportError:  # pragma: no cover
    essentia_tf = None  # type: ignore[assignment]


def is_available() -> bool:
    """
    Check if Essentia backend is available.

    Returns:
        True if essentia_tensorflow is installed and importable, False otherwise.

    Example:
        if not is_available():
            print("Essentia not available - skipping ML operations")
            return
    """
    return essentia_tf is not None


def require() -> None:
    """
    Require Essentia backend to be available, or raise clear error.

    Raises:
        RuntimeError: If essentia_tensorflow is not installed.

    Example:
        require()  # Fails fast if Essentia missing
        # Proceed with ML operations knowing Essentia is available
    """
    if essentia_tf is None:
        raise RuntimeError(
            "Essentia backend not installed. "
            "Install essentia-tensorflow to run ML inference. "
            "See installation docs for platform-specific instructions."
        )


def get_version() -> str:
    """
    Get Essentia version string.

    Returns:
        Version string if available, "unknown" if Essentia not installed.

    Example:
        version = get_version()
        print(f"Using Essentia {version}")
    """
    if essentia_tf is None:
        return "unknown"

    try:
        import essentia

        return str(essentia.__version__)
    except (ImportError, AttributeError):  # pragma: no cover
        return "unknown"


# Export the actual module or None
__all__ = [
    "essentia_tf",
    "get_version",
    "is_available",
    "require",
]
