"""Pre-change preservation baseline + session-neutrality oracle for the ML write aggregate.

P1-S3 / P1-S4 of ``TASK-ml-write-boundary-leaks-storage-representation-A-typed-
inference-write-boundary``. This module records the canonical persisted-row facts
that MUST be byte-for-byte identical after the typed write boundary lands (Phases
2-4): vector values/order, ``num_segments``, ``embed_dim``, suite-hash mapping
(the ``model_id`` column holds the semantic suite hash while the persisted
``model_suite_hash`` column stays ``""``), NULL ``segmentation_hash``,
``genres`` None-vs-empty, hot tier, millisecond timestamps, stable output
ids/values/order, last-wins stream deduplication, and stream bytes/order.

Comparator-only timestamp normalization is allowed on an EXPLICIT whitelist
(``created_at``/``updated_at`` on the embeddings and stream rows), and BEFORE
masking each whitelisted value is asserted to be an integer-millisecond epoch
timestamp (> 1_000_000_000_000) — so a seconds-epoch float, string, or NULL
regression is caught at the DB-truth layer rather than masked away. Stored
values are never rewritten.

Requires the real pgvector:pg17 container (the ``embeddings`` table uses a
PostgreSQL-only ``HALFVEC`` column), so this module is marked
``characterization`` + ``requires_database`` and runs only in the CI
``database-tests`` job. It is NOT runnable in this workspace (no Docker); the
baseline is authored from the requirement ledger and is the oracle P5-S3 executes
after the typed path lands.

Rows are read RAW (direct table selects through ``inference_session``) rather than
through ``VectorRepo.get_embeddings_for_song``, because that repository helper
filters ``tier='cold'`` and requires a ``backbone_id`` — it is not a read surface
for freshly-inserted hot rows.

The write driver ``_persist_typed`` drives the typed aggregate signature
``replace_song_inference_results(song: SongIdentity, backbone, *,
vectors: Sequence[BackboneVectorWrite], output_streams:
Sequence[OutputStreamWrite])`` (retargeted in P5-S3). It mirrors the production
worker boundary: the seeded storage song id is resolved once to a semantic
``SongIdentity`` through the authorized library identity bridge
(``db.library.resolve_song_identity``) and the legacy raw vector dicts
(``embedding_vector``/``model_id``/``num_segments``/``genres``) are translated to
``BackboneVectorWrite`` commands carrying the SAME values, so no integer storage
key or raw vector dictionary crosses ``db.ml``. Every assertion below is the
preservation proof — the typed call must reproduce the exact persisted-row facts.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, cast

import pytest
from sqlalchemy import select

from nomarr.helpers.dataclasses.ml_output_stream_dataclass import OutputStreamWrite
from nomarr.helpers.dataclasses.vector_dataclass import BackboneVectorWrite
from nomarr.persistence.models.embedding import Embedding
from nomarr.persistence.models.ml_output_stream import MlOutputStream

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.persistence.db import Database

# Embedding dimension must match HALFVEC(1280) in the Embedding model.
_EMBED_DIM = 1280
# R7 stable output identity: sha256(f"{model_id}:{output_index}").hexdigest()[:16].
# Comparator-only normalization whitelist — the ONLY fields ever rewritten.
_TIMESTAMP_FIELDS = ("created_at", "updated_at")

_EMBEDDING_TABLE = cast("Any", Embedding.__table__)
_STREAM_TABLE = cast("Any", MlOutputStream.__table__)


def canonical_output_id(model_id: str, output_index: int) -> str:
    """Replicate the documented stable output identity (never through id_codec)."""
    return hashlib.sha256(f"{model_id}:{output_index}".encode()).hexdigest()[:16]


def _normalize_row(row: Any) -> dict[str, Any]:
    """Map a raw table row for comparison, masking ONLY whitelisted timestamps.

    Every other stored value is preserved verbatim so pre/post drift shows up as a
    real mismatch rather than being masked. Before masking, each whitelisted
    ``created_at``/``updated_at`` value must be an integer-millisecond epoch
    timestamp (R7 project convention) — a seconds-epoch float/string/NULL would
    otherwise be masked away and pass undetected.
    """
    normalized: dict[str, Any] = {}
    for k, v in dict(row._mapping).items():
        if k in _TIMESTAMP_FIELDS:
            # BIGINT milliseconds arrives as a Python int via the driver. The
            # >1e12 guard discriminates ms-epoch from seconds-epoch.
            assert isinstance(v, int) and v > 1_000_000_000_000, f"{k} is not an integer-millisecond timestamp: {v!r}"
            normalized[k] = "<ts>"
        else:
            normalized[k] = v
    return normalized


def _decode_embedding(raw: Any) -> tuple[float, ...]:
    """Decode a pgvector HALFVEC column into an ordered float tuple.

    The driver returns the half-precision vector as a ``"[0.1,0.2,…]"`` string.
    """
    if isinstance(raw, (list, tuple)):
        return tuple(float(x) for x in raw)
    text = raw.strip()
    assert text.startswith("[") and text.endswith("]"), f"unexpected HALFVEC repr: {text!r}"
    inner = text[1:-1].strip()
    if not inner:
        return ()
    return tuple(float(x) for x in inner.split(","))


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


def _persist_typed(
    db: Database,
    song: SongIdentity,
    backbone: str,
    *,
    vectors: list[dict[str, Any]],
    streams: list[OutputStreamWrite],
) -> None:
    """Drive the typed aggregate with a semantic ``SongIdentity`` locator.

    The seeded locator is already supplied by the typed fixture. Only the
    identity and typed vector/stream commands cross ``db.ml``; storage IDs and
    raw vector dictionaries remain outside the persistence intent boundary.
    """
    typed_vectors = [
        BackboneVectorWrite(
            vector=tuple(v["embedding_vector"]),
            model_suite_hash=v["model_id"],
            num_segments=v.get("num_segments"),
            genres=tuple(v["genres"]) if v.get("genres") is not None else None,
        )
        for v in vectors
    ]
    db.ml.replace_song_inference_results(
        song=song,
        backbone=backbone,
        vectors=typed_vectors,
        output_streams=list(streams),
    )


def _vector_rows(session: Session, song_id: int) -> list[dict[str, Any]]:
    stmt = select(_EMBEDDING_TABLE).where(_EMBEDDING_TABLE.c.song_id == song_id)
    return [_normalize_row(r) for r in session.execute(stmt).all()]


def _stream_rows(session: Session, song_id: int) -> list[dict[str, Any]]:
    stmt = select(_STREAM_TABLE).where(_STREAM_TABLE.c.song_id == song_id)
    return [_normalize_row(r) for r in session.execute(stmt).all()]


@pytest.mark.characterization
@pytest.mark.requires_database
class TestWritePreservationBaseline:
    """Row-preservation oracle run on real PostgreSQL before/after the typed path."""

    def test_vector_row_field_preservation(self, db: Database, inference_session: Session, seed_data: dict) -> None:
        """embed_dim, suite-hash mapping, empty suite-hash col, NULL seg hash, hot tier."""
        song = cast("SongIdentity", seed_data["song_identities"][0])
        suite_hash = "suite-hash-canonical"
        stored = _random_vector(seed=101)

        _persist_typed(
            db,
            song,
            "effnet",
            vectors=[
                {
                    "embedding_vector": stored,
                    "model_id": suite_hash,
                    "num_segments": 7,
                    "genres": ["rock", "pop"],
                },
            ],
            streams=[],
        )

        rows = _vector_rows(inference_session, cast("int", seed_data["songs"][0]))
        assert len(rows) == 1
        row = rows[0]
        assert row["backbone_id"] == "effnet"
        # model_id column carries the semantic suite hash (persistence maps it).
        assert row["model_id"] == suite_hash
        # persisted model_suite_hash stays "" unless a payload supplied a key.
        assert row["model_suite_hash"] == ""
        assert row["embed_dim"] == _EMBED_DIM
        assert row["num_segments"] == 7
        assert row["segmentation_hash"] is None
        assert row["tier"] == "hot"
        assert row["genres"] == ["rock", "pop"]
        # vector values AND order preserved verbatim.
        assert _decode_embedding(row["embedding"]) == tuple(stored)

    def test_genres_none_is_distinct(self, db: Database, inference_session: Session, seed_data: dict) -> None:
        """genres=None persists as NULL (distinct from []); num_segments preserved."""
        song = cast("SongIdentity", seed_data["song_identities"][0])
        _persist_typed(
            db,
            song,
            "musicnn",
            vectors=[
                {
                    "embedding_vector": _random_vector(seed=7),
                    "model_id": "suite-hash-null",
                    "num_segments": 3,
                    "genres": None,
                },
            ],
            streams=[],
        )
        rows = _vector_rows(inference_session, cast("int", seed_data["songs"][0]))
        assert len(rows) == 1
        assert rows[0]["genres"] is None
        assert rows[0]["num_segments"] == 3
        assert rows[0]["segmentation_hash"] is None

    def test_multiple_backbones_coexist_and_replacement_is_backbone_scoped(
        self, db: Database, inference_session: Session, seed_data: dict
    ) -> None:
        """R5: persisting one backbone never erases another backbone's vectors."""
        song = cast("SongIdentity", seed_data["song_identities"][0])
        _persist_typed(
            db,
            song,
            "backbone_a",
            vectors=[
                {"embedding_vector": _random_vector(seed=1), "model_id": "model-a", "num_segments": 1, "genres": None}
            ],
            streams=[],
        )
        _persist_typed(
            db,
            song,
            "backbone_b",
            vectors=[
                {"embedding_vector": _random_vector(seed=2), "model_id": "model-b", "num_segments": 2, "genres": None}
            ],
            streams=[],
        )
        # Re-persist backbone_a: only backbone_a's rows are replaced.
        _persist_typed(
            db,
            song,
            "backbone_a",
            vectors=[
                {"embedding_vector": _random_vector(seed=3), "model_id": "model-a2", "num_segments": 4, "genres": None}
            ],
            streams=[],
        )
        rows = _vector_rows(inference_session, cast("int", seed_data["songs"][0]))
        by_backbone = {r["backbone_id"]: r for r in rows}
        assert set(by_backbone) == {"backbone_a", "backbone_b"}
        assert by_backbone["backbone_a"]["model_id"] == "model-a2"
        assert by_backbone["backbone_b"]["model_id"] == "model-b"

    def test_stream_rows_preserve_identity_values_order_and_dedup(
        self, db: Database, inference_session: Session, seed_data: dict
    ) -> None:
        """Stable ids/values/order round-trip; duplicate output_id is last-wins (1 row)."""
        song = cast("SongIdentity", seed_data["song_identities"][0])
        suite_hash = "suite-hash-streams"
        out_id_0 = canonical_output_id(suite_hash, 0)
        out_id_1 = canonical_output_id(suite_hash, 1)

        _persist_typed(
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

        rows = _stream_rows(inference_session, cast("int", seed_data["songs"][0]))
        by_id = {row["output_id"]: row for row in rows}
        assert set(by_id) == {out_id_0, out_id_1}
        # Stable string identity is exactly the documented sha256[:16] form.
        assert all(len(oid) == 16 for oid in by_id)
        assert by_id[out_id_0]["output_index"] == 0
        assert by_id[out_id_0]["values"] == [0.5]
        assert by_id[out_id_1]["output_index"] == 1
        assert by_id[out_id_1]["values"] == [9.0, 8.0, 7.0]

    def test_stream_clear_and_stream_only_sentinel(
        self, db: Database, inference_session: Session, seed_data: dict
    ) -> None:
        """output_streams=[] clears streams; streams-only (vectors=[], backbone="") keeps vectors."""
        song = cast("SongIdentity", seed_data["song_identities"][0])
        out_id = canonical_output_id("suite-clear", 0)

        _persist_typed(
            db,
            song,
            "effnet",
            vectors=[
                {
                    "embedding_vector": _random_vector(seed=55),
                    "model_id": "suite-clear",
                    "num_segments": 1,
                    "genres": None,
                }
            ],
            streams=[OutputStreamWrite(output_id=out_id, values=[1.0], output_index=0)],
        )
        assert _stream_rows(inference_session, cast("int", seed_data["songs"][0]))

        # Streams-only sentinel clears streams but must NOT delete vectors.
        _persist_typed(
            db,
            song,
            "",
            vectors=[],
            streams=[OutputStreamWrite(output_id=out_id, values=[2.0], output_index=0)],
        )
        streams = _stream_rows(inference_session, cast("int", seed_data["songs"][0]))
        assert [row["values"] for row in streams] == [[2.0]]
        assert len(_vector_rows(inference_session, cast("int", seed_data["songs"][0]))) == 1

    def test_empty_streams_arg_clears_streams(self, db: Database, inference_session: Session, seed_data: dict) -> None:
        """R6: output_streams=[] with an empty backbone is the clear-stream path."""
        song = cast("SongIdentity", seed_data["song_identities"][0])
        out_id = canonical_output_id("suite-empty", 0)
        _persist_typed(
            db,
            song,
            "",
            vectors=[],
            streams=[OutputStreamWrite(output_id=out_id, values=[1.0], output_index=0)],
        )
        assert _stream_rows(inference_session, cast("int", seed_data["songs"][0]))

        _persist_typed(db, song, "", vectors=[], streams=[])
        assert _stream_rows(inference_session, cast("int", seed_data["songs"][0])) == []


@pytest.mark.characterization
@pytest.mark.requires_database
class TestAggregateSessionNeutrality:
    """P1-S4/R9-R10: a failed aggregate rolls back cleanly; the session stays usable."""

    def test_failed_aggregate_leaves_no_partial_rows(
        self, db: Database, inference_session: Session, seed_data: dict
    ) -> None:
        """R10: an insert violation inside the aggregate rolls back both tables."""
        from nomarr.helpers.exceptions import DuplicateEntityError

        song = cast("SongIdentity", seed_data["song_identities"][0])
        with pytest.raises(DuplicateEntityError):
            _persist_typed(
                db,
                song,
                "effnet",
                vectors=[
                    {
                        "embedding_vector": _random_vector(seed=1),
                        "model_id": "dup-a",
                        "num_segments": 1,
                        "genres": None,
                    },
                    {
                        "embedding_vector": _random_vector(seed=2),
                        "model_id": "dup-b",
                        "num_segments": 1,
                        "genres": None,
                    },
                ],
                streams=[],
            )
        assert _vector_rows(inference_session, cast("int", seed_data["songs"][0])) == []

    def test_session_is_neutral_after_failure(self, db: Database, inference_session: Session, seed_data: dict) -> None:
        """R9: after an injected failure, a subsequent write on the same session succeeds."""
        from nomarr.helpers.exceptions import DuplicateEntityError

        song = cast("SongIdentity", seed_data["song_identities"][0])
        with pytest.raises(DuplicateEntityError):
            _persist_typed(
                db,
                song,
                "effnet",
                vectors=[
                    {"embedding_vector": _random_vector(seed=3), "model_id": "m-x", "num_segments": 1, "genres": None},
                    {"embedding_vector": _random_vector(seed=4), "model_id": "m-y", "num_segments": 1, "genres": None},
                ],
                streams=[],
            )

        good_vec = _random_vector(seed=5)
        _persist_typed(
            db,
            song,
            "effnet",
            vectors=[{"embedding_vector": good_vec, "model_id": "m-ok", "num_segments": 2, "genres": None}],
            streams=[],
        )
        rows = _vector_rows(inference_session, cast("int", seed_data["songs"][0]))
        assert len(rows) == 1
        assert rows[0]["model_id"] == "m-ok"
        assert _decode_embedding(rows[0]["embedding"]) == tuple(good_vec)
