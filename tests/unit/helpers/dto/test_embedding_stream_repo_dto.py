"""Unit tests for embedding_stream_repo_dto TypedDict definitions."""

from __future__ import annotations

import pytest

from nomarr.helpers.dto.embedding_stream_repo_dto import EmbeddingStreamRecord


@pytest.mark.unit
class TestEmbeddingStreamRecord:
    """Tests for EmbeddingStreamRecord TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """EmbeddingStreamRecord should be creatable with all required fields."""
        row = EmbeddingStreamRecord(
            id=1,
            file_id=42,
            backbone="bb_test",
            patches_emb=b"\x00\x01\x02\x03",
            created_at=1000,
            updated_at=2000,
        )
        assert row["id"] == 1
        assert row["file_id"] == 42
        assert row["backbone"] == "bb_test"
        assert row["patches_emb"] == b"\x00\x01\x02\x03"
        assert row["created_at"] == 1000
        assert row["updated_at"] == 2000
