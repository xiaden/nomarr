"""Unit tests for calibration_repo_dto TypedDict definitions."""

from __future__ import annotations

import pytest

from nomarr.helpers.dto.calibration_repo_dto import (
    CalibrationHistoryRecord,
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
