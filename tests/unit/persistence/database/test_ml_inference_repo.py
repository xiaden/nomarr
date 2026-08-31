"""Repository-level tests for ``MlInferenceRepo.replace_song_inference_results``.

Proves the canonical aggregate contract: backbone-scoped vector replacement,
song-scoped output-stream replacement, and atomic rollback (no partial state)
when an insert fails.  These are PostgreSQL-only checks — the aggregate writes
the ``embeddings`` table whose ``HALFVEC`` column type is not supported by the
SQLite test fixture, matching the existing ``test_vector_repo`` convention.
"""

from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy import insert

from nomarr.helpers.exceptions import DuplicateEntityError
from nomarr.persistence.database.ml_inference_repo import MlInferenceRepo
from nomarr.persistence.database.output_repo import OutputRepo
from nomarr.persistence.database.vector_repo import VectorRepo
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.song import Song

# Embedding dimension must match HALFVEC(1280) in the Embedding model.
_EMBED_DIM = 1280
_BACKBONE = "test_backbone"


def _create_library_and_song(session) -> tuple[int, int]:
    """Helper: create a library and a song, return (library_id, song_id)."""
    lib_r = session.execute(
        insert(Library).values(
            name="Inference Lib",
            path="/inference/lib",
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
            path="/inference/lib/test.mp3",
            normalized_path="/inference/lib/test.mp3",
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
    "uses HALFVEC type and the aggregate cannot run on SQLite"
)
class TestMlInferenceRepo:
    """Tests for MlInferenceRepo.replace_song_inference_results."""

    def test_replaces_backbone_scoped_vectors_and_song_streams(self, pg_session) -> None:
        """Replacement scopes vectors to (song, backbone) and streams to song."""
        _, song_id = _create_library_and_song(pg_session)
        vector_repo = VectorRepo(pg_session)
        output_repo = OutputRepo(pg_session)

        # Pre-existing vectors for two backbones of the same song.
        vector_repo.insert_embedding(
            song_id=song_id,
            backbone_id="backbone_a",
            model_id="old_model_a",
            embedding_vector=_random_vector(seed=1),
        )
        vector_repo.insert_embedding(
            song_id=song_id,
            backbone_id="backbone_b",
            model_id="old_model_b",
            embedding_vector=_random_vector(seed=2),
        )
        # Pre-existing streams for the song.
        output_repo.store_output_stream(song_id, output_id="old_stream", values=[9.9], output_index=0)

        repo = MlInferenceRepo(pg_session)
        repo.replace_song_inference_results(
            song_id,
            "backbone_a",
            vectors=[
                {
                    "embedding_vector": _random_vector(seed=3),
                    "model_id": "new_model_a",
                    "backbone_id": "backbone_a",
                },
            ],
            output_streams=[
                {"output_id": "new_stream", "values": [1.0, 2.0], "output_index": 0},
            ],
        )

        # backbone_a's vector was replaced; backbone_b's vector was preserved.
        embeddings = vector_repo.get_embeddings_for_song(song_id)
        by_backbone = {e["backbone_id"]: e for e in embeddings}
        assert set(by_backbone) == {"backbone_a", "backbone_b"}
        assert by_backbone["backbone_a"]["model_id"] == "new_model_a"
        assert by_backbone["backbone_b"]["model_id"] == "old_model_b"

        # Streams were replaced for the song.
        streams = output_repo.list_output_streams_for_song(song_id)
        assert [(s["output_id"], s["values"]) for s in streams] == [("new_stream", [1.0, 2.0])]

    def test_vector_metadata_fidelity_num_segments_and_suite_hash(self, pg_session) -> None:
        """_insert_vector persists num_segments and model_suite_hash from the payload."""
        _, song_id = _create_library_and_song(pg_session)
        vector_repo = VectorRepo(pg_session)

        repo = MlInferenceRepo(pg_session)
        repo.replace_song_inference_results(
            song_id,
            "bb_meta",
            vectors=[
                {
                    "embedding_vector": _random_vector(seed=20),
                    "model_id": "suite-hash-123",
                    "num_segments": 4,
                    "model_suite_hash": "suite-hash-123",
                },
            ],
            output_streams=[],
        )

        embeddings = vector_repo.get_embeddings_for_song(song_id)
        assert len(embeddings) == 1
        assert embeddings[0]["num_segments"] == 4
        assert embeddings[0]["model_suite_hash"] == "suite-hash-123"
        assert embeddings[0]["model_id"] == "suite-hash-123"

    def test_rolls_back_all_changes_on_insert_failure(self, pg_session) -> None:
        """A failed insert leaves vectors and streams untouched (no partial state)."""
        _, song_id = _create_library_and_song(pg_session)
        vector_repo = VectorRepo(pg_session)
        output_repo = OutputRepo(pg_session)

        # Pre-existing vector for (song, backbone) and streams for the song.
        vector_repo.insert_embedding(
            song_id=song_id,
            backbone_id=_BACKBONE,
            model_id="existing_model",
            embedding_vector=_random_vector(seed=11),
        )
        output_repo.store_output_stream(song_id, output_id="existing_stream", values=[7.7], output_index=0)

        repo = MlInferenceRepo(pg_session)
        with pytest.raises(DuplicateEntityError):
            repo.replace_song_inference_results(
                song_id,
                _BACKBONE,
                vectors=[
                    # Two vectors for the same (song, backbone) — the second
                    # insert violates uq_embeddings_song_backbone after the
                    # aggregate's deletes have run.
                    {"embedding_vector": _random_vector(seed=12), "model_id": "m1"},
                    {"embedding_vector": _random_vector(seed=13), "model_id": "m2"},
                ],
                output_streams=[
                    {"output_id": "new_stream", "values": [1.0], "output_index": 0},
                ],
            )

        # No partial state: the original vector and streams survive the rollback,
        # and the new stream was never inserted.
        embeddings = vector_repo.get_embeddings_for_song(song_id)
        assert len(embeddings) == 1
        assert embeddings[0]["backbone_id"] == _BACKBONE
        assert embeddings[0]["model_id"] == "existing_model"

        streams = output_repo.list_output_streams_for_song(song_id)
        assert [(s["output_id"], s["values"]) for s in streams] == [("existing_stream", [7.7])]
