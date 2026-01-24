"""
Info domain DTOs.

Data transfer objects for system info and health status endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SystemInfoResult:
    """Result from get_system_info service method."""

    version: str
    namespace: str
    models_dir: str
    worker_enabled: bool
    worker_count: int


@dataclass
class HealthStatusResult:
    """Result from get_health_status service method."""

    status: str
    processor_initialized: bool
    worker_count: int
    queue: dict[str, Any]
    warnings: list[str]


@dataclass
class GPUHealthResult:
    """
    Result from get_gpu_health service method.

    Contains GPU resource snapshot and monitor liveness.
    Monitor liveness is determined by HealthMonitorService, not DB.
    """

    available: bool
    error_summary: str | None
    monitor_healthy: bool = False  # True if GPUHealthMonitor subprocess is alive


# ----------------------------------------------------------------------
#  Public Info DTOs (for public API endpoint)
# ----------------------------------------------------------------------


@dataclass
class ConfigInfo:
    """Configuration information for public info endpoint."""

    db_path: str | None
    models_dir: str
    namespace: str
    api_host: str | None
    api_port: int | None
    worker_enabled: bool
    worker_enabled_default: bool
    worker_count: int
    poll_interval: float


@dataclass
class ModelsInfo:
    """Models information for public info endpoint."""

    total_heads: int
    embeddings: list[str]


@dataclass
class QueueInfo:
    """Queue information for public info endpoint."""

    depth: int
    counts: dict[str, int]


@dataclass
class WorkerInfo:
    """Worker information for public info endpoint."""

    enabled: bool
    alive: bool
    last_heartbeat: float | None


@dataclass
class PublicInfoResult:
    """Complete public info result from get_public_info."""

    config: ConfigInfo
    models: ModelsInfo
    queue: QueueInfo
    worker: WorkerInfo


# ----------------------------------------------------------------------
#  Work Status DTOs
# ----------------------------------------------------------------------


@dataclass
class ScanningLibraryInfo:
    """Info about a library currently being scanned."""

    library_id: str
    name: str
    progress: int
    total: int


@dataclass
class WorkStatusResult:
    """
    Result from get_work_status service method.

    Unified work status for the system: scanning, processing, tagging.
    """

    # Scanning status
    is_scanning: bool
    scanning_libraries: list[ScanningLibraryInfo]

    # ML processing status (files needing tagging)
    is_processing: bool
    pending_files: int
    processed_files: int
    total_files: int

    # Overall activity indicator
    is_busy: bool
