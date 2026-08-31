"""Unit tests for the calibration history snapshot domain value object.

``TASK-calibration-state-intent-facade-correction-A`` Phase 1 (P1-S2/P1-S3):
prove the frozen/slotted ``CalibrationHistorySnapshot`` domain value object
carries model/calibration natural identity and named snapshot metrics without
any history row id, ``event``, JSONB ``data`` envelope, or database-generated
``created_at``.  See
``nomarr/helpers/dataclasses/calibration_history_dataclass.py``.
"""

from __future__ import annotations

import pytest

from nomarr.helpers.dataclasses.calibration_history_dataclass import CalibrationHistorySnapshot

PERSISTENCE_FIELDS = ("id", "_key", "_id", "created_at", "event", "data", "row_id")
FACTORIES = ("from_db_doc", "from_row", "from_record")

_MODEL = "0123456789abcdef"


def _snapshot(**overrides: object) -> CalibrationHistorySnapshot:
    base: dict[str, object] = {
        "model_id": _MODEL,
        "head_name": "head",
        "label": "pop",
        "snapshot_at": 1000,
        "p5": 0.1,
        "p95": 0.9,
        "sample_count": 5,
        "underflow_count": 1,
        "overflow_count": 2,
    }
    base.update(overrides)
    return CalibrationHistorySnapshot(**base)  # type: ignore[arg-type]


@pytest.mark.unit
class TestCalibrationHistorySnapshotIdentity:
    def test_is_frozen_and_slotted(self) -> None:
        snapshot = _snapshot()
        with pytest.raises(AttributeError):
            snapshot.label = "rock"  # type: ignore[misc]
        assert not hasattr(snapshot, "__dict__")

    def test_equality_by_value(self) -> None:
        assert _snapshot() == _snapshot()
        assert _snapshot() != _snapshot(label="rock")

    def test_model_id_is_stable_string_identity(self) -> None:
        snapshot = _snapshot()
        assert snapshot.model_id == _MODEL

    def test_blank_model_id_rejected(self) -> None:
        for value in ("", "   "):
            with pytest.raises(ValueError):
                _snapshot(model_id=value)

    def test_non_str_model_id_rejected(self) -> None:
        for value in (None, 123):
            with pytest.raises(ValueError):
                _snapshot(model_id=value)  # type: ignore[arg-type]

    def test_blank_head_name_rejected(self) -> None:
        for value in ("", "   "):
            with pytest.raises(ValueError):
                _snapshot(head_name=value)

    def test_blank_label_rejected(self) -> None:
        for value in ("", "   "):
            with pytest.raises(ValueError):
                _snapshot(label=value)

    def test_calibration_key_is_stable_head_label_key(self) -> None:
        assert _snapshot(head_name="head", label="pop").calibration_key == "head:pop"

    def test_calibration_key_matches_state_convention(self) -> None:
        # Shared f"{head_name}:{label}" convention with CalibrationState.
        assert _snapshot().calibration_key == "head:pop"


@pytest.mark.unit
class TestCalibrationHistorySnapshotTimestamps:
    def test_snapshot_at_is_snapshot_semantic(self) -> None:
        # snapshot_at is an explicit integer-ms snapshot semantic, distinct
        # from a database-generated created_at column.
        snapshot = _snapshot(snapshot_at=1234)
        assert snapshot.snapshot_at == 1234
        assert not hasattr(snapshot, "created_at")

    def test_negative_snapshot_at_rejected(self) -> None:
        with pytest.raises(ValueError):
            _snapshot(snapshot_at=-1)

    def test_non_int_snapshot_at_rejected(self) -> None:
        with pytest.raises(ValueError):
            _snapshot(snapshot_at=1.5)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            _snapshot(snapshot_at=True)  # type: ignore[arg-type]


