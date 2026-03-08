"""Calibration API types - Pydantic models for Calibration domain.

External API contracts for calibration endpoints.
These models are thin adapters around DTOs from helpers/dto/.

Architecture:
- Response models use .from_dto() to convert DTOs to Pydantic
- Services continue using DTOs (no Pydantic imports in services layer)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from nomarr.helpers.dto.recalibration_dto import (
        ApplyCalibrationResult,
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

    processed: int = Field(..., description="Number of files successfully processed")
    failed: int = Field(..., description="Number of files that failed processing")
    total: int = Field(..., description="Total files attempted")
    message: str = Field(..., description="Status message")

    @classmethod
    def from_dto(cls, dto: ApplyCalibrationResult) -> ApplyCalibrationResponse:
        """Convert ApplyCalibrationResult DTO to Pydantic response model."""
        return cls(
            processed=dto.processed,
            failed=dto.failed,
            total=dto.total,
            message=dto.message,
        )


