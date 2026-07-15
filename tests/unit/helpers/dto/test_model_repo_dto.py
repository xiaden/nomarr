"""Unit tests for model_repo_dto TypedDict definitions."""

from __future__ import annotations

import pytest

from nomarr.helpers.dto.model_repo_dto import ModelRecord


@pytest.mark.unit
class TestModelRecord:
    """Tests for ModelRecord TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """ModelRecord should be creatable with all required fields."""
        row = ModelRecord(
            id="model_1",
            model_type="genre",
            backbone_id="bb_test",
            enabled=1,
            created_at=1000,
            updated_at=2000,
        )
        assert row["id"] == "model_1"
        assert row["model_type"] == "genre"
        assert row["backbone_id"] == "bb_test"
        assert row["enabled"] == 1
        assert row["created_at"] == 1000
        assert row["updated_at"] == 2000

    @pytest.mark.unit
    def test_can_create_with_extended_fields(self) -> None:
        """ModelRecord should be creatable with all 17 fields (6 required + 11 NotRequired)."""
        row = ModelRecord(
            id="model_ext",
            model_type="genre",
            backbone_id="bb_test",
            enabled=1,
            created_at=1000,
            updated_at=2000,
            path="/models/effnet/heads/sigmoid/mood_happy.onnx",
            backbone="effnet",
            head_type="sigmoid",
            model_stem="mood_happy",
            output_count=3,
            fully_configured=1,
            is_known=1,
            source="discovered",
            head_release_date="2026-01-15",
            embedder_release_date="2026-01-01",
            registered_at=1700000000,
        )
        assert row["id"] == "model_ext"
        assert row["path"] == "/models/effnet/heads/sigmoid/mood_happy.onnx"
        assert row["backbone"] == "effnet"
        assert row["head_type"] == "sigmoid"
        assert row["model_stem"] == "mood_happy"
        assert row["output_count"] == 3
        assert row["fully_configured"] == 1
        assert row["is_known"] == 1
        assert row["source"] == "discovered"
        assert row["head_release_date"] == "2026-01-15"
        assert row["embedder_release_date"] == "2026-01-01"
        assert row["registered_at"] == 1700000000
