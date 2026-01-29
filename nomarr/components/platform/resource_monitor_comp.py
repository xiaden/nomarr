"""Resource monitoring component for GPU/CPU adaptive resource management.

Provides GPU capability gating and resource telemetry with TTL caching.
This is a leaf component (no upward imports, no DB access).

Architecture:
- GPU Capability: Checked once at startup via nvidia-smi, cached forever
- GPU Telemetry: VRAM usage via nvidia-smi with TTL cache (not called until capability confirmed)
- RAM Telemetry: Process RSS via psutil with TTL cache

Per GPU_REFACTOR_PLAN.md Section 5:
- A container is GPU-capable iff nvidia-smi succeeds inside the container
- This check is performed once at startup and cached
"""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Any

from nomarr.helpers.time_helper import internal_ms

logger = logging.getLogger(__name__)

# Probe configuration
NVIDIA_SMI_TIMEOUT_S = 5.0  # Hard timeout for nvidia-smi subprocess
TELEMETRY_CACHE_TTL_MS = 1000  # TTL for VRAM/RAM readings in milliseconds

# Cached telemetry state
_vram_cache: dict[str, Any] | None = None
_vram_cache_ts: int = 0
_ram_cache: dict[str, Any] | None = None
_ram_cache_ts: int = 0

# GPU capability cache (checked once at startup, cached forever)
_gpu_capable_cache: bool | None = None


@dataclass
class ResourceStatus:
    """Resource status for tier selection and backbone placement decisions.

    Attributes:
        vram_ok: True if VRAM usage is below budget
        ram_ok: True if RAM usage is below budget
        vram_used_mb: Current VRAM usage in MB (0 if GPU not available)
        ram_used_mb: Current RAM usage in MB
        gpu_capable: True if nvidia-smi succeeded (GPU available)

    """

    vram_ok: bool
    ram_ok: bool
    vram_used_mb: int
    ram_used_mb: int
    gpu_capable: bool


def check_nvidia_gpu_capability(timeout: float = NVIDIA_SMI_TIMEOUT_S) -> bool:
    """Check if NVIDIA GPU is available in-container (capability signal, not telemetry).

    Per GPU_REFACTOR_PLAN.md Section 5:
    - A container is GPU-capable iff nvidia-smi succeeds inside the container
    - This check is performed once at startup and cached

    This function is idempotent - repeated calls return cached result.

    Args:
        timeout: Maximum seconds to wait for nvidia-smi

    Returns:
        True if GPU is available (nvidia-smi succeeded), False otherwise

    """
    global _gpu_capable_cache

    # Return cached result if already checked
    if _gpu_capable_cache is not None:
        return _gpu_capable_cache

    probe_start = internal_ms()

    try:
        # Run nvidia-smi with minimal output and hard timeout
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )

        duration_ms = internal_ms().value - probe_start.value

        # Success if nvidia-smi ran and returned GPU name(s)
        if result.stdout.strip():
            logger.info(
                "[resource_monitor] NVIDIA GPU detected (%s) - GPU tiers enabled (%dms)",
                result.stdout.strip().split("\n")[0],
                duration_ms,
            )
            _gpu_capable_cache = True
            return True

        # nvidia-smi ran but returned no GPUs
        logger.warning("[resource_monitor] nvidia-smi returned no GPUs - forcing CPU-only (Tier 3)")
        _gpu_capable_cache = False
        return False

    except subprocess.TimeoutExpired:
        duration_ms = internal_ms().value - probe_start.value
        logger.warning(
            "[resource_monitor] nvidia-smi timeout (%.1fs) - driver may be wedged, forcing CPU-only",
            timeout,
        )
        _gpu_capable_cache = False
        return False

    except FileNotFoundError:
        logger.info("[resource_monitor] nvidia-smi not found - no NVIDIA drivers, running CPU-only (Tier 3)")
        _gpu_capable_cache = False
        return False

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else f"exit code {e.returncode}"
        logger.warning(
            "[resource_monitor] nvidia-smi failed (%s) - Docker GPU injection may have failed, forcing CPU-only",
            error_msg[:100],
        )
        _gpu_capable_cache = False
        return False

    except Exception as e:
        logger.warning(
            "[resource_monitor] Unexpected error checking GPU capability (%s) - forcing CPU-only",
            type(e).__name__,
        )
        _gpu_capable_cache = False
        return False


