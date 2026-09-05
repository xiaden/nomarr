"""Spec-first tests for the filesystem-only reindex (Plan B P1-S5).

Proves ``reconcile_current_manifests(root, con)`` / ``reindex(root, con)``:

* rebuild the retained ``stream_registry`` / ``head_stream_registry`` cache/index
  rows from current-format filesystem manifests alone (DB-deletion recovery);
* refuse corrupt / incomplete / mismatched / partial / orphan / WAL-bearing
  state without old-format parsing, audio, models, sessions, ONNX/CUDA,
  path-derived IDs or segmentation recomputation;
* keep readers fail-closed until a committed observation group is reindexed to a
  validated ``ready`` registry row (payload/manifests/commit land before the row).
"""

from __future__ import annotations

import builtins
import json

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.streams.masks import MaskPayload
from scripts.embedding_research.streams.records import (
    STREAM_TABLE,
    StreamNotFoundError,
)
from scripts.embedding_research.streams.reindex import (
    reconcile_current_manifests,
    reindex,
)
from scripts.embedding_research.streams.store import HeadStreamStore, StreamStore

PATCH = 3
DIM = 4


@pytest.fixture
def con():
    """A fresh in-memory DuckDB with the full research schema (post-deletion empty registries)."""
    connection = duckdb.connect(":memory:")
    ensure_schema(connection)
    yield connection
    connection.close()


def _fresh_con():
    """Return a separate in-memory DB; its registries are empty (post-deletion state)."""
    connection = duckdb.connect(":memory:")
    ensure_schema(connection)
    return connection


