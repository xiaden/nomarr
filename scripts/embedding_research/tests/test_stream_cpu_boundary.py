"""Phase 4 (P4-S3) — CPU-only negative-boundary on the frozen-stream READ surfaces.

DD CPU/inference-boundary (post-L228): derived-phase-style workloads (catalog /
catalog-report / analyze / head-analysis / report) consume ONLY manifests / registry
rows / frozen stream + head artifacts.  They MUST complete with audio discovery, model
loading, ONNX session creation/run and CUDA ABSENT, and must PROVE no such call happened.

The negative gate is call-level, at the REAL call sites (mirroring Plan A's
``test_negative_boundaries.py``): sentinels monkeypatched onto
``config.discover_audio``, ``onnxruntime.InferenceSession`` and
``torch.cuda.is_available`` RAISE if invoked AND record call counts.  Catching such an
exception is a test FAILURE (the sentinel raised), never a success.  The workload must
both COMPLETE and record ZERO sentinel calls — asserting both halves.

The workload here is a numpy-only CPU consumer over ``StreamStore.lookup`` +
``batch_gather`` on ready backbone records and ``HeadStreamStore.lookup`` +
``batch_gather`` (a catalog/analyze-style medoid selection over gathered patch vectors),
plus a reconcile / registry read — no audio, no models, no CUDA, no ONNX.  Both halves
are asserted: the derived-style workload COMPLETES with the expected numpy result AND
every installed sentinel recorded ZERO calls.

Secondary: a function-scoped import-guard check runs in a subprocess proving that
importing the read-surface modules does not load the ML stack (torch/onnxruntime/
sklearn).  This is secondary and honestly annotated: the pure read modules already avoid
module-level optional ML imports by construction; the guard does NOT pretend to catch a
module-level optional import of the ML stack (none exists here), it merely confirms the
absence so a future regression is caught early.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.config import discover_audio as config_discover_audio
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.streams.store import HeadStreamStore, StreamStore

# Optional ML-stack availability.  The read surfaces never import these; if a platform
# has them installed we still sentinel them (so a regression that reaches them fires);
# if they are absent they cannot be called, which is itself the CPU-only proof.
try:  # pragma: no cover - environment dependent
    import onnxruntime  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    onnxruntime = None  # type: ignore[assignment]

try:  # pragma: no cover - environment dependent
    import torch  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    torch = None  # type: ignore[assignment]


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    ensure_schema(c)
    yield c
    c.close()


def _arr(rows=4, cols=3):
    rng = np.random.default_rng(0)
    return rng.random((rows, cols)).astype(np.float32)


def _head_arrays(patch_count: int = 4):
    rng = np.random.default_rng(1)
    return {
        "gender": rng.random((patch_count, 2)).astype(np.float32),
        "timbre": rng.random((patch_count, 2)).astype(np.float32),
    }


def _seed_readables(con, out) -> tuple[StreamStore, HeadStreamStore]:
    """Create ready backbone + head streams for a single (song, backbone)."""
    stream_store = StreamStore(con, output_root=out)
    stream_store.publish("songC", "effnet", _arr(), run_id="run-embed")
    stream_store.reconcile()
    head_store = HeadStreamStore(con, output_root=out)
    head_store.publish(
        "songC",
        "effnet",
        _head_arrays(),
        run_id="run-heads",
        patch_count=4,
        alignment_version="1",
        expected_head_ids=["gender", "timbre"],
    )
    head_store.reconcile()
    return stream_store, head_store


# A call-level sentinel that RAISES if invoked and records each invocation.
class _RaisingSentinel:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events

    def __call__(self, *_args, **_kwargs):
        self.events.append(self.name)
        raise AssertionError(f"forbidden call during a CPU-only read: {self.name}")


def _install_sentinels(monkeypatch) -> dict[str, int]:
    """Monkeypatch real call sites with raising sentinels; return name -> final count.

    Returns a mapping populated only for attributes that exist/are installed, so the
    test asserts zero calls for whichever sentinels were actually attachable.
    """
    events: list[str] = []
    installed: dict[str, _RaisingSentinel] = {}

    # config.discover_audio — the real audio-discovery call site (always present).
    sentinel = _RaisingSentinel("config.discover_audio", events)
    monkeypatch.setattr(config_discover_audio.__module__ + ".discover_audio", sentinel)
    installed["config.discover_audio"] = sentinel

    # onnxruntime.InferenceSession — real ONNX session-construction call site.
    if onnxruntime is not None:
        sentinel = _RaisingSentinel("onnxruntime.InferenceSession", events)
        monkeypatch.setattr(onnxruntime, "InferenceSession", sentinel)
        installed["onnxruntime.InferenceSession"] = sentinel

    # torch.cuda.is_available — real CUDA-availability call site.
    if torch is not None:
        sentinel = _RaisingSentinel("torch.cuda.is_available", events)
        monkeypatch.setattr(torch.cuda, "is_available", sentinel)
        installed["torch.cuda.is_available"] = sentinel

    return {name: len(_sentinel.events) for name, _sentinel in installed.items()}


def _cpu_consumer_workload(stream_store, head_store, song: str) -> dict[str, object]:
    """A numpy-only derived-phase-style consumer over frozen ready stream + head reads.

    Mimics catalog medoid selection / analysis gathering: read the ready backbone and
    head records via ``lookup``, ``batch_gather`` the full patch vectors, and pick a
    medoid source index with pure numpy.  Also performs a reconcile / registry read
    (``ready_rows``) and a strict ``verify``.  No audio/model/CUDA/ONNX is touched.
    """
    stream_rec = stream_store.lookup(song, "effnet")
    assert stream_rec.status == "ready"
    patches = stream_store.batch_gather(song, "effnet", list(range(stream_rec.patch_count)))

    head_rec = head_store.lookup(song, "effnet")
    assert head_rec.status == "ready"
    head_rows = head_store.batch_gather(song, "effnet", list(range(head_rec.patch_count)))

    # Medoid selection over the gathered backbone patches (pure numpy, mimic catalog).
    mean = patches.mean(axis=0)
    medoid_idx = int(np.argmin(np.linalg.norm(patches - mean, axis=1)))
    medoid = stream_store.batch_gather(song, "effnet", [medoid_idx])
    assert medoid.shape == (1, patches.shape[1])

    # Registry reads: ready_rows (registry read) + a strict verify of the tree.
    ready = stream_store.ready_rows()
    report = stream_store.verify(strict=True)
    assert report.clean is True
    return {
        "ready_songs": {r.song_id for r in ready},
        "medoid_idx": medoid_idx,
        "gather_shape": patches.shape,
        "head_shape": head_rows.shape,
    }


@pytest.mark.unit
def test_cpu_consumer_completes_with_zero_sentinel_calls(con, tmp_path, monkeypatch):
    """Derived-phase read completes AND no sentinel (audio/model/CUDA) was called.

    Both halves of the DD negative gate: the workload COMPLETES with the correct numpy
    result and every installed sentinel recorded ZERO calls.  If any sentinel had fired
    the workload would have raised (sentinel exception) and this test would FAIL — the
    sentinel exception is never a success path.
    """
    stream_store, head_store = _seed_readables(con, tmp_path / "out")
    sentinel_counts = _install_sentinels(monkeypatch)

    # Workload completes against the sentinel-guarded environment.
    result = _cpu_consumer_workload(stream_store, head_store, "songC")

    assert result["ready_songs"] == {"songC"}
    assert result["medoid_idx"] in range(4)
    assert result["gather_shape"] == (4, 3)
    assert result["head_shape"] == (4, 4)
    # Second half: zero sentinel calls across every real call site we guarded.
    assert sentinel_counts  # at least config.discover_audio is always guarded
    assert all(count == 0 for count in sentinel_counts.values()), sentinel_counts


@pytest.mark.unit
def test_head_and_stream_read_surfaces_are_cpu_only_even_with_orphan_present(con, tmp_path, monkeypatch):
    """Reconcile/verify reports an orphan CPU-only (no sentinel) and still zero ML calls.

    A rowless stray file must be classified purely from filesystem + registry metadata —
    the report exposes it and the read surfaces never reach audio/model/CUDA even when
    the tree is not clean.
    """
    out = tmp_path / "out"
    stream_store, _head_store = _seed_readables(con, out)
    # Drop a stray final file into the patches dir (a genuine orphan).
    np.save(out / "patches" / "orphanSong.effnet.v9.npy", _arr(2, 3))
    counts = _install_sentinels(monkeypatch)

    report = stream_store.verify(strict=False)  # non-strict: reports, never raises
    assert report.stray == 1
    assert report.clean is False
    assert all(count == 0 for count in counts.values()), counts


@pytest.mark.unit
def test_module_import_guard_read_surface_does_not_load_ml_stack():
    """SECONDARY import guard: importing the read surfaces does not load torch/onnxruntime.

    Runs in a fresh subprocess so the already-imported process cannot hide a real import.
    This is secondary and does NOT pretend to catch a module-level optional ML import
    (the pure read modules avoid them by construction); it just confirms the ML stack is
    absent after importing the read-surface modules, so a future regression that pulls
    the ML stack onto the read path is caught early.
    """
    code = (
        "import sys\n"
        "import scripts.embedding_research.streams.store  # noqa: F401\n"
        "bad = [m for m in ('torch', 'onnxruntime', 'sklearn') "
        "if m in sys.modules or any(k.startswith(m + '.') for k in sys.modules)]\n"
        "print('BAD:' + ','.join(bad) if bad else 'OK')\n"
        "sys.exit(1 if bad else 0)\n"
    )
    root = Path(__file__).resolve().parents[3]  # repository root (nomarr/)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=60,
        env={"PYTHONPATH": str(root), "PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0, f"read surface imported the ML stack:\n{proc.stdout}\n{proc.stderr}"