def get_vram_usage_mb(timeout: float = NVIDIA_SMI_TIMEOUT_S) -> dict[str, Any]:
    """Query VRAM usage via nvidia-smi (GPU telemetry, cached with TTL).

    Only call this after confirming GPU capability via check_nvidia_gpu_capability().

    Args:
        timeout: Maximum seconds to wait for nvidia-smi

    Returns:
        Dict with:
            - used_mb: int - VRAM used in MB
            - total_mb: int - Total VRAM in MB
            - error: str | None - Error message if query failed

    """
    global _vram_cache, _vram_cache_ts

    now = internal_ms().value

    # Return cached result if within TTL
    if _vram_cache is not None and (now - _vram_cache_ts) < TELEMETRY_CACHE_TTL_MS:
        return _vram_cache

    try:
        # Query VRAM usage for all GPUs
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )

        # Parse output: "1234, 8192" per line (used, total in MiB)
        lines = result.stdout.strip().split("\n")
        total_used_mb = 0
        total_capacity_mb = 0

        for line in lines:
            if "," in line:
                parts = line.split(",")
                try:
                    used = int(parts[0].strip())
                    total = int(parts[1].strip())
                    total_used_mb += used
                    total_capacity_mb += total
                except (ValueError, IndexError):
                    continue

        _vram_cache = {
            "used_mb": total_used_mb,
            "total_mb": total_capacity_mb,
            "error": None,
        }
        _vram_cache_ts = now
        return _vram_cache

    except subprocess.TimeoutExpired:
        logger.warning("[resource_monitor] nvidia-smi timeout during VRAM query")
        _vram_cache = {"used_mb": 0, "total_mb": 0, "error": "nvidia-smi timeout"}
        _vram_cache_ts = now
        return _vram_cache

    except (subprocess.CalledProcessError, FileNotFoundError, Exception) as e:
        logger.warning("[resource_monitor] VRAM query failed: %s", e)
        _vram_cache = {"used_mb": 0, "total_mb": 0, "error": str(e)}
        _vram_cache_ts = now
        return _vram_cache


