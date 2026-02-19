"""Essentia Backend Import Layer.

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

import contextlib
import logging
import os
import re
import sys
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator
    from typing import Any

    # Type hints for when Essentia is available (Any to avoid union-attr errors)
    essentia_tf: Any

_log = logging.getLogger(__name__)

# Patterns for TF/XLA GPU init noise that fires before absl::InitializeLog()
# These cannot be suppressed via TF_CPP_MIN_LOG_LEVEL because the logging
# system hasn't read env vars yet when GPU probing runs.
_TF_NOISE_PATTERNS = [
    re.compile(r"^I\d+ \d+:\d+:\d+\.\d+ .* gpu_device\.cc:\d+\]"),  # GPU device info
    re.compile(r"^I\d+ \d+:\d+:\d+\.\d+ .* cuda_executor\.cc:\d+\]"),  # CUDA executor
    re.compile(r"^I\d+ \d+:\d+:\d+\.\d+ .* gpu_process_state\.cc:\d+\]"),  # GPU state
    re.compile(r"^WARNING: All log messages before absl::InitializeLog\(\)"),
    re.compile(r"^I0000 00:00:\d+\.\d+ "),  # Timestamp-zero logs (pre-init)
]


def _is_tf_noise(line: str) -> bool:
    """Check if a line is TF/XLA GPU init noise."""
    return any(pattern.match(line) for pattern in _TF_NOISE_PATTERNS)


@contextlib.contextmanager
def filter_tf_stderr() -> Generator[None, None, None]:
    """Context manager that filters TF GPU init noise from stderr at fd level.

    Uses pipes to intercept fd-level writes from C++ code. All processing
    happens in memory - no temp files.

    Use this around TensorFlow predictor creation to suppress C++ library logs
    that are emitted before TensorFlow's logging system initializes.
    """
    # Save original stderr fd
    original_stderr_fd = sys.stderr.fileno()
    saved_stderr_fd = os.dup(original_stderr_fd)

    # Create pipe: C++ writes to write_fd, we read from read_fd
    read_fd, write_fd = os.pipe()

    # Storage for captured output
    captured_lines: list[str] = []
    reader_done = threading.Event()

    def reader_thread() -> None:
        """Read from pipe and collect lines until EOF."""
        buffer = b""
        while True:
            try:
                chunk = os.read(read_fd, 4096)
                if not chunk:
                    break
                buffer += chunk
            except OSError:
                break
        # Decode and split into lines
        captured_lines.extend(buffer.decode("utf-8", errors="replace").splitlines())
        reader_done.set()

    try:
        # Redirect stderr fd to our pipe's write end
        os.dup2(write_fd, original_stderr_fd)
        os.close(write_fd)  # Close our copy, fd 2 now owns it

        # Start reader thread
        reader = threading.Thread(target=reader_thread, daemon=True)
        reader.start()

        yield

    finally:
        # Flush Python's stderr buffer
        sys.stderr.flush()

        # Restore original stderr fd
        os.dup2(saved_stderr_fd, original_stderr_fd)
        os.close(saved_stderr_fd)

        # Close read end signals EOF to reader thread
        os.close(read_fd)
        reader_done.wait(timeout=1.0)

        # Process captured output
        noise_count = 0
        non_noise_lines: list[str] = []

        for line in captured_lines:
            if _is_tf_noise(line):
                noise_count += 1
            else:
                non_noise_lines.append(line)

        # Log how much noise was filtered
        if noise_count > 0:
            _log.info(
                "Essentia/TensorFlow import - filtered %d GPU init log lines",
                noise_count,
            )

        # Re-emit any non-noise output to real stderr
        for line in non_noise_lines:
            sys.stderr.write(line + "\n")


# Single guarded import point for Essentia
try:
    with filter_tf_stderr():
        import essentia  # type: ignore[import-not-found]
        import essentia.standard as essentia_tf  # type: ignore[import-not-found,no-redef]

    # Disable Essentia's verbose logging
    essentia.log.infoActive = False  # type: ignore[attr-defined]
    essentia.log.warningActive = False  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover
    essentia_tf = None  # type: ignore[assignment]


def is_available() -> bool:
    """Check if Essentia backend is available.

    Returns:
        True if essentia_tensorflow is installed and importable, False otherwise.

    Example:
        if not is_available():
            print("Essentia not available - skipping ML operations")
            return

    """
    return essentia_tf is not None


def require() -> None:
    """Require Essentia backend to be available, or raise clear error.

    Raises:
        RuntimeError: If essentia_tensorflow is not installed.

    Example:
        require()  # Fails fast if Essentia missing
        # Proceed with ML operations knowing Essentia is available

    """
    if essentia_tf is None:
        msg = (
            "Essentia backend not installed. "
            "Install essentia-tensorflow to run ML inference. "
            "See installation docs for platform-specific instructions."
        )
        raise RuntimeError(
            msg,
        )


def get_version() -> str:
    """Get Essentia version string.

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
    "filter_tf_stderr",
    "get_version",
    "is_available",
    "require",
]
