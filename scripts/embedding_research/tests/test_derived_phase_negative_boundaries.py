"""Plan E P2-S3 — call-level negative sentinels over the five derived phases.

DD CPU/inference-boundary (lines 228-233): ``catalog``, ``catalog-report``,
``analyze``, ``head-analysis``, and ``report`` consume only manifests, DuckDB
catalog rows, and frozen stream/head artifacts.  They must run when audio, model
directories, ONNX Runtime sessions, and CUDA are absent, and must PROVE no such
call happened — a caught sentinel exception is a test failure, never success.

The negative gate is call-level at the REAL call sites (mirroring
``test_stream_cpu_boundary.py`` and Plan A's ``test_negative_boundaries.py``):
raising sentinels are monkeypatched onto ``config.discover_audio`` (audio
discovery), ``onnxruntime.InferenceSession`` (ONNX session construction), the
research ML session-constructor path, the ONNX inference/batch helpers, and
``torch.cuda.is_available`` (CUDA).  Sentinels are attached ONLY when the
underlying call site is importable (e.g. onnxruntime / torch may be absent), and
each test asserts BOTH halves of the gate:

* the real canonical phase entry point COMPLETES with its expected result, and
* every installed sentinel recorded ZERO calls.

We drive the REAL canonical entries for the five derived phases:
``catalog.build_segmentation_catalog``, ``catalog_report.build_catalog_report``,
``common.catalog_analysis.run_catalog_analysis``,
``common.head_analysis.run_shared_catalog_head_analysis``, and ``report.run``,
reusing the ready-stream + verified-catalog seeding from the catalog tests.
"""

from __future__ import annotations

import json

import numpy as np

from scripts.embedding_research import catalog
from scripts.embedding_research.catalog_report import build_catalog_report
from scripts.embedding_research.common import catalog_analysis as ca
from scripts.embedding_research.common.head_analysis import run_shared_catalog_head_analysis
from scripts.embedding_research.config import discover_audio as _config_discover_audio
from scripts.embedding_research.report import run as report_run
from scripts.embedding_research.streams.store import StreamStore

# Optional ML-stack / research-inference availability.  The derived phases never
# import these; if a platform has them we still sentinel them so a regression that
# reaches them fires; if they are absent they cannot be called, which is itself the
# CPU-only proof.
try:  # pragma: no cover - environment dependent
    import onnxruntime  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    onnxruntime = None  # type: ignore[assignment]

try:  # pragma: no cover - environment dependent
    import torch  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    torch = None  # type: ignore[assignment]

try:  # pragma: no cover - environment dependent
    from nomarr.components.ml.onnx import ml_session_comp as _ml_session_comp
except Exception:  # pragma: no cover - onnxruntime absent
    _ml_session_comp = None  # type: ignore[assignment]

_SONGS = ("s1", "s2", "s3", "s4")
_ARTISTS = {"s1": "A", "s2": "A", "s3": "B", "s4": "B"}
_SCHEMA_VERSION = 1


def _unit(rng, n: int, d: int) -> np.ndarray:
    """Deterministic float32 L2-unit rows (a normalized frozen-stream stand-in)."""
    m = rng.standard_normal((n, d)) * 1.5
    m[0] += 3.0
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (m / norms).astype(np.float32)


def _publish_streams(con, out, song_ids=_SONGS, *, seed: int = 3) -> StreamStore:
    """Publish one ready effnet stream per song (the embed upstream artifact)."""
    store = StreamStore(con, output_root=str(out))
    rng = np.random.default_rng(seed)
    for song in song_ids:
        store.publish(song, "effnet", _unit(rng, 10, 6), run_id="run-embed")
    store.reconcile()
    return store


def _build_compact(store, out, *, song_ids=_SONGS, threshold: float = 0.7, run_id: str = "run-cat-guarded"):
    """Build one VERIFIED COMPACT catalog snapshot into ``out/catalogs/.staging-<run_id>/``."""
    from scripts.embedding_research.streams import make_current_stream_resolver

    rep = catalog.build_segmentation_catalog(
        make_current_stream_resolver(store),
        None,
        [
            catalog.SegConfigInput(
                backbone="effnet",
                bin_mode="temporal_global",
                threshold_configured=threshold,
                threshold_effective=threshold,
            )
        ],
        list(song_ids),
        output_root=str(out),
        run_id=run_id,
        verify=True,
    )
    assert rep.verify_ok is True
    return rep


