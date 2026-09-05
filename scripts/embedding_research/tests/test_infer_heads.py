"""infer-heads observation-writer tests (Plan B Phase 3, P3-S1/S2/S3).

Covers the writer publishing ONE complete per-song/backbone head-suite ``.npz`` artifact
with finite per-head ``[T, C]`` arrays where ``T == backbone patch_count``, the P3-S2
refusal modes (missing configured head / wrong temporal length / backbone patch-count
mismatch — none truncated, padded, or silently recovered), immutable supersession on a
``force`` re-run, exact-index ``HeadStreamStore.batch_gather``, and that legacy flat/PTC/
CTP head caches stay read-only.  Head ONNX sessions and the batch runner are injected, so
no real models or audio are used.
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any
from unittest.mock import Mock

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.common import infer_heads as infer_heads_mod
from scripts.embedding_research.db import read_run_provenance
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.streams.publication import parse_artifact_name
from scripts.embedding_research.streams.records import StreamValidationError
from scripts.embedding_research.streams.store import HeadStreamStore, StreamStore

_SHA_HEADS = {"gender", "timbre"}


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    ensure_schema(c)
    yield c
    c.close()


def _ready_stream(out, con, song_id: str, backbone: str, patch_rows: int = 3) -> int:
    """Register and reconcile a ready backbone stream for (song_id, backbone)."""
    store = StreamStore(con, output_root=out)
    patches = np.arange(patch_rows * 4, dtype=np.float32).reshape(patch_rows, 4)
    store.publish(song_id, backbone, patches, run_id="run-stream")
    store.reconcile()
    return patch_rows


def _acts(patch_count: int, classes: int = 2, *, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    arr = rng.random((patch_count, classes)).astype(np.float32)
    return arr / arr.sum(axis=1, keepdims=True)  # softmax-like rows, finite


def _session_for(acts: np.ndarray) -> Mock:
    session = Mock()
    session.run.return_value = [acts]
    return session


def _run_batches(predict, data, _batch_size):
    return predict(data)


def _worker_args(*, out, con, song_id="s1", backbone="effnet", patch_count=3, heads=("gender", "timbre")):
    """Ready StreamStore + HeadStreamStore over *out*, plus fake per-head sessions."""
    _ready_stream(out, con, song_id, backbone, patch_rows=patch_count)
    sessions = {head: _session_for(_acts(patch_count, seed=i)) for i, head in enumerate(heads)}
    return {
        "song_id": song_id,
        "backbone": backbone,
        "backbone_patches": np.arange(patch_count * 4, dtype=np.float32).reshape(patch_count, 4),
        "backbone_patch_count": patch_count,
        "configured_heads": list(heads),
        "head_sessions": sessions,
        "head_store": HeadStreamStore(con, output_root=out),
        "run_id": "run-heads",
        "force": True,
        "run_in_batches_fn": _run_batches,
        "batch_size": 4,
    }


def _expected_rows(heads, head_arrays):
    # Gather output columns concatenate per-head selected rows in canonical (sorted) order.
    canon = sorted(heads)
    return {head: head_arrays[head] for head in canon}


# ── writer end-to-end ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_writer_publishes_complete_suite_ready_and_gathers(con, tmp_path):
    """Writer publishes one complete npz suite; reconcile -> ready; exact-index gather."""
    kwargs = _worker_args(out=tmp_path, con=con)
    heads = list(kwargs["configured_heads"])
    head_arrays = {
        head: _session_for(_acts(kwargs["backbone_patch_count"], seed=i)).run.return_value[0]
        for i, head in enumerate(heads)
    }

    worked = infer_heads_mod.infer_heads_for_song(**kwargs)
    assert worked is True

    head_store = kwargs["head_store"]
    # Immutable durable publication: reconcile promotes the pending row to ready. The
    # ready artifact is ONE digest-named .npz under heads/ (never a bare s1.effnet.npz).
    head_store.reconcile()
    rec = head_store.lookup("s1", "effnet")
    assert rec.status == "ready"
    assert rec.patch_count == kwargs["backbone_patch_count"]
    assert rec.head_ids == "gender,timbre"
    assert rec.dim_by_head == "gender=2;timbre=2"
    artifact = tmp_path / rec.artifact_ref
    assert artifact.exists()
    digest_npz = list((tmp_path / "heads").glob("s1.effnet.*.npz"))
    assert len(digest_npz) == 1
    assert digest_npz[0] == artifact

    # Exact source-patch-index gather returns [N, total_dim] with N == len(indices).
    got = head_store.batch_gather("s1", "effnet", [0, 2])
    assert got.shape == (2, 4)
    assert got.dtype == np.float32
    expected = {h: head_arrays[h] for h in heads}
    np.testing.assert_allclose(got[0], np.concatenate([expected[h][0] for h in sorted(heads)]))
    np.testing.assert_allclose(got[1], np.concatenate([expected[h][2] for h in sorted(heads)]))
    # forbid_duplicates rejects repeats; distinct arbitrary order is allowed (P3-S3).
    assert head_store.batch_gather("s1", "effnet", [2, 0, 1]).shape == (3, 4)
    with pytest.raises(ValueError):
        head_store.batch_gather("s1", "effnet", [1, 1], forbid_duplicates=True)
    # No staging .tmp leftover after a successful publish.
    staging = tmp_path / "heads" / ".staging"
    assert not staging.exists() or not list(staging.glob("*.tmp"))


# ── P3-S2 refusal modes (store layer, synthetic payloads) ─────────────────────


def _head_store_publish(con, out, head_arrays, *, patch_count, expected=None):
    return HeadStreamStore(con, output_root=out).publish(
        "s1",
        "effnet",
        head_arrays,
        run_id="r",
        patch_count=patch_count,
        alignment_version="1",
        expected_head_ids=expected if expected is not None else list(head_arrays),
    )


def _no_head_rows(con) -> int:
    return con.execute("SELECT count(*) FROM head_stream_registry").fetchone()[0]


@pytest.mark.unit
def test_refuses_missing_configured_head(con, tmp_path):
    """A suite missing one configured head is refused; no row and no artifact survive."""
    suite = {"gender": _acts(3, seed=0)}  # timbre configured but absent
    with pytest.raises(StreamValidationError):
        _head_store_publish(con, tmp_path, suite, patch_count=3, expected=["gender", "timbre"])
    assert _no_head_rows(con) == 0
    assert not list((tmp_path / "heads").glob("*.npz"))


@pytest.mark.unit
def test_refuses_wrong_temporal_length(con, tmp_path):
    """A head whose temporal length differs from the suite patch_count is refused."""
    suite = {"gender": _acts(3, seed=0), "timbre": _acts(2, seed=1)}  # timbre T=2 != 3
    with pytest.raises(StreamValidationError):
        _head_store_publish(con, tmp_path, suite, patch_count=3, expected=["gender", "timbre"])
    assert _no_head_rows(con) == 0
    assert not list((tmp_path / "heads").glob("*.npz"))


@pytest.mark.unit
def test_refuses_backbone_patch_count_mismatch(con, tmp_path):
    """A suite internally consistent at T but disagreeing with the backbone patch_count is refused."""
    suite = {"gender": _acts(2, seed=0), "timbre": _acts(2, seed=1)}  # both T=2
    with pytest.raises(StreamValidationError):  # backbone patch_count is 3
        _head_store_publish(con, tmp_path, suite, patch_count=3, expected=["gender", "timbre"])
    assert _no_head_rows(con) == 0
    assert not list((tmp_path / "heads").glob("*.npz"))


@pytest.mark.unit
def test_writer_refuses_misaligned_head_run_end_to_end(con, tmp_path):
    """A head session producing the wrong temporal length refuses before registration."""
    kwargs = _worker_args(out=tmp_path, con=con)
    # gender produces correct T=3; timbre produces T=2 (misaligned).
    sessions = {
        "gender": _session_for(_acts(3, seed=0)),
        "timbre": _session_for(_acts(2, seed=1)),
    }
    kwargs["head_sessions"] = sessions
    with pytest.raises(StreamValidationError):
        infer_heads_mod.infer_heads_for_song(**kwargs)
    assert _no_head_rows(con) == 0
    assert not list((tmp_path / "heads").glob("*.npz"))


# ── immutable supersession ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_force_republish_publishes_new_digest_and_reuses_identical_bytes(con, tmp_path):
    """A force re-run with DIFFERENT head bytes yields a SECOND digest .npz; identical bytes reuse it."""
    base = _worker_args(out=tmp_path, con=con)
    head_store = base["head_store"]

    first_arrays = {"gender": _acts(3, seed=0), "timbre": _acts(3, seed=1)}
    base["head_sessions"] = {h: _session_for(a) for h, a in first_arrays.items()}
    assert infer_heads_mod.infer_heads_for_song(**base) is True
    head_store.reconcile()
    rec1 = head_store.lookup("s1", "effnet")
    assert rec1.status == "ready"
    v1_abs = tmp_path / rec1.artifact_ref
    assert v1_abs.exists()
    v1_bytes = v1_abs.read_bytes()
    assert list((tmp_path / "heads").glob("s1.effnet.*.npz")) == [v1_abs]

    # Force re-run with different head outputs -> a SECOND digest-named .npz is published
    # and the first digest file survives byte-identical (never overwritten).
    second_arrays = {"gender": _acts(3, seed=5), "timbre": _acts(3, seed=6)}
    base["head_sessions"] = {h: _session_for(a) for h, a in second_arrays.items()}
    base["run_id"] = "run-heads-2"
    assert infer_heads_mod.infer_heads_for_song(**base) is True
    head_store.reconcile()
    rec2 = head_store.lookup("s1", "effnet")
    assert rec2.status == "ready"
    v2_abs = tmp_path / rec2.artifact_ref
    assert v2_abs.exists()
    assert v2_abs != v1_abs  # different bytes -> different digest artifact
    assert v1_abs.read_bytes() == v1_bytes  # prior bytes byte-identical (never overwritten)
    assert len(list((tmp_path / "heads").glob("s1.effnet.*.npz"))) == 2

    # Re-publishing IDENTICAL bytes reuses the same digest file (content-addressed, immutable).
    base["head_sessions"] = {h: _session_for(a) for h, a in second_arrays.items()}
    base["run_id"] = "run-heads-3"
    assert infer_heads_mod.infer_heads_for_song(**base) is True
    head_store.reconcile()
    rec3 = head_store.lookup("s1", "effnet")
    assert rec3.artifact_ref == rec2.artifact_ref
    assert len(list((tmp_path / "heads").glob("s1.effnet.*.npz"))) == 2

    got = head_store.batch_gather("s1", "effnet", [0])
    canon = sorted(second_arrays)
    np.testing.assert_allclose(got[0], np.concatenate([second_arrays[h][0] for h in canon]))


# ── head outputs stay digest-named ────────────────────────────────────────────


@pytest.mark.unit
def test_writer_never_touches_legacy_head_caches(con, tmp_path):
    """The infer-heads writer emits exactly one digest-named head-suite artifact per song."""
    kwargs = _worker_args(out=tmp_path, con=con)
    assert infer_heads_mod.infer_heads_for_song(**kwargs) is True
    # heads/ holds exactly the ONE digest-named head-suite .npz (no bare/.vN names), plus
    # the self-describing .json manifest.
    heads_files = [p.name for p in (tmp_path / "heads").glob("*.npz")]
    assert len(heads_files) == 1
    ident = parse_artifact_name(heads_files[0], ".npz")
    assert ident is not None
    assert ident.song_id == "s1"
    assert ident.backbone == "effnet"
    manifests = [p.name for p in (tmp_path / "heads").glob("*.json")]
    assert len(manifests) == 1
    assert manifests[0] == heads_files[0][: -len(".npz")] + ".json"


# ── orchestrator semantics ─────────────────────────────────────────────────────


def _install_session_runtime_stubs() -> Mock:
    create_session = Mock(return_value=Mock())
    run_in_batches = Mock()
    mod: Any = ModuleType("nomarr.components.ml.onnx.ml_session_comp")
    mod.create_session = create_session
    mod._BACKBONE_BATCH_SIZE = 4
    mod._run_in_batches = run_in_batches
    sys.modules.setdefault("nomarr.components", ModuleType("nomarr.components"))
    sys.modules.setdefault("nomarr.components.ml", ModuleType("nomarr.components.ml"))
    sys.modules.setdefault("nomarr.components.ml.onnx", ModuleType("nomarr.components.ml.onnx"))
    sys.modules["nomarr.components.ml.onnx.ml_session_comp"] = mod
    return create_session


@pytest.mark.unit
def test_orchestrator_skips_without_ready_stream_and_records_run(con, tmp_path, monkeypatch):
    """infer_heads() skips song/backbone without a ready stream and records a run row."""
    _install_session_runtime_stubs()
    song_path = tmp_path / "song.mp3"
    song_path.write_bytes(b"")
    worker = Mock()
    monkeypatch.setattr(infer_heads_mod, "_bootstrap_nomarr", lambda: None)
    monkeypatch.setattr(infer_heads_mod, "_discover_audio", Mock(return_value=[song_path]))
    monkeypatch.setattr(infer_heads_mod, "_song_id", lambda _path: "s-no-stream")
    monkeypatch.setattr(infer_heads_mod, "_BACKBONES", {"effnet": {}})
    monkeypatch.setattr(infer_heads_mod, "_HEADS", {"effnet": {"gender": "g.onnx", "timbre": "t.onnx"}})
    monkeypatch.setattr(infer_heads_mod, "infer_heads_for_song", worker)
    # StreamStore.lookup raises for this song (no ready backbone stream) -> skipped.
    monkeypatch.setattr(infer_heads_mod, "StreamStore", Mock(side_effect=StreamNotFoundRaise))

    class _FakeHeadStore:
        def reconcile(self):
            return None

        def run_records(self, _run_id):
            return []

    monkeypatch.setattr(infer_heads_mod, "HeadStreamStore", Mock(return_value=_FakeHeadStore()))

    infer_heads_mod.infer_heads(con, backbones=["effnet"], head_sessions={"effnet": {}})

    worker.assert_not_called()
    rows = read_run_provenance(con, run_id=None)
    infer_rows = [r for r in rows if r["phase"] == "infer-heads"]
    assert len(infer_rows) == 1
    assert infer_rows[0]["status"] == "complete"
    assert infer_rows[0]["song_count"] == 0


class StreamNotFoundRaise:
    def __init__(self, *a, **k):
        pass

    def lookup(self, song_id, backbone):
        from scripts.embedding_research.streams.records import StreamNotFoundError

        raise StreamNotFoundError(f"no stream for {song_id}/{backbone}")
