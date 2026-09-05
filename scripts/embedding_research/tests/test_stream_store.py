"""StreamStore / HeadStreamStore behaviour tests (Plan B P1-S1/S2).

Exercises read gating (only ``ready`` rows validate), register + app duplicate guard +
transactional replace, reconcile promotion/demotion over digest-named payload + manifest
pairs, filesystem-authoritative manifest validation, and validated batch gather over tiny
float32 fixtures written under a tmp OUTPUT_ROOT (no real audio, models or ONNX).  All DB
tests use an in-memory DuckDB connection.

Post-migration (P1-S2) these fixtures publish/hand-register artifacts under the digest
grammar ``<subdir>/<sid>.<backbone>.<64-hex>.npy|.npz`` plus a self-describing ``.json``
manifest sibling — never bare or ``.vN`` names.  Rowless-orphan classification
(superseded/legacy/stray) is not a reconcile concern here (Phase 5 reindex owns it).
"""

from __future__ import annotations

import hashlib
import io
import json

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.streams.records import (
    DuplicateStreamError,
    HeadStreamRecord,
    StreamNotFoundError,
    StreamNotReadyError,
    StreamRecord,
    StreamValidationError,
    payload_to_manifest_ref,
)
from scripts.embedding_research.streams.store import HeadStreamStore, StreamStore

_SHA = "a" * 64
_TS = 1_700_000_000_000


