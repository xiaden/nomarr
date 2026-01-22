"""
Platform package.
"""

from .arango_bootstrap_comp import ensure_schema
from .arango_first_run_comp import (
    DB_NAME,
    USERNAME,
    get_root_password_from_env,
    is_first_run,
    provision_database_and_user,
    write_db_config,
)
from .gpu_monitor_comp import (
    GPU_PROBE_INTERVAL_SECONDS,
    GPU_PROBE_TIMEOUT_SECONDS,
    GPUHealthMonitor,
)
from .gpu_probe_comp import (
    NVIDIA_SMI_TIMEOUT_SECONDS,
    probe_gpu_availability,
)
from .resource_monitor_comp import (
    TELEMETRY_CACHE_TTL_MS,
    ResourceStatus,
    check_nvidia_gpu_capability,
    check_resource_headroom,
    get_ram_usage_mb,
    get_vram_usage_for_pid_mb,
    get_vram_usage_mb,
    reset_capability_cache,
    reset_telemetry_cache,
)

__all__ = [
    "DB_NAME",
    "GPU_PROBE_INTERVAL_SECONDS",
    "GPU_PROBE_TIMEOUT_SECONDS",
    "NVIDIA_SMI_TIMEOUT_SECONDS",
    "TELEMETRY_CACHE_TTL_MS",
    "USERNAME",
    "GPUHealthMonitor",
    "ResourceStatus",
    "check_nvidia_gpu_capability",
    "check_resource_headroom",
    "ensure_schema",
    "get_ram_usage_mb",
    "get_root_password_from_env",
    "get_vram_usage_for_pid_mb",
    "get_vram_usage_mb",
    "is_first_run",
    "probe_gpu_availability",
    "provision_database_and_user",
    "reset_capability_cache",
    "reset_telemetry_cache",
    "write_db_config",
]
