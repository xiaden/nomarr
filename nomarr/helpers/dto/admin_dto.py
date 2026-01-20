"""
Admin domain DTOs.

Data transfer objects for admin endpoints (job management, cache, worker operations).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class JobRemovalResult:
    """Result from admin job removal operations."""

    removed: int
    message: str


@dataclass
class CacheRefreshResult:
    """Result from cache refresh operations."""

    status: str
    message: str


@dataclass
class WorkerOperationResult:
    """Result from worker control operations (pause/resume)."""

    success: bool
    message: str
    worker_enabled: bool


@dataclass
class RunCalibrationResult:
    """Result from admin_run_calibration."""

    status: str
    calibration: dict[str, Any]


@dataclass
class CalibrationHistoryResult:
    """Result from admin_calibration_history."""

    status: str
    runs: list[dict[str, Any]]
    count: int


@dataclass
class RetagAllResult:
    """Result from admin_retag_all."""

    status: str
    message: str
    enqueued: int
