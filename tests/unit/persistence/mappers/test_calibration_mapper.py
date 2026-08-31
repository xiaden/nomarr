"""Contract tests for the persistence-owned calibration mappers.

``TASK-calibration-state-intent-facade-correction-B`` Phase 3 (P3-S2): prove
that ``nomarr/persistence/mappers/calibration_mapper.py`` converts repository
rows/join results to the calibration domain value objects internally and
builds the internal persistence payloads, so row DTOs, integer ids, JSONB
envelopes, and event/data shapes never leak past the persistence boundary.
"""

from __future__ import annotations

import pytest

from nomarr.helpers.dataclasses.calibration_history_dataclass import CalibrationHistorySnapshot
from nomarr.helpers.dataclasses.calibration_state_dataclass import CalibrationState
from nomarr.helpers.dto.calibration_repo_dto import (
    CalibrationHistoryRecord,
    CalibrationStateJoined,
    CalibrationStateRecord,
)
from nomarr.persistence.mappers.calibration_mapper import (
    calibration_history_from_record,
    calibration_history_payload,
    calibration_state_from_joined_record,
    calibration_state_from_record,
    calibration_state_payload,
)


def _joined_record(*, state_data: dict, backbone_id: str = "bb_1") -> CalibrationStateJoined:
    """Build a realistic ``CalibrationStateJoined`` with full model metadata."""
    return CalibrationStateJoined(
        model_id="m_abc123",
        state_data=state_data,
        updated_at=2000,
        id="m_abc123",
        path="/models/m_abc123",
        model_type="genre",
        backbone_id=backbone_id,
        backbone="bb_1",
        head_type="linear",
        model_stem="m_abc123",
        output_count=16,
        fully_configured=1,
        is_known=1,
        source="local",
        head_release_date="2026-01-01",
        embedder_release_date="2026-01-01",
    )


@pytest.mark.unit
class TestCalibrationStatePayload:
    """calibration_state_payload round-trips domain semantics to the envelope."""

    def test_sample_count_round_trips_through_n_key(self) -> None:
        state = CalibrationState(
            model_id="m1",
            head_name="head",
            label="pop",
            p5=0.1,
            p95=0.9,
            sample_count=42,
            underflow_count=2,
            overflow_count=3,
        )
        payload = calibration_state_payload(state)
        # The repo's internal envelope key for sample_count is "n".
        assert payload["n"] == 42
        assert payload["head_name"] == "head"
        assert payload["label"] == "pop"
        assert payload["p5"] == 0.1
        assert payload["p95"] == 0.9
        assert payload["underflow_count"] == 2
        assert payload["overflow_count"] == 3

    def test_payload_reads_back_via_state_from_data(self) -> None:
        state = CalibrationState(
            model_id="m1",
            head_name="head",
            label="rock",
            calibration_def_hash="def",
            histogram={"bins": [1, 2]},
            histogram_bins=[{"b": 1}],
            p5=0.05,
            p95=0.95,
            sample_count=7,
            underflow_count=1,
            overflow_count=2,
            updated_at=1000,
        )
        record = CalibrationStateRecord(
            id=1,
            model_id="m1",
            state_data=calibration_state_payload(state),
            updated_at=1000,
        )
        round_tripped = calibration_state_from_record(record)
        assert round_tripped == state
        assert round_tripped.sample_count == 7


@pytest.mark.unit
class TestCalibrationStateFromRecord:
    def test_maps_domain_value_never_row_dict(self) -> None:
        record = CalibrationStateRecord(
            id=5,
            model_id="m1",
            state_data={
                "head_name": "head",
                "label": "pop",
                "n": 3,
                "underflow_count": 1,
                "overflow_count": 2,
                "p5": 0.1,
                "p95": 0.9,
            },
            updated_at=1500,
        )
        state = calibration_state_from_record(record)
        assert isinstance(state, CalibrationState)
        assert not isinstance(state, dict)
        assert not hasattr(state, "id")
        assert state.model_id == "m1"
        assert state.head_name == "head"
        assert state.label == "pop"
        assert state.sample_count == 3
        assert state.underflow_count == 1
        assert state.overflow_count == 2
        assert state.p5 == 0.1
        assert state.p95 == 0.9
        assert state.updated_at == 1500


@pytest.mark.unit
class TestCalibrationStateFromJoinedRecord:
    def test_constructing_from_joined_record_does_not_raise(self) -> None:
        # Regression: the joined record carries backbone_id model metadata, but
        # CalibrationState has no backbone_id field. The mapper must not forward
        # it (Plan A removed the field) — constructing must not raise TypeError.
        record = _joined_record(state_data={"head_name": "head", "label": "pop", "n": 5, "p5": 0.1, "p95": 0.9})
        state = calibration_state_from_joined_record(record)
        assert isinstance(state, CalibrationState)
        assert state.model_id == "m_abc123"
        assert state.head_name == "head"
        assert state.label == "pop"
        assert state.sample_count == 5

    def test_backbone_id_metadata_never_leaks_into_domain(self) -> None:
        record = _joined_record(
            backbone_id="bb_9",
            state_data={"head_name": "head", "label": "pop"},
        )
        state = calibration_state_from_joined_record(record)
        assert not hasattr(state, "backbone_id")


