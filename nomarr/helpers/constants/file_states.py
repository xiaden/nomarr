"""Canonical song-state axis-pair vertex identifiers shared across layers.

State constants use bare axis names per AR-SDR-6.
"""

from __future__ import annotations

from typing import Literal

STATE_PROCESSED = "processed"
STATE_NOT_PROCESSED = "not_processed"
STATE_CALIBRATED = "calibrated"
STATE_NOT_CALIBRATED = "not_calibrated"
STATE_WRITTEN = "written"
STATE_NOT_WRITTEN = "not_written"
STATE_TAGS_CURRENT = "tags_current"
STATE_TAGS_NOT_FRESH = "tags_not_fresh"
STATE_HYDRATED = "hydrated"
STATE_NOT_HYDRATED = "not_hydrated"
STATE_SCANNED = "scanned"
STATE_NOT_SCANNED = "not_scanned"
STATE_VECTORS_EXTRACTED = "vectors_extracted"
STATE_NOT_VECTORS_EXTRACTED = "not_vectors_extracted"
STATE_ERRORED = "errored"
STATE_NOT_ERRORED = "not_errored"

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
