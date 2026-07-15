"""Integration tests — HNSW recall benchmark and concurrent access.

Verifies:

* HNSW index returns nearest neighbours in correct cosine-distance order
  with reasonable distance values.
* Concurrent inserts via ``asyncio.gather`` all persist without loss.
* Concurrent ``find_nearest`` queries produce no crashes or corruption.
* ``find_nearest`` on an empty table returns ``[]`` gracefully.

Covers plan steps P4-S1 (HNSW recall) and P4-S2 (concurrency).
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from nomarr.persistence.database.vector_repo import VectorRepo
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.library_file import LibraryFile

# Embedding dimension must match HALFVEC(1280) in the Embedding model.
_EMBED_DIM = 1280
_BACKBONE = "hnsw_recall_bb"


# ── helpers ─────────────────────────────────────────────────────


async def _create_library_and_file(
    session: AsyncSession, *, lib_name: str = "HNSW Lib", idx: int = 0
) -> tuple[int, int]:
    """Insert a library + one file.  Return ``(library_id, file_id)``."""
    lib_r = await session.execute(
        insert(Library).values(
            name=lib_name,
            path=f"/hnsw/lib{idx}",
            library_type="music",
            auto_tag=0,
            auto_curate=0,
            created_at=1000,
            updated_at=1000,
        )
    )
    lib_id = lib_r.inserted_primary_key[0]  # type: ignore[attr-defined]
    file_r = await session.execute(
        insert(LibraryFile).values(
            library_id=lib_id,
            path=f"/hnsw/lib{idx}/track{idx}.mp3",
            normalized_path=f"/hnsw/lib{idx}/track{idx}.mp3",
            file_size=1000 + idx,
            modified_time=1000 + idx,
            duration_seconds=180.0,
            needs_tagging=0,
            is_valid=1,
            tagged=0,
            created_at=1000 + idx,
        )
    )
    file_id = file_r.inserted_primary_key[0]  # type: ignore[attr-defined]
    return lib_id, file_id


def _random_vector(dim: int = _EMBED_DIM, seed: int | None = None) -> list[float]:
    """Generate a deterministic random L2-normalized vector."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    v /= np.linalg.norm(v)
    return v.tolist()  # type: ignore[no-any-return]


# ── P4-S1: HNSW recall benchmark ──────────────────────────────


