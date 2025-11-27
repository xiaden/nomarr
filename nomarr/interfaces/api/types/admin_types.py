"""
Admin API response models.

Pydantic models for admin endpoints (job management, cache, worker operations, calibration).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from nomarr.helpers.dto.admin_dto import (
    CacheRefreshResult,
    CalibrationHistoryResult,
    JobRemovalResult,
    RetagAllResult,
    RunCalibrationResult,
    WorkerOperationResult,
)


class JobRemovalResponse(BaseModel):
    """Response model for job removal operations."""

    removed: int
    message: str

    @classmethod
    def from_dto(cls, dto: JobRemovalResult) -> JobRemovalResponse:
        """Convert DTO to Pydantic response model."""
        return cls(removed=dto.removed, message=dto.message)


class CacheRefreshResponse(BaseModel):
    """Response model for cache refresh operations."""

    status: str
    message: str

    @classmethod
    def from_dto(cls, dto: CacheRefreshResult) -> CacheRefreshResponse:
        """Convert DTO to Pydantic response model."""
        return cls(status=dto.status, message=dto.message)


class WorkerOperationResponse(BaseModel):
    """Response model for worker control operations (pause/resume)."""

    status: str
    message: str

    @classmethod
    def from_dto(cls, dto: WorkerOperationResult) -> WorkerOperationResponse:
        """Convert DTO to Pydantic response model."""
        return cls(status=dto.status, message=dto.message)


class RunCalibrationResponse(BaseModel):
    """Response model for admin_run_calibration."""

    status: str
    calibration: dict[str, Any]

    @classmethod
    def from_dto(cls, dto: RunCalibrationResult) -> RunCalibrationResponse:
        """Convert DTO to Pydantic response model."""
        return cls(status=dto.status, calibration=dto.calibration)


class CalibrationHistoryResponse(BaseModel):
    """Response model for admin_calibration_history."""

    status: str
    runs: list[dict[str, Any]]
    count: int

    @classmethod
    def from_dto(cls, dto: CalibrationHistoryResult) -> CalibrationHistoryResponse:
        """Convert DTO to Pydantic response model."""
        return cls(status=dto.status, runs=dto.runs, count=dto.count)


class RetagAllResponse(BaseModel):
    """Response model for admin_retag_all."""

    status: str
    message: str
    enqueued: int

    @classmethod
    def from_dto(cls, dto: RetagAllResult) -> RetagAllResponse:
        """Convert DTO to Pydantic response model."""
        return cls(status=dto.status, message=dto.message, enqueued=dto.enqueued)
