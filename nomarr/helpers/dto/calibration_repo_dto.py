"""TypedDict DTOs for the CalibrationRepo return types.

These mirror the SQLAlchemy ``CalibrationState`` and ``CalibrationHistory``
model columns from Part A and provide type-safe return types for
calibration repository methods.  Import only from ``typing``.
"""

from __future__ import annotations

from typing import Any, TypedDict


class CalibrationStateRecord(TypedDict):
    """Single row from the ``calibration_states`` table."""

    id: int
    model_id: str
    state_data: dict[str, Any]
    updated_at: int


class CalibrationHistoryRecord(TypedDict):
    """Single row from the ``calibration_history`` table."""

    id: int
    model_id: str
    event: str
    data: dict[str, Any]
    created_at: int


__all__ = ["CalibrationHistoryRecord", "CalibrationStateRecord"]
