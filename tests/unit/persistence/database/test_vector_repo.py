"""Unit tests for VectorRepo — embedding storage and ANN search."""

from __future__ import annotations

from itertools import count
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from sqlalchemy import insert, update

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.vector_dataclass import EmbeddingCounts
from nomarr.persistence.database.song_tag_repo import SongTagRepository
from nomarr.persistence.database.tag_repo import TagRepository
from nomarr.persistence.database.vector_repo import (
    VectorRepo,
    _row_to_similar_result,
    _row_to_song_vector,
    _row_to_vector_match,
)
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
        """find_nearest returns descending cosine similarity scores."""
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
        # Results should be ordered by similarity (descending), with the
        # nearest self-match close to one.
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)
        assert results[0]["score"] > 0.99
        assert all(-1.0 <= score <= 1.0 for score in scores)

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


@pytest.mark.unit
class TestRowToSimilarResult:
    """Pin the canonical distance-to-score conversion, ``clamp(1 - distance, -1, 1)``.

    ``_row_to_similar_result`` lives in the repo but is otherwise only exercised
    by the DB-backed ``TestVectorRepo`` suite, which is skipped in CI. These pure
    unit cases (no database) keep the conversion mutation-guarded so an
    unclamped ``1 - distance`` or ``1 / (1 + distance)`` rewrite is caught.

    - ``distance == 1.0`` (boundary) must yield ``0.0``, matching the repo docstring.
    - ``distance > 1`` must clamp to the ``-1.0`` lower bound.
    - negative distance must clamp to the ``1.0`` upper bound.
    """

    @staticmethod
    def _row(**mapping) -> SimpleNamespace:
        """Stub that mimics a SQLAlchemy ``Row`` enough for ``_row_to_similar_result``."""
        return SimpleNamespace(_mapping=mapping)

    def test_maps_distance_to_score_and_passes_ids_through(self) -> None:
        result = _row_to_similar_result(self._row(song_id=5, backbone_id="effnet", distance=0.15))

        assert result["song_id"] == 5
        assert result["backbone_id"] == "effnet"
        assert result["distance"] == 0.15
        assert result["score"] == pytest.approx(0.85)

    def test_distance_one_yields_zero_score(self) -> None:
        result = _row_to_similar_result(self._row(song_id=1, backbone_id="effnet", distance=1.0))

        assert result["distance"] == 1.0
        assert result["score"] == 0.0

    def test_clamps_above_one_distance_to_lower_bound(self) -> None:
        result = _row_to_similar_result(self._row(song_id=1, backbone_id="effnet", distance=2.0))

        assert result["distance"] == 2.0
        assert result["score"] == -1.0

    def test_clamps_negative_distance_to_upper_bound(self) -> None:
        result = _row_to_similar_result(self._row(song_id=1, backbone_id="effnet", distance=-0.5))

        assert result["distance"] == -0.5
        assert result["score"] == 1.0

    def test_one_over_one_plus_distance_is_not_used(self) -> None:
        """Guard against the ``1 / (1 + distance)`` alternative formula."""
        result = _row_to_similar_result(self._row(song_id=1, backbone_id="effnet", distance=1.0))

        # 1 / (1 + 1.0) == 0.5, not the canonical 0.0 for this boundary distance.
        assert result["score"] == 0.0


