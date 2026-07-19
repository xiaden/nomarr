"""Unit tests for VectorRepo — embedding storage and ANN search."""

from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy import insert

from nomarr.persistence.database.vector_repo import VectorRepo
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.library_file import LibraryFile

# Embedding dimension must match HALFVEC(1280) in the Embedding model.
_EMBED_DIM = 1280
_BACKBONE = "test_backbone"


def _create_library_and_file(session) -> tuple[int, int]:
    """Helper: create a library and a file, return (library_id, file_id)."""
    lib_r = session.execute(
        insert(Library).values(
            name="Vector Lib",
            path="/vector/lib",
            library_type="music",
            auto_tag=0,
            auto_curate=0,
            created_at=1000,
            updated_at=1000,
        )
    )
    lib_id = lib_r.inserted_primary_key[0]
    file_r = session.execute(
        insert(LibraryFile).values(
            library_id=lib_id,
            path="/vector/lib/test.mp3",
            normalized_path="/vector/lib/test.mp3",
            file_size=1000,
            modified_time=1000,
            duration_seconds=180,
            needs_tagging=0,
            is_valid=1,
            tagged=0,
            created_at=1000,
        )
    )
    file_id = file_r.inserted_primary_key[0]
    return lib_id, file_id


def _random_vector(dim: int = _EMBED_DIM, seed: int | None = None) -> list[float]:
    """Generate a random L2-normalized vector."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    v /= np.linalg.norm(v)
    return v.tolist()  # type: ignore[no-any-return]


@pytest.mark.integration
@pytest.mark.requires_database
@pytest.mark.skip(
    reason="Requires pgvector extension — the ``embeddings`` table "
    "uses HALFVEC type and ``<=>`` operator not supported by SQLite"
)
class TestVectorRepo:
    """Tests for VectorRepo methods."""

    # ── insert_embedding ────────────────────────────────────────

    def test_insert_embedding(self, pg_session) -> None:
        """insert_embedding should insert a row with tier='hot'."""
        _, file_id = _create_library_and_file(pg_session)
        repo = VectorRepo(pg_session)
        vec = _random_vector(seed=1)
        record = repo.insert_embedding(
            file_id=file_id,
            backbone_id=_BACKBONE,
            model_id="test_model",
            embedding_vector=vec,
        )
        assert record["id"] > 0
        assert record["file_id"] == file_id
        assert record["backbone_id"] == _BACKBONE
        assert record["tier"] == "hot"
        assert record["embed_dim"] == _EMBED_DIM

    def test_insert_embedding_with_genres(self, pg_session) -> None:
        """insert_embedding should store genres when provided."""
        _, file_id = _create_library_and_file(pg_session)
        repo = VectorRepo(pg_session)
        vec = _random_vector(seed=2)
        record = repo.insert_embedding(
            file_id=file_id,
            backbone_id=_BACKBONE,
            model_id="test_model",
            embedding_vector=vec,
            genres=["rock", "progressive"],
        )
        assert record["genres"] == ["rock", "progressive"]

    # ── find_nearest ────────────────────────────────────────────

    def test_find_nearest_returns_ordered_results(self, pg_session) -> None:
        """find_nearest should return SimilarResult list ordered by cosine distance."""
        lib_id, file_id = _create_library_and_file(pg_session)
        repo = VectorRepo(pg_session)

        # Insert several embeddings — each needs a unique file_id due to FK constraint
        vectors = [_random_vector(seed=i) for i in range(10)]
        file_ids = [file_id]
        for i in range(1, 10):
            file_r = pg_session.execute(
                insert(LibraryFile).values(
                    library_id=lib_id,
                    path=f"/vector/lib/test_{i}.mp3",
                    normalized_path=f"/vector/lib/test_{i}.mp3",
                    file_size=1000 + i,
                    modified_time=1000 + i,
                    duration_seconds=180,
                    needs_tagging=0,
                    is_valid=1,
                    tagged=0,
                    created_at=1000 + i,
                )
            )
            file_ids.append(file_r.inserted_primary_key[0])

        for i, vec in enumerate(vectors):
            repo.insert_embedding(
                file_id=file_ids[i],
                backbone_id=_BACKBONE,
                model_id="test_model",
                embedding_vector=vec,
            )

        # Drain to cold so find_nearest can search them
        repo.drain_hot_to_cold(_BACKBONE)

        # Query with the first vector — it should be the nearest to itself
        query_vec = vectors[0]
        results = repo.find_nearest(query_vec, _BACKBONE, limit=5)
        assert len(results) > 0
        assert len(results) <= 5
        # Results should be ordered by distance (ascending)
        distances = [r["distance"] for r in results]
        assert distances == sorted(distances)
        # First result should have very small distance (near-zero for same vector)
        assert results[0]["distance"] < 0.01

    def test_find_nearest_empty_table(self, pg_session) -> None:
        """find_nearest should return empty list when no cold embeddings exist."""
        repo = VectorRepo(pg_session)
        query_vec = _random_vector(seed=99)
        results = repo.find_nearest(query_vec, _BACKBONE, limit=10)
        assert results == []

    # ── drain_hot_to_cold ───────────────────────────────────────

    def test_drain_hot_to_cold(self, pg_session) -> None:
        """drain_hot_to_cold should update tier and return count."""
        _, file_id = _create_library_and_file(pg_session)
        repo = VectorRepo(pg_session)

        # Insert 5 hot embeddings
        for i in range(5):
            repo.insert_embedding(
                file_id=file_id,
                backbone_id=_BACKBONE,
                model_id="test_model",
                embedding_vector=_random_vector(seed=100 + i),
            )

        # Verify they're hot
        stats = repo.get_embedding_stats(_BACKBONE)
        assert stats["hot_count"] == 5
        assert stats["cold_count"] == 0

        # Drain
        count = repo.drain_hot_to_cold(_BACKBONE)
        assert count == 5

        # Verify they're now cold
        stats = repo.get_embedding_stats(_BACKBONE)
        assert stats["hot_count"] == 0
        assert stats["cold_count"] == 5

    def test_drain_hot_to_cold_no_rows(self, pg_session) -> None:
        """drain_hot_to_cold should return 0 when no hot embeddings exist."""
        repo = VectorRepo(pg_session)
        count = repo.drain_hot_to_cold("nonexistent_backbone")
        assert count == 0

    # ── get_embeddings_for_file ─────────────────────────────────

    def test_get_embeddings_for_file(self, pg_session) -> None:
        """get_embeddings_for_file should return all embeddings for a file."""
        _, file_id = _create_library_and_file(pg_session)
        repo = VectorRepo(pg_session)

        # Insert embeddings for this file with different backbones
        repo.insert_embedding(
            file_id=file_id,
            backbone_id="backbone_a",
            model_id="model_a",
            embedding_vector=_random_vector(seed=200),
        )
        repo.insert_embedding(
            file_id=file_id,
            backbone_id="backbone_b",
            model_id="model_b",
            embedding_vector=_random_vector(seed=201),
        )

        results = repo.get_embeddings_for_file(file_id)
        assert len(results) == 2
        backbone_ids = {r["backbone_id"] for r in results}
        assert "backbone_a" in backbone_ids
        assert "backbone_b" in backbone_ids

    def test_get_embeddings_for_file_nonexistent(self, pg_session) -> None:
        """get_embeddings_for_file should return empty list for unknown file."""
        repo = VectorRepo(pg_session)
        results = repo.get_embeddings_for_file(999999)
        assert results == []

    # ── count_cold_embeddings ───────────────────────────────────

    def test_count_cold_embeddings(self, pg_session) -> None:
        """count_cold_embeddings should return correct count after drain."""
        _, file_id = _create_library_and_file(pg_session)
        repo = VectorRepo(pg_session)

        for i in range(3):
            repo.insert_embedding(
                file_id=file_id,
                backbone_id=_BACKBONE,
                model_id="test_model",
                embedding_vector=_random_vector(seed=300 + i),
            )

        # Before drain — all hot
        assert repo.count_cold_embeddings(_BACKBONE) == 0

        # After drain
        repo.drain_hot_to_cold(_BACKBONE)
        assert repo.count_cold_embeddings(_BACKBONE) == 3

    # ── get_embedding_stats ─────────────────────────────────────

    def test_get_embedding_stats(self, pg_session) -> None:
        """get_embedding_stats should return hot and cold counts."""
        _, file_id = _create_library_and_file(pg_session)
        repo = VectorRepo(pg_session)

        # Insert 4 embeddings (all hot)
        for i in range(4):
            repo.insert_embedding(
                file_id=file_id,
                backbone_id=_BACKBONE,
                model_id="test_model",
                embedding_vector=_random_vector(seed=400 + i),
            )

        stats = repo.get_embedding_stats(_BACKBONE)
        assert stats["hot_count"] == 4
        assert stats["cold_count"] == 0

        # Drain 2 by inserting 2 more and draining all
        repo.drain_hot_to_cold(_BACKBONE)
        stats = repo.get_embedding_stats(_BACKBONE)
        assert stats["hot_count"] == 0
        assert stats["cold_count"] == 4

    def test_get_embedding_stats_nonexistent_backbone(self, pg_session) -> None:
        """get_embedding_stats should return zeros for unknown backbone."""
        repo = VectorRepo(pg_session)
        stats = repo.get_embedding_stats("nonexistent")
        assert stats["hot_count"] == 0
        assert stats["cold_count"] == 0

    # ── delete_all_embeddings ───────────────────────────────────

    def test_delete_all_embeddings(self, pg_session) -> None:
        """delete_all_embeddings should remove all rows."""
        _, file_id = _create_library_and_file(pg_session)
        repo = VectorRepo(pg_session)

        for i in range(3):
            repo.insert_embedding(
                file_id=file_id,
                backbone_id=_BACKBONE,
                model_id="test_model",
                embedding_vector=_random_vector(seed=500 + i),
            )

        repo.delete_all_embeddings()
        assert repo.count_cold_embeddings(_BACKBONE) == 0
        stats = repo.get_embedding_stats(_BACKBONE)
        assert stats["hot_count"] == 0

    # ── truncate_embeddings ────────────────────────────────────

    def test_truncate_embeddings_clears_all_rows(self, pg_session) -> None:
        """truncate_embeddings should remove all rows from the embeddings table."""
        _lib_id1, file_id1 = _create_library_and_file(pg_session)
        # Create a second library + file
        lib_r = pg_session.execute(
            insert(Library).values(
                name="Truncate Lib 2",
                path="/vector/lib/truncate2",
                library_type="music",
                auto_tag=0,
                auto_curate=0,
                created_at=2000,
                updated_at=2000,
            )
        )
        lib_id2 = lib_r.inserted_primary_key[0]
        file_r = pg_session.execute(
            insert(LibraryFile).values(
                library_id=lib_id2,
                path="/vector/lib/truncate2.mp3",
                normalized_path="/vector/lib/truncate2.mp3",
                file_size=2000,
                modified_time=2000,
                duration_seconds=200,
                needs_tagging=0,
                is_valid=1,
                tagged=0,
                created_at=2000,
            )
        )
        file_id2 = file_r.inserted_primary_key[0]

        repo = VectorRepo(pg_session)

        # Insert embeddings for two different files
        repo.insert_embedding(
            file_id=file_id1,
            backbone_id=_BACKBONE,
            model_id="test_model",
            embedding_vector=_random_vector(seed=700),
        )
        repo.insert_embedding(
            file_id=file_id2,
            backbone_id=_BACKBONE,
            model_id="test_model",
            embedding_vector=_random_vector(seed=701),
        )

        # Drain to cold
        repo.drain_hot_to_cold(_BACKBONE)

        # Verify embeddings exist
        stats = repo.get_embedding_stats(_BACKBONE)
        assert stats["cold_count"] == 2

        # Truncate
        repo.truncate_embeddings()

        # Verify all embeddings are gone
        stats = repo.get_embedding_stats(_BACKBONE)
        assert stats["hot_count"] == 0
        assert stats["cold_count"] == 0

    # ── delete_embeddings_for_file ──────────────────────────────

    def test_delete_embeddings_for_file(self, pg_session) -> None:
        """delete_embeddings_for_file should remove only that file's embeddings."""
        lib_id, file_id1 = _create_library_and_file(pg_session)
        # Create a second file
        file_r = pg_session.execute(
            insert(LibraryFile).values(
                library_id=lib_id,
                path="/vector/lib/test2.mp3",
                normalized_path="/vector/lib/test2.mp3",
                file_size=2000,
                modified_time=2000,
                duration_seconds=200,
                needs_tagging=0,
                is_valid=1,
                tagged=0,
                created_at=2000,
            )
        )
        file_id2 = file_r.inserted_primary_key[0]

        repo = VectorRepo(pg_session)
        repo.insert_embedding(
            file_id=file_id1,
            backbone_id=_BACKBONE,
            model_id="test_model",
            embedding_vector=_random_vector(seed=600),
        )
        repo.insert_embedding(
            file_id=file_id2,
            backbone_id=_BACKBONE,
            model_id="test_model",
            embedding_vector=_random_vector(seed=601),
        )

        # Delete only file_id1's embeddings
        repo.delete_embeddings_for_file(file_id1)

        # file_id1 should have none
        results1 = repo.get_embeddings_for_file(file_id1)
        assert len(results1) == 0

        # file_id2 should still have its embedding
        results2 = repo.get_embeddings_for_file(file_id2)
        assert len(results2) == 1