def _compact_streams(*, seed: int = 3) -> dict[tuple[str, str], np.ndarray]:
    """Ready effnet streams for every song (the factory seeding input)."""
    rng = np.random.default_rng(seed)
    return {(song, "effnet"): _unit(rng, 10, 6) for song in _SONGS}


def _cfg(run_id: str, song_ids=_SONGS, artists=_ARTISTS) -> ca.CatalogAnalysisConfig:
    return ca.CatalogAnalysisConfig(run_id=run_id, backbone="effnet", song_ids=song_ids, artists=artists)


# --------------------------------------------------------------------------- #
# Call-level raising sentinels at the real call sites                          #
# --------------------------------------------------------------------------- #


class _RaisingSentinel:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events

    def __call__(self, *_args, **_kwargs):
        self.events.append(self.name)
        raise AssertionError(f"forbidden call during a CPU-only derived phase: {self.name}")


def _install_sentinels(monkeypatch) -> dict[str, int]:
    """Monkeypatch real call sites with raising sentinels; return name -> final count.

    Only attributes that exist / are importable are patched, so the test asserts zero
    calls for whichever sentinels were actually attachable.
    """
    events: list[str] = []
    installed: dict[str, _RaisingSentinel] = {}

    # config.discover_audio — the real audio-discovery call site (always present).
    sentinel = _RaisingSentinel("config.discover_audio", events)
    monkeypatch.setattr(_config_discover_audio.__module__ + ".discover_audio", sentinel)
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

    # Research ML session constructor + ONNX inference/batch helper.  classify/run use
    # nomarr.ml_session_comp.create_session / _run_in_batches lazily behind bootstrap; the
    # derived phases must never reach them.  Attach only if importable (onnxruntime absent
    # here makes the module unimportable, which is itself the CPU-only proof).
    if _ml_session_comp is not None:
        for attr in ("create_session", "_run_in_batches"):
            if hasattr(_ml_session_comp, attr):
                sentinel = _RaisingSentinel(f"ml_session_comp.{attr}", events)
                monkeypatch.setattr(_ml_session_comp, attr, sentinel)
                installed[f"ml_session_comp.{attr}"] = sentinel

    return {name: len(sentinel.events) for name, sentinel in installed.items()}


def _assert_zero_sentinel_calls(counts: dict[str, int]) -> None:
    assert counts, "at least config.discover_audio must be guarded"
    assert all(c == 0 for c in counts.values()), counts


# --------------------------------------------------------------------------- #
# Five derived phases complete AND make zero sentinel calls                    #
# --------------------------------------------------------------------------- #


def test_catalog_phase_completes_with_zero_sentinel_calls(con, tmp_path, monkeypatch):
    """catalog (build_segmentation_catalog) completes on frozen streams, no audio/ML."""
    store = _publish_streams(con, tmp_path / "out")
    counts = _install_sentinels(monkeypatch)

    rep = _build_compact(store, tmp_path / "out", run_id="run-cat-guarded")

    assert rep.verify_ok is True
    assert rep.configs and rep.configs[0].backbone == "effnet"
    _assert_zero_sentinel_calls(counts)


def test_catalog_report_phase_completes_with_zero_sentinel_calls(con, tmp_path, monkeypatch, compact_catalog_factory):
    """catalog-report (build_catalog_report) completes over catalog rows only."""
    harness = compact_catalog_factory(
        con,
        tmp_path / "out",
        streams=_compact_streams(),
        configs=[_compact_config()],
        song_ids=list(_SONGS),
        run_id="run-cat-guarded",
    )
    try:
        counts = _install_sentinels(monkeypatch)

        report = build_catalog_report(harness.con, schema_version=_SCHEMA_VERSION)

        assert 1 in report.canonical_config_ids
        assert len(report.catalog_fingerprint) == 64
        assert report.membership_row_total >= 1
        _assert_zero_sentinel_calls(counts)
    finally:
        harness.close()


def _compact_config() -> catalog.SegConfigInput:
    return catalog.SegConfigInput(
        backbone="effnet",
        bin_mode="temporal_global",
        threshold_configured=0.7,
        threshold_effective=0.7,
    )