def get_vram_usage_for_pid_mb(pid: int, timeout: float = NVIDIA_SMI_TIMEOUT_S) -> int:
    """Query VRAM usage for a specific process via nvidia-smi.

    Args:
        pid: Process ID to query
        timeout: Maximum seconds to wait for nvidia-smi

    Returns:
        VRAM used by the process in MB, or 0 if not found/error

    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,used_memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )

        # Parse output: "1234, 8192" per line (pid, used_memory in MiB)
        for line in result.stdout.strip().split("\n"):
            if "," in line:
                parts = line.split(",")
                try:
                    proc_pid = int(parts[0].strip())
                    used_mb = int(parts[1].strip())
                    if proc_pid == pid:
                        return used_mb
                except (ValueError, IndexError):
                    continue

        return 0  # Process not found in GPU compute apps

    except Exception:
        return 0


def get_ram_usage_mb(detection_mode: str = "auto") -> dict[str, Any]:
    """Query RAM usage (process RSS) via psutil with TTL caching.

    Args:
        detection_mode: How to detect RAM usage:
            - "auto": Try cgroup first (Docker), fall back to host
            - "cgroup": Use cgroup memory stats only (Docker)
            - "host": Use host memory stats only

    Returns:
        Dict with:
            - used_mb: int - RAM used by this process in MB
            - available_mb: int - Available system RAM in MB
            - error: str | None - Error message if query failed

    """
    global _ram_cache, _ram_cache_ts

    now = internal_ms().value

    # Return cached result if within TTL
    if _ram_cache is not None and (now - _ram_cache_ts) < TELEMETRY_CACHE_TTL_MS:
        return _ram_cache

    try:
        import psutil

        # Get current process RSS
        process = psutil.Process(os.getpid())
        rss_bytes = process.memory_info().rss
        rss_mb = rss_bytes // (1024 * 1024)

        # Get available system memory based on detection mode
        if detection_mode == "cgroup":
            available_mb = _get_cgroup_available_mb()
        elif detection_mode == "host":
            mem = psutil.virtual_memory()
            available_mb = mem.available // (1024 * 1024)
        else:  # auto
            # Try cgroup first (Docker), fall back to host
            cgroup_mb = _get_cgroup_available_mb()
            if cgroup_mb > 0:
                available_mb = cgroup_mb
            else:
                mem = psutil.virtual_memory()
                available_mb = mem.available // (1024 * 1024)

        _ram_cache = {
            "used_mb": rss_mb,
            "available_mb": available_mb,
            "error": None,
        }
        _ram_cache_ts = now
        return _ram_cache

    except ImportError:
        logger.exception("[resource_monitor] psutil not available - cannot query RAM")
        _ram_cache = {"used_mb": 0, "available_mb": 0, "error": "psutil not available"}
        _ram_cache_ts = now
        return _ram_cache

    except Exception as e:
        logger.warning("[resource_monitor] RAM query failed: %s", e)
        _ram_cache = {"used_mb": 0, "available_mb": 0, "error": str(e)}
        _ram_cache_ts = now
        return _ram_cache


def _get_cgroup_available_mb() -> int:
    """Read available memory from cgroup (Docker containers).

    Returns:
        Available memory in MB, or 0 if not in a cgroup

    """
    # Try cgroup v2 first
    cgroup_v2_path = "/sys/fs/cgroup/memory.max"
    cgroup_v2_current = "/sys/fs/cgroup/memory.current"

    with contextlib.suppress(Exception):
        if os.path.exists(cgroup_v2_path) and os.path.exists(cgroup_v2_current):
            with open(cgroup_v2_path) as f:
                max_bytes_str = f.read().strip()
            with open(cgroup_v2_current) as f:
                current_bytes = int(f.read().strip())

            if max_bytes_str == "max":
                return 0  # No limit set, fall back to host
            max_bytes = int(max_bytes_str)
            available_bytes = max_bytes - current_bytes
            return max(0, available_bytes // (1024 * 1024))

    # Try cgroup v1
    cgroup_v1_limit = "/sys/fs/cgroup/memory/memory.limit_in_bytes"
    cgroup_v1_usage = "/sys/fs/cgroup/memory/memory.usage_in_bytes"

    with contextlib.suppress(Exception):
        if os.path.exists(cgroup_v1_limit) and os.path.exists(cgroup_v1_usage):
            with open(cgroup_v1_limit) as f:
                limit_bytes = int(f.read().strip())
            with open(cgroup_v1_usage) as f:
                usage_bytes = int(f.read().strip())

            # Limit of 9223372036854771712 means no limit
            if limit_bytes > 9000000000000000000:
                return 0  # No limit set, fall back to host

            available_bytes = limit_bytes - usage_bytes
            return max(0, available_bytes // (1024 * 1024))

    return 0  # Not in a cgroup or error reading


def check_resource_headroom(
    vram_budget_mb: int,
    ram_budget_mb: int,
    vram_estimate_mb: int,
    ram_estimate_mb: int,
    ram_detection_mode: str = "auto",
) -> ResourceStatus:
    """Check if there's headroom for ML work within configured budgets.

    Per GPU_REFACTOR_PLAN.md Section 6:
    - Budgets are absolute caps, expressed in MB
    - Budget semantics: used_mb + estimated_mb <= budget_mb

    Args:
        vram_budget_mb: Maximum VRAM ML may consume (0 = no GPU budget)
        ram_budget_mb: Maximum RAM ML may consume
        vram_estimate_mb: Estimated VRAM for next operation
        ram_estimate_mb: Estimated RAM for next operation
        ram_detection_mode: RAM detection mode (auto/cgroup/host)

    Returns:
        ResourceStatus with headroom assessment

    """
    gpu_capable = check_nvidia_gpu_capability()

    # Get current VRAM usage (only if GPU capable and budget > 0)
    vram_used_mb = 0
    vram_ok = False

    if gpu_capable and vram_budget_mb > 0:
        vram_info = get_vram_usage_mb()
        vram_used_mb = vram_info["used_mb"]
        # Check if we have headroom: used + estimate <= budget
        vram_ok = (vram_used_mb + vram_estimate_mb) <= vram_budget_mb
    elif vram_budget_mb == 0:
        # No VRAM budget = CPU-only mode, VRAM check passes trivially
        vram_ok = True

    # Get current RAM usage
    ram_info = get_ram_usage_mb(ram_detection_mode)
    ram_used_mb = ram_info["used_mb"]
    # Check if we have headroom: used + estimate <= budget
    ram_ok = (ram_used_mb + ram_estimate_mb) <= ram_budget_mb

    return ResourceStatus(
        vram_ok=vram_ok,
        ram_ok=ram_ok,
        vram_used_mb=vram_used_mb,
        ram_used_mb=ram_used_mb,
        gpu_capable=gpu_capable,
    )


def reset_capability_cache() -> None:
    """Reset the GPU capability cache (for testing only)."""
    global _gpu_capable_cache
    _gpu_capable_cache = None


def reset_telemetry_cache() -> None:
    """Reset telemetry caches (for testing only)."""
    global _vram_cache, _vram_cache_ts, _ram_cache, _ram_cache_ts
    _vram_cache = None
    _vram_cache_ts = 0
    _ram_cache = None
    _ram_cache_ts = 0
