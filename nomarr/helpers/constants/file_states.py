"""Canonical file-state vertex identifiers shared across layers."""

from __future__ import annotations

from typing import Literal

STATE_PROCESSED = "file_states/processed"
STATE_NOT_PROCESSED = "file_states/not_processed"
STATE_CALIBRATED = "file_states/calibrated"
STATE_NOT_CALIBRATED = "file_states/not_calibrated"
STATE_WRITTEN = "file_states/written"
STATE_NOT_WRITTEN = "file_states/not_written"
STATE_TAGS_CURRENT = "file_states/tags_current"
STATE_TAGS_NOT_FRESH = "file_states/tags_not_fresh"
STATE_HYDRATED = "file_states/hydrated"
STATE_NOT_HYDRATED = "file_states/not_hydrated"
STATE_SCANNED = "file_states/scanned"
STATE_NOT_SCANNED = "file_states/not_scanned"
STATE_VECTORS_EXTRACTED = "file_states/vectors_extracted"
STATE_NOT_VECTORS_EXTRACTED = "file_states/not_vectors_extracted"
STATE_ERRORED = "file_states/errored"
STATE_NOT_ERRORED = "file_states/not_errored"

type StateAxis = Literal[
    "processed",
    "calibrated",
    "written",
    "tags_current",
    "hydrated",
    "scanned",
    "vectors_extracted",
    "errored",
]

ALL_STATE_VERTICES = (
    STATE_PROCESSED,
    STATE_NOT_PROCESSED,
    STATE_CALIBRATED,
    STATE_NOT_CALIBRATED,
    STATE_WRITTEN,
    STATE_NOT_WRITTEN,
    STATE_TAGS_CURRENT,
    STATE_TAGS_NOT_FRESH,
    STATE_HYDRATED,
    STATE_NOT_HYDRATED,
    STATE_SCANNED,
    STATE_NOT_SCANNED,
    STATE_VECTORS_EXTRACTED,
    STATE_NOT_VECTORS_EXTRACTED,
    STATE_ERRORED,
    STATE_NOT_ERRORED,
)

AXIS_PAIRS: dict[StateAxis, tuple[str, str]] = {
    "processed": (STATE_PROCESSED, STATE_NOT_PROCESSED),
    "calibrated": (STATE_CALIBRATED, STATE_NOT_CALIBRATED),
    "written": (STATE_WRITTEN, STATE_NOT_WRITTEN),
    "tags_current": (STATE_TAGS_CURRENT, STATE_TAGS_NOT_FRESH),
    "hydrated": (STATE_HYDRATED, STATE_NOT_HYDRATED),
    "scanned": (STATE_SCANNED, STATE_NOT_SCANNED),
    "vectors_extracted": (STATE_VECTORS_EXTRACTED, STATE_NOT_VECTORS_EXTRACTED),
    "errored": (STATE_ERRORED, STATE_NOT_ERRORED),
}

__all__ = [
    "ALL_STATE_VERTICES",
    "AXIS_PAIRS",
    "STATE_CALIBRATED",
    "STATE_ERRORED",
    "STATE_HYDRATED",
    "STATE_NOT_CALIBRATED",
    "STATE_NOT_ERRORED",
    "STATE_NOT_HYDRATED",
    "STATE_NOT_PROCESSED",
    "STATE_NOT_SCANNED",
    "STATE_NOT_VECTORS_EXTRACTED",
    "STATE_NOT_WRITTEN",
    "STATE_PROCESSED",
    "STATE_SCANNED",
    "STATE_TAGS_CURRENT",
    "STATE_TAGS_NOT_FRESH",
    "STATE_VECTORS_EXTRACTED",
    "STATE_WRITTEN",
    "StateAxis",
]
