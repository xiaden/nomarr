"""Domain value object for one ML calibration history snapshot."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CalibrationHistorySnapshot:
    """One persisted calibration history snapshot for a model/head/label.

    This is the contract of the ML persistence intent facade for history.  It
    carries stable model identity, the calibration identity, and named snapshot
    metrics only; history row id, ``event``, the JSONB ``data`` envelope, and
    the database-generated ``created_at`` column are deliberately absent.

    ``model_id`` is the stable string ``RegisteredModel.id`` (the 16-hex
    ``_model_key``), never a PostgreSQL primary key.  The complete logical
    identity is ``(model_id, head_name, label)``; ``calibration_key`` provides
    the stable ``head_name:label`` key convention shared with
    :class:`CalibrationState`.

    ``snapshot_at`` is an explicit *snapshot* semantic: the integer-millisecond
    time at which this calibration snapshot was recorded.  ``output_id``, when
    present, is the stable ML output identity (string-only per the
    ``ml-output-identity`` contract); it is never an integer/row-generated id.
    ``p5``/``p95`` may be NaN as data markers; the ``p5<=p95`` ordering
    invariant is enforced only when both values are finite.
    """

    model_id: str
    head_name: str
    label: str
    snapshot_at: int
    p5: float
    p95: float
    sample_count: int
    underflow_count: int
    overflow_count: int
    p5_delta: float | None = None
    p95_delta: float | None = None
    n_delta: int | None = None
    output_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("model_id", "head_name", "label"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"CalibrationHistorySnapshot.{name} must not be blank")
        if not isinstance(self.snapshot_at, int) or isinstance(self.snapshot_at, bool) or self.snapshot_at < 0:
            raise ValueError("CalibrationHistorySnapshot.snapshot_at must be a non-negative int millisecond timestamp")
        for name in ("p5", "p95"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(f"CalibrationHistorySnapshot.{name} must be a float")
        for name in ("sample_count", "underflow_count", "overflow_count"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"CalibrationHistorySnapshot.{name} must be an int")
            if value < 0:
                raise ValueError(f"CalibrationHistorySnapshot.{name} must not be negative")
        for name in ("p5_delta", "p95_delta"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool)):
                raise TypeError(f"CalibrationHistorySnapshot.{name} must be a float or None")
        if self.n_delta is not None and (not isinstance(self.n_delta, int) or isinstance(self.n_delta, bool)):
            raise TypeError("CalibrationHistorySnapshot.n_delta must be an int or None")
        if self.output_id is not None and (not isinstance(self.output_id, str) or not self.output_id.strip()):
            raise ValueError("CalibrationHistorySnapshot.output_id must not be blank")
        # Percentile ordering is enforced only when both values are finite
        # numbers; NaN percentiles are permitted as data markers and are
        # not compared.
        if self.p5 > self.p95:
            raise ValueError("CalibrationHistorySnapshot.p5 must not exceed p95")

    @property
    def calibration_key(self) -> str:
        """Return the stable logical head/label identity."""
        return f"{self.head_name}:{self.label}"


__all__ = ["CalibrationHistorySnapshot"]
