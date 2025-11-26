"""
DTOs for calibration-related operations.

Cross-layer data contracts for calibration service operations (used by services and interfaces).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RecalibrateFileWorkflowParams:
    """Parameters for workflows/calibration/recalibrate_file_wf.py::recalibrate_file_workflow."""

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

    id: int
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
