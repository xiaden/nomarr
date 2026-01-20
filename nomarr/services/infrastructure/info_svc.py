"""
InfoService - System information and health status.

Provides consolidated system information and health checks for API endpoints.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.info_dto import (
    ConfigInfo,
    GPUHealthResult,
    HealthStatusResult,
    ModelsInfo,
    PublicInfoResult,
    QueueInfo,
    SystemInfoResult,
    WorkerInfo,
)

if TYPE_CHECKING:
    from nomarr.services.infrastructure.ml_svc import MLService


logger = logging.getLogger(__name__)


@dataclass
class InfoConfig:
    """Configuration for InfoService."""

    version: str
    namespace: str
    models_dir: str
    db: Any  # Database instance for reading GPU health
    # Additional fields for public info endpoint
    db_path: str | None = None
    api_host: str | None = None
    api_port: int | None = None
    worker_enabled_default: bool = True
    tagger_worker_count: int = 1
    poll_interval: float = 1.0


class InfoService:
    """
    Service for system info and health status operations.

    Consolidates information from multiple services into unified DTOs.
    """

    def __init__(
        self,
        cfg: InfoConfig,
        workers_coordinator: Any = None,
        ml_service: MLService | None = None,
    ):
        """
        Initialize info service.

        Args:
            cfg: Info configuration
            workers_coordinator: Worker system service instance (optional)
            ml_service: ML service instance (optional)
        """
        self.cfg = cfg
        self.workers_coordinator = workers_coordinator
        self.ml_service = ml_service

    def get_system_info(self) -> SystemInfoResult:
        """
        Get system information for API endpoints.

        Returns:
            SystemInfoResult DTO with version, namespace, models_dir, worker status
        """
        worker_enabled = self.workers_coordinator.is_worker_system_enabled() if self.workers_coordinator else False
        # For worker_count, get from workers_coordinator
        worker_count = 0
        if self.workers_coordinator:
            status = self.workers_coordinator.get_workers_status()
            worker_count = status.get("worker_count", 0)

        return SystemInfoResult(
            version=self.cfg.version,
            namespace=self.cfg.namespace,
            models_dir=self.cfg.models_dir,
            worker_enabled=worker_enabled,
            worker_count=worker_count,
        )

    def get_health_status(self) -> HealthStatusResult:
        """
        Get health status with warnings and diagnostics.

        Analyzes worker status and generates warnings for potential issues.
        Queue-based statistics removed in favor of discovery workers.

        Returns:
            HealthStatusResult DTO with status, warnings, worker count
        """
        # Compute worker count from worker system
        worker_count = 0
        if self.workers_coordinator:
            worker_status = self.workers_coordinator.get_workers_status()
            worker_count = worker_status.get("running", 0)

        # Detect potential issues
        warnings: list[str] = []

        # Determine overall health status
        health_status = "healthy" if not warnings else "degraded"

        return HealthStatusResult(
            status=health_status,
            processor_initialized=self.workers_coordinator is not None,
            worker_count=worker_count,
            queue={},  # No queue in discovery worker model
            warnings=warnings,
        )

    def get_public_info(self) -> PublicInfoResult:
        """
        Get comprehensive public info for API endpoint.

        Orchestrates calls to multiple services and computes:
        - Worker enabled/alive status and heartbeat
        - Queue summary
        - Models/heads breakdown
        - Config subset

        Returns:
            PublicInfoResult DTO with config, models, queue, worker sections
        """
        # Worker status computation
        worker_enabled = self.workers_coordinator.is_worker_system_enabled() if self.workers_coordinator else False
        worker_alive = False
        last_hb = None

        if self.workers_coordinator and worker_enabled:
            status = self.workers_coordinator.get_workers_status()
            # Check if any workers are running
            worker_alive = status.get("running", 0) > 0

        # Queue info - deprecated in discovery worker model
        # TODO: Phase 2 - Replace with needs_tagging count from library_files
        queue_info = QueueInfo(
            depth=0,
            counts={},
        )

        # Models info
        if self.ml_service:
            heads = self.ml_service.discover_heads()
            embeddings = sorted({h.backbone for h in heads})
            models_info = ModelsInfo(total_heads=len(heads), embeddings=embeddings)
        else:
            models_info = ModelsInfo(total_heads=0, embeddings=[])

        # Config info
        config_info = ConfigInfo(
            db_path=self.cfg.db_path,
            models_dir=self.cfg.models_dir,
            namespace=self.cfg.namespace,
            api_host=self.cfg.api_host,
            api_port=self.cfg.api_port,
            worker_enabled=worker_enabled,
            worker_enabled_default=self.cfg.worker_enabled_default,
            worker_count=self.cfg.tagger_worker_count,
            poll_interval=self.cfg.poll_interval,
        )

        # Worker info
        worker_info = WorkerInfo(
            enabled=worker_enabled,
            alive=worker_alive,
            last_heartbeat=last_hb,
        )

        return PublicInfoResult(
            config=config_info,
            models=models_info,
            queue=queue_info,
            worker=worker_info,
        )

    def get_gpu_health(self) -> GPUHealthResult:
        """
        Get GPU health status from DB meta table.

        Reads cached GPU probe results written by GPUHealthMonitor process.
        Does NOT run nvidia-smi inline (non-blocking).

        Returns:
            GPUHealthResult with GPU status or error state
        """
        import json

        from nomarr.components.platform.gpu_monitor_comp import (
            GPU_HEALTH_STALENESS_THRESHOLD_SECONDS,
            check_gpu_health_staleness,
        )

        # Read GPU health from DB meta table
        gpu_health_json = self.cfg.db.meta.get("gpu_health")
        if not gpu_health_json:
            # No GPU health data in DB yet
            return GPUHealthResult(
                available=False,
                last_check_at=None,
                last_ok_at=None,
                consecutive_failures=0,
                error_summary="GPU health not yet initialized",
            )

        try:
            health_data = json.loads(gpu_health_json)
        except json.JSONDecodeError:
            return GPUHealthResult(
                available=False,
                last_check_at=None,
                last_ok_at=None,
                consecutive_failures=0,
                error_summary="GPU health data corrupted",
            )

        # Check staleness
        last_check_at = health_data.get("probe_time")
        if check_gpu_health_staleness(last_check_at):
            return GPUHealthResult(
                available=False,
                last_check_at=last_check_at,
                last_ok_at=health_data.get("last_ok_at"),
                consecutive_failures=health_data.get("consecutive_failures", 0),
                error_summary=f"GPU health data stale (>{GPU_HEALTH_STALENESS_THRESHOLD_SECONDS}s)",
            )

        # Fresh data
        return GPUHealthResult(
            available=health_data.get("available", False),
            last_check_at=last_check_at,
            last_ok_at=health_data.get("last_ok_at"),
            consecutive_failures=health_data.get("consecutive_failures", 0),
            error_summary=health_data.get("error_summary"),
        )
