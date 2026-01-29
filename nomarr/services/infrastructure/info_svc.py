"""InfoService - System information.

Provides consolidated system information for API endpoints.
Owns GPUHealthMonitor lifecycle as it produces system resource facts.

NOT a health service - HealthMonitorService tracks component liveness.
"""

from __future__ import annotations

import contextlib
import logging
import multiprocessing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nomarr.components.platform.gpu_monitor_comp import (
    GPU_PROBE_INTERVAL_SECONDS,
    GPUHealthMonitor,
)
from nomarr.helpers.dto.health_dto import ComponentLifecycleHandler, ComponentPolicy
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
    from nomarr.services.infrastructure.health_monitor_svc import HealthMonitorService
    from nomarr.services.infrastructure.ml_svc import MLService


logger = logging.getLogger(__name__)


@dataclass
class InfoConfig:
    """Configuration for InfoService."""

    version: str
    namespace: str
    models_dir: str
    db: Any  # Database instance for reading GPU resources
    health_monitor: HealthMonitorService | None = None  # For GPU monitor liveness
    # Additional fields for public info endpoint
    db_path: str | None = None
    api_host: str | None = None
    api_port: int | None = None
    worker_enabled_default: bool = True
    tagger_worker_count: int = 1
    poll_interval: float = 1.0


# Component ID for GPU monitor registration with HealthMonitorService
GPU_MONITOR_COMPONENT_ID = "gpu_monitor"


class _GPUMonitorLifecycleHandler(ComponentLifecycleHandler):
    """Lifecycle handler for GPUHealthMonitor - receives callbacks from HealthMonitorService."""

    def __init__(self, info_service: InfoService) -> None:
        self.info_service = info_service

    def on_status_change(
        self,
        component_id: str,
        old_status: str,
        new_status: str,
        context: Any,
    ) -> None:
        """Handle GPU monitor status changes from HealthMonitorService."""
        logger.info(f"[InfoService] GPU monitor status: {old_status} -> {new_status}")

        if new_status == "dead":
            # GPU monitor died - restart it
            logger.warning("[InfoService] GPU monitor died, restarting...")
            self.info_service._restart_gpu_monitor()