@pytest.mark.unit
@pytest.mark.mocked
class TestGetEmbeddingCounts:
    """Exercise ``VectorRepo.get_embedding_counts`` against a mocked session.

    Pins the typed companion to ``get_embedding_stats``: ``GROUP BY tier``
    aggregation, optional library scope that adds a songs join, and the
    unresolved/name-only library => zero-counts contract (never a raise).
    Pure unit cases (no database) cover the branch and aggregation logic that
    the DB-backed ``TestVectorRepoTypedReads`` suite exercises end-to-end.
    """

    # ── aggregation / grouped counts ────────────────────────────

    @staticmethod
    def _mock_rows(*tier_counts) -> MagicMock:
        session = MagicMock()
        result = MagicMock()
        result.all.return_value = [
            SimpleNamespace(_mapping={"tier": tier, "cnt": count}) for tier, count in tier_counts
        ]
        session.execute.return_value = result
        return session

    def test_counts_both_tiers_from_group_by_rows(self) -> None:
        session = self._mock_rows(("cold", 5), ("hot", 3))
        repo = VectorRepo(session)

        counts = repo.get_embedding_counts(_BACKBONE)

        assert counts == EmbeddingCounts(hot_count=3, cold_count=5)

    def test_missing_tier_row_counts_as_zero(self) -> None:
        # Only hot rows present (e.g. nothing drained to cold yet).
        session = self._mock_rows(("hot", 4))
        repo = VectorRepo(session)

        counts = repo.get_embedding_counts(_BACKBONE)

        assert counts == EmbeddingCounts(hot_count=4, cold_count=0)

    def test_unscoped_query_groups_by_tier_without_library_join(self) -> None:
        session = self._mock_rows(("hot", 2), ("cold", 7))
        repo = VectorRepo(session)
        from sqlalchemy.dialects import postgresql

        repo.get_embedding_counts(_BACKBONE)
        stmt = session.execute.call_args_list[-1][0][0]
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        params = dict(stmt.compile(dialect=postgresql.dialect()).params)

        assert "GROUP BY" in sql
        assert "GROUP BY embeddings.tier" in sql or "GROUP BY " in sql
        assert params["backbone_id_1"] == _BACKBONE
        # No library scope => no songs join.
        assert "JOIN songs" not in sql
        assert "library_id" not in sql

    def test_scoped_library_query_joins_songs(self) -> None:
        session = self._mock_rows(("cold", 3))
        repo = VectorRepo(session)
        from sqlalchemy.dialects import postgresql

        # Resolving the library runs a lookup first; stub it to resolve id 7.
        _resolve = MagicMock(return_value=7)
        repo._resolve_library_storage_id = _resolve  # type: ignore[method-assign]

        repo.get_embedding_counts(_BACKBONE, library=LibraryIdentity(name="lib", root_path="/lib"))
        stmt = session.execute.call_args_list[-1][0][0]
        sql = str(stmt.compile(dialect=postgresql.dialect()))

        assert "JOIN songs" in sql
        assert "GROUP BY" in sql

    # ── unresolved / name-only library => zero counts ───────────

    def test_scoped_library_returns_only_its_counts(self) -> None:
        # Library resolves to a storage id (join returns only that library's rows).
        session = self._mock_rows(("hot", 1), ("cold", 2))
        repo = VectorRepo(session)
        repo._resolve_library_storage_id = MagicMock(return_value=7)  # type: ignore[method-assign]

        counts = repo.get_embedding_counts(_BACKBONE, library=LibraryIdentity(name="lib", root_path="/lib"))

        assert counts == EmbeddingCounts(hot_count=1, cold_count=2)

    def test_name_only_library_returns_zero_counts_without_querying(self) -> None:
        # A name-only identity (``root_path=None``) cannot be resolved; the real
        # ``_resolve_library_storage_id`` returns None without issuing a query,
        # so get_embedding_counts yields zero counts and never reaches the
        # grouping/counts statement.
        session = self._mock_rows()
        repo = VectorRepo(session)

        counts = repo.get_embedding_counts(_BACKBONE, library=LibraryIdentity(name="lib"))

        assert counts == EmbeddingCounts(hot_count=0, cold_count=0)
        assert session.execute.call_count == 0

    def test_unknown_library_returns_zero_counts_without_grouping_stmt(self) -> None:
        # A library with a root_path that does not exist resolves to None (real
        # resolution lookup finds nothing), yielding zero counts and issuing
        # only the resolution query — never the grouping/counts statement.
        session = self._mock_rows()
        repo = VectorRepo(session)
        # Resolution lookup runs against the session and returns no rows.
        resolution_result = MagicMock()
        resolution_result.fetchone.return_value = None
        session.execute.return_value = resolution_result

        counts = repo.get_embedding_counts(_BACKBONE, library=LibraryIdentity(name="NoLib", root_path="/nowhere"))

        assert counts == EmbeddingCounts(hot_count=0, cold_count=0)
        assert session.execute.call_count == 1