@pytest.mark.integration
@pytest.mark.requires_database
class TestHnswRecall:
    """HNSW index recall and distance-ordering tests."""

    @pytest.mark.asyncio
    @pytest.mark.hnsw_build
    async def test_find_nearest_returns_correct_order(self, pg_session) -> None:
        """find_nearest must return cold embeddings in ascending cosine distance.

        Inserts 20 embeddings, drains to cold, then queries with one of the
        inserted vectors.  The self-match must be the nearest result (distance
        ≈ 0), and all returned distances must be monotonically non-decreasing.
        """
        lib_id, file_id = await _create_library_and_file(pg_session)
        repo = VectorRepo(pg_session)

        num_vectors = 20
        vectors = [_random_vector(seed=i) for i in range(num_vectors)]

        # Create additional files for each embedding (FK constraint)
        file_ids = [file_id]
        for i in range(1, num_vectors):
            file_r = await pg_session.execute(
                insert(LibraryFile).values(
                    library_id=lib_id,
                    path=f"/hnsw/lib0/track_{i}.mp3",
                    normalized_path=f"/hnsw/lib0/track_{i}.mp3",
                    file_size=1000 + i,
                    modified_time=1000 + i,
                    duration_seconds=180.0,
                    needs_tagging=0,
                    is_valid=1,
                    tagged=0,
                    created_at=1000 + i,
                )
            )
            file_ids.append(file_r.inserted_primary_key[0])

        for i, vec in enumerate(vectors):
            await repo.insert_embedding(
                file_id=file_ids[i],
                backbone_id=_BACKBONE,
                model_id="recall_model",
                embedding_vector=vec,
            )

        # find_nearest only searches cold-tier rows.
        await repo.drain_hot_to_cold(_BACKBONE)

        # Query with the first vector — it should be nearest to itself.
        query_vec = vectors[0]
        results = await repo.find_nearest(query_vec, _BACKBONE, limit=10)

        # Must return results (we inserted 20 cold rows).
        assert len(results) > 0
        assert len(results) <= 10

        # Distances must be in ascending order.
        distances = [r["distance"] for r in results]
        assert distances == sorted(distances), f"Distances not sorted: {distances}"

        # Self-match distance should be near-zero (cosine distance of identical
        # unit vectors is 0; halfvec quantisation may add tiny error).
        assert results[0]["distance"] < 0.01, f"Self-match distance too large: {results[0]['distance']}"

        # All distances must be non-negative (cosine distance ∈ [0, 2]).
        assert all(d >= 0.0 for d in distances), f"Negative distance found: {distances}"

        # All results should reference the correct backbone.
        assert all(r["backbone_id"] == _BACKBONE for r in results)

    @pytest.mark.asyncio
    @pytest.mark.hnsw_build
    async def test_hnsw_recall_benchmark(self, pg_session) -> None:
        """HNSW index should achieve recall@10 >= 0.90 against brute-force baseline.

        Inserts 1000 vectors, drains to cold (building the HNSW index), then
        queries with a test vector. Compares HNSW results against exhaustive
        brute-force search to compute recall@10.
        """
        lib_id, file_id = await _create_library_and_file(pg_session)
        repo = VectorRepo(pg_session)

        # Generate 1000 vectors of dimension 1280
        num_vectors = 1000
        rng = np.random.default_rng(seed=42)
        vectors = []
        for _ in range(num_vectors):
            v = rng.standard_normal(_EMBED_DIM).astype(np.float32)
            v /= np.linalg.norm(v)
            vectors.append(v.tolist())

        # Create additional files for each embedding (FK constraint)
        file_ids = [file_id]
        for i in range(1, num_vectors):
            file_r = await pg_session.execute(
                insert(LibraryFile).values(
                    library_id=lib_id,
                    path=f"/hnsw/lib0/recall_track_{i}.mp3",
                    normalized_path=f"/hnsw/lib0/recall_track_{i}.mp3",
                    file_size=1000 + i,
                    modified_time=1000 + i,
                    duration_seconds=180.0,
                    needs_tagging=0,
                    is_valid=1,
                    tagged=0,
                    created_at=1000 + i,
                )
            )
            file_ids.append(file_r.inserted_primary_key[0])

        # Insert all vectors as hot embeddings
        for i, vec in enumerate(vectors):
            await repo.insert_embedding(
                file_id=file_ids[i],
                backbone_id=_BACKBONE,
                model_id="recall_benchmark_model",
                embedding_vector=vec,
            )

        # Drain to cold (triggers HNSW index build on next VACUUM)
        await repo.drain_hot_to_cold(_BACKBONE)

        # Query with a test vector
        test_vec = vectors[0]
        hnsw_results = await repo.find_nearest(test_vec, _BACKBONE, limit=10)

        # Compute brute-force top-10 (exhaustive search)
        test_vec_np = np.array(test_vec, dtype=np.float32)
        distances = []
        for i, vec in enumerate(vectors):
            vec_np = np.array(vec, dtype=np.float32)
            # Cosine distance = 1 - cosine_similarity
            cosine_sim = np.dot(test_vec_np, vec_np) / (np.linalg.norm(test_vec_np) * np.linalg.norm(vec_np))
            cosine_dist = 1.0 - cosine_sim
            distances.append((i, cosine_dist))

        # Sort by distance and take top 10
        distances.sort(key=lambda x: x[1])
        brute_force_top10 = {idx for idx, _ in distances[:10]}

        # Extract file_ids from HNSW results
        hnsw_file_ids = {r["file_id"] for r in hnsw_results}

        # Map file_ids back to vector indices
        file_id_to_idx = {fid: i for i, fid in enumerate(file_ids)}
        hnsw_indices = {file_id_to_idx[fid] for fid in hnsw_file_ids if fid in file_id_to_idx}

        # Compute recall@10
        true_positives = len(brute_force_top10 & hnsw_indices)
        recall_at_10 = true_positives / len(brute_force_top10)

        # Assert recall >= 0.90
        assert recall_at_10 >= 0.90, (
            f"HNSW recall@10 = {recall_at_10:.2f}, expected >= 0.90. True positives: {true_positives}/10"
        )

    @pytest.mark.asyncio
    async def test_find_nearest_empty_table(self, pg_session) -> None:
        """find_nearest on an empty table must return [] without errors."""
        repo = VectorRepo(pg_session)
        query_vec = _random_vector(seed=999)
        results = await repo.find_nearest(query_vec, _BACKBONE, limit=10)
        assert results == []


# ── P4-S2: concurrent access ─────────────────────────────────


