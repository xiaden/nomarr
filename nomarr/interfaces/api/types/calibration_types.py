"""Pydantic response models for calibration endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class ClearCalibrationResponse(BaseModel):
    """Response after clearing all calibration data."""

    files_updated: int
    meta_keys_cleared: int


class BackgroundStartResponse(BaseModel):
    """Response when starting a background task (apply or histogram generation)."""

    status: str
    message: str


class ApplyCalibrationResultResponse(BaseModel):
    """Structured result from an apply-calibration run."""

    processed: int
    failed: int
    total: int
    message: str


class ApplyCalibrationStatusResponse(BaseModel):
    """Combined background apply lifecycle and progress snapshot."""

    status: Literal["idle", "running", "completed", "failed"]
    result: ApplyCalibrationResultResponse | None
    error: str | None
    total_files: int
    completed_files: int
    current_file: str | None
    is_running: bool


class LibraryCalibrationStatusResponse(BaseModel):
    """Calibration status for a single library."""

    library_id: str
    library_name: str
    total_files: int
    current_count: int
    outdated_count: int
    percentage: float


class CalibrationStatusResponse(BaseModel):
    """Global calibration status with per-library breakdown."""

    global_version: str | None
    last_run: int | None
    libraries: list[LibraryCalibrationStatusResponse]


class HistogramGenerationStatusResponse(BaseModel):
    """Combined background histogram-generation lifecycle and progress snapshot."""

    running: bool
    completed: bool
    error: str | None
    result: dict[str, Any] | None
    current_head: str | None
    current_head_index: int | None
    total_heads: int
    completed_heads: int
    remaining_heads: int
    last_updated: int | None
    is_running: bool


class GetAllCalibrationHistogramsResponse(BaseModel):
    """Wrapper for all calibration histograms (one per label)."""

    calibrations: list[dict[str, Any]]