def _sha256_hex_bytes(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest_ref(subdir: str, song_id: str, backbone: str, sha: str, suffix: str) -> str:
    return f"{subdir}/{song_id}.{backbone}.{sha}{suffix}"


def _write_manifest(out, artifact_ref: str, sha: str, *, kind: str, patch_count: int) -> None:
    """Write the self-describing manifest sibling for a hand-registered fixture artifact."""
    mpath = out / payload_to_manifest_ref(artifact_ref)
    mpath.parent.mkdir(parents=True, exist_ok=True)
    song_id, backbone = artifact_ref.split("/")[1].split(".")[:2]
    data = {
        "kind": kind,
        "schema_version": "1",
        "payload_sha256": sha,
        "song_id": song_id,
        "backbone": backbone,
        "patch_count": patch_count,
    }
    mpath.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    ensure_schema(c)
    yield c
    c.close()


@pytest.fixture
def out(tmp_path):
    return tmp_path


def _write_stream(out, song_id: str, backbone: str, arr: np.ndarray) -> tuple[str, str]:
    """Write a float32 stream payload + manifest at a digest name; return (sha, artifact_ref)."""
    arr = np.asarray(arr, dtype=np.float32)
    payload = np.ascontiguousarray(arr)
    buffer = io.BytesIO()
    np.save(buffer, payload)
    sha = hashlib.sha256(buffer.getvalue()).hexdigest()
    artifact_ref = _digest_ref("streams", song_id, backbone, sha, ".npy")
    path = out / artifact_ref
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(str(path), payload)
    _write_manifest(out, artifact_ref, sha, kind="stream", patch_count=arr.shape[0])
    return sha, artifact_ref


def _stream_record(**over) -> StreamRecord:
    fields = {
        "song_id": "s1",
        "backbone": "effnet",
        "artifact_ref": "streams/s1.effnet" + "." + "a" * 64 + ".npy",
        "patch_count": 3,
        "dim": 4,
        "dtype": "float32",
        "format_version": "1",
        "fingerprint_sha256": _SHA,
        "preprocess_fn": "standardize",
        "preprocess_version": "1.0",
        "backbone_model_hash": "bbhash",
        "audio_params": "44.1k/mono",
        "embed_semantics_version": 1,
        "provenance_source": "embed",
        "provenance_assumption": "",
        "status": "pending",
        "run_id": "run-1",
        "created_at": _TS,
        "updated_at": _TS,
    }
    fields.update(over)
    return StreamRecord(**fields)


def _registered_stream(out, store, arr, *, status="pending"):
    sha, artifact_ref = _write_stream(out, "s1", "effnet", arr)
    return store.register(_stream_record(artifact_ref=artifact_ref, fingerprint_sha256=sha), status=status)


# ── register / duplicate guard / replace ──────────────────────────────────────


def test_register_then_reconcile_promotes_pending_to_ready(con, out):
    arr = np.arange(12, dtype=np.float32).reshape(3, 4)
    store = StreamStore(con, output_root=out)
    _registered_stream(out, store, arr)  # pending by default

    # Not yet ready -> reads refuse.
    with pytest.raises(StreamNotReadyError):
        store.lookup("s1", "effnet")

    report = store.reconcile()
    assert report.scanned == 1
    assert report.ready == 1
    assert report.clean is True
    rec = store.lookup("s1", "effnet")
    assert rec.status == "ready"
    got = store.batch_gather("s1", "effnet", [0, 2])
    assert got.shape == (2, 4)
    assert got.dtype == np.float32
    np.testing.assert_allclose(got, arr[[0, 2]])


def test_duplicate_register_is_rejected_and_replace_repoints(con, out):
    arr = np.arange(12, dtype=np.float32).reshape(3, 4)
    store = StreamStore(con, output_root=out)
    _registered_stream(out, store, arr, status="ready")

    # Same logical identity without replacement -> duplicate rejected.
    with pytest.raises(DuplicateStreamError):
        _registered_stream(out, store, arr, status="ready")

    # replace repoints the identity at a newer immutable artifact (patch_count 3 -> 4).
    bigger = np.arange(16, dtype=np.float32).reshape(4, 4)
    sha2, artifact_ref2 = _write_stream(out, "s1", "effnet", bigger)
    replaced = store.replace(
        _stream_record(artifact_ref=artifact_ref2, fingerprint_sha256=sha2, patch_count=4, status="pending")
    )
    assert replaced.patch_count == 4
    # Only one row remains for the identity (no duplicate survived replace).
    rows = con.execute("SELECT count(*) FROM stream_registry WHERE song_id='s1' AND backbone='effnet'").fetchone()[0]
    assert rows == 1
    store.reconcile()
    got = store.batch_gather("s1", "effnet", [0, 1, 2, 3])
    assert got.shape == (4, 4)


# ── read gating ───────────────────────────────────────────────────────────────


def test_lookup_and_gather_refuse_non_ready_rows(con, out):
    arr = np.arange(12, dtype=np.float32).reshape(3, 4)
    store = StreamStore(con, output_root=out)
    _registered_stream(out, store, arr, status="pending")
    with pytest.raises(StreamNotReadyError):
        store.lookup("s1", "effnet")
    with pytest.raises(StreamNotReadyError):
        store.batch_gather("s1", "effnet", [0])
    with pytest.raises(StreamNotFoundError):
        store.lookup("missing", "effnet")


def test_gather_validation_and_index_guards(con, out):
    arr = np.arange(12, dtype=np.float32).reshape(3, 4)
    store = StreamStore(con, output_root=out)
    _registered_stream(out, store, arr, status="ready")

    # Duplicate index is a legal row selection; empty selection yields [0, D].
    np.testing.assert_allclose(store.batch_gather("s1", "effnet", [0, 0]), arr[[0, 0]])
    assert store.batch_gather("s1", "effnet", []).shape == (0, 4)

    with pytest.raises(ValueError):
        store.batch_gather("s1", "effnet", [3])  # out of range
    with pytest.raises(ValueError):
        store.batch_gather("s1", "effnet", [-1])
    with pytest.raises(ValueError):
        store.batch_gather("s1", "effnet", [0, 3])
    with pytest.raises(ValueError):
        store.batch_gather("s1", "effnet", ["0"])  # non-integer
    with pytest.raises(ValueError):
        store.batch_gather("s1", "effnet", 0)  # not 1-D


# ── corrupt / missing / manifest reconciliation (filesystem is authority) ─────


def test_corrupt_artifact_fails_gather_and_reconciles_to_corrupt(con, out):
    good = np.arange(12, dtype=np.float32).reshape(3, 4)
    sha, artifact_ref = _write_stream(out, "s1", "effnet", good)
    store = StreamStore(con, output_root=out)
    store.register(_stream_record(artifact_ref=artifact_ref, fingerprint_sha256=sha), status="ready")

    # Corrupt the payload after registration (bytes change -> sha mismatch).
    path = out / artifact_ref
    path.write_bytes(path.read_bytes() + b"\x00")
    with pytest.raises(StreamValidationError):
        store.batch_gather("s1", "effnet", [0])
    report = store.reconcile()
    assert report.corrupt == 1
    assert report.ready == 0
    assert report.clean is False


def test_missing_artifact_reconciles_ready_to_missing(con, out):
    arr = np.arange(12, dtype=np.float32).reshape(3, 4)
    store = StreamStore(con, output_root=out)
    _registered_stream(out, store, arr, status="ready")
    assert store.reconcile().ready == 1

    _sha, artifact_ref = _write_stream(out, "s1", "effnet", arr)  # same digest -> same file
    (out / artifact_ref).unlink()
    with pytest.raises(StreamValidationError):
        store.batch_gather("s1", "effnet", [0])
    report = store.reconcile()
    assert report.missing == 1
    assert report.stale == 1  # a previously-ready row degraded
    assert report.clean is False


def test_ready_row_without_manifest_reconciles_to_corrupt(con, out):
    # Filesystem is authoritative: a ready CLAIM with a valid payload but NO self-describing
    # manifest must not stay ready (reconcile refuses; a manifest is part of the committed
    # artifact).  Rowless-orphan scanning is not a Phase-2 reconcile concern.
    arr = np.arange(12, dtype=np.float32).reshape(3, 4)
    payload = np.ascontiguousarray(arr, dtype=np.float32)
    buffer = io.BytesIO()
    np.save(buffer, payload)
    sha = hashlib.sha256(buffer.getvalue()).hexdigest()
    artifact_ref = _digest_ref("streams", "s1", "effnet", sha, ".npy")
    path = out / artifact_ref
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(str(path), payload)
    # deliberately NO manifest written
    store = StreamStore(con, output_root=out)
    store.register(_stream_record(artifact_ref=artifact_ref, fingerprint_sha256=sha), status="ready")
    report = store.reconcile()
    assert report.corrupt == 1
    assert report.ready == 0
    assert report.clean is False


# ── head store ────────────────────────────────────────────────────────────────


def _write_head(out, patch_count: int = 3) -> tuple[str, str]:
    """Write a float32 .npz head suite + manifest at a digest name; return (sha, artifact_ref)."""
    buf = io.BytesIO()
    np.savez(
        buf,
        gender=np.arange(patch_count * 2, dtype=np.float32).reshape(patch_count, 2),
        timbre=np.ones((patch_count, 2), dtype=np.float32),
    )
    sha = hashlib.sha256(buf.getvalue()).hexdigest()
    artifact_ref = _digest_ref("heads", "s1", "effnet", sha, ".npz")
    path = out / artifact_ref
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        str(path),
        gender=np.arange(patch_count * 2, dtype=np.float32).reshape(patch_count, 2),
        timbre=np.ones((patch_count, 2), dtype=np.float32),
    )
    _write_manifest(out, artifact_ref, sha, kind="head", patch_count=patch_count)
    return sha, artifact_ref


