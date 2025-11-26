"""
DTOs for calibration-related operations.

Cross-layer data contracts for calibration service operations (used by services and interfaces).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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


@dataclass
class LoadLibraryStateResult:
    """Result from _load_library_state() private helper in recalibrate_file_wf."""

    file_id: int
    all_tags: dict[str, Any]
    calibration_map: dict[str, str]


@dataclass
class CompareCalibrationsResult:
    """Result from _compare_calibrations() private helper in generate_calibration_wf."""

    apd_p5: float
    apd_p95: float
    srd: float
    jsd: float
    median_drift: float
    iqr_drift: float
    is_stable: bool
    failed_metrics: list[str]


@dataclass
class ParseTagKeyResult:
    """Result from _parse_tag_key() private helper in generate_calibration_wf."""

    model_name: str
    head_name: str
    label: str


@dataclass
class CalculateHeadDriftResult:
    """Result from _calculate_head_drift() private helper in generate_calibration_wf."""

    apd_p5: float
    apd_p95: float
    srd: float
    jsd: float
    median_drift: float
    iqr_drift: float
    is_stable: bool
    failed_metrics: list[str]