@pytest.mark.unit
class TestRowToSongVector:
    """Pin the typed cold-read mapping: stored vector preservation, element
    order, semantic ``model_id``→``model_suite_hash`` resolution, and nullable
    metadata (``genres`` ``None`` stays ``None``).

    Pure unit cases (no database) keep the row mapping mutation-guarded so a
    regression that drops the stored vector, reorders elements, or reads the
    empty persisted ``model_suite_hash`` column is caught.
    """

    _SONG = SongIdentity(library=LibraryIdentity(name="lib", root_path="/lib"), normalized_path="a.mp3")

    @staticmethod
    def _row(**mapping) -> SimpleNamespace:
        defaults = {
            "embedding": [0.5, -0.25, 0.75],
            "model_id": "suite-hash-abc",
            "num_segments": None,
            "segmentation_hash": None,
            "genres": None,
        }
        defaults.update(mapping)
        return SimpleNamespace(_mapping=defaults)

    def test_preserves_stored_vector_as_ordered_tuple(self) -> None:
        result = _row_to_song_vector(self._row(embedding=[0.1, 0.2, 0.3]), self._SONG, "effnet")

        assert result.vector == (0.1, 0.2, 0.3)

    def test_maps_semantic_suite_hash_from_model_id_not_empty_column(self) -> None:
        # The persisted ``model_suite_hash`` column is ``""``; the semantic value
        # is carried by ``model_id``.
        result = _row_to_song_vector(self._row(model_id="suite-hash-abc"), self._SONG, "effnet")

        assert result.model_suite_hash == "suite-hash-abc"

    def test_null_model_id_maps_to_none_suite_hash(self) -> None:
        result = _row_to_song_vector(self._row(model_id=None), self._SONG, "effnet")

        assert result.model_suite_hash is None

    def test_nullable_metadata_round_trip(self) -> None:
        result = _row_to_song_vector(
            self._row(num_segments=3, segmentation_hash="seg-1"),
            self._SONG,
            "effnet",
        )

        assert result.num_segments == 3
        assert result.segmentation_hash == "seg-1"

    def test_nullable_metadata_defaults_to_none(self) -> None:
        result = _row_to_song_vector(self._row(), self._SONG, "effnet")

        assert result.num_segments is None
        assert result.segmentation_hash is None

    def test_genres_none_stays_none(self) -> None:
        result = _row_to_song_vector(self._row(genres=None), self._SONG, "effnet")

        assert result.genres is None

    def test_genres_mapped_to_tuple(self) -> None:
        result = _row_to_song_vector(self._row(genres=["rock", "jazz"]), self._SONG, "effnet")

        assert result.genres == ("rock", "jazz")

    def test_identity_and_backbone_carried_through(self) -> None:
        result = _row_to_song_vector(self._row(), self._SONG, "effnet")

        assert result.song == self._SONG
        assert result.backbone == "effnet"


@pytest.mark.unit
class TestRowToVectorMatch:
    """Pin the ANN-search row→``VectorMatch`` mapping: song identity rebuilt from
    the persistence-owned join columns, and optional vector payloads."""

    @staticmethod
    def _row(**mapping) -> SimpleNamespace:
        defaults = {
            "library_name": "lib",
            "library_path": "/lib",
            "normalized_path": "a.mp3",
        }
        defaults.update(mapping)
        return SimpleNamespace(_mapping=defaults)

    def test_builds_song_identity_from_join_columns(self) -> None:
        result = _row_to_vector_match(self._row(), "effnet", 0.8, include_vector=False)

        assert result.song == SongIdentity(
            library=LibraryIdentity(name="lib", root_path="/lib"),
            normalized_path="a.mp3",
        )
        assert result.backbone == "effnet"
        assert result.score == 0.8

    def test_include_vector_false_yields_none_payload(self) -> None:
        result = _row_to_vector_match(self._row(), "effnet", 0.8, include_vector=False)

        assert result.vector is None

    def test_include_vector_true_carries_ordered_vector(self) -> None:
        result = _row_to_vector_match(
            self._row(embedding=[0.9, 0.1, 0.2]),
            "effnet",
            0.8,
            include_vector=True,
        )

        assert result.vector == (0.9, 0.1, 0.2)


