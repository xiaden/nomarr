"""Library pipeline state constants — multi-axis model.

Each library carries four independent state axes as document fields.
Each axis has three lifecycle poles: not_started, in_progress, completed.

Axes:
    scan: Has the filesystem been walked?
    ml: Have all files been through ML inference?
    calibration: Have calibration thresholds been computed and applied?
    tag_write: Have tags been written to audio files on disk?

Backwards transitions are valid — new files or config changes can reset an axis
to not_started, requiring reprocessing.
"""

from __future__ import annotations

from typing import Literal

# ---------------------------------------------------------------------------
#  scan axis
# ---------------------------------------------------------------------------
SCAN_NOT_SCANNED = "not_scanned"
SCAN_IN_PROGRESS = "scanning"
SCAN_COMPLETE = "scanned"

type ScanState = Literal["not_scanned", "scanning", "scanned"]

SCAN_AXIS: tuple[str, ...] = (
    SCAN_NOT_SCANNED,
    SCAN_IN_PROGRESS,
    SCAN_COMPLETE,
)

# ---------------------------------------------------------------------------
#  ml axis
# ---------------------------------------------------------------------------
ML_NOT_PROCESSED = "not_ML_processed"
ML_IN_PROGRESS = "ML_processing"
ML_COMPLETE = "ML_processed"

type MlState = Literal["not_ML_processed", "ML_processing", "ML_processed"]

ML_AXIS: tuple[str, ...] = (
    ML_NOT_PROCESSED,
    ML_IN_PROGRESS,
    ML_COMPLETE,
)

# ---------------------------------------------------------------------------
#  calibration axis
# ---------------------------------------------------------------------------
CAL_NOT_CALIBRATED = "not_calibrated"
CAL_IN_PROGRESS = "calibrating"
CAL_COMPLETE = "calibrated"

type CalibrationState = Literal["not_calibrated", "calibrating", "calibrated"]

CAL_AXIS: tuple[str, ...] = (
    CAL_NOT_CALIBRATED,
    CAL_IN_PROGRESS,
    CAL_COMPLETE,
)

# ---------------------------------------------------------------------------
#  tag_write axis
# ---------------------------------------------------------------------------
WRITE_NOT_WRITTEN = "not_written"
WRITE_IN_PROGRESS = "writing"
WRITE_COMPLETE = "written"

type TagWriteState = Literal["not_written", "writing", "written"]

WRITE_AXIS: tuple[str, ...] = (
    WRITE_NOT_WRITTEN,
    WRITE_IN_PROGRESS,
    WRITE_COMPLETE,
)

# ---------------------------------------------------------------------------
#  Field names on the library document
# ---------------------------------------------------------------------------
SCAN_STATE_FIELD = "scan_state"
ML_STATE_FIELD = "ml_state"
CAL_STATE_FIELD = "calibration_state"
WRITE_STATE_FIELD = "tag_write_state"

# All four axis field names, for iteration
PIPELINE_AXIS_FIELDS: tuple[str, ...] = (
    SCAN_STATE_FIELD,
    ML_STATE_FIELD,
    CAL_STATE_FIELD,
    WRITE_STATE_FIELD,
)

# Default states for a newly created library
PIPELINE_DEFAULTS: dict[str, str] = {
    SCAN_STATE_FIELD: SCAN_NOT_SCANNED,
    ML_STATE_FIELD: ML_NOT_PROCESSED,
    CAL_STATE_FIELD: CAL_NOT_CALIBRATED,
    WRITE_STATE_FIELD: WRITE_NOT_WRITTEN,
}

# ---------------------------------------------------------------------------
#  Valid transitions per axis (any pole → any pole is allowed, including backwards)
# ---------------------------------------------------------------------------
VALID_SCAN_TRANSITIONS: dict[str, set[str]] = {
    SCAN_NOT_SCANNED: {SCAN_IN_PROGRESS},
    SCAN_IN_PROGRESS: {SCAN_NOT_SCANNED, SCAN_COMPLETE},
    SCAN_COMPLETE: {SCAN_IN_PROGRESS},
}

VALID_ML_TRANSITIONS: dict[str, set[str]] = {
    ML_NOT_PROCESSED: {ML_IN_PROGRESS},
    ML_IN_PROGRESS: {ML_NOT_PROCESSED, ML_COMPLETE},
    ML_COMPLETE: {ML_IN_PROGRESS, ML_NOT_PROCESSED},
}

VALID_CAL_TRANSITIONS: dict[str, set[str]] = {
    CAL_NOT_CALIBRATED: {CAL_IN_PROGRESS},
    CAL_IN_PROGRESS: {CAL_NOT_CALIBRATED, CAL_COMPLETE},
    CAL_COMPLETE: {CAL_IN_PROGRESS, CAL_NOT_CALIBRATED},
}

VALID_WRITE_TRANSITIONS: dict[str, set[str]] = {
    WRITE_NOT_WRITTEN: {WRITE_IN_PROGRESS},
    WRITE_IN_PROGRESS: {WRITE_NOT_WRITTEN, WRITE_COMPLETE},
    WRITE_COMPLETE: {WRITE_IN_PROGRESS, WRITE_NOT_WRITTEN},
}

VALID_PIPELINE_TRANSITIONS: dict[str, dict[str, set[str]]] = {
    SCAN_STATE_FIELD: VALID_SCAN_TRANSITIONS,
    ML_STATE_FIELD: VALID_ML_TRANSITIONS,
    CAL_STATE_FIELD: VALID_CAL_TRANSITIONS,
    WRITE_STATE_FIELD: VALID_WRITE_TRANSITIONS,
}

# ---------------------------------------------------------------------------
#  Backwards-compatible state keys (for UI and DTOs)
# ---------------------------------------------------------------------------
# Legacy single-value states are no longer stored, but the UI still references
# these keys for display.  Kept as string literals for migration mapping only.
LEGACY_STATE_IDLE = "idle"
LEGACY_STATE_SCANNING = "scanning"
LEGACY_STATE_ML_RUNNING = "ml_running"
LEGACY_STATE_TOO_SMALL = "too_small"
LEGACY_STATE_AWAITING_CALIBRATION = "awaiting_calibration"
LEGACY_STATE_CALIBRATING = "calibrating"
LEGACY_STATE_APPLYING = "applying"
LEGACY_STATE_WRITE_READY = "write_ready"
LEGACY_STATE_WRITING = "writing"
LEGACY_STATE_DONE = "done"

__all__ = [
    "CAL_AXIS",
    "CAL_COMPLETE",
    "CAL_IN_PROGRESS",
    # calibration axis
    "CAL_NOT_CALIBRATED",
    "CAL_STATE_FIELD",
    # legacy
    "LEGACY_STATE_IDLE",
    "ML_AXIS",
    "ML_COMPLETE",
    "ML_IN_PROGRESS",
    # ml axis
    "ML_NOT_PROCESSED",
    "ML_STATE_FIELD",
    "PIPELINE_AXIS_FIELDS",
    "PIPELINE_DEFAULTS",
    "SCAN_AXIS",
    "SCAN_COMPLETE",
    "SCAN_IN_PROGRESS",
    # scan axis
    "SCAN_NOT_SCANNED",
    # field names
    "SCAN_STATE_FIELD",
    # transitions
    "VALID_PIPELINE_TRANSITIONS",
    "WRITE_AXIS",
    "WRITE_COMPLETE",
    "WRITE_IN_PROGRESS",
    # tag_write axis
    "WRITE_NOT_WRITTEN",
    "WRITE_STATE_FIELD",
    "CalibrationState",
    "MlState",
    "ScanState",
    "TagWriteState",
]
