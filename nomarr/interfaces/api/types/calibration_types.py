"""Pydantic response models for calibration endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class ClearCalibrationResponse(BaseModel):
    """Response after clearing all calibration data."""

    files_updated: int
    bookkeeping_values_cleared: int


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


class CalibrationHistogramItem(BaseModel):
    """One flat calibration histogram record for the frontend histogram view.

    Mirrors the frontend ``HeadHistogramResponse`` flat contract (the stable
    per-model ``model_key``, head/label identity, histogram bins, percentiles,
    sample count, and histogram spec) plus the optional fields already carried
    by the domain state.  ``model_key`` is the stable ``CalibrationState.model_id``
    (the 16-hex ``RegisteredModel.id`` surfaced to the frontend as the model id
    elsewhere); ``histogram_spec`` is the calibration ``histogram`` and ``n`` is
    the ``sample_count``.  No storage envelope, row id, or nested
    ``CalibrationState`` is exposed.
    """

    model_key: str
    head_name: str
    label: str
    histogram_bins: list[dict[str, Any]]
    p5: float | None
    p95: float | None
    n: int
    histogram_spec: dict[str, Any]
    calibration_def_hash: str | None = None
    underflow_count: int | None = None
    overflow_count: int | None = None


class GetAllCalibrationHistogramsResponse(BaseModel):
    """Wrapper for all calibration histograms (one per label)."""

    calibrations: list[CalibrationHistogramItem]
