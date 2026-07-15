"""Integration tests — cascade delete and drain operations.

Verifies cross-repository invariants that unit tests cannot cover:

* FK ``ON DELETE CASCADE`` from ``libraries`` cascades through
  ``library_files`` (and transitively to ``embeddings``, ``file_tags``,
  ``ml_output_streams``).
* ``VectorRepo.delete_embeddings_for_file`` removes only the target
  file's embeddings.
* ``VectorRepo.drain_hot_to_cold`` moves every hot-tier row to cold
  without data loss.
* ``VectorRepo.delete_all_embeddings`` clears the entire table.
"""

from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy import insert, text

from nomarr.persistence.database.file_repo import FileRepository
from nomarr.persistence.database.library_repo import LibraryRepository
from nomarr.persistence.database.vector_repo import VectorRepo
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.library_file import LibraryFile

# Embedding dimension must match HALFVEC(1280) in the Embedding model.
_EMBED_DIM = 1280
_BACKBONE = "cascade_drain_bb"


# ── helpers ─────────────────────────────────────────────────────


async def _create_library_and_file(session, *, lib_name: str = "CD Lib", idx: int = 0):
    """Insert a library + one file.  Return ``(library_id, file_id)``."""
    lib_r = await session.execute(
        insert(Library).values(
            name=lib_name,
            path=f"/cd/lib{idx}",
            library_type="music",
            auto_tag=0,
            auto_curate=0,
            created_at=1000,
            updated_at=1000,
        )
    )
    lib_id = lib_r.inserted_primary_key[0]
    file_r = await session.execute(
        insert(LibraryFile).values(
            library_id=lib_id,
            path=f"/cd/lib{idx}/track{idx}.mp3",
            normalized_path=f"/cd/lib{idx}/track{idx}.mp3",
            file_size=1000 + idx,
            modified_time=1000 + idx,
            duration_seconds=180.0,
            needs_tagging=0,
            is_valid=1,
            tagged=0,
            created_at=1000 + idx,
        )
    )
    file_id = file_r.inserted_primary_key[0]
    return lib_id, file_id


def _random_vector(dim: int = _EMBED_DIM, seed: int | None = None) -> list[float]:
    """Generate a deterministic random L2-normalized vector."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    v /= np.linalg.norm(v)
    return v.tolist()  # type: ignore[no-any-return]


# ── tests ───────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.requires_database
class TestCascadeAndDrain:
    """Cross-repository cascade-delete and drain integration tests."""

    # ── P3-S1: cascade delete ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_delete_library_cascades_to_files(self, pg_session) -> None:
        """Deleting a library must cascade-delete its library_files rows."""
        lib_id, _file_id = await _create_library_and_file(pg_session)

        lib_repo = LibraryRepository(pg_session)
        file_repo = FileRepository(pg_session)

        # Sanity: library and file exist before delete.
        assert await lib_repo.get_library(lib_id) is not None
        assert await file_repo.count_library_files(lib_id) == 1

        # Delete the library — FK ON DELETE CASCADE removes files.
        await lib_repo.remove_library(lib_id)

        # Library gone.
        assert await lib_repo.get_library(lib_id) is None
        # Files gone (cascade).
        assert await file_repo.count_library_files(lib_id) == 0

    # ── P3-S2: drain + delete verification ──────────────────────

    @pytest.mark.asyncio
    async def test_delete_embeddings_for_file(self, pg_session) -> None:
        """delete_embeddings_for_file removes only the target file's rows."""
        _, file_id_a = await _create_library_and_file(pg_session, lib_name="Def Lib A", idx=10)
        # Second library + file (independent data).
        _, file_id_b = await _create_library_and_file(pg_session, lib_name="Def Lib B", idx=11)

        vec_repo = VectorRepo(pg_session)

        # Two embeddings per file.
        for seed_offset, fid in enumerate((file_id_a, file_id_b)):
            for j in range(2):
                await vec_repo.insert_embedding(
                    file_id=fid,
                    backbone_id=_BACKBONE,
                    model_id="model_x",
                    embedding_vector=_random_vector(seed=700 + seed_offset * 10 + j),
                )

        # Sanity: 2 embeddings for each file.
        assert len(await vec_repo.get_embeddings_for_file(file_id_a)) == 2
        assert len(await vec_repo.get_embeddings_for_file(file_id_b)) == 2

        # Delete only file A's embeddings.
        await vec_repo.delete_embeddings_for_file(file_id_a)

        assert len(await vec_repo.get_embeddings_for_file(file_id_a)) == 0
        # File B untouched.
        assert len(await vec_repo.get_embeddings_for_file(file_id_b)) == 2

    @pytest.mark.asyncio
    async def test_drain_hot_to_cold_no_data_loss(self, pg_session) -> None:
        """drain_hot_to_cold moves all hot rows to cold; counts match."""
        _, file_id = await _create_library_and_file(pg_session, lib_name="Drain Lib", idx=20)

        vec_repo = VectorRepo(pg_session)
        num_embeddings = 50

        for i in range(num_embeddings):
            await vec_repo.insert_embedding(
                file_id=file_id,
                backbone_id=_BACKBONE,
                model_id="model_drain",
                embedding_vector=_random_vector(seed=800 + i),
            )

        # All hot before drain.
        stats_before = await vec_repo.get_embedding_stats(_BACKBONE)
        assert stats_before["hot_count"] == num_embeddings
        assert stats_before["cold_count"] == 0

        # Drain.
        drained = await vec_repo.drain_hot_to_cold(_BACKBONE)
        assert drained == num_embeddings

        # All cold after drain — zero data loss.
        stats_after = await vec_repo.get_embedding_stats(_BACKBONE)
        assert stats_after["hot_count"] == 0
        assert stats_after["cold_count"] == num_embeddings
        assert await vec_repo.count_cold_embeddings(_BACKBONE) == num_embeddings

    @pytest.mark.asyncio
    async def test_delete_all_embeddings_clears_table(self, pg_session) -> None:
        """delete_all_embeddings removes every row from the embeddings table."""
        _, file_id_a = await _create_library_and_file(pg_session, lib_name="Clr Lib A", idx=30)
        _, file_id_b = await _create_library_and_file(pg_session, lib_name="Clr Lib B", idx=31)

        vec_repo = VectorRepo(pg_session)

        # Embeddings across two files and two backbones.
        for fid in (file_id_a, file_id_b):
            for bb in ("bb_clear_1", "bb_clear_2"):
                await vec_repo.insert_embedding(
                    file_id=fid,
                    backbone_id=bb,
                    model_id="model_clr",
                    embedding_vector=_random_vector(seed=900 + fid),
                )

        # Sanity: 4 total embeddings.
        row = await pg_session.execute(text("SELECT COUNT(*) FROM embeddings"))
        assert row.scalar() == 4

        await vec_repo.delete_all_embeddings()

        row = await pg_session.execute(text("SELECT COUNT(*) FROM embeddings"))
        assert row.scalar() == 0
