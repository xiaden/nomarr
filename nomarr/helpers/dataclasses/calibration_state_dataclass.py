"""Domain value object for one ML calibration state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CalibrationState:
    """Calibration parameters for one model/head/label combination.

    This is the contract of the ML persistence intent facade.  It contains
    stable model identity and calibration semantics; database row identifiers
    and the JSONB envelope are deliberately absent.

    ``model_id`` is the stable string ``RegisteredModel.id`` (the 16-hex
    ``_model_key``), never a PostgreSQL primary key.  The complete logical
    state identity is ``(model_id, head_name, label)``; ``calibration_key``
    provides the stable ``head_name:label`` key convention.

    ``updated_at`` is an optional *semantic* last-calibrated timestamp in
    integer milliseconds (non-negative); it is not a database-generated
    column.  Callers that need authoritative freshness must use a dedicated
    facade query rather than a storage timestamp.  ``histogram`` /
    ``histogram_bins`` are calibration semantics (the fitted distribution),
    not a storage envelope.
    """

    model_id: str
    head_name: str
    label: str
    calibration_def_hash: str = ""
    histogram: dict[str, Any] = field(default_factory=dict)
    histogram_bins: list[dict[str, Any]] | None = None
    p5: float | None = None
    p95: float | None = None
    sample_count: int = 0
    underflow_count: int = 0
    overflow_count: int = 0
    updated_at: int | None = None

    def __post_init__(self) -> None:
        for name in ("model_id", "head_name", "label"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"CalibrationState.{name} must not be blank")
        for name in ("sample_count", "underflow_count", "overflow_count"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"CalibrationState.{name} must be an int")
            if value < 0:
                raise ValueError(f"CalibrationState.{name} must not be negative")
        if self.updated_at is not None and (
            not isinstance(self.updated_at, int) or isinstance(self.updated_at, bool) or self.updated_at < 0
        ):
            raise ValueError("CalibrationState.updated_at must be a non-negative int millisecond timestamp")

    @property
    def calibration_key(self) -> str:
        """Return the stable logical head/label identity."""
        return f"{self.head_name}:{self.label}"


__all__ = ["CalibrationState"]
