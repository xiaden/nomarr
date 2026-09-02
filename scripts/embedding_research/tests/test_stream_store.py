"""StreamStore / HeadStreamStore behaviour tests (Plan B Phase 1, P1-S1/S2/S3).

Exercises read gating (only ``ready`` rows validate), register + app duplicate guard +
transactional replace, reconcile promotion/demotion + orphan detection, and validated
batch gather over tiny float32 fixtures written under a tmp OUTPUT_ROOT (no real audio,
models or ONNX).  All DB tests use an in-memory DuckDB connection.
"""

from __future__ import annotations

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
)
from scripts.embedding_research.streams.store import HeadStreamStore, StreamStore

_SHA = "a" * 64
_TS = 1_700_000_000_000


def _sha256_hex(path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    ensure_schema(c)
    yield c
    c.close()


@pytest.fixture
def out(tmp_path):
    (tmp_path / "patches").mkdir()
    (tmp_path / "heads").mkdir()
    return tmp_path


def _stream_record(**over) -> StreamRecord:
    fields = {
        "song_id": "s1",
        "backbone": "effnet",
        "artifact_ref": "patches/s1.effnet.npy",
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


def _write_stream(out, artifact_ref: str, arr: np.ndarray) -> str:
    path = out / artifact_ref
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(str(path), np.asarray(arr, dtype=np.float32))
    return _sha256_hex(path)


# ── register / duplicate guard / replace ──────────────────────────────────────


def test_register_then_reconcile_promotes_pending_to_ready(con, out):
    arr = np.arange(12, dtype=np.float32).reshape(3, 4)
    sha = _write_stream(out, "patches/s1.effnet.npy", arr)
    store = StreamStore(con, output_root=out)
    store.register(_stream_record(fingerprint_sha256=sha))

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
    sha = _write_stream(out, "patches/s1.effnet.npy", arr)
    store = StreamStore(con, output_root=out)
    store.register(_stream_record(fingerprint_sha256=sha), status="ready")

    # Same logical identity without replacement -> duplicate rejected.
    with pytest.raises(DuplicateStreamError):
        store.register(_stream_record(fingerprint_sha256=sha), status="ready")

    # replace repoints the identity at a newer immutable artifact (patch_count 3 -> 4).
    bigger = np.arange(16, dtype=np.float32).reshape(4, 4)
    sha2 = _write_stream(out, "patches/s1.effnet.npy", bigger)
    replaced = store.replace(_stream_record(fingerprint_sha256=sha2, patch_count=4, status="pending"))
    assert replaced.patch_count == 4
    # Only one row remains for the identity (no duplicate survived replace).
    rows = con.execute("SELECT count(*) FROM stream_registry WHERE song_id='s1' AND backbone='effnet'").fetchone()[0]
    assert rows == 1
    store.reconcile()
    got = store.batch_gather("s1", "effnet", [0, 1, 2, 3])
    assert got.shape == (4, 4)


# ── read gating ───────────────────────────────────────────────────────────────


def test_lookup_and_gather_refuse_non_ready_rows(con, out):
    sha = _write_stream(out, "patches/s1.effnet.npy", np.arange(12, dtype=np.float32).reshape(3, 4))
    store = StreamStore(con, output_root=out)
    store.register(_stream_record(fingerprint_sha256=sha, status="pending"))
    with pytest.raises(StreamNotReadyError):
        store.lookup("s1", "effnet")
    with pytest.raises(StreamNotReadyError):
        store.batch_gather("s1", "effnet", [0])
    with pytest.raises(StreamNotFoundError):
        store.lookup("missing", "effnet")


def test_gather_validation_and_index_guards(con, out):
    arr = np.arange(12, dtype=np.float32).reshape(3, 4)
    sha = _write_stream(out, "patches/s1.effnet.npy", arr)
    store = StreamStore(con, output_root=out)
    store.register(_stream_record(fingerprint_sha256=sha), status="ready")

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


# ── corrupt / missing / orphan reconciliation ─────────────────────────────────


def test_corrupt_artifact_fails_gather_and_reconciles_to_corrupt(con, out):
    good = np.arange(12, dtype=np.float32).reshape(3, 4)
    path = out / "patches/s1.effnet.npy"
    np.save(str(path), good)
    sha = _sha256_hex(path)
    store = StreamStore(con, output_root=out)
    store.register(_stream_record(fingerprint_sha256=sha), status="ready")

    # Corrupt the payload after registration (bytes change -> sha mismatch).
    path.write_bytes(path.read_bytes() + b"\x00")
    with pytest.raises(StreamValidationError):
        store.batch_gather("s1", "effnet", [0])
    report = store.reconcile()
    assert report.corrupt == 1
    assert report.ready == 0
    assert report.clean is False


def test_missing_artifact_reconciles_ready_to_missing(con, out):
    arr = np.arange(12, dtype=np.float32).reshape(3, 4)
    sha = _write_stream(out, "patches/s1.effnet.npy", arr)
    store = StreamStore(con, output_root=out)
    store.register(_stream_record(fingerprint_sha256=sha), status="ready")
    assert store.reconcile().ready == 1

    (out / "patches/s1.effnet.npy").unlink()
    with pytest.raises(StreamValidationError):
        store.batch_gather("s1", "effnet", [0])
    report = store.reconcile()
    assert report.missing == 1
    assert report.stale == 1  # a previously-ready row degraded
    assert report.clean is False


def test_orphan_final_file_is_reported(con, out):
    # A valid stream plus an unreferenced final sidecar under the scan root.
    sha = _write_stream(out, "patches/s1.effnet.npy", np.arange(12, dtype=np.float32).reshape(3, 4))
    _write_stream(out, "patches/orphan.effnet.npy", np.arange(4, dtype=np.float32).reshape(1, 4))
    store = StreamStore(con, output_root=out)
    store.register(_stream_record(fingerprint_sha256=sha), status="ready")
    report = store.reconcile()
    assert report.orphan == 1
    assert report.clean is False


# ── head store ────────────────────────────────────────────────────────────────


def _write_head(out, artifact_ref: str, patch_count: int = 3) -> str:
    path = out / artifact_ref
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        str(path),
        gender=np.arange(patch_count * 2, dtype=np.float32).reshape(patch_count, 2),
        timbre=np.ones((patch_count, 2), dtype=np.float32),
    )
    return _sha256_hex(path)


def _head_record(artifact_ref="heads/s1.effnet.npz", status="pending", patch_count=3, **over):
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
    sha = _write_head(out, "heads/s1.effnet.npz", patch_count=3)
    store = HeadStreamStore(con, output_root=out)
    store.register(_head_record(fingerprint_sha256=sha), status="ready")
    # Not-ready refused before it is ready? It IS ready here; also verify pending refused separately.
    got = store.batch_gather("s1", "effnet", [0, 2])
    assert got.shape == (2, 4)  # N=2 requested, total_dim = gender(2)+timbre(2)
    assert got.dtype == np.float32
    report = store.reconcile()
    assert report.ready == 1
    assert report.clean is True


def test_head_store_refuses_non_ready(con, out):
    sha = _write_head(out, "heads/s1.effnet.npz")
    store = HeadStreamStore(con, output_root=out)
    store.register(_head_record(fingerprint_sha256=sha), status="pending")
    with pytest.raises(StreamNotReadyError):
        store.batch_gather("s1", "effnet", [0])


def test_head_store_rejects_duplicate_identity(con, out):
    sha = _write_head(out, "heads/s1.effnet.npz")
    store = HeadStreamStore(con, output_root=out)
    store.register(_head_record(fingerprint_sha256=sha), status="ready")
    with pytest.raises(DuplicateStreamError):
        store.register(_head_record(fingerprint_sha256=sha), status="ready")


def test_head_store_rejects_layout_mismatch_at_gather(con, out):
    # Head record claims patch_count=3 but the npz holds only 2 temporal rows.
    sha = _write_head(out, "heads/s1.effnet.npz", patch_count=2)
    store = HeadStreamStore(con, output_root=out)
    store.register(_head_record(patch_count=3, fingerprint_sha256=sha), status="ready")
    with pytest.raises(StreamValidationError):
        store.batch_gather("s1", "effnet", [0, 1])
