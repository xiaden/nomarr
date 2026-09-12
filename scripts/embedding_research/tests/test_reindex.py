"""Geometry-era reindex tests: rebuild registry rows from committed current-format evidence.

``reconcile_current_manifests`` walks the committed observation markers and
current-format stream/mask/head manifests on disk and rebuilds the retained
``stream_registry`` / ``head_stream_registry`` index rows.  These tests use only
synthetic committed evidence (no real corpus, audio, models, or filesystem Gram)
and cover rebuild, idempotency, refusal of corrupt evidence, orphan reporting,
and the missing-root refusal.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.streams.masks import MaskPayload
from scripts.embedding_research.streams.records import StreamNotFoundError
from scripts.embedding_research.streams.reindex import reconcile_current_manifests, reindex
from scripts.embedding_research.streams.store import HeadStreamStore, StreamStore

PATCH = 3
DIM = 4


def _fresh_con():
    connection = duckdb.connect(":memory:")
    ensure_schema(connection)
    return connection


def _embeddings(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.random((PATCH, DIM), dtype=np.float32)


def _seed_committed_group(root, *, with_heads: bool = True) -> np.ndarray:
    """Publish one committed stream+mask group (+ optional current head suite) to *root*."""
    root.mkdir(parents=True, exist_ok=True)
    con = _fresh_con()
    try:
        store = StreamStore(con, output_root=root)
        emb = _embeddings()
        record = store.publish("s1", "effnet", emb, run_id="run-1")
        store.publish_observation_group(
            record,
            MaskPayload(
                song_id="s1",
                backbone="effnet",
                patch_count=PATCH,
                mask=np.ones(PATCH, dtype=np.uint8),
                run_id="run-1",
                params_id="mask-params-1",
                audio_content_sha256="0" * 64,
            ),
        )
        if with_heads:
            HeadStreamStore(con, output_root=root).publish(
                "s1",
                "effnet",
                {"head_logit": np.arange(PATCH * 2, dtype=np.float32).reshape(PATCH, 2)},
                run_id="run-1",
                patch_count=PATCH,
                alignment_version="1",
                expected_head_ids={"head_logit"},
                stream_ref=record.artifact_ref,
            )
        return emb
    finally:
        con.close()


@pytest.fixture
def con():
    connection = _fresh_con()
    yield connection
    connection.close()


def test_reindex_rebuilds_registry_from_committed_evidence(tmp_path, con):
    root = tmp_path / "root"
    emb = _seed_committed_group(root)

    report = reconcile_current_manifests(root, con)

    assert report.issues == ()
    assert report.scanned == 2
    assert report.ready == 2
    assert report.rows_rebuilt == 2
    assert report.orphan_payloads == 0
    assert report.clean

    stream = StreamStore(con, output_root=root)
    assert stream.lookup("s1", "effnet").status == "ready"
    assert np.array_equal(stream.batch_gather("s1", "effnet", [0, 2]), emb[[0, 2]])
    assert HeadStreamStore(con, output_root=root).lookup("s1", "effnet").status == "ready"


def test_reindex_is_idempotent(tmp_path, con):
    root = tmp_path / "root"
    _seed_committed_group(root)

    first = reindex(root, con)
    second = reindex(root, con)

    assert first.clean and second.clean
    assert con.execute("SELECT COUNT(*) FROM stream_registry").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM head_stream_registry").fetchone()[0] == 1


def test_reindex_zero_ready_until_observation_is_committed(tmp_path, con):
    root = tmp_path / "root"
    root.mkdir()
    seed = _fresh_con()
    try:
        StreamStore(seed, output_root=root).publish("s1", "effnet", _embeddings(), run_id="run-1")
    finally:
        seed.close()

    report = reconcile_current_manifests(root, con)

    assert report.ready == 0
    assert report.rows_rebuilt == 0
    with pytest.raises(StreamNotFoundError):
        StreamStore(con, output_root=root).lookup("s1", "effnet")


def test_reindex_refuses_corrupt_stream_payload(tmp_path, con):
    root = tmp_path / "root"
    _seed_committed_group(root)
    payload = next((root / "streams").glob("*.npy"))
    payload.write_bytes(b"not-a-valid-npy-payload")

    report = reconcile_current_manifests(root, con)

    assert report.ready == 0
    assert report.issues
    assert not report.clean


def test_reindex_reports_orphan_payload_without_manifest(tmp_path, con):
    root = tmp_path / "root"
    _seed_committed_group(root)
    next((root / "streams").glob("*.json")).unlink()

    report = reconcile_current_manifests(root, con)

    assert report.orphan_payloads == 1
    assert not report.clean


def test_reindex_nonexistent_root_raises(tmp_path, con):
    with pytest.raises(ValueError):
        reindex(tmp_path / "missing", con)
