"""Integration tests — cascade delete and drain operations.

Verifies cross-repository invariants that unit tests cannot cover:

* FK ``ON DELETE CASCADE`` from ``libraries`` cascades through
  ``songs`` (and transitively to ``embeddings``, ``song_tags``,
  ``ml_output_streams``).
* Deleting a single song's embeddings (``DELETE FROM embeddings
  WHERE song_id = :song_id``) removes only that song's rows.
* Moving hot-tier rows to cold tier (``UPDATE embeddings SET tier =
  'cold'``) does not lose data.
* Deleting every ``embeddings`` row (``DELETE FROM embeddings``)
  clears the entire table.

Plan A note: this file is a fresh-establishment gate and is kept
self-contained — data setup and assertions use the renamed ORM models
(``Library``/``Song``) and raw SQL against the corrected schema
(``songs``/``embeddings`` with ``song_id``). Repository classes under
``nomarr/persistence/database/`` are transiently broken by the hard cut
(Plan B fixes them) and are intentionally not imported.
"""

from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy import insert, text

from nomarr.persistence.models.library import Library
from nomarr.persistence.models.song import Song

# Embedding dimension must match HALFVEC(1280) in the Embedding model.
_EMBED_DIM = 1280
_BACKBONE = "cascade_drain_bb"


# ── helpers ─────────────────────────────────────────────────────


