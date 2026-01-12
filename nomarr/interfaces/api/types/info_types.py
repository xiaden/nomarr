"""
Info API types - Pydantic models for system info and health endpoints.

External API contracts for info endpoints.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from nomarr.helpers.dto.info_dto import GPUHealthResult, HealthStatusResult, PublicInfoResult, SystemInfoResult


class SystemInfoResponse(BaseModel):
    """Response for system info endpoint."""

    version: str = Field(..., description="Application version")
    namespace: str = Field(..., description="Tag namespace")
    models_dir: str = Field(..., description="Models directory path")
    worker_enabled: bool = Field(..., description="Whether workers are enabled")
    worker_count: int = Field(..., description="Number of workers configured")

    @classmethod
    def from_dto(cls, dto: SystemInfoResult) -> SystemInfoResponse:
        """Convert SystemInfoResult DTO to Pydantic response model."""
        return cls(
            version=dto.version,
            namespace=dto.namespace,
            models_dir=dto.models_dir,
            worker_enabled=dto.worker_enabled,
            worker_count=dto.worker_count,
        )


class HealthStatusResponse(BaseModel):
    """Response for health status endpoint."""

    status: str = Field(..., description="Health status (healthy/degraded/unavailable)")
    processor_initialized: bool = Field(..., description="Whether processor is initialized")
    worker_count: int = Field(..., description="Number of workers")
    queue: dict[str, Any] = Field(..., description="Queue statistics")
    warnings: list[str] = Field(default_factory=list, description="List of warnings")

    @classmethod
    def from_dto(cls, dto: HealthStatusResult) -> HealthStatusResponse:
        """Convert HealthStatusResult DTO to Pydantic response model."""
        return cls(
            status=dto.status,
            processor_initialized=dto.processor_initialized,
            worker_count=dto.worker_count,
            queue=dto.queue,
            warnings=dto.warnings,
        )


class GPUHealthResponse(BaseModel):
    """Response for GPU health endpoint."""

    available: bool = Field(..., description="GPU is available and responding")
    last_check_at: float | None = Field(None, description="Unix timestamp of last probe")
    last_ok_at: float | None = Field(None, description="Unix timestamp of last successful probe")
    consecutive_failures: int = Field(..., description="Number of consecutive probe failures")
    error_summary: str | None = Field(None, description="Short error message if unavailable")

    @classmethod
    def from_dto(cls, dto: GPUHealthResult) -> GPUHealthResponse:
        """Convert GPUHealthResult DTO to Pydantic response model."""
        return cls(
            available=dto.available,
            last_check_at=dto.last_check_at,
            last_ok_at=dto.last_ok_at,
            consecutive_failures=dto.consecutive_failures,
            error_summary=dto.error_summary,
        )


# ----------------------------------------------------------------------
#  Public Info Response Models
# ----------------------------------------------------------------------


class ConfigInfoResponse(BaseModel):
    """Configuration info for public API."""

    db_path: str | None = Field(None, description="Database path")
    models_dir: str = Field(..., description="Models directory path")
    namespace: str = Field(..., description="Tag namespace")
    api_host: str | None = Field(None, description="API host")
    api_port: int | None = Field(None, description="API port")
    worker_enabled: bool = Field(..., description="Whether workers are enabled")
    worker_enabled_default: bool = Field(..., description="Default worker enabled state")
    worker_count: int = Field(..., description="Number of workers configured")
    poll_interval: float = Field(..., description="Worker poll interval in seconds")


class ModelsInfoResponse(BaseModel):
    """Models info for public API."""

    total_heads: int = Field(..., description="Total number of model heads")
    embeddings: list[str] = Field(..., description="List of embedding backbones")


class QueueInfoResponse(BaseModel):
    """Queue info for public API."""

    depth: int = Field(..., description="Total queue depth")
    counts: dict[str, int] = Field(..., description="Job counts by status")


class WorkerInfoResponse(BaseModel):
    """Worker info for public API."""

    enabled: bool = Field(..., description="Whether workers are enabled")
    alive: bool = Field(..., description="Whether any worker is alive")
    last_heartbeat: float | None = Field(None, description="Last worker heartbeat timestamp")


class PublicInfoResponse(BaseModel):
    """Complete public info response."""

    config: ConfigInfoResponse = Field(..., description="Configuration information")
    models: ModelsInfoResponse = Field(..., description="Models information")
    queue: QueueInfoResponse = Field(..., description="Queue information")
    worker: WorkerInfoResponse = Field(..., description="Worker information")

    @classmethod
    def from_dto(cls, dto: PublicInfoResult) -> PublicInfoResponse:
        """Convert PublicInfoResult DTO to Pydantic response model."""
        return cls(
            config=ConfigInfoResponse(
                db_path=dto.config.db_path,
                models_dir=dto.config.models_dir,
                namespace=dto.config.namespace,
                api_host=dto.config.api_host,
                api_port=dto.config.api_port,
                worker_enabled=dto.config.worker_enabled,
                worker_enabled_default=dto.config.worker_enabled_default,
                worker_count=dto.config.worker_count,
                poll_interval=dto.config.poll_interval,
            ),
            models=ModelsInfoResponse(
                total_heads=dto.models.total_heads,
                embeddings=dto.models.embeddings,
            ),
            queue=QueueInfoResponse(
                depth=dto.queue.depth,
                counts=dto.queue.counts,
            ),
            worker=WorkerInfoResponse(
                enabled=dto.worker.enabled,
                alive=dto.worker.alive,
                last_heartbeat=dto.worker.last_heartbeat,
            ),
        )
