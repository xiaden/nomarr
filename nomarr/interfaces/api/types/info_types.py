"""Info API types - Pydantic models for system info and health endpoints.

External API contracts for info endpoints.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from nomarr.helpers.dto.info_dto import (
        GPUHealthResult,
        HealthStatusResult,
        PublicInfoResult,
        ScanningLibraryInfo,
        SystemInfoResult,
        WorkStatusResult,
    )


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
    """Response for GPU health endpoint.

    Contains GPU resource snapshot and monitor liveness.
    """

    available: bool = Field(..., description="GPU is available and responding")
    error_summary: str | None = Field(None, description="Short error message if unavailable")
    monitor_healthy: bool = Field(..., description="GPU monitor subprocess is alive and healthy")

    @classmethod
    def from_dto(cls, dto: GPUHealthResult) -> GPUHealthResponse:
        """Convert GPUHealthResult DTO to Pydantic response model."""
        return cls(
            available=dto.available,
            error_summary=dto.error_summary,
            monitor_healthy=dto.monitor_healthy,
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


# ----------------------------------------------------------------------
#  Work Status Response Models
# ----------------------------------------------------------------------


class ScanningLibraryResponse(BaseModel):
    """Info about a library currently being scanned."""

    library_id: str = Field(..., description="Library document _id")
    name: str = Field(..., description="Library name")
    progress: int = Field(..., description="Files processed so far")
    total: int = Field(..., description="Total files to process")

    @classmethod
    def from_dto(cls, dto: ScanningLibraryInfo) -> ScanningLibraryResponse:
        """Convert ScanningLibraryInfo DTO to Pydantic response model."""
        return cls(
            library_id=dto.library_id,
            name=dto.name,
            progress=dto.progress,
            total=dto.total,
        )


class WorkStatusResponse(BaseModel):
    """Unified work status for the system.

    Indicates if any scanning, ML processing, or tagging is happening.
    Used by frontend for polling and activity indicators.
    """

    # Scanning status
    is_scanning: bool = Field(..., description="Any library is currently being scanned")
    scanning_libraries: list[ScanningLibraryResponse] = Field(..., description="Libraries currently being scanned")

    # ML processing status (files needing tagging)
    is_processing: bool = Field(..., description="Files are pending ML processing")
    pending_files: int = Field(..., description="Number of files waiting for ML processing")
    processed_files: int = Field(..., description="Number of files already processed")
    total_files: int = Field(..., description="Total files in library")

    # Overall activity indicator
    is_busy: bool = Field(..., description="System is doing any work (scanning or processing)")

    @classmethod
    def from_dto(cls, dto: WorkStatusResult) -> WorkStatusResponse:
        """Convert WorkStatusResult DTO to Pydantic response model."""
        return cls(
            is_scanning=dto.is_scanning,
            scanning_libraries=[ScanningLibraryResponse.from_dto(lib) for lib in dto.scanning_libraries],
            is_processing=dto.is_processing,
            pending_files=dto.pending_files,
            processed_files=dto.processed_files,
            total_files=dto.total_files,
            is_busy=dto.is_busy,
        )
