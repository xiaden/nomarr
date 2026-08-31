"""Unit tests for calibration_repo_dto repository-internal DTO definitions.

These DTOs are strictly repository-internal (ADR-032/040, ASR-0013/0014): they
mirror the SQLAlchemy ``CalibrationState``/``CalibrationHistory`` row shapes and
the ``list_states_with_models`` join result so that repository method return
types are type-safe.  They must never surface on the caller-facing intent
facade — the persistence mapper converts them to domain value objects before
anything crosses the boundary.
"""

from __future__ import annotations

import pytest

from nomarr.helpers.dto.calibration_repo_dto import (
    CalibrationHistoryRecord,
    CalibrationStateJoined,
    CalibrationStateRecord,
)


@pytest.mark.unit
class TestCalibrationStateRecord:
    """Tests for CalibrationStateRecord TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """CalibrationStateRecord should be creatable with all required fields."""
        row = CalibrationStateRecord(
            id=1,
            model_id="model_1",
            state_data={"threshold": 0.8, "status": "calibrated"},
            updated_at=2000,
        )
        assert row["id"] == 1
        assert row["model_id"] == "model_1"
        assert row["state_data"]["threshold"] == 0.8
        assert row["state_data"]["status"] == "calibrated"
        assert row["updated_at"] == 2000


@pytest.mark.unit
class TestCalibrationHistoryRecord:
    """Tests for CalibrationHistoryRecord TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """CalibrationHistoryRecord should be creatable with all required fields."""
        row = CalibrationHistoryRecord(
            id=1,
            model_id="model_1",
            event="calibration_started",
            data={"iterations": 100},
            created_at=1000,
        )
        assert row["id"] == 1
        assert row["model_id"] == "model_1"
        assert row["event"] == "calibration_started"
        assert row["data"]["iterations"] == 100
        assert row["created_at"] == 1000


@pytest.mark.unit
class TestCalibrationStateJoined:
    """Tests for the repository-internal CalibrationStateJoined join result."""

    def test_can_create_with_closed_field_set(self) -> None:
        row = CalibrationStateJoined(
            model_id="m_abc",
            state_data={"head_name": "head", "label": "pop"},
            updated_at=2000,
            id="m_abc",
            path="/models/m_abc",
            model_type="genre",
            backbone_id="bb_1",
            backbone="bb_1",
            head_type="linear",
            model_stem="m_abc",
            output_count=16,
            fully_configured=1,
            is_known=1,
            source="local",
            head_release_date="2026-01-01",
            embedder_release_date="2026-01-01",
        )
        assert row["model_id"] == "m_abc"
        assert row["state_data"]["label"] == "pop"
        assert row["backbone_id"] == "bb_1"
        assert row["model_type"] == "genre"
        assert row["output_count"] == 16
        assert row["fully_configured"] == 1

    def test_is_dict_subclass_assignable_to_dict(self) -> None:
        # CalibrationStateJoined is a dict subclass so ml.py's
        # calibration_state_from_joined_record(dict[str, Any]) call stays
        # mypy-clean while the typed constructor enforces the closed field set.
        row = CalibrationStateJoined(
            model_id="m_abc",
            state_data={},
            updated_at=2000,
            id="m_abc",
            path="p",
            model_type="genre",
            backbone_id="bb_1",
            backbone="bb_1",
            head_type="linear",
            model_stem="s",
            output_count=1,
            fully_configured=1,
            is_known=1,
            source="local",
            head_release_date="2026-01-01",
            embedder_release_date="2026-01-01",
        )
        assert isinstance(row, dict)
        assert row.get("model_id") == "m_abc"
        assert row.get("updated_at") == 2000
