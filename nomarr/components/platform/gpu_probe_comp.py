"""
GPU availability probe component.

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


def probe_gpu_availability(timeout: float = NVIDIA_SMI_TIMEOUT_SECONDS) -> dict[str, Any]:
    """
    Check GPU availability using nvidia-smi subprocess with timeout.

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
            logger.debug(f"[gpu_probe] GPU available ({duration_ms:.1f}ms)")
            return {
                "gpu_available": True,
                "error_summary": None,
                "duration_ms": duration_ms,
            }

        # nvidia-smi ran but returned no GPUs
        logger.warning("[gpu_probe] nvidia-smi returned no GPUs")
        return {
            "gpu_available": False,
            "error_summary": "No GPUs detected by nvidia-smi",
            "duration_ms": duration_ms,
        }

    except subprocess.TimeoutExpired:
        duration_ms = (internal_s().value - probe_start.value) * 1000
        logger.error(f"[gpu_probe] nvidia-smi timeout after {timeout}s - driver may be wedged")
        return {
            "gpu_available": False,
            "error_summary": f"nvidia-smi timeout ({timeout}s) - driver wedged",
            "duration_ms": duration_ms,
        }

    except FileNotFoundError:
        duration_ms = (internal_s().value - probe_start.value) * 1000
        logger.warning("[gpu_probe] nvidia-smi not found - NVIDIA drivers not installed")
        return {
            "gpu_available": False,
            "error_summary": "nvidia-smi not found - no NVIDIA drivers",
            "duration_ms": duration_ms,
        }

    except subprocess.CalledProcessError as e:
        duration_ms = (internal_s().value - probe_start.value) * 1000
        error_msg = e.stderr.strip() if e.stderr else f"exit code {e.returncode}"
        logger.error(f"[gpu_probe] nvidia-smi failed: {error_msg}")
        return {
            "gpu_available": False,
            "error_summary": f"nvidia-smi error: {error_msg}"[:100],  # Truncate long errors
            "duration_ms": duration_ms,
        }

    except Exception as e:
        duration_ms = (internal_s().value - probe_start.value) * 1000
        logger.error(f"[gpu_probe] Unexpected error during GPU probe: {e}")
        return {
            "gpu_available": False,
            "error_summary": f"Unexpected error: {type(e).__name__}",
            "duration_ms": duration_ms,
        }
