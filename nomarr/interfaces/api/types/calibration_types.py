"""
Calibration API types - Pydantic models for Calibration domain.

External API contracts for calibration endpoints.
These models are thin adapters around DTOs from helpers/dto/.

Architecture:
- Response models use .from_dto() to convert DTOs to Pydantic
- Request models already exist (CalibrationRequest in calibration_if.py)
- Services continue using DTOs (no Pydantic imports in services layer)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from nomarr.helpers.dto.ml_dto import (
    GenerateMinmaxCalibrationResult,
    SaveCalibrationSidecarsResult,
)
from nomarr.helpers.dto.recalibration_dto import (
    ApplyCalibrationResult,
    ClearCalibrationQueueResult,
    GenerateCalibrationResult,
    GetStatusResult,
)

# ──────────────────────────────────────────────────────────────────────
# Response Models
# ──────────────────────────────────────────────────────────────────────


class RecalibrationStatusResponse(BaseModel):
    """Pydantic model for GetStatusResult DTO."""

    pending: int = Field(..., description="Number of pending jobs")
    running: int = Field(..., description="Number of running jobs")
    completed: int = Field(..., description="Number of completed jobs")
    errors: int = Field(..., description="Number of failed jobs")
    worker_alive: bool = Field(..., description="Whether the recalibration worker is alive")
    worker_busy: bool = Field(..., description="Whether the recalibration worker is busy")

    @classmethod
    def from_dto(cls, dto: GetStatusResult, worker_alive: bool, worker_busy: bool) -> RecalibrationStatusResponse:
        """Convert GetStatusResult DTO to Pydantic response model."""
        return cls(
            pending=dto.pending,
            running=dto.running,
            completed=dto.done,
            errors=dto.error,
            worker_alive=worker_alive,
            worker_busy=worker_busy,
        )


class ApplyCalibrationResponse(BaseModel):
    """Response for apply calibration to library endpoint."""

    queued: int = Field(..., description="Number of files queued for recalibration")
    message: str = Field(..., description="Status message")

    @classmethod
    def from_dto(cls, dto: ApplyCalibrationResult) -> ApplyCalibrationResponse:
        """Convert ApplyCalibrationResult DTO to Pydantic response model."""
        return cls(
            queued=dto.queued,
            message=dto.message,
        )


class ClearCalibrationQueueResponse(BaseModel):
    """Response for clear calibration queue endpoint."""

    cleared: int = Field(..., description="Number of jobs cleared")
    message: str = Field(..., description="Status message")

    @classmethod
    def from_dto(cls, dto: ClearCalibrationQueueResult) -> ClearCalibrationQueueResponse:
        """Convert ClearCalibrationQueueResult DTO to Pydantic response model."""
        return cls(
            cleared=dto.cleared,
            message=dto.message,
        )


class GenerateMinmaxCalibrationResponse(BaseModel):
    """Pydantic model for GenerateMinmaxCalibrationResult DTO."""

    method: str = Field(..., description="Calibration method (e.g., 'minmax')")
    library_size: int = Field(..., description="Number of files analyzed")
    min_samples: int = Field(..., description="Minimum samples required per tag")
    calibrations: dict[str, Any] = Field(default_factory=dict, description="Calibration parameters by tag")
    skipped_tags: int = Field(..., description="Number of tags skipped due to insufficient samples")

    @classmethod
    def from_dto(cls, dto: GenerateMinmaxCalibrationResult) -> GenerateMinmaxCalibrationResponse:
        """Convert GenerateMinmaxCalibrationResult DTO to Pydantic response model."""
        return cls(
            method=dto.method,
            library_size=dto.library_size,
            min_samples=dto.min_samples,
            calibrations=dto.calibrations,
            skipped_tags=dto.skipped_tags,
        )


class SaveCalibrationSidecarsResponse(BaseModel):
    """Pydantic model for SaveCalibrationSidecarsResult DTO."""

    saved_files: dict[str, dict[str, Any]] = Field(default_factory=dict, description="Saved sidecar files")
    total_files: int = Field(..., description="Total number of files saved")
    total_labels: int = Field(..., description="Total number of labels saved")

    @classmethod
    def from_dto(cls, dto: SaveCalibrationSidecarsResult) -> SaveCalibrationSidecarsResponse:
        """Convert SaveCalibrationSidecarsResult DTO to Pydantic response model."""
        return cls(
            saved_files=dto.saved_files,
            total_files=dto.total_files,
            total_labels=dto.total_labels,
        )


class GenerateCalibrationResponse(BaseModel):
    """Combined response for calibration generation."""

    status: str = Field(..., description="Operation status")
    data: GenerateMinmaxCalibrationResponse = Field(..., description="Calibration data")
    saved_files: SaveCalibrationSidecarsResponse | None = Field(None, description="Saved sidecar files (if requested)")

    @classmethod
    def from_dto(cls, dto: GenerateCalibrationResult) -> GenerateCalibrationResponse:
        """Convert GenerateCalibrationResult DTO to Pydantic response model."""
        # Build calibration data response
        data = GenerateMinmaxCalibrationResponse(
            method=dto.method,
            library_size=dto.library_size,
            min_samples=dto.min_samples,
            calibrations=dto.calibrations,
            skipped_tags=dto.skipped_tags,
        )

        # Build saved files response if available
        saved_files = None
        if dto.saved_files is not None and dto.total_files is not None and dto.total_labels is not None:
            saved_files = SaveCalibrationSidecarsResponse(
                saved_files=dto.saved_files,
                total_files=dto.total_files,
                total_labels=dto.total_labels,
            )

        return cls(
            status=dto.status,
            data=data,
            saved_files=saved_files,
        )


# ──────────────────────────────────────────────────────────────────────
# Request Models
# ──────────────────────────────────────────────────────────────────────


class CalibrationRequest(BaseModel):
    """Request to generate calibration."""

    save_sidecars: bool = Field(True, description="Save calibration files next to models")