def test_analyze_phase_completes_with_zero_sentinel_calls(con, tmp_path, monkeypatch, compact_catalog_factory):
    """analyze (run_catalog_analysis) completes via bounded CPU scoring, no ML."""
    harness = compact_catalog_factory(
        con,
        tmp_path / "out",
        streams=_compact_streams(),
        configs=[_compact_config()],
        song_ids=list(_SONGS),
        run_id="run-cat-guarded",
    )
    try:
        counts = _install_sentinels(monkeypatch)

        result = ca.run_catalog_analysis(harness.stream_store, harness.con, _cfg("run-an-guarded"), research_con=con)

        assert result.finite is True
        assert result.n_queries == len(_SONGS)
        assert result.strategy_key.startswith("catalog:effnet:")
        for key in ("map_k", "mrr", "ndcg_k", "recall_k", "disc_artist"):
            assert np.isfinite(result.metrics[key]), key
        _assert_zero_sentinel_calls(counts)
    finally:
        harness.close()


def _fake_head_store():
    """Minimal HeadStreamStore stand-in: gathered row value == its source patch index."""

    class _FakeHeadStore:
        def lookup(self, song_id, backbone):  # noqa: ARG002 - interface-parity fake
            import types

            return types.SimpleNamespace(head_ids="mood", dim_by_head="mood=3")

        def batch_gather(self, song_id, backbone, source_patch_indices):  # noqa: ARG002
            return np.asarray(
                [[float(i), float(i) + 1.0, float(i) + 2.0] for i in source_patch_indices],
                dtype=np.float32,
            )

    return _FakeHeadStore()


def test_head_analysis_phase_completes_with_zero_sentinel_calls(con, tmp_path, monkeypatch, compact_catalog_factory):
    """head-analysis (run_shared_catalog_head_analysis) pools exact M_g, CPU only.

    Builds a real COMPACT snapshot over the four songs and routes the snapshot
    (``harness``, whose ``.con`` the runner duck-types) into the runner — the retained
    ``_run_head_analysis`` seam opens the latest compact snapshot and passes it as the
    catalog for reads while keeping the research connection for the head store +
    provenance.  No committed mask loader exists on this path, so reconstruction passes
    ``mask=None`` (no silence exclusion).
    """
    import numpy as _np

    rng = _np.random.default_rng(3)
    streams = {}
    for song in _SONGS:
        streams[(song, "effnet")] = _unit(rng, 10, 6)
    harness = compact_catalog_factory(
        con,
        tmp_path / "out",
        streams=streams,
        configs=[
            catalog.SegConfigInput(
                backbone="effnet",
                bin_mode="temporal_global",
                threshold_configured=0.7,
                threshold_effective=0.7,
            )
        ],
        song_ids=list(_SONGS),
        run_id="run-head-guarded",
    )
    try:
        config_id = harness_report_config_id(harness)
        counts = _install_sentinels(monkeypatch)
        head_store = _fake_head_store()

        manifest = run_shared_catalog_head_analysis(
            harness,
            head_store,
            config_ids=[config_id],
            song_ids=_SONGS,
            heads=["mood"],
            run_id="run-head-guarded",
        )

        assert manifest.done >= 1
        assert manifest.errors == 0
        assert config_id in manifest.config_ids
        assert manifest.finite is True
        _assert_zero_sentinel_calls(counts)
    finally:
        harness.close()


def harness_report_config_id(harness) -> int:
    """The canonical compact config id for the built snapshot (single effnet config)."""
    from scripts.embedding_research.catalog import compact_configs_by_backbone

    return int(compact_configs_by_backbone(harness.con, "effnet")[0].config_id)


def test_report_phase_completes_with_zero_sentinel_calls(con, tmp_path, monkeypatch, compact_catalog_factory):
    """report (report.run) renders a report over catalog + analyze rows, no ML."""
    from scripts.embedding_research.db import analyze_scope

    harness = compact_catalog_factory(
        con,
        tmp_path / "out",
        streams=_compact_streams(),
        configs=[_compact_config()],
        song_ids=list(_SONGS),
        run_id="run-cat-guarded",
    )
    try:
        result = ca.run_catalog_analysis(harness.stream_store, harness.con, _cfg("run-an-1"), research_con=con)
        assert result.finite is True
        analyze_scope.write_catalog_analyze_rows(con, run_id="run-an-1", result=result)
        out = tmp_path / "report-out"
        counts = _install_sentinels(monkeypatch)

        report_run(con, str(out))

        assert (out / "report.json").exists()
        assert (out / "report.html").exists()
        payload = json.loads((out / "report.json").read_text(encoding="utf-8"))
        assert payload["schema_version"] == 2
        assert any(s["id"] == "winners" for s in payload["sections"])
        _assert_zero_sentinel_calls(counts)
    finally:
        harness.close()
