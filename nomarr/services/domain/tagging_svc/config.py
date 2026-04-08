"""Tagging service configuration and status types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

CALIBRATION_APPLY_TASK_ID = "calibration_apply"


class ApplyCalibrationResultDict(TypedDict):
    """Structured apply-calibration result payload."""

    processed: int
    failed: int
    total: int
    message: str


class ApplyCalibrationStatusDict(TypedDict):
    """Background apply lifecycle snapshot."""

    status: Literal["idle", "running", "completed", "failed"]
    result: ApplyCalibrationResultDict | None
    error: str | None


class ApplyCalibrationProgressDict(TypedDict):
    """Background apply per-file progress snapshot."""

    total_files: int
    completed_files: int
    current_file: str | None
    is_running: bool


class ApplyCalibrationCombinedStatusDict(TypedDict):
    """Combined background apply lifecycle and progress snapshot."""

    status: Literal["idle", "running", "completed", "failed"]
    result: ApplyCalibrationResultDict | None
    error: str | None
    total_files: int
    completed_files: int
    current_file: str | None
    is_running: bool


@dataclass
class TaggingServiceConfig:
    """Configuration for TaggingService.

    Attributes:
        models_dir: Path to ML models directory
        namespace: Tag namespace (e.g., "nom")
        version_tag_key: Metadata key for version tracking

    """

    models_dir: str
    namespace: str
    version_tag_key: str
