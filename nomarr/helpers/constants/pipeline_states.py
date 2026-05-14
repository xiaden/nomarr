"""Library pipeline state document identifiers."""

PIPELINE_IDLE = "library_pipeline_states/idle"
PIPELINE_SCANNING = "library_pipeline_states/scanning"
PIPELINE_ML_RUNNING = "library_pipeline_states/ml_running"
PIPELINE_TOO_SMALL = "library_pipeline_states/too_small"
PIPELINE_AWAITING_CALIBRATION = "library_pipeline_states/awaiting_calibration"
PIPELINE_CALIBRATING = "library_pipeline_states/calibrating"
PIPELINE_APPLYING = "library_pipeline_states/applying"
PIPELINE_WRITE_READY = "library_pipeline_states/write_ready"
PIPELINE_WRITING = "library_pipeline_states/writing"
PIPELINE_DONE = "library_pipeline_states/done"

ALL_PIPELINE_STATES = (
    PIPELINE_IDLE,
    PIPELINE_SCANNING,
    PIPELINE_ML_RUNNING,
    PIPELINE_TOO_SMALL,
    PIPELINE_AWAITING_CALIBRATION,
    PIPELINE_CALIBRATING,
    PIPELINE_APPLYING,
    PIPELINE_WRITE_READY,
    PIPELINE_WRITING,
    PIPELINE_DONE,
)

__all__ = [
    "ALL_PIPELINE_STATES",
    "PIPELINE_APPLYING",
    "PIPELINE_AWAITING_CALIBRATION",
    "PIPELINE_CALIBRATING",
    "PIPELINE_DONE",
    "PIPELINE_IDLE",
    "PIPELINE_ML_RUNNING",
    "PIPELINE_SCANNING",
    "PIPELINE_TOO_SMALL",
    "PIPELINE_WRITE_READY",
    "PIPELINE_WRITING",
]
