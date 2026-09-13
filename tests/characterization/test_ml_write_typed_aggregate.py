"""Typed ML write aggregate positive/negative + session-neutrality coverage (P2-S5).

``TASK-ml-write-boundary-leaks-storage-representation-A-typed-inference-write-
boundary`` Phase 2 (P2-S5). Exercises the typed write aggregate
``MlDb.replace_song_inference_results(song: SongIdentity, backbone, *, vectors:
Sequence[BackboneVectorWrite], output_streams: Sequence[OutputStreamWrite])``
against the real pgvector:pg17 container and asserts the SAME persisted-row facts
as the P1 preservation oracle
(``tests/characterization/test_ml_write_preservation_baseline.py``) — vector
values/order, ``embed_dim``, ``model_id``==semantic suite hash with the persisted
``model_suite_hash`` column == "" , NULL ``segmentation_hash``, genres
None-vs-empty, hot tier, ms timestamps, stable caller-supplied 16-hex
``output_id`` stored verbatim, last-wins stream de-duplication, and order — plus
the negative paths (unknown SongIdentity, wrong identity type, raw vector dicts,
storage fields on the command) and outer-session neutrality after a failed
aggregate.

Like the oracle this module requires the real pgvector container (the
``embeddings`` table uses a PostgreSQL-only ``HALFVEC`` column), so it is marked
``characterization`` + ``requires_database`` and runs only in the CI
``database-tests`` job. It is NOT runnable in this workspace (no Docker /
pgvector wheel); it is verified here via ``py_compile`` + ``ruff`` only.

The read helpers mirror the oracle's (raw table selects + HALFVEC decode +
timestamp whitelist) so the typed path is asserted byte-for-byte against the
identical facts the legacy path is held to. Timestamps on the whitelist are
also asserted to be integer-millisecond epoch values (> 1_000_000_000_000)
before masking, so a ms-scale regression is never masked away.
"""

from __future__ import annotations

import hashlib
from typing import Any, cast

import pytest
from sqlalchemy import select

from nomarr.helpers.dataclasses.ml_output_stream_dataclass import OutputStreamWrite
from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
from nomarr.helpers.dataclasses.vector_dataclass import BackboneVectorWrite
from nomarr.persistence.models.embedding import Embedding
from nomarr.persistence.models.ml_output_stream import MlOutputStream

_EMBED_DIM = 1280
_TIMESTAMP_FIELDS = ("created_at", "updated_at")
_EMBEDDING_TABLE = cast("Any", Embedding.__table__)
_STREAM_TABLE = cast("Any", MlOutputStream.__table__)


def canonical_output_id(model_id: str, output_index: int) -> str:
    """Replicate the documented stable output identity (never through id_codec)."""
    return hashlib.sha256(f"{model_id}:{output_index}".encode()).hexdigest()[:16]


def _random_vector(dim: int = _EMBED_DIM, seed: int | None = None) -> list[float]:
    """Generate a deterministic, L2-normalized 1280-dim vector."""
    import numpy as np

    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    v /= np.linalg.norm(v)
    # Round-trip through fp16: the embeddings.embedding column is HALFVEC(1280),
    # so PostgreSQL quantizes inserted values to fp16 and the decoded read-back
    # never equals an unquantized fp32 input. Converting here makes every
    # produced float exactly fp16-representable, so equality against the decoded
    # column holds.
    return v.astype(np.float16).tolist()  # type: ignore[no-any-return]


def _decode_embedding(raw: Any) -> tuple[float, ...]:
    """Decode a pgvector HALFVEC column into an ordered float tuple."""
    if isinstance(raw, (list, tuple)):
        return tuple(float(x) for x in raw)
    text = raw.strip()
    assert text.startswith("[") and text.endswith("]"), f"unexpected HALFVEC repr: {text!r}"
    inner = text[1:-1].strip()
    if not inner:
        return ()
    return tuple(float(x) for x in inner.split(","))


def _normalize_row(row: Any) -> dict[str, Any]:
    """Mask ONLY the comparator whitelist timestamps; keep every other value verbatim.

    Before masking, each whitelisted ``created_at``/``updated_at`` value is asserted
    to be an integer-millisecond epoch timestamp (R7 project convention), so a
    seconds-epoch float/string/NULL regression would fail rather than be masked.
    """
    normalized: dict[str, Any] = {}
    for k, v in dict(row._mapping).items():
        if k in _TIMESTAMP_FIELDS:
            # BIGINT milliseconds arrives as a Python int via the driver; the
            # >1e12 guard discriminates ms-epoch from seconds-epoch.
            assert isinstance(v, int) and v > 1_000_000_000_000, f"{k} is not an integer-millisecond timestamp: {v!r}"
            normalized[k] = "<ts>"
        else:
            normalized[k] = v
    return normalized