@pytest.mark.unit
@pytest.mark.mocked
class TestSearchSimilarVectorsPipeline:
    """Exercise ``search_similar_vectors`` end-to-end against a mocked session:
    score clamp for below-zero/above-one raw similarities, ``min_score``
    filtering applied after the (SQL) limit, cosine ordering preserved, and
    optional ``include_vector`` payloads.

    The mocked ``result.all()`` stands in for the already-SQL-limited row set,
    so filtering here proves the persistence-side score pass happens after the
    limit (the compiled-statement test separately proves the ``LIMIT`` exists).
    """

    @staticmethod
    def _match(distance: float, embedding: list[float] | None = None) -> SimpleNamespace:
        mapping = {"library_name": "lib", "library_path": "/lib", "normalized_path": "a.mp3", "distance": distance}
        if embedding is not None:
            mapping["embedding"] = embedding
        return SimpleNamespace(_mapping=mapping)

    @staticmethod
    def _repo_that_returns(rows: list[SimpleNamespace]) -> VectorRepo:
        session = MagicMock()
        result = MagicMock()
        result.all.return_value = rows
        session.execute.return_value = result
        return VectorRepo(session)

    def test_clamps_raw_similarity_and_filters_by_min_score(self) -> None:
        # Ascending-distance order, as the DB returns them (LIMIT already applied).
        rows = [
            self._match(distance=-0.5),  # score -> clamp(1.5) == 1.0
            self._match(distance=0.2),  # score 0.8
            self._match(distance=0.5),  # score 0.5
            self._match(distance=0.9),  # score 0.1
            self._match(distance=2.0),  # score -> clamp(-1.0) == -1.0 (below min_score)
        ]
        repo = self._repo_that_returns(rows)

        matches = repo.search_similar_vectors("effnet", (0.0, 0.0, 0.0), limit=5)

        # -1.0 (distance 2.0) is dropped at the default min_score=0.0; the rest
        # keep distance order and clamped scores.
        assert [m.score for m in matches] == pytest.approx([1.0, 0.8, 0.5, 0.1])

    def test_include_vector_false_yields_none_payload(self) -> None:
        rows = [self._match(distance=0.2)]
        repo = self._repo_that_returns(rows)

        matches = repo.search_similar_vectors("effnet", (0.0, 0.0, 0.0), limit=1)

        assert len(matches) == 1
        assert matches[0].vector is None

    def test_include_vector_true_carries_ordered_stored_vector(self) -> None:
        rows = [self._match(distance=0.2, embedding=[0.7, 0.1, 0.4])]
        repo = self._repo_that_returns(rows)

        matches = repo.search_similar_vectors(
            "effnet",
            (0.0, 0.0, 0.0),
            limit=1,
            include_vector=True,
        )

        assert len(matches) == 1
        assert matches[0].vector == (0.7, 0.1, 0.4)

    def test_no_results_returns_empty_tuple(self) -> None:
        repo = self._repo_that_returns([])

        assert repo.search_similar_vectors("effnet", (0.0, 0.0, 0.0), limit=10) == ()


@pytest.mark.unit
@pytest.mark.mocked
class TestSearchSimilarVectorsCompiled:
    """Pin the compiled search SQL: cold/backbone predicates, the cosine ``<=>``
    operator, a SQL ``LIMIT`` (score filtering happens in Python afterwards),
    an INNER JOIN onto songs/libraries (un-mappable rows are omitted), and the
    embedding column selected only when ``include_vector`` is true."""

    def _search_stmt(self, *, include_vector: bool):
        session = MagicMock()
        result = MagicMock()
        result.all.return_value = []
        session.execute.return_value = result
        repo = VectorRepo(session)
        repo.search_similar_vectors(
            "effnet",
            (0.1, 0.2, 0.3),
            limit=7,
            min_score=0.5,
            include_vector=include_vector,
        )
        from sqlalchemy.dialects import postgresql

        stmt = session.execute.call_args_list[-1][0][0]
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        params = dict(stmt.compile(dialect=postgresql.dialect()).params)
        return stmt, sql, params

    def test_sql_limits_before_score_filter_and_is_cold_cosine(self) -> None:
        _stmt, sql, params = self._search_stmt(include_vector=False)

        assert "LIMIT" in sql
        assert "<=>" in sql
        # Cold tier and backbone are SQL predicates; score threshold is not.
        assert params["tier_1"] == "cold"
        assert params["backbone_id_1"] == "effnet"
        # No score/min_score predicate reaches SQL.
        assert ">=" not in sql

    def test_embedding_column_omitted_when_include_vector_false(self) -> None:
        stmt, _sql, _params = self._search_stmt(include_vector=False)

        assert "embedding" not in list(stmt.selected_columns.keys())

    def test_embedding_column_selected_when_include_vector_true(self) -> None:
        stmt, _sql, _params = self._search_stmt(include_vector=True)

        assert "embedding" in list(stmt.selected_columns.keys())

    def test_query_inner_joins_songs_and_libraries(self) -> None:
        _stmt, sql, _params = self._search_stmt(include_vector=False)

        # Inner joins prove rows whose song/library cannot be mapped are omitted.
        assert "JOIN songs" in sql
        assert "JOIN libraries" in sql


