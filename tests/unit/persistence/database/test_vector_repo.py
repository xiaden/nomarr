"""Unit tests for VectorRepo — embedding storage and ANN search."""

from __future__ import annotations

from itertools import count
from unittest.mock import MagicMock

import numpy as np
import pytest
from sqlalchemy import insert, update

from nomarr.persistence.database.song_tag_repo import SongTagRepository
from nomarr.persistence.database.tag_repo import TagRepository
from nomarr.persistence.database.vector_repo import VectorRepo
from nomarr.persistence.models.embedding import Embedding
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.song import Song

# Embedding dimension must match HALFVEC(1280) in the Embedding model.
_EMBED_DIM = 1280
_BACKBONE = "test_backbone"
_LIBRARY_NAMES = count(1)


def _create_library_and_song(session) -> tuple[int, int]:
    """Helper: create a library and a song, return (library_id, song_id)."""
    lib_r = session.execute(
        insert(Library).values(
            name=f"Vector Lib {next(_LIBRARY_NAMES)}",
            path="/vector/lib",
            library_type="music",
            auto_tag=0,
            auto_curate=0,
            created_at=1000,
            updated_at=1000,
        )
    )
    lib_id = lib_r.inserted_primary_key[0]
    song_r = session.execute(
        insert(Song).values(
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
    song_id = song_r.inserted_primary_key[0]
    return lib_id, song_id


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
        _, song_id = _create_library_and_song(pg_session)
        repo = VectorRepo(pg_session)
        vec = _random_vector(seed=1)
        record = repo.insert_embedding(
            song_id=song_id,
            backbone_id=_BACKBONE,
            model_id="test_model",
            embedding_vector=vec,
        )
        assert record["id"] > 0
        assert record["song_id"] == song_id
        assert record["backbone_id"] == _BACKBONE
        assert record["tier"] == "hot"
        assert record["embed_dim"] == _EMBED_DIM

    def test_insert_embedding_with_genres(self, pg_session) -> None:
        """insert_embedding should store genres when provided."""
        _, song_id = _create_library_and_song(pg_session)
        repo = VectorRepo(pg_session)
        vec = _random_vector(seed=2)
        record = repo.insert_embedding(
            song_id=song_id,
            backbone_id=_BACKBONE,
            model_id="test_model",
            embedding_vector=vec,
            genres=["rock", "progressive"],
        )
        assert record["genres"] == ["rock", "progressive"]

    def test_backfill_genres_updates_cold_embeddings(self, pg_session) -> None:
        """backfill_genres should copy genre tags onto missing cold embeddings."""
        _, song_id = _create_library_and_song(pg_session)
        tag_id = TagRepository(pg_session).create_tag(
            {"name": "genre", "value": "rock", "namespace": "nom", "source": "test", "created_at": 1000}
        )
        SongTagRepository(pg_session).assign_tag_to_song(song_id, tag_id, source="test")
        repo = VectorRepo(pg_session)
        repo.insert_embedding(
            song_id=song_id,
            backbone_id=_BACKBONE,
            model_id="test_model",
            embedding_vector=_random_vector(seed=3),
        )
        pg_session.execute(
            update(Embedding.__table__).where(Embedding.__table__.c.song_id == song_id).values(tier="cold")
        )
        pg_session.commit()

        assert repo.backfill_genres(_BACKBONE) == 1
        record = repo.get_embeddings_for_song(song_id, _BACKBONE)[0]
        assert record["genres"] == ["rock"]

    # ── find_nearest ────────────────────────────────────────────

    def test_find_nearest_returns_ordered_results(self, pg_session) -> None:
        """find_nearest should return SimilarResult list ordered by cosine distance."""
        lib_id, song_id = _create_library_and_song(pg_session)
        repo = VectorRepo(pg_session)

        # Insert several embeddings — each needs a unique song_id due to FK constraint
        vectors = [_random_vector(seed=i) for i in range(10)]
        song_ids = [song_id]
        for i in range(1, 10):
            song_r = pg_session.execute(
                insert(Song).values(
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
            song_ids.append(song_r.inserted_primary_key[0])

        for i, vec in enumerate(vectors):
            repo.insert_embedding(
                song_id=song_ids[i],
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
        _, song_id = _create_library_and_song(pg_session)
        repo = VectorRepo(pg_session)

        # Insert 5 hot embeddings
        for i in range(5):
            repo.insert_embedding(
                song_id=song_id,
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

    # ── get_embeddings_for_song ─────────────────────────────────

    def test_get_embeddings_for_song_filters_backbone_and_tier(self, pg_session) -> None:
        """get_embeddings_for_song should not return another backbone or hot row."""
        _, song_id = _create_library_and_song(pg_session)
        repo = VectorRepo(pg_session)

        # Insert embeddings for this song with different backbones
        repo.insert_embedding(
            song_id=song_id,
            backbone_id="backbone_a",
            model_id="model_a",
            embedding_vector=_random_vector(seed=200),
        )
        repo.insert_embedding(
            song_id=song_id,
            backbone_id="backbone_b",
            model_id="model_b",
            embedding_vector=_random_vector(seed=201),
        )

        repo.drain_hot_to_cold("backbone_a")

        results = repo.get_embeddings_for_song(song_id, "backbone_a")
        assert len(results) == 1
        assert results[0]["backbone_id"] == "backbone_a"
        assert repo.get_embeddings_for_song(song_id, "backbone_b") == []

    def test_get_embeddings_for_song_nonexistent(self, pg_session) -> None:
        """get_embeddings_for_song should return empty list for unknown song."""
        repo = VectorRepo(pg_session)
        results = repo.get_embeddings_for_song(999999, "unknown")
        assert results == []

    def test_multiple_backbones_for_same_song_are_preserved(self, pg_session) -> None:
        """Inserting embeddings for different backbones of one song preserves both.

        The ``embeddings`` table keys rows by ``(song_id, backbone_id)``, so
        backbone-scoped deletion (as performed by
        ``MlInferenceRepo.replace_song_inference_results``) can replace one
        backbone without erasing others.
        """
        _, song_id = _create_library_and_song(pg_session)
        repo = VectorRepo(pg_session)
        repo.insert_embedding(
            song_id=song_id,
            backbone_id="backbone_a",
            model_id="model_a",
            embedding_vector=_random_vector(seed=810),
        )
        repo.insert_embedding(
            song_id=song_id,
            backbone_id="backbone_b",
            model_id="model_b",
            embedding_vector=_random_vector(seed=811),
        )

        repo.drain_hot_to_cold("backbone_a")
        repo.drain_hot_to_cold("backbone_b")
        results = repo.get_embeddings_for_song(song_id, "backbone_a")
        backbone_ids = {r["backbone_id"] for r in results}
        assert backbone_ids == {"backbone_a"}

    # ── count_cold_embeddings ───────────────────────────────────

    def test_count_cold_embeddings(self, pg_session) -> None:
        """count_cold_embeddings should return correct count after drain."""
        _, song_id = _create_library_and_song(pg_session)
        repo = VectorRepo(pg_session)

        for i in range(3):
            repo.insert_embedding(
                song_id=song_id,
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
        _, song_id = _create_library_and_song(pg_session)
        repo = VectorRepo(pg_session)

        # Insert 4 embeddings (all hot)
        for i in range(4):
            repo.insert_embedding(
                song_id=song_id,
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

    def test_get_embedding_stats_scopes_to_library(self, pg_session) -> None:
        """Scoped stats should exclude embeddings belonging to another library."""
        first_library_id, first_song_id = _create_library_and_song(pg_session)
        _, second_song_id = _create_library_and_song(pg_session)
        repo = VectorRepo(pg_session)

        for song_id in (first_song_id, second_song_id):
            repo.insert_embedding(
                song_id=song_id,
                backbone_id=_BACKBONE,
                model_id="test_model",
                embedding_vector=_random_vector(seed=500 + song_id),
            )

        stats = repo.get_embedding_stats(_BACKBONE, library_id=first_library_id)

        assert stats == {"hot_count": 1, "cold_count": 0}

    # ── delete_all_embeddings ───────────────────────────────────

    def test_delete_all_embeddings(self, pg_session) -> None:
        """delete_all_embeddings should remove all rows."""
        _, song_id = _create_library_and_song(pg_session)
        repo = VectorRepo(pg_session)

        for i in range(3):
            repo.insert_embedding(
                song_id=song_id,
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
        _lib_id1, song_id1 = _create_library_and_song(pg_session)
        # Create a second library + song
        lib_r = pg_session.execute(
            insert(Library).values(
                name=f"Vector Lib {next(_LIBRARY_NAMES)}",
                path="/vector/lib/truncate2",
                library_type="music",
                auto_tag=0,
                auto_curate=0,
                created_at=2000,
                updated_at=2000,
            )
        )
        lib_id2 = lib_r.inserted_primary_key[0]
        song_r = pg_session.execute(
            insert(Song).values(
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
        song_id2 = song_r.inserted_primary_key[0]

        repo = VectorRepo(pg_session)

        # Insert embeddings for two different songs
        repo.insert_embedding(
            song_id=song_id1,
            backbone_id=_BACKBONE,
            model_id="test_model",
            embedding_vector=_random_vector(seed=700),
        )
        repo.insert_embedding(
            song_id=song_id2,
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

    # ── delete_embeddings_for_song ──────────────────────────────

    def test_delete_embeddings_for_song(self, pg_session) -> None:
        """delete_embeddings_for_song should remove only that song's embeddings."""
        lib_id, song_id1 = _create_library_and_song(pg_session)
        # Create a second song
        song_r = pg_session.execute(
            insert(Song).values(
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
        song_id2 = song_r.inserted_primary_key[0]

        repo = VectorRepo(pg_session)
        repo.insert_embedding(
            song_id=song_id1,
            backbone_id=_BACKBONE,
            model_id="test_model",
            embedding_vector=_random_vector(seed=600),
        )
        repo.insert_embedding(
            song_id=song_id2,
            backbone_id=_BACKBONE,
            model_id="test_model",
            embedding_vector=_random_vector(seed=601),
        )
        repo.insert_embedding(
            song_id=song_id1,
            backbone_id="other_backbone",
            model_id="other_model",
            embedding_vector=_random_vector(seed=602),
        )

        # Delete only song_id1's embeddings for the selected backbone.
        repo.delete_embeddings_for_song(song_id1, _BACKBONE)

        # song_id1 should have none
        results1 = repo.get_embeddings_for_song(song_id1, _BACKBONE, tier="hot")
        assert len(results1) == 0

        # song_id1's other backbone should still be present.
        other_results = repo.get_embeddings_for_song(song_id1, "other_backbone", tier="hot")
        assert len(other_results) == 1

        # song_id2 should still have its embedding
        results2 = repo.get_embeddings_for_song(song_id2, _BACKBONE, tier="hot")
        assert len(results2) == 1


@pytest.mark.unit
@pytest.mark.mocked
class TestVectorRepoSqlAlchemyTyping:
    """Pin the SQLAlchemy typing/rowcount conventions added by P2-S2.

    - ``rebuild_cold_hnsw_index`` narrows ``get_bind()`` to an ``Engine`` so
      ``.connect()`` type-checks, then runs outside a transaction.
    - ``drain_hot_to_cold``/``backfill_genres`` read the affected-row count via
      ``int(result.rowcount)`` — the existing rowcount convention — rather than
      a non-existent ``result.rowcount`` attribute access.
    """

    def test_rebuild_cold_hnsw_index_uses_narrowed_engine_and_connect(self) -> None:
        session = MagicMock()
        engine = MagicMock()
        connection = MagicMock()
        session.get_bind.return_value = engine
        # ``cast("Engine", get_bind())`` -> ``.connect().execution_options(...)``
        engine.connect.return_value.execution_options.return_value = connection
        connection.__enter__ = MagicMock(return_value=connection)
        connection.__exit__ = MagicMock(return_value=False)
        repo = VectorRepo(session)

        repo.rebuild_cold_hnsw_index()

        session.get_bind.assert_called_once_with()
        engine.connect.assert_called_once_with()
        engine.connect.return_value.execution_options.assert_called_once_with(isolation_level="AUTOCOMMIT")
        connection.execute.assert_called_once()

    def test_drain_hot_to_cold_returns_int_rowcount(self) -> None:
        session = MagicMock()
        result = MagicMock()
        result.rowcount = 5
        session.execute.return_value = result
        repo = VectorRepo(session)

        count = repo.drain_hot_to_cold(_BACKBONE)

        assert count == 5
        session.commit.assert_called_once_with()

    def test_backfill_genres_returns_int_rowcount(self) -> None:
        session = MagicMock()
        result = MagicMock()
        result.rowcount = 3
        session.execute.return_value = result
        repo = VectorRepo(session)

        count = repo.backfill_genres(_BACKBONE)

        assert count == 3
        session.commit.assert_called_once_with()
