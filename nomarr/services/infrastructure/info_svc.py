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
    from nomarr.services.infrastructure.queue_svc import QueueService
    from nomarr.services.infrastructure.worker_system_svc import WorkerSystemService


logger = logging.getLogger(__name__)


@dataclass
class InfoConfig:
    """Configuration for InfoService."""

    version: str
    namespace: str
    models_dir: str
    # Additional fields for public info endpoint
    db_path: str | None = None
    api_host: str | None = None
    api_port: int | None = None
    worker_enabled_default: bool = True
    tagger_worker_count: int = 1
    scanner_worker_count: int = 1
    recalibration_worker_count: int = 1
    poll_interval: float = 1.0
    event_broker: Any | None = None  # StateBroker for GPU health access


class InfoService:
    """
    Service for system info and health status operations.

    Consolidates information from multiple services into unified DTOs.
    """

    def __init__(
        self,
        cfg: InfoConfig,
        workers_coordinator: WorkerSystemService | None = None,
        queue_service: QueueService | None = None,
        ml_service: MLService | None = None,
    ):
        """
        Initialize info service.

        Args:
            cfg: Info configuration
            workers_coordinator: Worker system service instance (optional)
            queue_service: Queue service instance (optional)
            ml_service: ML service instance (optional)
        """
        self.cfg = cfg
        self.workers_coordinator = workers_coordinator
        self.queue_service = queue_service
        self.ml_service = ml_service

    def get_system_info(self) -> SystemInfoResult:
        """
        Get system information for API endpoints.

        Returns:
            SystemInfoResult DTO with version, namespace, models_dir, worker status
        """
        worker_enabled = self.workers_coordinator.is_worker_system_enabled() if self.workers_coordinator else False
        # For worker_count, we'll use the total from all pools
        worker_count = 0
        if self.workers_coordinator:
            status = self.workers_coordinator.get_workers_status()
            for pool_status in status["pools"].values():
                worker_count += pool_status["worker_count"]

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

        Analyzes queue statistics, worker status, and generates warnings
        for potential issues.

        Returns:
            HealthStatusResult DTO with status, warnings, queue info, worker count
        """
        if not self.queue_service:
            return HealthStatusResult(
                status="unavailable",
                processor_initialized=False,
                worker_count=0,
                queue={},
                warnings=["Queue service not available"],
            )

        # Get queue statistics
        queue_stats = self.queue_service.get_status()

        # Compute worker count from worker system
        worker_count = 0
        if self.workers_coordinator:
            worker_status = self.workers_coordinator.get_workers_status()
            for pool_status in worker_status["pools"].values():
                worker_count += pool_status["count"]
        running_jobs = queue_stats.counts.get("running", 0)

        # Detect potential issues
        warnings: list[str] = []

        # Check for more running jobs than workers (stuck jobs)
        if running_jobs > worker_count:
            warnings.append(
                f"More running jobs ({running_jobs}) than workers ({worker_count}). "
                f"Some jobs may be stuck in 'running' state."
            )

        # Determine overall health status
        health_status = "healthy" if not warnings else "degraded"

        # Convert queue_stats to dict for response
        queue_dict: dict[str, Any] = {
            "depth": queue_stats.depth,
            "counts": queue_stats.counts,
        }

        return HealthStatusResult(
            status=health_status,
            processor_initialized=self.workers_coordinator is not None,
            worker_count=worker_count,
            queue=queue_dict,
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
            # Check if any pool has running workers
            for pool_status in status["pools"].values():
                if pool_status["running"]:
                    worker_alive = True
                    break

        # Queue info
        queue_stats = self.queue_service.get_status() if self.queue_service else None
        queue_info = QueueInfo(
            depth=queue_stats.depth if queue_stats else 0,
            counts=queue_stats.counts if queue_stats else {},
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
            worker_count=self.cfg.tagger_worker_count
            + self.cfg.scanner_worker_count
            + self.cfg.recalibration_worker_count,
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
        Get GPU health status from StateBroker cached state.

        This is a read-only view of cached GPU probe results.
        Does NOT run nvidia-smi inline (non-blocking).

        Returns:
            GPUHealthResult DTO with GPU availability and error info

        Raises:
            RuntimeError: If event_broker is not configured
        """
        if not self.cfg.event_broker:
            raise RuntimeError("GPU health requires event_broker to be configured")

        gpu_health = self.cfg.event_broker.get_gpu_health()

        return GPUHealthResult(
            available=gpu_health.available,
            last_check_at=gpu_health.last_check_at,
            last_ok_at=gpu_health.last_ok_at,
            consecutive_failures=gpu_health.consecutive_failures,
            error_summary=gpu_health.error_summary,
        )
