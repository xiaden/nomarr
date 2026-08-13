"""Unit tests for vector_repo_dto TypedDict definitions."""

from __future__ import annotations

import pytest

from nomarr.helpers.dto.vector_repo_dto import EmbeddingRecord, SimilarResult


@pytest.mark.unit
class TestEmbeddingRecord:
    """Tests for EmbeddingRecord TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """EmbeddingRecord should be creatable with all required fields."""
        row = EmbeddingRecord(
            id=1,
            song_id=42,
            backbone_id="bb_test",
            tier="hot",
            embed_dim=128,
            model_suite_hash="abc123",
            num_segments=10,
            segmentation_hash="seg_hash",
            genres=["rock", "pop"],
            created_at=1000,
            updated_at=2000,
        )
        assert row["id"] == 1
        assert row["song_id"] == 42
        assert row["backbone_id"] == "bb_test"
        assert row["tier"] == "hot"
        assert row["embed_dim"] == 128
        assert row["model_suite_hash"] == "abc123"
        assert row["num_segments"] == 10
        assert row["segmentation_hash"] == "seg_hash"
        assert row["genres"] == ["rock", "pop"]
        assert row["created_at"] == 1000
        assert row["updated_at"] == 2000


@pytest.mark.unit
class TestSimilarResult:
    """Tests for SimilarResult TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """SimilarResult should be creatable with all required fields."""
        row = SimilarResult(
            song_id=42,
            backbone_id="bb_test",
            distance=0.15,
        )
        assert row["song_id"] == 42
        assert row["backbone_id"] == "bb_test"
        assert row["distance"] == 0.15