class InfoService:
    """Service for system information.

    Owns GPUHealthMonitor lifecycle - starts/stops the subprocess and
    registers it with HealthMonitorService for liveness tracking.

    GPU resource snapshot is written to DB by GPUHealthMonitor.
    GPU monitor liveness is tracked by HealthMonitorService.
    """

    def __init__(
        self,
        cfg: InfoConfig,
        workers_coordinator: Any = None,
        ml_service: MLService | None = None,
    ) -> None:
        """Initialize info service.

        Args:
            cfg: Info configuration (includes health_monitor for GPU registration)
            workers_coordinator: Worker system service instance (optional)
            ml_service: ML service instance (optional)

        """
        self.cfg = cfg
        self.workers_coordinator = workers_coordinator
        self.ml_service = ml_service

        # GPU monitor state (owned by InfoService)
        self._gpu_monitor: GPUHealthMonitor | None = None
        self._gpu_pipe_parent: Any = None  # Parent end of pipe for HealthMonitor
        self._gpu_lifecycle_handler: _GPUMonitorLifecycleHandler | None = None

    # ----------------------------- Lifecycle ---------------------------------

    def start(self) -> None:
        """Start InfoService - initializes GPU monitor subprocess.

        Call this after all services are registered.
        """
        self._start_gpu_monitor()

    def stop(self) -> None:
        """Stop InfoService - gracefully shuts down GPU monitor."""
        self._stop_gpu_monitor()

    def _start_gpu_monitor(self) -> None:
        """Start GPUHealthMonitor subprocess and register with HealthMonitorService."""
        if self._gpu_monitor is not None:
            logger.warning("[InfoService] GPU monitor already started")
            return

        # Create pipe for IPC with HealthMonitorService
        parent_conn, child_conn = multiprocessing.Pipe(duplex=False)
        self._gpu_pipe_parent = parent_conn

        # Create and start GPU monitor
        self._gpu_monitor = GPUHealthMonitor(
            probe_interval=GPU_PROBE_INTERVAL_SECONDS,
            health_pipe=child_conn,  # type: ignore[arg-type]
        )
        self._gpu_monitor.start()
        logger.info("[InfoService] Started GPUHealthMonitor subprocess")

        # Register with HealthMonitorService if available
        if self.cfg.health_monitor:
            self._gpu_lifecycle_handler = _GPUMonitorLifecycleHandler(self)
            policy = ComponentPolicy(
                startup_timeout_s=30.0,  # GPU probe may take time on cold start
                staleness_interval_s=GPU_PROBE_INTERVAL_SECONDS,  # Check at probe interval
                max_consecutive_misses=3,  # 3 missed probes = dead
            )
            self.cfg.health_monitor.register_component(
                component_id=GPU_MONITOR_COMPONENT_ID,
                handler=self._gpu_lifecycle_handler,
                pipe_conn=self._gpu_pipe_parent,
                policy=policy,
            )
            logger.info("[InfoService] Registered GPU monitor with HealthMonitorService")

    def _stop_gpu_monitor(self) -> None:
        """Stop GPUHealthMonitor subprocess and unregister from HealthMonitorService."""
        # Unregister from HealthMonitorService
        if self.cfg.health_monitor:
            self.cfg.health_monitor.unregister_component(GPU_MONITOR_COMPONENT_ID)
            logger.debug("[InfoService] Unregistered GPU monitor from HealthMonitorService")

        # Stop the subprocess
        if self._gpu_monitor:
            self._gpu_monitor.stop()
            self._gpu_monitor.join(timeout=5.0)
            if self._gpu_monitor.is_alive():
                logger.warning("[InfoService] GPU monitor did not stop gracefully, terminating")
                self._gpu_monitor.terminate()
            self._gpu_monitor = None
            logger.info("[InfoService] Stopped GPUHealthMonitor subprocess")

        # Close pipe
        if self._gpu_pipe_parent:
            with contextlib.suppress(Exception):
                self._gpu_pipe_parent.close()
            self._gpu_pipe_parent = None

    def _restart_gpu_monitor(self) -> None:
        """Restart GPUHealthMonitor after crash."""
        logger.info("[InfoService] Restarting GPU monitor...")
        self._stop_gpu_monitor()
        self._start_gpu_monitor()

    # ----------------------------- Query Methods -----------------------------

    def get_system_info(self) -> SystemInfoResult:
        """Get system information for API endpoints.

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
        """Get health status with warnings and diagnostics.

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
        """Get comprehensive public info for API endpoint.

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
        """Get GPU resource snapshot and monitor liveness.

        Reads cached GPU probe results written by GPUHealthMonitor process.
        Does NOT run nvidia-smi inline (non-blocking).

        Monitor liveness is determined by HealthMonitorService.

        Returns:
            GPUHealthResult with GPU resource snapshot and monitor liveness

        """
        import json

        # Check monitor liveness via HealthMonitorService
        monitor_healthy = False
        if self.cfg.health_monitor:
            status = self.cfg.health_monitor.get_status(GPU_MONITOR_COMPONENT_ID)
            monitor_healthy = status in ("healthy", "recovering")

        # Read GPU resources from DB
        gpu_resources_json = self.cfg.db.meta.get("gpu_resources")
        if not gpu_resources_json:
            # No GPU resource data in DB yet
            return GPUHealthResult(
                available=False,
                error_summary="GPU resources not yet initialized",
                monitor_healthy=monitor_healthy,
            )

        try:
            resource_data = json.loads(gpu_resources_json)
        except json.JSONDecodeError:
            return GPUHealthResult(
                available=False,
                error_summary="GPU resource data corrupted",
                monitor_healthy=monitor_healthy,
            )

        # Return resource snapshot with monitor liveness
        return GPUHealthResult(
            available=resource_data.get("gpu_available", False),
            error_summary=resource_data.get("error_summary"),
            monitor_healthy=monitor_healthy,
        )
