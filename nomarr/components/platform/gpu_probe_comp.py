"""GPU availability probe via nvidia-smi with hard timeouts to prevent driver-wedge blocking."""

from __future__ import annotations

import logging
import subprocess
from typing import TypedDict

from nomarr.helpers.time_helper import internal_ms

logger = logging.getLogger(__name__)

# Probe constants
NVIDIA_SMI_TIMEOUT_SECONDS = 5.0


class _GpuProbeResult(TypedDict):
    """GPU probe result from nvidia-smi check."""

    gpu_available: bool
    error_summary: str | None
    duration_ms: float

# State tracking for logging (only log on state changes)
_last_gpu_state: dict[str, bool | str | None] = {
    "available": None,  # None = unknown, True = available, False = unavailable
    "last_error": None,  # Track last error message to detect error type changes
}


def probe_gpu_availability(timeout: float = NVIDIA_SMI_TIMEOUT_SECONDS) -> _GpuProbeResult:
    """Check GPU availability using nvidia-smi subprocess with timeout.

    This is a non-blocking, fail-fast check that detects:
    - NVIDIA driver not loaded
    - nvidia-smi binary missing
    - GPU driver hung/wedged (via timeout)
    - GPU hardware failure

    Does NOT import TensorFlow or CUDA libraries - this is a pure driver check.

    Args:
        timeout: Maximum seconds to wait for nvidia-smi (default: 5.0)

    Returns:
        Dict with GPU resource snapshot (no timestamps):
            - gpu_available: bool - True if GPU is accessible
            - error_summary: str | None - Short error message if unavailable
            - duration_ms: float - How long the probe took

    Example:
        >>> result = probe_gpu_availability()
        >>> if result["gpu_available"]:
        ...     # Safe to submit GPU jobs
        ...     pass
        ... else:
        ...     logger.error(f"GPU unavailable: {result['error_summary']}")

    """
    probe_start = internal_ms()

    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )

        duration_ms = internal_ms().value - probe_start.value

        if result.stdout.strip():
            if _last_gpu_state["available"] is not True:
                logger.info("[gpu_probe] GPU now available (%.1fms)", duration_ms)
                _last_gpu_state["available"] = True
                _last_gpu_state["last_error"] = None
            return {
                "gpu_available": True,
                "error_summary": None,
                "duration_ms": duration_ms,
            }

        error_message = "No GPUs detected by nvidia-smi"
        if _last_gpu_state["available"] is not False or _last_gpu_state["last_error"] != error_message:
            logger.warning("[gpu_probe] %s", error_message)
            _last_gpu_state["available"] = False
            _last_gpu_state["last_error"] = error_message
        return {
            "gpu_available": False,
            "error_summary": error_message,
            "duration_ms": duration_ms,
        }

    except subprocess.TimeoutExpired:
        duration_ms = internal_ms().value - probe_start.value
        error_message = f"nvidia-smi timeout ({timeout}s) - driver wedged"
        if _last_gpu_state["available"] is not False or _last_gpu_state["last_error"] != error_message:
            logger.exception("[gpu_probe] nvidia-smi timeout after %.1fs - driver may be wedged", timeout)
            _last_gpu_state["available"] = False
            _last_gpu_state["last_error"] = error_message
        return {
            "gpu_available": False,
            "error_summary": error_message,
            "duration_ms": duration_ms,
        }

    except FileNotFoundError:
        duration_ms = internal_ms().value - probe_start.value
        error_message = "nvidia-smi not found - no NVIDIA drivers"
        # Only log once on first detection or state change
        if _last_gpu_state["available"] is not False or _last_gpu_state["last_error"] != error_message:
            logger.warning("[gpu_probe] nvidia-smi not found - NVIDIA drivers not installed")
            _last_gpu_state["available"] = False
            _last_gpu_state["last_error"] = error_message
        return {
            "gpu_available": False,
            "error_summary": error_message,
            "duration_ms": duration_ms,
        }

    except subprocess.CalledProcessError as e:
        duration_ms = internal_ms().value - probe_start.value
        error_message = e.stderr.strip() if e.stderr else f"exit code {e.returncode}"
        full_error_summary = f"nvidia-smi error: {error_message}"[:100]
        if _last_gpu_state["available"] is not False or _last_gpu_state["last_error"] != full_error_summary:
            logger.exception("[gpu_probe] nvidia-smi failed: %s", error_message)
            _last_gpu_state["available"] = False
            _last_gpu_state["last_error"] = full_error_summary
        return {
            "gpu_available": False,
            "error_summary": full_error_summary,
            "duration_ms": duration_ms,
        }

    except (OSError, RuntimeError) as e:
        # Broad catch: subprocess may raise unexpected OS-level errors
        # (e.g. EAGAIN under heavy system load). Treat as GPU unavailable.
        duration_ms = internal_ms().value - probe_start.value
        error_summary = f"Unexpected error: {type(e).__name__}"
        if _last_gpu_state["available"] is not False or _last_gpu_state["last_error"] != error_summary:
            logger.exception("[gpu_probe] Unexpected error during GPU probe: %s", e)
            _last_gpu_state["available"] = False
            _last_gpu_state["last_error"] = error_summary
        return {
            "gpu_available": False,
            "error_summary": error_summary,
            "duration_ms": duration_ms,
        }
