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
    """Complete public info result from get_public_info_for_api."""

    config: ConfigInfo
    models: ModelsInfo
    queue: QueueInfo
    worker: WorkerInfo