@pytest.mark.integration
@pytest.mark.requires_database
class TestConcurrentAccess:
    """Concurrent insert and query stress tests.

    These tests use ``pg_async_engine`` to create independent sessions per
    coroutine — the ``pg_session`` fixture's transactional wrapper does not
    support concurrent use from multiple coroutines on a single connection.
    """

    @pytest.mark.asyncio
    async def test_concurrent_inserts(self, pg_async_engine: AsyncEngine) -> None:
        """Multiple coroutines inserting embeddings concurrently must all persist.

        Pre-creates N files in a single session, then uses ``asyncio.gather``
        to insert one embedding per file from N independent sessions.  After
        all inserts complete, verifies every row is present.
        """
        num_concurrent = 10

        # Pre-create library + files in a single session.
        async with pg_async_engine.begin() as conn:
            session = AsyncSession(bind=conn)
            lib_r = await session.execute(
                insert(Library).values(
                    name="Concurrent Insert Lib",
                    path="/hnsw/conc_insert",
                    library_type="music",
                    auto_tag=0,
                    auto_curate=0,
                    created_at=1000,
                    updated_at=1000,
                )
            )
            lib_id = lib_r.inserted_primary_key[0]  # type: ignore[attr-defined]

            file_ids: list[int] = []
            for i in range(num_concurrent):
                file_r = await session.execute(
                    insert(LibraryFile).values(
                        library_id=lib_id,
                        path=f"/hnsw/conc_insert/track{i}.mp3",
                        normalized_path=f"/hnsw/conc_insert/track{i}.mp3",
                        file_size=1000 + i,
                        modified_time=1000 + i,
                        duration_seconds=180.0,
                        needs_tagging=0,
                        is_valid=1,
                        tagged=0,
                        created_at=1000 + i,
                    )
                )
                file_ids.append(file_r.inserted_primary_key[0])  # type: ignore[attr-defined]
            await session.commit()

        # Concurrent inserts — each coroutine gets its own session.
        async def _insert_one(fid: int, seed: int) -> None:
            async with pg_async_engine.begin() as conn:
                s = AsyncSession(bind=conn)
                repo = VectorRepo(s)
                await repo.insert_embedding(
                    file_id=fid,
                    backbone_id=_BACKBONE,
                    model_id="concurrent_model",
                    embedding_vector=_random_vector(seed=seed),
                )

        await asyncio.gather(*[_insert_one(fid, seed=1000 + i) for i, fid in enumerate(file_ids)])

        # Verify all inserts persisted.
        async with pg_async_engine.connect() as conn:
            verify_session = AsyncSession(bind=conn)
            verify_repo = VectorRepo(verify_session)
            stats = await verify_repo.get_embedding_stats(_BACKBONE)
            assert stats["hot_count"] == num_concurrent, (
                f"Expected {num_concurrent} hot embeddings, got {stats['hot_count']}"
            )

    @pytest.mark.asyncio
    async def test_concurrent_queries(self, pg_async_engine: AsyncEngine) -> None:
        """Multiple concurrent find_nearest queries must not crash or corrupt.

        Inserts and drains embeddings in a setup phase, then fires
        ``asyncio.gather`` with N concurrent ``find_nearest`` calls, each
        in its own session.  All must return valid, distance-ordered results.
        """
        num_queries = 10

        # Setup: insert embeddings and drain to cold.
        async with pg_async_engine.begin() as conn:
            session = AsyncSession(bind=conn)
            lib_r = await session.execute(
                insert(Library).values(
                    name="Concurrent Query Lib",
                    path="/hnsw/conc_query",
                    library_type="music",
                    auto_tag=0,
                    auto_curate=0,
                    created_at=1000,
                    updated_at=1000,
                )
            )
            lib_id = lib_r.inserted_primary_key[0]  # type: ignore[attr-defined]
            file_r = await session.execute(
                insert(LibraryFile).values(
                    library_id=lib_id,
                    path="/hnsw/conc_query/track0.mp3",
                    normalized_path="/hnsw/conc_query/track0.mp3",
                    file_size=1000,
                    modified_time=1000,
                    duration_seconds=180.0,
                    needs_tagging=0,
                    is_valid=1,
                    tagged=0,
                    created_at=1000,
                )
            )
            file_id = file_r.inserted_primary_key[0]  # type: ignore[attr-defined]

            repo = VectorRepo(session)
            for i in range(15):
                await repo.insert_embedding(
                    file_id=file_id,
                    backbone_id=_BACKBONE,
                    model_id="conc_query_model",
                    embedding_vector=_random_vector(seed=2000 + i),
                )
            await repo.drain_hot_to_cold(_BACKBONE)

        query_vec = _random_vector(seed=2000)

        # Concurrent queries — each coroutine gets its own session.
        async def _query_one() -> list:
            async with pg_async_engine.connect() as conn:
                s = AsyncSession(bind=conn)
                r = VectorRepo(s)
                return await r.find_nearest(query_vec, _BACKBONE, limit=5)

        results_list = await asyncio.gather(*[_query_one() for _ in range(num_queries)])

        # Every query must return valid, distance-ordered results.
        for results in results_list:
            assert len(results) > 0, "Concurrent query returned no results"
            assert len(results) <= 5
            distances = [r["distance"] for r in results]
            assert distances == sorted(distances), f"Distances not sorted under concurrency: {distances}"
            assert all(d >= 0.0 for d in distances)
