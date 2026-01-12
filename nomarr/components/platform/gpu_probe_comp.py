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
import time
from typing import Any

logger = logging.getLogger(__name__)

# Probe constants
NVIDIA_SMI_TIMEOUT_SECONDS = 5.0  # Hard timeout for nvidia-smi subprocess
DEFAULT_PROBE_INTERVAL_SECONDS = 15.0  # Default interval between probes


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
        Dict with probe results:
            - available: bool - True if GPU is accessible
            - error_summary: str | None - Short error message if unavailable
            - probe_time: float - Unix timestamp of probe
            - duration_ms: float - How long the probe took

    Example:
        >>> result = probe_gpu_availability()
        >>> if result["available"]:
        ...     # Safe to submit GPU jobs
        ...     pass
        ... else:
        ...     logger.error(f"GPU unavailable: {result['error_summary']}")
    """
    probe_start = time.time()
    probe_time = probe_start

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

        duration_ms = (time.time() - probe_start) * 1000

        # Success - GPU responded
        if result.stdout.strip():
            logger.debug(f"[gpu_probe] GPU available ({duration_ms:.1f}ms)")
            return {
                "available": True,
                "error_summary": None,
                "probe_time": probe_time,
                "duration_ms": duration_ms,
            }

        # nvidia-smi ran but returned no GPUs
        logger.warning("[gpu_probe] nvidia-smi returned no GPUs")
        return {
            "available": False,
            "error_summary": "No GPUs detected by nvidia-smi",
            "probe_time": probe_time,
            "duration_ms": duration_ms,
        }

    except subprocess.TimeoutExpired:
        duration_ms = (time.time() - probe_start) * 1000
        logger.error(f"[gpu_probe] nvidia-smi timeout after {timeout}s - driver may be wedged")
        return {
            "available": False,
            "error_summary": f"nvidia-smi timeout ({timeout}s) - driver wedged",
            "probe_time": probe_time,
            "duration_ms": duration_ms,
        }

    except FileNotFoundError:
        duration_ms = (time.time() - probe_start) * 1000
        logger.warning("[gpu_probe] nvidia-smi not found - NVIDIA drivers not installed")
        return {
            "available": False,
            "error_summary": "nvidia-smi not found - no NVIDIA drivers",
            "probe_time": probe_time,
            "duration_ms": duration_ms,
        }

    except subprocess.CalledProcessError as e:
        duration_ms = (time.time() - probe_start) * 1000
        error_msg = e.stderr.strip() if e.stderr else f"exit code {e.returncode}"
        logger.error(f"[gpu_probe] nvidia-smi failed: {error_msg}")
        return {
            "available": False,
            "error_summary": f"nvidia-smi error: {error_msg}"[:100],  # Truncate long errors
            "probe_time": probe_time,
            "duration_ms": duration_ms,
        }

    except Exception as e:
        duration_ms = (time.time() - probe_start) * 1000
        logger.error(f"[gpu_probe] Unexpected error during GPU probe: {e}")
        return {
            "available": False,
            "error_summary": f"Unexpected error: {type(e).__name__}",
            "probe_time": probe_time,
            "duration_ms": duration_ms,
        }


def should_run_gpu_probe(last_check_at: float | None, interval: float = DEFAULT_PROBE_INTERVAL_SECONDS) -> bool:
    """
    Check if enough time has elapsed since last probe.

    Args:
        last_check_at: Unix timestamp of last probe (None if never probed)
        interval: Minimum seconds between probes (default: 15.0)

    Returns:
        True if a new probe should be run
    """
    if last_check_at is None:
        return True

    elapsed = time.time() - last_check_at
    return elapsed >= interval