def _vector_rows(session: Any, song_id: int) -> list[dict[str, Any]]:
    stmt = select(_EMBEDDING_TABLE).where(_EMBEDDING_TABLE.c.song_id == song_id)
    return [_normalize_row(r) for r in session.execute(stmt).all()]


def _stream_rows(session: Any, song_id: int) -> list[dict[str, Any]]:
    stmt = select(_STREAM_TABLE).where(_STREAM_TABLE.c.song_id == song_id)
    return [_normalize_row(r) for r in session.execute(stmt).all()]


def _typed_write(db: Any, song: SongIdentity, backbone: str, *, vectors: list[Any], streams: list[Any]) -> None:
    """Drive the typed aggregate (song identity + typed commands)."""
    db.ml.replace_song_inference_results(
        song=song,
        backbone=backbone,
        vectors=vectors,
        output_streams=streams,
    )


def _song_identity(seed_data: dict[str, Any], index: int = 0) -> SongIdentity:
    """Read the seeded semantic SongIdentity without crossing an integer bridge."""
    identity = seed_data["song_identities"][index]
    assert isinstance(identity, SongIdentity)
    return identity


@pytest.mark.characterization
@pytest.mark.requires_database
class TestTypedWritePreservation:
    """Typed aggregate reproduces the oracle's persisted-row facts."""

    def test_vector_row_field_preservation(self, db: Any, inference_session: Any, seed_data: dict) -> None:
        """embed_dim, suite-hash mapping, empty suite-hash col, NULL seg hash, hot tier."""
        song_id = seed_data["songs"][0]
        song = _song_identity(seed_data, seed_data["songs"].index(song_id))
        suite_hash = "suite-hash-canonical"
        stored = tuple(_random_vector(seed=101))

        _typed_write(
            db,
            song,
            "effnet",
            vectors=[
                BackboneVectorWrite(vector=stored, num_segments=7, model_suite_hash=suite_hash, genres=("rock", "pop"))
            ],
            streams=[],
        )

        rows = _vector_rows(inference_session, song_id)
        assert len(rows) == 1
        row = rows[0]
        assert row["backbone_id"] == "effnet"
        # model_id column carries the semantic suite hash (persistence maps it).
        assert row["model_id"] == suite_hash
        # persisted model_suite_hash stays "" (preservation oracle).
        assert row["model_suite_hash"] == ""
        assert row["embed_dim"] == _EMBED_DIM
        assert row["num_segments"] == 7
        assert row["segmentation_hash"] is None
        assert row["tier"] == "hot"
        assert row["genres"] == ["rock", "pop"]
        assert _decode_embedding(row["embedding"]) == stored

    def test_genres_none_is_distinct(self, db: Any, inference_session: Any, seed_data: dict) -> None:
        """genres=None persists as NULL (distinct from []); num_segments preserved."""
        song_id = seed_data["songs"][0]
        song = _song_identity(seed_data, seed_data["songs"].index(song_id))
        _typed_write(
            db,
            song,
            "musicnn",
            vectors=[
                BackboneVectorWrite(
                    vector=tuple(_random_vector(seed=7)),
                    num_segments=3,
                    model_suite_hash="suite-hash-null",
                    genres=None,
                )
            ],
            streams=[],
        )
        rows = _vector_rows(inference_session, song_id)
        assert len(rows) == 1
        assert rows[0]["genres"] is None
        assert rows[0]["num_segments"] == 3
        assert rows[0]["segmentation_hash"] is None

    def test_genres_empty_tuple_is_empty_list_distinct_from_null(
        self, db: Any, inference_session: Any, seed_data: dict
    ) -> None:
        """genres=() persists as [] (empty array), distinct from genres=None (NULL)."""
        song_id = seed_data["songs"][0]
        song = _song_identity(seed_data, seed_data["songs"].index(song_id))
        _typed_write(
            db,
            song,
            "musicnn",
            vectors=[
                BackboneVectorWrite(
                    vector=tuple(_random_vector(seed=8)),
                    num_segments=2,
                    model_suite_hash="suite-empty-genres",
                    genres=(),
                )
            ],
            streams=[],
        )
        rows = _vector_rows(inference_session, song_id)
        assert len(rows) == 1
        # () maps to a persisted empty array ([]), never NULL.
        assert rows[0]["genres"] == []

    def test_multiple_backbones_coexist_and_replacement_is_backbone_scoped(
        self, db: Any, inference_session: Any, seed_data: dict
    ) -> None:
        """R5: persisting one backbone never erases another backbone's vectors."""
        song_id = seed_data["songs"][0]
        song = _song_identity(seed_data, seed_data["songs"].index(song_id))
        _typed_write(
            db,
            song,
            "backbone_a",
            vectors=[
                BackboneVectorWrite(
                    vector=tuple(_random_vector(seed=1)), num_segments=1, model_suite_hash="model-a", genres=None
                )
            ],
            streams=[],
        )
        _typed_write(
            db,
            song,
            "backbone_b",
            vectors=[
                BackboneVectorWrite(
                    vector=tuple(_random_vector(seed=2)), num_segments=2, model_suite_hash="model-b", genres=None
                )
            ],
            streams=[],
        )
        # Re-persist backbone_a: only backbone_a's rows are replaced.
        _typed_write(
            db,
            song,
            "backbone_a",
            vectors=[
                BackboneVectorWrite(
                    vector=tuple(_random_vector(seed=3)), num_segments=4, model_suite_hash="model-a2", genres=None
                )
            ],
            streams=[],
        )
        rows = _vector_rows(inference_session, song_id)
        by_backbone = {r["backbone_id"]: r for r in rows}
        assert set(by_backbone) == {"backbone_a", "backbone_b"}
        assert by_backbone["backbone_a"]["model_id"] == "model-a2"
        assert by_backbone["backbone_b"]["model_id"] == "model-b"

    def test_stream_rows_preserve_identity_values_order_and_dedup(
        self, db: Any, inference_session: Any, seed_data: dict
    ) -> None:
        """Stable ids/values/order round-trip; duplicate output_id is last-wins (1 row)."""
        song_id = seed_data["songs"][0]
        song = _song_identity(seed_data, seed_data["songs"].index(song_id))
        suite_hash = "suite-hash-streams"
        out_id_0 = canonical_output_id(suite_hash, 0)
        out_id_1 = canonical_output_id(suite_hash, 1)

        _typed_write(
            db,
            song,
            "",
            vectors=[],
            streams=[
                OutputStreamWrite(output_id=out_id_1, values=[2.0, 1.0], output_index=1),
                OutputStreamWrite(output_id=out_id_0, values=[0.5], output_index=0),
                # Duplicate output_id: last wins within the batch.
                OutputStreamWrite(output_id=out_id_1, values=[9.0, 8.0, 7.0], output_index=1),
            ],
        )

        rows = _stream_rows(inference_session, song_id)
        by_id = {row["output_id"]: row for row in rows}
        assert set(by_id) == {out_id_0, out_id_1}
        # Stable string identity is the documented sha256[:16] form, stored verbatim.
        assert all(len(oid) == 16 for oid in by_id)
        assert by_id[out_id_0]["output_index"] == 0
        assert by_id[out_id_0]["values"] == [0.5]
        assert by_id[out_id_1]["output_index"] == 1
        assert by_id[out_id_1]["values"] == [9.0, 8.0, 7.0]

    def test_stream_only_sentinel_keeps_vectors(self, db: Any, inference_session: Any, seed_data: dict) -> None:
        """Streams-only (vectors=[], backbone="") clears streams but keeps vectors."""
        song_id = seed_data["songs"][0]
        song = _song_identity(seed_data, seed_data["songs"].index(song_id))
        out_id = canonical_output_id("suite-clear", 0)
        _typed_write(
            db,
            song,
            "effnet",
            vectors=[
                BackboneVectorWrite(
                    vector=tuple(_random_vector(seed=55)), num_segments=1, model_suite_hash="suite-clear", genres=None
                )
            ],
            streams=[OutputStreamWrite(output_id=out_id, values=[1.0], output_index=0)],
        )
        assert _stream_rows(inference_session, song_id)

        # Streams-only sentinel clears streams but must NOT delete vectors.
        _typed_write(
            db,
            song,
            "",
            vectors=[],
            streams=[OutputStreamWrite(output_id=out_id, values=[2.0], output_index=0)],
        )
        streams = _stream_rows(inference_session, song_id)
        assert [row["values"] for row in streams] == [[2.0]]
        assert len(_vector_rows(inference_session, song_id)) == 1

    def test_empty_streams_arg_clears_streams(self, db: Any, inference_session: Any, seed_data: dict) -> None:
        """R6: output_streams=[] with an empty backbone is the clear-stream path."""
        song_id = seed_data["songs"][0]
        song = _song_identity(seed_data, seed_data["songs"].index(song_id))
        out_id = canonical_output_id("suite-empty", 0)
        _typed_write(
            db,
            song,
            "",
            vectors=[],
            streams=[OutputStreamWrite(output_id=out_id, values=[1.0], output_index=0)],
        )
        assert _stream_rows(inference_session, song_id)

        _typed_write(db, song, "", vectors=[], streams=[])
        assert _stream_rows(inference_session, song_id) == []