def _embeddings(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.random((PATCH, DIM), dtype=np.float32)


def _seed_corpus(out, *, with_heads: bool = True) -> np.ndarray:
    """Publish a fully committed stream+mask group (+ optional head suite) to *out*.

    Uses a throwaway in-memory DB purely to drive the durable filesystem publication;
    registry rows in that DB are irrelevant (``reindex`` rebuilds from the FS alone).
    Returns the committed stream embeddings for equality assertions.
    """
    out.mkdir(parents=True, exist_ok=True)
    con = _fresh_con()
    try:
        store = StreamStore(con, output_root=out)
        emb = _embeddings()
        rec = store.publish("s1", "effnet", emb, run_id="run-1")
        mask = MaskPayload(
            song_id="s1",
            backbone="effnet",
            patch_count=PATCH,
            mask=np.ones(PATCH, dtype=np.uint8),
            run_id="run-1",
            params_id="mask-params-1",
        )
        store.publish_observation_group(rec, mask)
        if with_heads:
            head_arrays = {"head_logit": np.arange(PATCH * 2, dtype=np.float32).reshape(PATCH, 2)}
            HeadStreamStore(con, output_root=out).publish(
                "s1",
                "effnet",
                head_arrays,
                run_id="run-1",
                patch_count=PATCH,
                alignment_version="1",
                expected_head_ids={"head_logit"},
                stream_ref=rec.artifact_ref,
            )
        return emb
    finally:
        con.close()


# ── rebuild after DB deletion ────────────────────────────────────────────────


def test_reindex_rebuilds_registries_from_current_manifests_after_db_deletion(tmp_path, con):
    out = tmp_path / "root"
    emb = _seed_corpus(out)

    # `con` is a brand-new (post-deletion) database with empty registries.
    report = reconcile_current_manifests(out, con)

    assert report.clean, report
    assert report.ready == 2  # 1 committed stream group + 1 head suite
    assert report.rows_rebuilt == 2
    assert report.scanned == 2
    assert report.orphan_payloads == 0

    # Retained registry is a validated index/cache: ready rows resolve & gather.
    stream = StreamStore(con, output_root=out)
    row = stream.lookup("s1", "effnet")
    assert row.status == "ready"
    assert np.array_equal(stream.batch_gather("s1", "effnet", [0, 2]), emb[[0, 2]], equal_nan=False)

    head = HeadStreamStore(con, output_root=out).lookup("s1", "effnet")
    assert head.status == "ready"

    # Public wrapper is a thin alias of the internal walk.
    con2 = _fresh_con()
    assert reindex(out, con2).clean


def test_empty_root_does_not_fail_but_is_not_unqualifiedly_clean(tmp_path, con):
    out = tmp_path / "root"
    out.mkdir()
    report = reindex(out, con)
    assert report.issues == ()
    assert report.ready == 0


def test_reindex_nonexistent_root_raises(tmp_path, con):
    with pytest.raises(ValueError):
        reindex(tmp_path / "does-not-exist", con)


# ── same-run publication ordering / fail-closed ──────────────────────────────


def test_reader_fails_closed_until_committed_group_is_reindexed(tmp_path):
    out = tmp_path / "root"
    _seed_corpus(out, with_heads=False)

    con = _fresh_con()  # DB deletion: registry empty even though FS is fully populated
    store = StreamStore(con, output_root=out)

    # Payload + manifest + commit marker already durable on disk BEFORE any row.
    assert len(list((out / "streams").glob("*.npy"))) == 1
    assert len(list((out / "streams").glob("*.json"))) == 1
    assert len(list((out / "audio_masks").glob("*.json"))) == 1
    assert len(list((out / "observation_commits").glob("*.json"))) == 1

    # Reader must fail closed: no ready registry row yet.
    with pytest.raises(StreamNotFoundError):
        store.lookup("s1", "effnet")

    report = reindex(out, con)
    assert report.clean
    assert store.lookup("s1", "effnet").status == "ready"


# ── refusal of corrupt / incomplete / mismatched state ───────────────────────


def test_reindex_refuses_partial_stream_without_commit_marker(tmp_path, con):
    out = tmp_path / "root"
    out.mkdir()
    seed_con = _fresh_con()
    try:
        StreamStore(seed_con, output_root=out).publish("s1", "effnet", _embeddings(), run_id="run-1")
    finally:
        seed_con.close()

    report = reconcile_current_manifests(out, con)
    assert report.ready == 0
    assert report.scanned == 0
    assert any("without a valid observation-commit marker" in issue for issue in report.issues)
    assert not report.clean
    with pytest.raises(StreamNotFoundError):
        StreamStore(con, output_root=out).lookup("s1", "effnet")


def test_reindex_refuses_corrupt_stream_payload(tmp_path, con):
    out = tmp_path / "root"
    _seed_corpus(out, with_heads=False)
    payload = next((out / "streams").glob("*.npy"))
    payload.write_bytes(b"corrupt-bytes-not-a-valid-npy")

    report = reconcile_current_manifests(out, con)
    assert not report.clean
    assert report.ready == 0
    assert any("payload" in issue and "refused" in issue for issue in report.issues)
    with pytest.raises(StreamNotFoundError):
        StreamStore(con, output_root=out).lookup("s1", "effnet")


def test_reindex_refuses_mismatched_stream_manifest_digest(tmp_path, con):
    out = tmp_path / "root"
    _seed_corpus(out, with_heads=False)
    manifest = next((out / "streams").glob("*.json"))
    data = json.loads(manifest.read_text())
    data["fingerprint_sha256"] = "0" * 64  # manifest digest no longer matches the payload
    manifest.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")))

    report = reconcile_current_manifests(out, con)
    assert not report.clean
    assert report.ready == 0
    assert any("payload" in issue and "refused" in issue for issue in report.issues)


def test_reindex_reports_orphan_payload_without_manifest(tmp_path, con):
    out = tmp_path / "root"
    _seed_corpus(out, with_heads=False)
    # Delete a committed stream's sibling manifest -> digest payload becomes an orphan.
    manifest = next((out / "streams").glob("*.json"))
    manifest.unlink()

    report = reconcile_current_manifests(out, con)
    assert report.orphan_payloads == 1
    assert not report.clean
    assert report.ready == 0


# ── current-format-only / no old-format parsing ──────────────────────────────


def test_reindex_never_parses_bare_or_versioned_names(tmp_path, con):
    out = tmp_path / "root"
    _seed_corpus(out)
    # Legacy/bare/.vN payloads that MUST be ignored, never parsed or adopted.
    for name in ("s1.effnet.v3.npy", "s1.effnet.npy", "old.effnet.v2.npy"):
        (out / "streams" / name).write_bytes(b"ignored-legacy-bytes")

    report = reconcile_current_manifests(out, con)
    # Only the current digest group + head are indexed; legacy files are invisible.
    assert report.clean, report
    assert report.ready == 2
    rows = con.execute(f"SELECT song_id, backbone FROM {STREAM_TABLE}").fetchall()
    assert rows == [("s1", "effnet")]


# ── catalog WAL / close-state handling (Plan C grammar, dormant until C lands) ─


def test_reindex_is_clean_without_corrected_grammar_catalogs(tmp_path, con):
    out = tmp_path / "root"
    _seed_corpus(out)
    assert not (out / "catalogs").exists()
    assert reindex(out, con).clean  # absence of corrected catalogs is NOT a failure


def test_reindex_refuses_wal_bearing_current_catalog(tmp_path, con):
    out = tmp_path / "root"
    _seed_corpus(out)
    cat = out / "catalogs" / "catalog-1"
    cat.mkdir(parents=True)
    (out / "catalogs").joinpath("current.json").write_text('{"catalog_id": "catalog-1"}', encoding="utf-8")
    cat.joinpath("catalog.manifest.json").write_text('{"kind": "catalog", "schema_version": "1"}', encoding="utf-8")
    cat.joinpath("catalog.duckdb").write_bytes(b"")
    cat.joinpath("catalog.duckdb.wal").write_bytes(b"")  # WAL-bearing -> refused

    report = reconcile_current_manifests(out, con)
    assert any("WAL-bearing" in issue for issue in report.issues)
    assert not report.clean
    # Stream/head registry still rebuilt from current manifests despite catalog refusal.
    assert report.ready == 2


# ── CPU-only: no audio / models / sessions / ONNX / CUDA / segmentation ──────


def test_reindex_uses_no_audio_model_session_onnx_cuda(tmp_path, con, monkeypatch):
    out = tmp_path / "root"
    _seed_corpus(out)

    banned = {"onnxruntime", "torch", "essentia", "tensorflow", "librosa"}
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in banned:
            raise AssertionError(f"reindex reached a banned runtime import: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    report = reindex(out, con)

    assert report.clean, report
    assert report.ready == 2
    # And the rebuilt rows resolve to real finite float32 payloads via pure numpy.
    gathered = StreamStore(con, output_root=out).batch_gather("s1", "effnet", [1])
    assert gathered.dtype == np.float32 and bool(np.isfinite(gathered).all())


# ── row/column/status vocabulary retained for C/E consumers ──────────────────


def test_reindex_retains_row_contract_columns_and_statuses(tmp_path, con):
    out = tmp_path / "root"
    _seed_corpus(out)
    reindex(out, con)

    (song_id, backbone, artifact_ref, *_rest) = con.execute(f"SELECT * FROM {STREAM_TABLE}").fetchone()
    assert song_id == "s1" and backbone == "effnet"
    assert artifact_ref.startswith("streams/s1.effnet.")

    (head_ids, dim_by_head, status_col) = con.execute(
        "SELECT head_ids, dim_by_head, status FROM head_stream_registry"
    ).fetchone()
    assert head_ids == "head_logit" and dim_by_head == "head_logit=2"
    assert status_col == "ready"