@pytest.mark.unit
class TestCalibrationHistorySnapshotCounts:
    def test_negative_counts_rejected(self) -> None:
        for field_name in ("sample_count", "underflow_count", "overflow_count"):
            with pytest.raises(ValueError):
                _snapshot(**{field_name: -1})

    def test_non_int_counts_rejected(self) -> None:
        for field_name in ("sample_count", "underflow_count", "overflow_count"):
            with pytest.raises(TypeError):
                _snapshot(**{field_name: 1.5})  # type: ignore[arg-type]
            with pytest.raises(TypeError):
                _snapshot(**{field_name: True})  # type: ignore[arg-type]

    def test_zero_counts_are_valid(self) -> None:
        snapshot = _snapshot(sample_count=0, underflow_count=0, overflow_count=0)
        assert (snapshot.sample_count, snapshot.underflow_count, snapshot.overflow_count) == (0, 0, 0)


@pytest.mark.unit
class TestCalibrationHistorySnapshotPercentiles:
    def test_p5_must_not_exceed_p95(self) -> None:
        with pytest.raises(ValueError, match="p5"):
            _snapshot(p5=0.9, p95=0.1)

    def test_p5_equals_p95_is_valid(self) -> None:
        assert _snapshot(p5=0.5, p95=0.5).p95 == 0.5

    def test_nan_percentiles_are_not_compared(self) -> None:
        snapshot = _snapshot(p5=float("nan"), p95=float("nan"))
        assert snapshot.p5 != snapshot.p5  # NaN marker preserved

    def test_one_nan_percentile_is_not_compared(self) -> None:
        # p5=nan/p95 finite and p5 finite/p95=nan must NOT raise; NaN skips
        # the p5<=p95 comparison entirely.
        snapshot = _snapshot(p5=float("nan"), p95=0.9)
        assert snapshot.p5 != snapshot.p5
        snapshot = _snapshot(p5=0.1, p95=float("nan"))
        assert snapshot.p95 != snapshot.p95

    def test_non_numeric_percentile_rejected(self) -> None:
        with pytest.raises(TypeError):
            _snapshot(p5="0.1")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            _snapshot(p95=True)  # type: ignore[arg-type]


@pytest.mark.unit
class TestCalibrationHistorySnapshotOptionals:
    def test_deltas_and_output_id_default_to_none(self) -> None:
        snapshot = _snapshot()
        assert snapshot.p5_delta is None
        assert snapshot.p95_delta is None
        assert snapshot.n_delta is None
        assert snapshot.output_id is None

    def test_deltas_accept_numeric_values(self) -> None:
        snapshot = _snapshot(p5_delta=-0.05, p95_delta=0.03, n_delta=2)
        assert snapshot.p5_delta == -0.05
        assert snapshot.p95_delta == 0.03
        assert snapshot.n_delta == 2

    def test_delta_type_errors(self) -> None:
        with pytest.raises(TypeError):
            _snapshot(p5_delta="x")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            _snapshot(p95_delta=True)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            _snapshot(n_delta=1.5)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            _snapshot(n_delta=True)  # type: ignore[arg-type]

    def test_output_id_is_stable_string_identity(self) -> None:
        snapshot = _snapshot(output_id="0a1b2c3d4e5f60718293a4b5c6d7e8f9")
        assert snapshot.output_id == "0a1b2c3d4e5f60718293a4b5c6d7e8f9"

    def test_blank_output_id_rejected(self) -> None:
        for value in ("", "   "):
            with pytest.raises(ValueError):
                _snapshot(output_id=value)

    def test_non_str_output_id_rejected(self) -> None:
        for value in (123, True):
            with pytest.raises(ValueError):
                _snapshot(output_id=value)  # type: ignore[arg-type]


@pytest.mark.unit
class TestCalibrationHistorySnapshotPersistenceAbsence:
    def test_no_persistence_owned_fields(self) -> None:
        snapshot = _snapshot()
        for attr in PERSISTENCE_FIELDS:
            assert not hasattr(snapshot, attr), f"CalibrationHistorySnapshot must not expose {attr!r}"

    def test_no_db_row_factories(self) -> None:
        for name in FACTORIES:
            assert not hasattr(CalibrationHistorySnapshot, name), f"CalibrationHistorySnapshot must not expose {name!r}"