@pytest.mark.characterization
@pytest.mark.requires_database
class TestTypedWriteRejectsStorageShapedInput:
    """Negative paths: semantic identity only, typed commands only, no storage fields."""

    def test_unknown_song_identity_raises_persistence_error(self, db: Any, seed_data: dict) -> None:
        """Resolution failure surfaces as EntityNotFoundError (repo-owned mapping)."""
        from nomarr.helpers.exceptions import EntityNotFoundError

        known = _song_identity(db, seed_data["songs"][0])
        unknown = SongIdentity(library=known.library, normalized_path="/tmp/test1/does-not-exist.flac")
        with pytest.raises(EntityNotFoundError):
            _typed_write(
                db,
                unknown,
                "effnet",
                vectors=[BackboneVectorWrite(vector=(0.1, 0.2), num_segments=1, model_suite_hash="m", genres=None)],
                streams=[],
            )

    def test_integer_song_key_rejected(self, db: Any, seed_data: dict) -> None:
        """An integer song storage key is rejected at the typed boundary (TypeError)."""
        with pytest.raises(TypeError):
            db.ml.replace_song_inference_results(seed_data["songs"][0], "effnet", vectors=[], output_streams=[])  # type: ignore[arg-type]

    def test_raw_vector_dictionary_rejected(self, db: Any, seed_data: dict) -> None:
        """A raw vector dict (with storage fields) is rejected at the typed boundary."""
        song = _song_identity(db, seed_data["songs"][0])
        with pytest.raises(TypeError):
            db.ml.replace_song_inference_results(
                song,
                "effnet",
                vectors=[{"embedding_vector": [0.1], "model_id": "m"}],  # type: ignore[list-item]
                output_streams=[],
            )

    def test_embed_dim_on_command_rejected(self) -> None:
        """embed_dim is a storage-derived field the command must never carry."""
        with pytest.raises(TypeError):
            BackboneVectorWrite(  # type: ignore[call-arg]
                vector=(0.1, 0.2),
                num_segments=1,
                model_suite_hash="m",
                genres=None,
                embed_dim=2,  # type: ignore[call-arg]
            )


