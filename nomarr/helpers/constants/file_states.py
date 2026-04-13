"""Canonical file-state vertex identifiers shared across layers."""

from __future__ import annotations

from typing import Literal

STATE_TAGGED = "file_states/tagged"
STATE_NOT_TAGGED = "file_states/not_tagged"
STATE_TOO_SHORT = "file_states/too_short"
STATE_NOT_TOO_SHORT = "file_states/not_too_short"
STATE_CALIBRATED = "file_states/calibrated"
STATE_NOT_CALIBRATED = "file_states/not_calibrated"
STATE_TAGS_WRITTEN = "file_states/tags_written"
STATE_TAGS_NOT_WRITTEN = "file_states/tags_not_written"
STATE_TAGS_CURRENT = "file_states/tags_current"
STATE_TAGS_STALE = "file_states/tags_stale"
STATE_SCANNED = "file_states/scanned"
STATE_NOT_SCANNED = "file_states/not_scanned"
STATE_VECTORS_EXTRACTED = "file_states/vectors_extracted"
STATE_NOT_VECTORS_EXTRACTED = "file_states/not_vectors_extracted"
STATE_ERRORED = "file_states/errored"
STATE_NOT_ERRORED = "file_states/not_errored"

type StateAxis = Literal[
    "tagged",
    "too_short",
    "calibrated",
    "tags_written",
    "tags_current",
    "scanned",
    "vectors_extracted",
    "errored",
]

ALL_STATE_VERTICES = (
    STATE_TAGGED,
    STATE_NOT_TAGGED,
    STATE_TOO_SHORT,
    STATE_NOT_TOO_SHORT,
    STATE_CALIBRATED,
    STATE_NOT_CALIBRATED,
    STATE_TAGS_WRITTEN,
    STATE_TAGS_NOT_WRITTEN,
    STATE_TAGS_CURRENT,
    STATE_TAGS_STALE,
    STATE_SCANNED,
    STATE_NOT_SCANNED,
    STATE_VECTORS_EXTRACTED,
    STATE_NOT_VECTORS_EXTRACTED,
    STATE_ERRORED,
    STATE_NOT_ERRORED,
)

AXIS_PAIRS: dict[StateAxis, tuple[str, str]] = {
    "tagged": (STATE_TAGGED, STATE_NOT_TAGGED),
    "too_short": (STATE_TOO_SHORT, STATE_NOT_TOO_SHORT),
    "calibrated": (STATE_CALIBRATED, STATE_NOT_CALIBRATED),
    "tags_written": (STATE_TAGS_WRITTEN, STATE_TAGS_NOT_WRITTEN),
    "tags_current": (STATE_TAGS_CURRENT, STATE_TAGS_STALE),
    "scanned": (STATE_SCANNED, STATE_NOT_SCANNED),
    "vectors_extracted": (STATE_VECTORS_EXTRACTED, STATE_NOT_VECTORS_EXTRACTED),
    "errored": (STATE_ERRORED, STATE_NOT_ERRORED),
}

__all__ = [
    "ALL_STATE_VERTICES",
    "AXIS_PAIRS",
    "STATE_CALIBRATED",
    "STATE_ERRORED",
    "STATE_NOT_CALIBRATED",
    "STATE_NOT_ERRORED",
    "STATE_NOT_SCANNED",
    "STATE_NOT_TAGGED",
    "STATE_NOT_TOO_SHORT",
    "STATE_NOT_VECTORS_EXTRACTED",
    "STATE_SCANNED",
    "STATE_TAGGED",
    "STATE_TAGS_CURRENT",
    "STATE_TAGS_NOT_WRITTEN",
    "STATE_TAGS_STALE",
    "STATE_TAGS_WRITTEN",
    "STATE_TOO_SHORT",
    "STATE_VECTORS_EXTRACTED",
    "StateAxis",
]
