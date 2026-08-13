"""Unit tests for output_repo_dto TypedDict definitions."""

from __future__ import annotations

import pytest

from nomarr.helpers.dto.output_repo_dto import ModelOutputRecord, OutputStreamRecord


@pytest.mark.unit
class TestOutputStreamRecord:
    """Tests for OutputStreamRecord TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """OutputStreamRecord should be creatable with all required fields."""
        row = OutputStreamRecord(
            id=1,
            song_id=42,
            model_id="model_1",
            status="pending",
            created_at=1000,
        )
        assert row["id"] == 1
        assert row["song_id"] == 42
        assert row["model_id"] == "model_1"
        assert row["status"] == "pending"
        assert row["created_at"] == 1000


@pytest.mark.unit
class TestModelOutputRecord:
    """Tests for ModelOutputRecord TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """ModelOutputRecord should be creatable with all required fields."""
        row = ModelOutputRecord(
            id=1,
            song_id=42,
            model_id="model_1",
            output_data={"genre": "rock", "confidence": 0.95},
            created_at=1000,
        )
        assert row["id"] == 1
        assert row["song_id"] == 42
        assert row["model_id"] == "model_1"
        assert row["output_data"]["genre"] == "rock"
        assert row["output_data"]["confidence"] == 0.95
        assert row["created_at"] == 1000

    @pytest.mark.unit
    def test_can_create_with_extended_fields(self) -> None:
        """ModelOutputRecord should be creatable with all 8 fields (5 required + 3 NotRequired)."""
        row = ModelOutputRecord(
            id=1,
            song_id=42,
            model_id="model_1",
            output_data={"genre": "rock", "confidence": 0.95},
            created_at=1000,
            output_index=0,
            label="rock",
            fully_labeled=True,
        )
        assert row["id"] == 1
        assert row["song_id"] == 42
        assert row["model_id"] == "model_1"
        assert row["output_data"]["genre"] == "rock"
        assert row["created_at"] == 1000
        assert row["output_index"] == 0
        assert row["label"] == "rock"
        assert row["fully_labeled"] is True
