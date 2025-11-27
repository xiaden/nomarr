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
    HealthStatusResult,
    ModelsInfo,
    PublicInfoResult,
    QueueInfo,
    SystemInfoResult,
    WorkerInfo,
)

if TYPE_CHECKING:
    from nomarr.services.coordinator_svc import CoordinatorService
    from nomarr.services.ml_svc import MLService
    from nomarr.services.queue_svc import QueueService
    from nomarr.services.worker_svc import WorkerService


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
    worker_count: int = 1
    poll_interval: float = 1.0


class InfoService:
    """
    Service for system info and health status operations.

    Consolidates information from multiple services into unified DTOs.
    """

    def __init__(
        self,
        cfg: InfoConfig,
        worker_service: WorkerService | None = None,
        queue_service: QueueService | None = None,
        processor_coord: CoordinatorService | None = None,
        ml_service: MLService | None = None,
        worker_pool: list | None = None,
    ):
        """
        Initialize info service.

        Args:
            cfg: Info configuration
            worker_service: Worker service instance (optional)
            queue_service: Queue service instance (optional)
            processor_coord: Processor coordinator instance (optional)
            ml_service: ML service instance (optional)
            worker_pool: Worker pool list (optional)
        """
        self.cfg = cfg
        self.worker_service = worker_service
        self.queue_service = queue_service
        self.processor_coord = processor_coord
        self.ml_service = ml_service
        self.worker_pool = worker_pool or []

    def get_system_info_for_api(self) -> SystemInfoResult:
        """
        Get system information for API endpoints.

        Returns:
            SystemInfoResult DTO with version, namespace, models_dir, worker status
        """
        worker_enabled = self.worker_service.is_enabled() if self.worker_service else False
        worker_count = self.worker_service.cfg.worker_count if self.worker_service else 0

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

        # Compute worker count and running jobs
        worker_count = self.processor_coord.worker_count if self.processor_coord else 0
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
        status = "healthy" if not warnings else "degraded"

        # Convert queue_stats to dict for response
        queue_dict: dict[str, Any] = {
            "depth": queue_stats.depth,
            "counts": queue_stats.counts,
        }

        return HealthStatusResult(
            status=status,
            processor_initialized=self.processor_coord is not None,
            worker_count=worker_count,
            queue=queue_dict,
            warnings=warnings,
        )

    def get_public_info_for_api(self) -> PublicInfoResult:
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
        worker_enabled = self.worker_service.is_enabled() if self.worker_service else False
        worker_alive = any(w.is_alive() for w in self.worker_pool) if worker_enabled and self.worker_pool else False
        last_hb = (
            max((w.last_heartbeat() for w in self.worker_pool if w.is_alive()), default=None)
            if worker_enabled and self.worker_pool
            else None
        )

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
            worker_count=self.cfg.worker_count,
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