def _create_library_and_file(session, *, lib_name: str = "CD Lib", idx: int = 0):
    """Insert a library + one song.  Return ``(library_id, song_id)``.

    The helper keeps its historical name but inserts a ``songs`` row
    (the file-domain model no longer exists).
    """
    lib_r = session.execute(
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
    song_r = session.execute(
        insert(Song).values(
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
    song_id = song_r.inserted_primary_key[0]
    return lib_id, song_id


def _random_vector(dim: int = _EMBED_DIM, seed: int | None = None) -> list[float]:
    """Generate a deterministic random L2-normalized vector."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    v /= np.linalg.norm(v)
    return v.tolist()  # type: ignore[no-any-return]


def _insert_embedding(
    session,
    song_id: int,
    *,
    backbone_id: str = _BACKBONE,
    model_id: str = "model_x",
    seed: int = 0,
) -> None:
    """Insert an embedding row via raw SQL against the ``embeddings`` table."""
    vec = _random_vector(seed=seed)
    # Render the halfvec literal as PG expects it: '[0.1,0.2,...]'
    vec_literal = "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
    session.execute(
        text(
            "INSERT INTO embeddings (song_id, backbone_id, model_id, embed_dim, model_suite_hash, "
            "embedding, tier, created_at, updated_at) "
            "VALUES (:song_id, :backbone_id, :model_id, :embed_dim, :model_suite_hash, "
            ":embedding::halfvec, 'hot', :created_at, :updated_at)"
        ),
        {
            "song_id": song_id,
            "backbone_id": backbone_id,
            "model_id": model_id,
            "embed_dim": _EMBED_DIM,
            "model_suite_hash": "test_suite_hash",
            "embedding": vec_literal,
            "created_at": 1000,
            "updated_at": 1000,
        },
    )


def _count_embeddings_for_song(session, song_id: int) -> int:
    """Return the number of ``embeddings`` rows for a song."""
    result = session.execute(text("SELECT COUNT(*) FROM embeddings WHERE song_id = :song_id"), {"song_id": song_id})
    return int(result.scalar())


def _count_embeddings(session, *, backbone_id: str | None = None, tier: str | None = None) -> int:
    """Count ``embeddings`` rows, optionally filtered by backbone and/or tier."""
    if backbone_id is not None and tier is not None:
        result = session.execute(
            text("SELECT COUNT(*) FROM embeddings WHERE backbone_id = :bb AND tier = :tier"),
            {"bb": backbone_id, "tier": tier},
        )
    elif backbone_id is not None:
        result = session.execute(
            text("SELECT COUNT(*) FROM embeddings WHERE backbone_id = :bb"),
            {"bb": backbone_id},
        )
    elif tier is not None:
        result = session.execute(
            text("SELECT COUNT(*) FROM embeddings WHERE tier = :tier"),
            {"tier": tier},
        )
    else:
        result = session.execute(text("SELECT COUNT(*) FROM embeddings"))
    return int(result.scalar())


# ── tests ───────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.requires_database
class TestCascadeAndDrain:
    """Cross-repository cascade-delete and drain integration tests."""

    # ── P3-S1: cascade delete ───────────────────────────────────

    def test_delete_library_cascades_to_files(self, pg_session) -> None:
        """Deleting a library must cascade through songs to dependent rows.

        The FK chain is: libraries → songs → {embeddings, song_tags,
        ml_output_streams} (all ON DELETE CASCADE).
        """
        lib_id, song_id = _create_library_and_file(pg_session)

        # Seed dependent rows so the cascade chain is observable.
        _insert_embedding(pg_session, song_id=song_id, seed=1)
        tag_id = pg_session.execute(
            text(
                "INSERT INTO tags (name, value, namespace, source, created_at) "
                "VALUES ('genre', 'test', 'test', 'test', 1000) RETURNING id"
            )
        ).scalar()
        pg_session.execute(
            text(
                "INSERT INTO song_tags (song_id, tag_id, source, created_at) VALUES (:song_id, :tag_id, 'test', 1000)"
            ),
            {"song_id": song_id, "tag_id": tag_id},
        )
        pg_session.execute(
            text(
                "INSERT INTO ml_models (id, model_type, backbone_id, created_at, updated_at) "
                "VALUES ('test_model', 'test', :backbone_id, 1000, 1000)"
            ),
            {"backbone_id": _BACKBONE},
        )
        pg_session.execute(
            text(
                "INSERT INTO ml_output_streams (song_id, model_id, status, created_at) "
                "VALUES (:song_id, 'test_model', 'done', 1000)"
            ),
            {"song_id": song_id},
        )

        # Sanity: library, song, and dependent rows exist before delete.
        assert pg_session.execute(text("SELECT COUNT(*) FROM libraries WHERE id = :id"), {"id": lib_id}).scalar() == 1
        assert pg_session.execute(text("SELECT COUNT(*) FROM songs WHERE id = :id"), {"id": song_id}).scalar() == 1
        assert _count_embeddings_for_song(pg_session, song_id) == 1
        assert (
            pg_session.execute(text("SELECT COUNT(*) FROM song_tags WHERE song_id = :id"), {"id": song_id}).scalar()
            == 1
        )
        assert (
            pg_session.execute(
                text("SELECT COUNT(*) FROM ml_output_streams WHERE song_id = :id"), {"id": song_id}
            ).scalar()
            == 1
        )

        # Delete the library — FK ON DELETE CASCADE removes songs and all dependents.
        pg_session.execute(text("DELETE FROM libraries WHERE id = :id"), {"id": lib_id})

        # Library gone.
        assert pg_session.execute(text("SELECT COUNT(*) FROM libraries WHERE id = :id"), {"id": lib_id}).scalar() == 0
        # Songs gone (cascade).
        assert pg_session.execute(text("SELECT COUNT(*) FROM songs WHERE id = :id"), {"id": song_id}).scalar() == 0
        # Embeddings gone (cascade through songs).
        assert _count_embeddings_for_song(pg_session, song_id) == 0
        # Song tags gone (cascade through songs).
        assert (
            pg_session.execute(text("SELECT COUNT(*) FROM song_tags WHERE song_id = :id"), {"id": song_id}).scalar()
            == 0
        )
        # ML output streams gone (cascade through songs).
        assert (
            pg_session.execute(
                text("SELECT COUNT(*) FROM ml_output_streams WHERE song_id = :id"), {"id": song_id}
            ).scalar()
            == 0
        )

    # ── P3-S2: drain + delete verification ──────────────────────

    def test_delete_embeddings_for_file(self, pg_session) -> None:
        """Deleting a song's embeddings removes only that song's rows."""
        _, song_id_a = _create_library_and_file(pg_session, lib_name="Def Lib A", idx=10)
        # Second library + song (independent data).
        _, song_id_b = _create_library_and_file(pg_session, lib_name="Def Lib B", idx=11)

        # Two embeddings per song — distinct backbone per row so each
        # (song_id, backbone_id) pair is unique (uq_embeddings_song_backbone).
        for seed_offset, song_id in enumerate((song_id_a, song_id_b)):
            for j in range(2):
                _insert_embedding(
                    pg_session,
                    song_id=song_id,
                    backbone_id=f"bb_def_{j}",
                    model_id="model_x",
                    seed=700 + seed_offset * 10 + j,
                )

        # Sanity: 2 embeddings for each song.
        assert _count_embeddings_for_song(pg_session, song_id_a) == 2
        assert _count_embeddings_for_song(pg_session, song_id_b) == 2

        # Delete only song A's embeddings.
        pg_session.execute(text("DELETE FROM embeddings WHERE song_id = :song_id"), {"song_id": song_id_a})

        assert _count_embeddings_for_song(pg_session, song_id_a) == 0
        # Song B untouched.
        assert _count_embeddings_for_song(pg_session, song_id_b) == 2

    def test_drain_hot_to_cold_no_data_loss(self, pg_session) -> None:
        """Moving hot-tier rows to cold tier; counts match, zero data loss."""
        _, song_id = _create_library_and_file(pg_session, lib_name="Drain Lib", idx=20)

        num_embeddings = 50
        for i in range(num_embeddings):
            _insert_embedding(
                pg_session,
                song_id=song_id,
                backbone_id=f"bb_drain_{i}",
                model_id="model_drain",
                seed=800 + i,
            )

        # All hot before drain (rows span distinct backbones, so count by tier).
        assert _count_embeddings(session=pg_session, tier="hot") == num_embeddings
        assert _count_embeddings(session=pg_session, tier="cold") == 0

        # Drain: hot → cold for every row (each row has its own backbone id).
        pg_session.execute(
            text("UPDATE embeddings SET tier = 'cold', updated_at = :now WHERE tier = 'hot'"),
            {"now": 1000},
        )

        # All cold after drain — zero data loss.
        assert _count_embeddings(session=pg_session, tier="hot") == 0
        assert _count_embeddings(session=pg_session, tier="cold") == num_embeddings
        assert _count_embeddings(session=pg_session) == num_embeddings

    def test_delete_all_embeddings_clears_table(self, pg_session) -> None:
        """Deleting every ``embeddings`` row clears the table."""
        _, song_id_a = _create_library_and_file(pg_session, lib_name="Clr Lib A", idx=30)
        _, song_id_b = _create_library_and_file(pg_session, lib_name="Clr Lib B", idx=31)

        # Embeddings across two songs and two backbones.
        for song_id in (song_id_a, song_id_b):
            for bb in ("bb_clear_1", "bb_clear_2"):
                _insert_embedding(
                    pg_session,
                    song_id=song_id,
                    backbone_id=bb,
                    model_id="model_clr",
                    seed=900 + song_id,
                )

        # Sanity: 4 total embeddings.
        assert _count_embeddings(session=pg_session) == 4

        pg_session.execute(text("DELETE FROM embeddings"))

        assert _count_embeddings(session=pg_session) == 0
