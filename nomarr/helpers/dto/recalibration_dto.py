"""
DTOs for recalibration service operations.

Cross-layer data contracts for recalibration service (used by services and interfaces).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class GetStatusResult:
    """Result from recalibration_service.get_status()."""

    pending: int
    running: int
    done: int
    error: int


@dataclass
class ApplyCalibrationResult:
    """Result from recalibration_service.queue_library_for_recalibration()."""

    queued: int
    message: str


@dataclass
class ClearCalibrationQueueResult:
    """Result from recalibration_service.clear_queue_with_result()."""

    cleared: int
    message: str


@dataclass
class GenerateCalibrationResult:
    """Result from calibration_service.generate_calibration_with_sidecars().

    Contains calibration data and optionally saved sidecar file information.
    """

    status: str
    method: str
    library_size: int
    min_samples: int
    calibrations: dict[str, Any]
    skipped_tags: int
    saved_files: dict[str, dict[str, Any]] | None
    total_files: int | None
    total_labels: int | None
