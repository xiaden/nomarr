"""Unit tests pinning the persistence-internal vector_repo DTO TypedDicts.

``EmbeddingRecord`` and ``SimilarResult`` are persistence-internal storage DTOs
used only by the vector repository row mappers (``nomarr/persistence/database/
vector_repo.py``).  They mirror SQLAlchemy ``Embedding`` columns / search rows
and are NOT the caller-facing vector contract.

The corrected caller-facing vector contract lives in
``nomarr/helpers/dataclasses/vector_dataclass.py`` (``SongVector``,
``VectorMatch``, ``EmbeddingCounts``) and is what ``MlDb`` read intents expose.
These tests keep the DTOs pinned as valid TypedDicts so repository mapping stays
type-safe while proving their keys are persistence-shaped (storage ``song_id``,
``backbone_id``, ``tier``, ``distance``) rather than domain semantics.
"""

from __future__ import annotations

import pytest

from nomarr.helpers.dto.vector_repo_dto import EmbeddingRecord, SimilarResult


@pytest.mark.unit
class TestEmbeddingRecordIsPersistenceInternal:
    """EmbeddingRecord mirrors embeddings-table storage columns."""

    def test_can_create_with_all_storage_fields(self) -> None:
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

    def test_keys_are_storage_shaped_not_domain(self) -> None:
        """DTO keys are storage row concepts, not caller-facing domain values."""
        # Storage song foreign key and tier predicate are persistence concerns.
        assert set(EmbeddingRecord.__annotations__).issuperset(
            {"id", "song_id", "backbone_id", "tier", "embed_dim", "created_at", "updated_at"}
        )
        # The DTO does not carry the caller-facing domain identity/song fields.
        assert not set(EmbeddingRecord.__annotations__).intersection({"song", "vector"})


@pytest.mark.unit
class TestSimilarResultIsPersistenceInternal:
    """SimilarResult mirrors an ANN search row (storage ids plus distance)."""

    def test_can_create_with_all_storage_fields(self) -> None:
        """SimilarResult should be creatable with all required fields."""
        row = SimilarResult(
            song_id=42,
            backbone_id="bb_test",
            distance=0.15,
            score=0.85,
        )
        assert row["song_id"] == 42
        assert row["backbone_id"] == "bb_test"
        assert row["distance"] == 0.15
        assert row["score"] == 0.85

    def test_keys_are_storage_shaped_not_domain(self) -> None:
        """SimilarResult carries a storage song id, not a domain identity."""
        assert set(SimilarResult.__annotations__).issuperset({"song_id", "backbone_id", "distance", "score"})
        # The caller-facing VectorMatch carries SongIdentity.song, not song_id.
        assert "song" not in SimilarResult.__annotations__
