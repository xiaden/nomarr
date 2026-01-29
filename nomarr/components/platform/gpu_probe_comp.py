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
from typing import Any

from nomarr.helpers.time_helper import internal_s

logger = logging.getLogger(__name__)

# Probe constants
NVIDIA_SMI_TIMEOUT_SECONDS = 5.0  # Hard timeout for nvidia-smi subprocess

# State tracking for logging (only log on state changes)
_last_gpu_state: dict[str, bool | str | None] = {
    "available": None,  # None = unknown, True = available, False = unavailable
    "last_error": None,  # Track last error message to detect error type changes
}


def probe_gpu_availability(timeout: float = NVIDIA_SMI_TIMEOUT_SECONDS) -> dict[str, Any]:
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
    probe_start = internal_s()

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

        duration_ms = (internal_s().value - probe_start.value) * 1000

        # Success - GPU responded
        if result.stdout.strip():
            # Only log on state change
            if _last_gpu_state["available"] is not True:
                logger.info(f"[gpu_probe] GPU now available ({duration_ms:.1f}ms)")
                _last_gpu_state["available"] = True
                _last_gpu_state["last_error"] = None
            return {
                "gpu_available": True,
                "error_summary": None,
                "duration_ms": duration_ms,
            }

        # nvidia-smi ran but returned no GPUs
        error_msg = "No GPUs detected by nvidia-smi"
        if _last_gpu_state["available"] is not False or _last_gpu_state["last_error"] != error_msg:
            logger.warning(f"[gpu_probe] {error_msg}")
            _last_gpu_state["available"] = False
            _last_gpu_state["last_error"] = error_msg
        return {
            "gpu_available": False,
            "error_summary": error_msg,
            "duration_ms": duration_ms,
        }

    except subprocess.TimeoutExpired:
        duration_ms = (internal_s().value - probe_start.value) * 1000
        error_msg = f"nvidia-smi timeout ({timeout}s) - driver wedged"
        if _last_gpu_state["available"] is not False or _last_gpu_state["last_error"] != error_msg:
            logger.exception(f"[gpu_probe] nvidia-smi timeout after {timeout}s - driver may be wedged")
            _last_gpu_state["available"] = False
            _last_gpu_state["last_error"] = error_msg
        return {
            "gpu_available": False,
            "error_summary": error_msg,
            "duration_ms": duration_ms,
        }

    except FileNotFoundError:
        duration_ms = (internal_s().value - probe_start.value) * 1000
        error_msg = "nvidia-smi not found - no NVIDIA drivers"
        # Only log once on first detection or state change
        if _last_gpu_state["available"] is not False or _last_gpu_state["last_error"] != error_msg:
            logger.warning("[gpu_probe] nvidia-smi not found - NVIDIA drivers not installed")
            _last_gpu_state["available"] = False
            _last_gpu_state["last_error"] = error_msg
        return {
            "gpu_available": False,
            "error_summary": error_msg,
            "duration_ms": duration_ms,
        }

    except subprocess.CalledProcessError as e:
        duration_ms = (internal_s().value - probe_start.value) * 1000
        error_msg = e.stderr.strip() if e.stderr else f"exit code {e.returncode}"
        full_error_summary = f"nvidia-smi error: {error_msg}"[:100]  # Truncate long errors
        if _last_gpu_state["available"] is not False or _last_gpu_state["last_error"] != full_error_summary:
            logger.exception(f"[gpu_probe] nvidia-smi failed: {error_msg}")
            _last_gpu_state["available"] = False
            _last_gpu_state["last_error"] = full_error_summary
        return {
            "gpu_available": False,
            "error_summary": full_error_summary,
            "duration_ms": duration_ms,
        }

    except Exception as e:
        duration_ms = (internal_s().value - probe_start.value) * 1000
        error_summary = f"Unexpected error: {type(e).__name__}"
        if _last_gpu_state["available"] is not False or _last_gpu_state["last_error"] != error_summary:
            logger.exception(f"[gpu_probe] Unexpected error during GPU probe: {e}")
            _last_gpu_state["available"] = False
            _last_gpu_state["last_error"] = error_summary
        return {
            "gpu_available": False,
            "error_summary": error_summary,
            "duration_ms": duration_ms,
        }
