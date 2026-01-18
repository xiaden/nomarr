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
    GPU_HEALTH_STALENESS_THRESHOLD_SECONDS,
    GPU_PROBE_INTERVAL_SECONDS,
    GPU_PROBE_TIMEOUT_SECONDS,
    GPUHealthMonitor,
    check_gpu_health_staleness,
)
from .gpu_probe_comp import (
    DEFAULT_PROBE_INTERVAL_SECONDS,
    NVIDIA_SMI_TIMEOUT_SECONDS,
    probe_gpu_availability,
    should_run_gpu_probe,
)

__all__ = [
    "DB_NAME",
    "DEFAULT_PROBE_INTERVAL_SECONDS",
    "GPU_HEALTH_STALENESS_THRESHOLD_SECONDS",
    "GPU_PROBE_INTERVAL_SECONDS",
    "GPU_PROBE_TIMEOUT_SECONDS",
    "NVIDIA_SMI_TIMEOUT_SECONDS",
    "USERNAME",
    "GPUHealthMonitor",
    "check_gpu_health_staleness",
    "ensure_schema",
    "get_root_password_from_env",
    "is_first_run",
    "probe_gpu_availability",
    "provision_database_and_user",
    "should_run_gpu_probe",
    "write_db_config",
]