def _head_record(artifact_ref="heads/s1.effnet" + "." + "a" * 64 + ".npz", status="pending", patch_count=3, **over):
    fields = {
        "song_id": "s1",
        "backbone": "effnet",
        "artifact_ref": artifact_ref,
        "patch_count": patch_count,
        "head_ids": "gender,timbre",
        "dim_by_head": "gender=2;timbre=2",
        "format_version": "1",
        "fingerprint_sha256": _SHA,
        "preprocess_fn": "standardize",
        "preprocess_version": "1.0",
        "backbone_model_hash": "bbhash",
        "alignment_version": "v1",
        "status": status,
        "run_id": "run-1",
        "created_at": _TS,
        "updated_at": _TS,
    }
    fields.update(over)
    return HeadStreamRecord(**fields)


def test_head_store_gather_returns_patch_aligned_rows(con, out):
    sha, artifact_ref = _write_head(out, patch_count=3)
    store = HeadStreamStore(con, output_root=out)
    store.register(_head_record(artifact_ref=artifact_ref, fingerprint_sha256=sha), status="ready")
    got = store.batch_gather("s1", "effnet", [0, 2])
    assert got.shape == (2, 4)  # N=2 requested, total_dim = gender(2)+timbre(2)
    assert got.dtype == np.float32
    report = store.reconcile()
    assert report.ready == 1
    assert report.clean is True


def test_head_store_refuses_non_ready(con, out):
    sha, artifact_ref = _write_head(out)
    store = HeadStreamStore(con, output_root=out)
    store.register(_head_record(artifact_ref=artifact_ref, fingerprint_sha256=sha), status="pending")
    with pytest.raises(StreamNotReadyError):
        store.batch_gather("s1", "effnet", [0])


def test_head_store_rejects_duplicate_identity(con, out):
    sha, artifact_ref = _write_head(out)
    store = HeadStreamStore(con, output_root=out)
    store.register(_head_record(artifact_ref=artifact_ref, fingerprint_sha256=sha), status="ready")
    with pytest.raises(DuplicateStreamError):
        store.register(_head_record(artifact_ref=artifact_ref, fingerprint_sha256=sha), status="ready")


def test_head_store_rejects_layout_mismatch_at_gather(con, out):
    # Head record claims patch_count=3 but the npz holds only 2 temporal rows.
    sha, artifact_ref = _write_head(out, patch_count=2)
    store = HeadStreamStore(con, output_root=out)
    store.register(_head_record(artifact_ref=artifact_ref, patch_count=3, fingerprint_sha256=sha), status="ready")
    with pytest.raises(StreamValidationError):
        store.batch_gather("s1", "effnet", [0, 1])


def test_publish_refuses_non_finite_embeddings(con, out):
    """A frozen stream carrying NaN/Infinity is rejected at publish, before any durable write.

    Mirrors the ledger no-NaN/Infinity + digest-publication invariant: a backbone stream
    with a non-finite row must raise ``ValueError`` and leave NO digest artifact, manifest,
    or registry row behind (nothing half-published).  Head-side non-finite rejection is
    pinned separately in ``test_head_suite_spec.py``.
    """
    store = StreamStore(con, output_root=out)
    for bad in (
        np.array([[1.0, np.nan]], dtype=np.float32),
        np.array([[1.0, np.inf]], dtype=np.float32),
        np.array([[-np.inf, 1.0], [1.0, 2.0]], dtype=np.float32),
    ):
        with pytest.raises(ValueError, match="non-finite"):
            store.publish("s1", "effnet", bad, run_id="run-nonfinite")
    # Nothing was durably written or registered for any rejected payload.
    assert not list(out.rglob("*.npy"))
    assert not list(out.rglob("*.json"))
    assert con.execute("SELECT count(*) FROM stream_registry").fetchone()[0] == 0
