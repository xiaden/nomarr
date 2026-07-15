"""Platform package.

Exports are resolved lazily so importing this package for one utility does not
eagerly load unrelated bootstrap modules and create import cycles.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "GPU_PROBE_INTERVAL_SECONDS",
    "GPU_PROBE_TIMEOUT_SECONDS",
    "NVIDIA_SMI_TIMEOUT_SECONDS",
    "TELEMETRY_CACHE_TTL_MS",
    "GPUHealthMonitor",
    "ResourceStatus",
    "check_nvidia_gpu_capability",
    "check_resource_headroom",
    "get_ram_usage_mb",
    "get_vram_usage_for_pid_mb",
    "get_vram_usage_mb",
    "probe_gpu_availability",
    "reset_capability_cache",
    "reset_telemetry_cache",
]

_EXPORT_MAP: dict[str, tuple[str, str | None]] = {
    "GPU_PROBE_INTERVAL_SECONDS": ("nomarr.components.platform.gpu_monitor_comp", "GPU_PROBE_INTERVAL_SECONDS"),
    "GPU_PROBE_TIMEOUT_SECONDS": ("nomarr.components.platform.gpu_monitor_comp", "GPU_PROBE_TIMEOUT_SECONDS"),
    "GPUHealthMonitor": ("nomarr.components.platform.gpu_monitor_comp", "GPUHealthMonitor"),
    "NVIDIA_SMI_TIMEOUT_SECONDS": ("nomarr.components.platform.gpu_probe_comp", "NVIDIA_SMI_TIMEOUT_SECONDS"),
    "probe_gpu_availability": ("nomarr.components.platform.gpu_probe_comp", "probe_gpu_availability"),
    "TELEMETRY_CACHE_TTL_MS": ("nomarr.components.platform.resource_monitor_comp", "TELEMETRY_CACHE_TTL_MS"),
    "ResourceStatus": ("nomarr.components.platform.resource_monitor_comp", "ResourceStatus"),
    "check_nvidia_gpu_capability": (
        "nomarr.components.platform.resource_monitor_comp",
        "check_nvidia_gpu_capability",
    ),
    "check_resource_headroom": ("nomarr.components.platform.resource_monitor_comp", "check_resource_headroom"),
    "get_ram_usage_mb": ("nomarr.components.platform.resource_monitor_comp", "get_ram_usage_mb"),
    "get_vram_usage_for_pid_mb": (
        "nomarr.components.platform.resource_monitor_comp",
        "get_vram_usage_for_pid_mb",
    ),
    "get_vram_usage_mb": ("nomarr.components.platform.resource_monitor_comp", "get_vram_usage_mb"),
    "reset_capability_cache": ("nomarr.components.platform.resource_monitor_comp", "reset_capability_cache"),
    "reset_telemetry_cache": ("nomarr.components.platform.resource_monitor_comp", "reset_telemetry_cache"),
    "resource_monitor_comp": ("nomarr.components.platform.resource_monitor_comp", None),
}


def __getattr__(name: str) -> Any:
    """Lazily resolve platform exports and selected module aliases."""
    module_name, attr_name = _EXPORT_MAP.get(name, (None, None))
    if module_name is None:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)
    module = import_module(module_name)
    value = module if attr_name is None else getattr(module, attr_name)
    globals()[name] = value
    return value