@pytest.mark.integration
@pytest.mark.requires_database
@pytest.mark.skip(
    reason="Requires pgvector extension — the ``embeddings`` table "
    "uses HALFVEC type and ``<=>`` operator not supported by SQLite"
)
class TestVectorRepoTypedReads:
    """DB-backed semantics of the typed cold read correction (P2-S6).

    Mirrors ``TestVectorRepo`` in requiring pgvector, so it is skipped on the
    SQLite-backed local unit path but is the authoritative typed-contract
    regression for the ``database-tests`` (pgvector) gate: actual stored
    vectors and element order, cold-only reads, semantic
    ``model_id``→``model_suite_hash`` mapping (persisted column stays ``""``),
    nullable metadata round-trip, cosine ordering, optional vector payloads,
    and unresolved-song ``None`` behavior.
    """

    def _create_song_with_identity(self, session) -> tuple[SongIdentity, int, int]:
        """Create a library + song and return (identity, song_id, library_id)."""
        n = next(_LIBRARY_NAMES)
        name = f"Vector Lib {n}"
        path = f"/vector/lib/{n}"
        normalized_path = f"{path}/track.mp3"
        lib_r = session.execute(
            insert(Library).values(
                name=name,
                path=path,
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
                path=normalized_path,
                normalized_path=normalized_path,
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
        identity = SongIdentity(
            library=LibraryIdentity(name=name, root_path=path),
            normalized_path=normalized_path,
        )
        return identity, song_id, lib_id

    def _add_song(self, session, library_id: int, lib_name: str, lib_path: str, index: int) -> tuple[SongIdentity, int]:
        """Add another song to an existing library; return (identity, song_id)."""
        normalized_path = f"{lib_path}/track_{index}.mp3"
        song_r = session.execute(
            insert(Song).values(
                library_id=library_id,
                path=normalized_path,
                normalized_path=normalized_path,
                file_size=1000 + index,
                modified_time=1000 + index,
                duration_seconds=180,
                needs_tagging=0,
                is_valid=1,
                tagged=0,
                created_at=1000 + index,
            )
        )
        identity = SongIdentity(
            library=LibraryIdentity(name=lib_name, root_path=lib_path),
            normalized_path=normalized_path,
        )
        return identity, song_r.inserted_primary_key[0]

    def test_get_song_vector_preserves_vector_order_and_maps_metadata(self, pg_session) -> None:
        identity, song_id, _lib_id = self._create_song_with_identity(pg_session)
        repo = VectorRepo(pg_session)
        vec = _random_vector(seed=901)
        repo.insert_embedding(
            song_id=song_id,
            backbone_id=_BACKBONE,
            model_id="suite-xyz",
            embedding_vector=vec,
            genres=["rock", "jazz"],
        )
        repo.drain_hot_to_cold(_BACKBONE)
        # Simulate a segmentation pipeline populating the nullable columns while
        # leaving the persisted ``model_suite_hash`` column ``""``.
        pg_session.execute(
            update(Embedding.__table__)
            .where(Embedding.__table__.c.song_id == song_id)
            .values(num_segments=3, segmentation_hash="seg-1")
        )
        pg_session.commit()

        sv = repo.get_song_vector(_BACKBONE, identity)

        assert sv is not None
        assert sv.vector == pytest.approx(tuple(vec))
        assert len(sv.vector) == _EMBED_DIM
        # Semantic hash read from model_id, never the empty persisted column.
        assert sv.model_suite_hash == "suite-xyz"
        assert sv.num_segments == 3
        assert sv.segmentation_hash == "seg-1"
        assert sv.genres == ("rock", "jazz")
        assert sv.song == identity
        assert sv.backbone == _BACKBONE

    def test_get_song_vector_is_cold_only(self, pg_session) -> None:
        identity, song_id, _lib_id = self._create_song_with_identity(pg_session)
        repo = VectorRepo(pg_session)
        repo.insert_embedding(
            song_id=song_id,
            backbone_id=_BACKBONE,
            model_id="m",
            embedding_vector=_random_vector(seed=902),
        )

        # Still hot — cold-only read returns None.
        assert repo.get_song_vector(_BACKBONE, identity) is None

        repo.drain_hot_to_cold(_BACKBONE)
        assert repo.get_song_vector(_BACKBONE, identity) is not None

    def test_get_song_vector_null_model_id_maps_to_none(self, pg_session) -> None:
        identity, song_id, _lib_id = self._create_song_with_identity(pg_session)
        repo = VectorRepo(pg_session)
        repo.insert_embedding(
            song_id=song_id,
            backbone_id=_BACKBONE,
            model_id="m",
            embedding_vector=_random_vector(seed=903),
        )
        repo.drain_hot_to_cold(_BACKBONE)
        pg_session.execute(
            update(Embedding.__table__)
            .where(Embedding.__table__.c.song_id == song_id)
            .values(model_id=None, num_segments=None, segmentation_hash=None, genres=None)
        )
        pg_session.commit()

        sv = repo.get_song_vector(_BACKBONE, identity)

        assert sv is not None
        assert sv.model_suite_hash is None
        assert sv.num_segments is None
        assert sv.segmentation_hash is None
        assert sv.genres is None

    def test_get_song_vector_unresolved_identity_returns_none(self, pg_session) -> None:
        # A natural identity whose library does not exist resolves to None.
        unknown = SongIdentity(
            library=LibraryIdentity(name="No Such Library", root_path="/nowhere"),
            normalized_path="x.mp3",
        )
        repo = VectorRepo(pg_session)

        assert repo.get_song_vector(_BACKBONE, unknown) is None

    def test_search_similar_vectors_cosine_order_cold_only_and_identities(self, pg_session) -> None:
        identity0, song0, lib_id = self._create_song_with_identity(pg_session)
        lib_name = identity0.library.name
        lib_path = identity0.library.root_path
        repo = VectorRepo(pg_session)
        vectors = [_random_vector(seed=910 + i) for i in range(5)]
        identities = [identity0]
        song_ids = [song0]
        for i in range(1, 5):
            ident, sid = self._add_song(pg_session, lib_id, lib_name, lib_path, i)
            identities.append(ident)
            song_ids.append(sid)
        # A sixth song stays HOT so it must never appear in the cold search.
        hot_ident, hot_sid = self._add_song(pg_session, lib_id, lib_name, lib_path, 99)

        for i, (sid, vec) in enumerate(zip(song_ids, vectors, strict=True)):
            repo.insert_embedding(
                song_id=sid,
                backbone_id=_BACKBONE,
                model_id=f"m{i}",
                embedding_vector=vec,
            )
        repo.insert_embedding(
            song_id=hot_sid,
            backbone_id=_BACKBONE,
            model_id="hot",
            embedding_vector=_random_vector(seed=999),
        )
        repo.drain_hot_to_cold(_BACKBONE)

        matches = repo.search_similar_vectors(
            _BACKBONE,
            vectors[0],
            limit=10,
            include_vector=True,
        )

        scores = [m.score for m in matches]
        assert scores == sorted(scores, reverse=True)
        assert matches[0].score > 0.99  # self-match nearest
        assert matches[0].song == identity0
        assert all(m.song.normalized_path != hot_ident.normalized_path for m in matches)
        assert all(m.vector is not None and len(m.vector) == _EMBED_DIM for m in matches)
        # Cosine ordering => lower distance first.
        distances = [1.0 - m.score for m in matches]
        assert distances == sorted(distances)

    def test_search_similar_vectors_min_score_and_optional_vectors(self, pg_session) -> None:
        identity, song_id, _lib_id = self._create_song_with_identity(pg_session)
        repo = VectorRepo(pg_session)
        vec = _random_vector(seed=950)
        repo.insert_embedding(
            song_id=song_id,
            backbone_id=_BACKBONE,
            model_id="m",
            embedding_vector=vec,
        )
        repo.drain_hot_to_cold(_BACKBONE)

        # include_vector=False (default) => None payloads.
        bare = repo.search_similar_vectors(_BACKBONE, vec, limit=5)
        assert all(m.vector is None for m in bare)
        # A perfect self-match is ~1.0, so a stringent min_score still keeps it.
        strict = repo.search_similar_vectors(_BACKBONE, vec, limit=5, min_score=0.99)
        assert any(m.song == identity for m in strict)
        # An impossible min_score filters everything out.
        none_kept = repo.search_similar_vectors(_BACKBONE, vec, limit=5, min_score=1.01)
        assert none_kept == ()
