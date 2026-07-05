"""GPU availability probe component.

Platform-level component that checks GPU accessibility via nvidia-smi subprocess
with hard timeouts to prevent blocking when driver is wedged.

Architecture:
- Leaf component (no upward imports, no DB access)
- Returns simple dict results for consumption by services/workflows
- Subprocess calls with timeouts to avoid hanging
- No TensorFlow/CUDA library imports (driver-level check only)
"""

from __future__ import annotations

import logging
import subprocess
from typing import TypedDict

from nomarr.helpers.time_helper import internal_ms

logger = logging.getLogger(__name__)

# Probe constants
NVIDIA_SMI_TIMEOUT_SECONDS = 5.0  # Hard timeout for nvidia-smi subprocess

# State tracking for logging (only log on state changes)
_last_gpu_state: dict[str, bool | str | None] = {
    "available": None,  # None = unknown, True = available, False = unavailable
    "last_error": None,  # Track last error message to detect error type changes
}


class GpuProbeResult(TypedDict):
    """Result of a GPU availability probe."""

    gpu_available: bool
    error_summary: str | None
    duration_ms: float


def probe_gpu_availability(timeout: float = NVIDIA_SMI_TIMEOUT_SECONDS) -> GpuProbeResult:
    """Check GPU availability using nvidia-smi subprocess with timeout.

    Non-blocking, fail-fast driver-level check. Does not import
    TensorFlow or CUDA libraries.
    """
    probe_start = internal_ms()

    try:
        # Run nvidia-smi with minimal output and hard timeout
        # --query-gpu=name just checks that driver can enumerate GPUs
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )

        duration_ms = internal_ms().value - probe_start.value

        # Success - GPU responded
        if result.stdout.strip():
            # Only log on state change
            if _last_gpu_state["available"] is not True:
                logger.info("[gpu_probe] GPU now available (%.1fms)", duration_ms)
                _last_gpu_state["available"] = True
                _last_gpu_state["last_error"] = None
            return {
                "gpu_available": True,
                "error_summary": None,
                "duration_ms": duration_ms,
            }

        # nvidia-smi ran but returned no GPUs
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
            logger.exception("[gpu_probe] nvidia-smi timeout after %ss - driver may be wedged", timeout)
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
        full_error_summary = f"nvidia-smi error: {error_message}"[:100]  # Truncate long errors
        if _last_gpu_state["available"] is not False or _last_gpu_state["last_error"] != full_error_summary:
            logger.exception("[gpu_probe] nvidia-smi failed: %s", error_message)
            _last_gpu_state["available"] = False
            _last_gpu_state["last_error"] = full_error_summary
        return {
            "gpu_available": False,
            "error_summary": full_error_summary,
            "duration_ms": duration_ms,
        }

    except Exception as e:
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
