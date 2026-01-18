"""
DTOs for calibration-related operations.

Cross-layer data contracts for calibration service operations (used by services and interfaces).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class WriteCalibratedTagsParams:
    """Parameters for workflows/calibration/write_calibrated_tags_wf.py::write_calibrated_tags_wf."""

    file_path: str
    models_dir: str
    namespace: str
    version_tag_key: str
    calibrate_heads: bool


@dataclass
class EnsureCalibrationsExistResult:
    """Result from calibration_download_svc.ensure_calibrations_exist."""

    has_calibrations: bool
    missing_count: int
    missing_heads: list[dict[str, Any]]
    action_required: str | None


@dataclass
class CalibrationRunResult:
    """Single calibration run from calibration_svc.get_calibration_history."""

    _id: str  # ArangoDB _id
    model_name: str
    head_name: str
    version: int
    file_count: int
    timestamp: int
    p5: float
    p95: float
    range: float
    reference_version: int | None
    apd_p5: float | None
    apd_p95: float | None
    srd: float | None
    jsd: float | None
    median_drift: float | None
    iqr_drift: float | None
    is_stable: int


@dataclass
class GenerateCalibrationResult:
    """Result from calibration_svc.generate_calibration_with_tracking."""

    version: int | None
    library_size: int
    heads: dict[str, Any]
    saved_files: dict[str, Any]
    reference_updates: dict[str, str]
    summary: dict[str, Any]


@dataclass
class CalibrationStateDict:
    """Calibration state document from calibration_state collection."""

    _key: str  # "model_key:head_name"
    model_key: str
    head_name: str
    calibration_def_hash: str
    version: int
    histogram: dict[str, Any]  # {lo, hi, bins, bin_width}
    p5: float
    p95: float
    n: int
    underflow_count: int
    overflow_count: int
    created_at: int
    updated_at: int
    last_computation_at: int


@dataclass
class HistogramCalibrationResult:
    """Result from histogram-based calibration generation."""

    version: int
    heads_processed: int
    heads_success: int
    heads_failed: int
    results: dict[str, dict[str, Any]]  # {head_key: {p5, p95, n, underflow_count, overflow_count}}


@dataclass
class LibraryCalibrationStatus:
    """Calibration status for a single library (derived from file-level tracking)."""

    library_id: str
    library_name: str
    total_files: int
    current_count: int  # Files with current calibration
    outdated_count: int  # Files with outdated or missing calibration
    percentage: float  # current_count / total_files * 100


@dataclass
class GlobalCalibrationStatus:
    """Global calibration status with per-library breakdown."""

    global_version: str | None  # MD5 hash of all calibrations combined
    last_run: int | None  # Unix timestamp (ms) of last calibration generation
    libraries: list[LibraryCalibrationStatus]