@pytest.mark.unit
class TestCalibrationHistoryPayload:
    def test_builds_metrics_payload_with_all_required_fields(self) -> None:
        snapshot = CalibrationHistorySnapshot(
            model_id="m1",
            head_name="head",
            label="pop",
            snapshot_at=1000,
            p5=0.1,
            p95=0.9,
            sample_count=10,
            underflow_count=2,
            overflow_count=3,
            output_id="deadbeef12345678",
        )
        payload = calibration_history_payload(snapshot)
        assert payload["p5"] == 0.1
        assert payload["p95"] == 0.9
        assert payload["sample_count"] == 10
        assert payload["underflow_count"] == 2
        assert payload["overflow_count"] == 3
        # output_id forwarded verbatim, string-only
        assert payload["output_id"] == "deadbeef12345678"
        # head_name/label are injected by the repository, not the payload builder
        assert "head_name" not in payload
        assert "label" not in payload
        # None deltas are omitted (kept out of the envelope)
        assert "p5_delta" not in payload
        assert "p95_delta" not in payload
        assert "n_delta" not in payload

    def test_includes_optional_deltas_when_present(self) -> None:
        snapshot = CalibrationHistorySnapshot(
            model_id="m1",
            head_name="head",
            label="pop",
            snapshot_at=1000,
            p5=0.1,
            p95=0.9,
            sample_count=10,
            underflow_count=2,
            overflow_count=3,
            p5_delta=0.01,
            p95_delta=-0.02,
            n_delta=4,
        )
        payload = calibration_history_payload(snapshot)
        assert payload["p5_delta"] == 0.01
        assert payload["p95_delta"] == -0.02
        assert payload["n_delta"] == 4

    def test_omits_output_id_when_none(self) -> None:
        snapshot = CalibrationHistorySnapshot(
            model_id="m1",
            head_name="head",
            label="pop",
            snapshot_at=1000,
            p5=0.1,
            p95=0.9,
            sample_count=1,
            underflow_count=0,
            overflow_count=0,
        )
        assert "output_id" not in calibration_history_payload(snapshot)


@pytest.mark.unit
class TestCalibrationHistoryFromRecord:
    def _record(
        self,
        *,
        created_at: int = 1000,
        data: dict | None = None,
        model_id: str = "m1",
    ) -> CalibrationHistoryRecord:
        return CalibrationHistoryRecord(
            id=1,
            model_id=model_id,
            event="calibration_snapshot",
            data=data or {},
            created_at=created_at,
        )

    def test_maps_envelope_fields_and_created_at(self) -> None:
        record = self._record(
            created_at=1234,
            data={
                "head_name": "head",
                "label": "pop",
                "p5": 0.1,
                "p95": 0.9,
                "sample_count": 8,
                "underflow_count": 1,
                "overflow_count": 2,
                "p5_delta": 0.005,
                "p95_delta": -0.01,
                "n_delta": 3,
                "output_id": "deadbeef12345678",
            },
        )
        snapshot = calibration_history_from_record(record)
        assert isinstance(snapshot, CalibrationHistorySnapshot)
        assert not isinstance(snapshot, dict)
        assert not hasattr(snapshot, "id")
        assert not hasattr(snapshot, "event")
        assert not hasattr(snapshot, "data")
        assert snapshot.model_id == "m1"
        assert snapshot.head_name == "head"
        assert snapshot.label == "pop"
        assert snapshot.snapshot_at == 1234  # from the created_at epoch-ms column
        assert snapshot.p5 == 0.1
        assert snapshot.p95 == 0.9
        assert snapshot.sample_count == 8
        assert snapshot.underflow_count == 1
        assert snapshot.overflow_count == 2
        assert snapshot.p5_delta == 0.005
        assert snapshot.p95_delta == -0.01
        assert snapshot.n_delta == 3
        assert snapshot.output_id == "deadbeef12345678"

    def test_output_id_forwarded_verbatim_string_only(self) -> None:
        record = self._record(data={"head_name": "head", "label": "pop", "output_id": "cafebabe00000000"})
        snapshot = calibration_history_from_record(record)
        assert snapshot.output_id == "cafebabe00000000"
        assert isinstance(snapshot.output_id, str)

    def test_deltas_none_safe(self) -> None:
        record = self._record(data={"head_name": "head", "label": "pop", "p5": 0.2, "p95": 0.8})
        snapshot = calibration_history_from_record(record)
        assert snapshot.p5_delta is None
        assert snapshot.p95_delta is None
        assert snapshot.n_delta is None
        assert snapshot.output_id is None

    def test_zero_delta_preserved(self) -> None:
        # A stored delta of exactly 0.0 is a genuine value, not a falsy sentinel.
        record = self._record(data={"head_name": "head", "label": "pop", "p5_delta": 0.0, "p95_delta": 0.0})
        snapshot = calibration_history_from_record(record)
        assert snapshot.p5_delta == 0.0
        assert snapshot.p95_delta == 0.0
