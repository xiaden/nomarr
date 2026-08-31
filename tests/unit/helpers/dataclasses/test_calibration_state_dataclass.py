"""Unit tests for the canonical calibration state domain value object.

``TASK-calibration-state-intent-facade-correction-A`` Phase 1 (P1-S1/P1-S3):
prove the frozen/slotted ``CalibrationState`` domain value object carries only
calibration semantics and stable string model identity, and never exposes
PostgreSQL primary keys, table metadata, or storage envelopes.  See
``nomarr/helpers/dataclasses/calibration_state_dataclass.py``.
"""

from __future__ import annotations

import pytest

from nomarr.helpers.dataclasses.calibration_state_dataclass import CalibrationState

PERSISTENCE_FIELDS = ("id", "_key", "_id", "created_at", "event", "data", "state_data", "backbone_id")
FACTORIES = ("from_db_doc", "from_row", "from_record")


def _state(**kwargs: object) -> CalibrationState:
    base: dict[str, object] = {"model_id": "m", "head_name": "h", "label": "l"}
    base.update(kwargs)
    return CalibrationState(**base)  # type: ignore[arg-type]


@pytest.mark.unit
class TestCalibrationStateIdentity:
    def test_is_frozen_and_slotted(self) -> None:
        state = CalibrationState(model_id="m", head_name="h", label="l")
        with pytest.raises(AttributeError):
            state.label = "other"  # type: ignore[misc]
        assert not hasattr(state, "__dict__")

    def test_equality_by_value(self) -> None:
        a = CalibrationState(model_id="m", head_name="h", label="l")
        b = CalibrationState(model_id="m", head_name="h", label="l")
        assert a == b
        assert a != CalibrationState(model_id="m", head_name="h", label="x")

    def test_model_id_is_stable_string_identity(self) -> None:
        # model_id is the stable RegisteredModel.id (16-hex model key), never a
        # PostgreSQL primary key.  A 16-hex string is the canonical value.
        state = CalibrationState(model_id="0123456789abcdef", head_name="head", label="pop")
        assert state.model_id == "0123456789abcdef"

    def test_blank_model_id_rejected(self) -> None:
        for value in ("", "   "):
            with pytest.raises(ValueError):
                CalibrationState(model_id=value, head_name="h", label="l")

    def test_non_str_model_id_rejected(self) -> None:
        for value in (None, 123):
            with pytest.raises(ValueError):
                CalibrationState(model_id=value, head_name="h", label="l")  # type: ignore[arg-type]

    def test_blank_head_name_rejected(self) -> None:
        for value in ("", "   "):
            with pytest.raises(ValueError):
                CalibrationState(model_id="m", head_name=value, label="l")

    def test_blank_label_rejected(self) -> None:
        for value in ("", "   "):
            with pytest.raises(ValueError):
                CalibrationState(model_id="m", head_name="h", label=value)

    def test_calibration_key_is_stable_head_label_key(self) -> None:
        state = CalibrationState(model_id="m", head_name="head", label="pop")
        assert state.calibration_key == "head:pop"


@pytest.mark.unit
class TestCalibrationStateCounts:
    def test_negative_counts_rejected(self) -> None:
        for field_name in ("sample_count", "underflow_count", "overflow_count"):
            with pytest.raises(ValueError):
                _state(**{field_name: -1})

    def test_non_int_counts_rejected(self) -> None:
        for field_name in ("sample_count", "underflow_count", "overflow_count"):
            with pytest.raises(TypeError):
                _state(**{field_name: 1.5})
            with pytest.raises(TypeError):
                _state(**{field_name: True})

    def test_zero_counts_are_valid(self) -> None:
        state = CalibrationState(model_id="m", head_name="h", label="l")
        assert (state.sample_count, state.underflow_count, state.overflow_count) == (0, 0, 0)


@pytest.mark.unit
class TestCalibrationStateTimestamps:
    def test_updated_at_defaults_to_none(self) -> None:
        state = CalibrationState(model_id="m", head_name="h", label="l")
        assert state.updated_at is None

    def test_updated_at_accepts_non_negative_int_ms(self) -> None:
        state = CalibrationState(model_id="m", head_name="h", label="l", updated_at=1234)
        assert state.updated_at == 1234
        assert CalibrationState(model_id="m", head_name="h", label="l", updated_at=0).updated_at == 0

    def test_updated_at_rejects_negative(self) -> None:
        with pytest.raises(ValueError):
            CalibrationState(model_id="m", head_name="h", label="l", updated_at=-1)

    def test_updated_at_rejects_bool(self) -> None:
        with pytest.raises(ValueError):
            CalibrationState(model_id="m", head_name="h", label="l", updated_at=True)  # type: ignore[arg-type]

    def test_updated_at_is_semantic_last_calibrated_not_storage_column(self) -> None:
        # updated_at is a validated non-negative int-ms semantic timestamp, not
        # a database-generated column; the dataclass exposes no row metadata.
        state = CalibrationState(model_id="m", head_name="h", label="l", updated_at=42)
        assert state.updated_at == 42
        assert not hasattr(state, "created_at")


@pytest.mark.unit
class TestCalibrationStateCalibrationSemantics:
    def test_histogram_fields_are_calibration_semantics(self) -> None:
        state = CalibrationState(
            model_id="m",
            head_name="h",
            label="l",
            histogram={"bins": [1, 2, 3]},
            histogram_bins=[{"lo": 0.0, "hi": 1.0}],
            p5=0.1,
            p95=0.9,
        )
        assert state.histogram == {"bins": [1, 2, 3]}
        assert state.histogram_bins == [{"lo": 0.0, "hi": 1.0}]
        assert state.p5 == 0.1
        assert state.p95 == 0.9

    def test_histogram_defaults_are_empty(self) -> None:
        state = CalibrationState(model_id="m", head_name="h", label="l")
        assert state.histogram == {}
        assert state.histogram_bins is None


@pytest.mark.unit
class TestCalibrationStatePersistenceAbsence:
    def test_no_persistence_owned_fields(self) -> None:
        state = CalibrationState(model_id="m", head_name="h", label="l")
        for attr in PERSISTENCE_FIELDS:
            assert not hasattr(state, attr), f"CalibrationState must not expose {attr!r}"

    def test_no_db_row_factories(self) -> None:
        for name in FACTORIES:
            assert not hasattr(CalibrationState, name), f"CalibrationState must not expose {name!r}"

    def test_backbone_id_removed_from_domain_state(self) -> None:
        # backbone_id is model metadata owned by RegisteredModel, not a
        # calibration semantic; it must not surface on the calibration state.
        assert not hasattr(CalibrationState, "backbone_id")