@pytest.mark.characterization
@pytest.mark.requires_database
class TestTypedAggregateSessionNeutrality:
    """A failed typed aggregate rolls back cleanly; the outer session stays usable."""

    def test_failed_aggregate_leaves_no_partial_rows(self, db: Any, inference_session: Any, seed_data: dict) -> None:
        """R10: an insert violation inside the aggregate rolls back both tables."""
        from nomarr.helpers.exceptions import DuplicateEntityError

        song_id = seed_data["songs"][0]
        song = _song_identity(seed_data, seed_data["songs"].index(song_id))
        with pytest.raises(DuplicateEntityError):
            _typed_write(
                db,
                song,
                "effnet",
                vectors=[
                    BackboneVectorWrite(
                        vector=tuple(_random_vector(seed=1)), num_segments=1, model_suite_hash="dup-a", genres=None
                    ),
                    BackboneVectorWrite(
                        vector=tuple(_random_vector(seed=2)), num_segments=1, model_suite_hash="dup-b", genres=None
                    ),
                ],
                streams=[],
            )
        assert _vector_rows(inference_session, song_id) == []

    def test_session_is_neutral_after_failure(self, db: Any, inference_session: Any, seed_data: dict) -> None:
        """R9: after an injected failure, a subsequent write on the same session succeeds."""
        from nomarr.helpers.exceptions import DuplicateEntityError

        song_id = seed_data["songs"][0]
        song = _song_identity(seed_data, seed_data["songs"].index(song_id))
        with pytest.raises(DuplicateEntityError):
            _typed_write(
                db,
                song,
                "effnet",
                vectors=[
                    BackboneVectorWrite(
                        vector=tuple(_random_vector(seed=3)), num_segments=1, model_suite_hash="m-x", genres=None
                    ),
                    BackboneVectorWrite(
                        vector=tuple(_random_vector(seed=4)), num_segments=1, model_suite_hash="m-y", genres=None
                    ),
                ],
                streams=[],
            )

        # R9 hardening: the aggregate must roll back the autobegun outer
        # transaction on failure, so the aggregate's shared scoped session is
        # NOT left in an open/pending transaction that the worker's subsequent
        # errored-transition/release calls would inherit.
        assert not db._scoped.in_transaction()

        good_vec = tuple(_random_vector(seed=5))
        _typed_write(
            db,
            song,
            "effnet",
            vectors=[BackboneVectorWrite(vector=good_vec, num_segments=2, model_suite_hash="m-ok", genres=None)],
            streams=[],
        )
        rows = _vector_rows(inference_session, song_id)
        assert len(rows) == 1
        assert rows[0]["model_id"] == "m-ok"
        assert _decode_embedding(rows[0]["embedding"]) == good_vec
