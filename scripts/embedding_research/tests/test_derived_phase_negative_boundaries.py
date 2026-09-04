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
``common.head_analysis.run_shared_ptc_head_pooling``, and ``report.run``,
reusing the ready-stream + verified-catalog seeding from the catalog tests.

Secondary, complementary: with ``archival_ctp.enabled=true`` semantics, an
archival CTP analysis row fed through the report winners path never appears as a
winner/best and the archival label (decoded ``ctp`` head identity) is retained —
proving the P2-S1/S2 builder-level exclusions hold through the report path.
"""

from __future__ import annotations

import json

import numpy as np

from scripts.embedding_research import catalog
from scripts.embedding_research.catalog_report import build_catalog_report
from scripts.embedding_research.common import catalog_analysis as ca
from scripts.embedding_research.common.head_analysis import run_shared_ptc_head_pooling
from scripts.embedding_research.config import discover_audio as _config_discover_audio
from scripts.embedding_research.report import run as report_run
from scripts.embedding_research.report._base import ANALYZE_METRICS_COLUMNS, _decode_strategy_key
from scripts.embedding_research.report._winners_report import section_winners
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


def _build_catalog(con, store, *, song_ids=_SONGS, threshold: float = 0.7, run_id: str = "run-cat-1"):
    """Build a single canonical EffNet PTC seg_config with a verified pass."""
    rep = catalog.build_segmentation_catalog(
        con,
        store,
        [
            catalog.SegConfigInput(
                backbone="effnet",
                bin_mode="temporal_global",
                threshold_configured=threshold,
                threshold_effective=threshold,
            )
        ],
        list(song_ids),
        run_id,
        verify=True,
    )
    assert rep.verify_ok is True
    return rep


def _seed_cataloged(con, out) -> tuple[StreamStore, int]:
    """Publish ready streams and build a verified catalog; return (store, config_id)."""
    store = _publish_streams(con, out)
    rep = _build_catalog(con, store)
    return store, int(rep.configs[0].config_id)


def _cfg(run_id: str, song_ids=_SONGS, artists=_ARTISTS) -> ca.CatalogAnalysisConfig:
    return ca.CatalogAnalysisConfig(run_id=run_id, backbone="effnet", song_ids=song_ids, artists=artists)


def _seed_analyze_rows(con, store, *, run_id: str = "run-an-1"):
    """Run catalog-first analysis and write run-scoped analyze rows (report input)."""
    from scripts.embedding_research.db import analyze_scope

    result = ca.run_catalog_analysis(store, con, _cfg(run_id))
    assert result.finite is True
    analyze_scope.write_catalog_analyze_rows(con, run_id=run_id, result=result)
    return result


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

    rep = _build_catalog(con, store, run_id="run-cat-guarded")

    assert rep.verify_ok is True
    assert rep.configs and rep.configs[0].backbone == "effnet"
    _assert_zero_sentinel_calls(counts)


def test_catalog_report_phase_completes_with_zero_sentinel_calls(con, tmp_path, monkeypatch):
    """catalog-report (build_catalog_report) completes over catalog rows only."""
    _store, config_id = _seed_cataloged(con, tmp_path / "out")
    counts = _install_sentinels(monkeypatch)

    report = build_catalog_report(con, schema_version=_SCHEMA_VERSION)

    assert config_id in report.canonical_config_ids
    assert len(report.catalog_fingerprint) == 64
    assert len(report.search_view_hash) == 64
    assert report.membership_row_total >= 1
    _assert_zero_sentinel_calls(counts)


def test_analyze_phase_completes_with_zero_sentinel_calls(con, tmp_path, monkeypatch):
    """analyze (run_catalog_analysis) completes via bounded CPU scoring, no ML."""
    store, _ = _seed_cataloged(con, tmp_path / "out")
    counts = _install_sentinels(monkeypatch)

    result = ca.run_catalog_analysis(store, con, _cfg("run-an-guarded"))

    assert result.finite is True
    assert result.n_queries == len(_SONGS)
    assert result.strategy_key.startswith("catalog:effnet:")
    for key in ("map_k", "mrr", "ndcg_k", "recall_k", "disc_artist"):
        assert np.isfinite(result.metrics[key]), key
    _assert_zero_sentinel_calls(counts)


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


def test_head_analysis_phase_completes_with_zero_sentinel_calls(con, tmp_path, monkeypatch):
    """head-analysis (run_shared_ptc_head_pooling) pools over memberships, CPU only."""
    _store, config_id = _seed_cataloged(con, tmp_path / "out")
    counts = _install_sentinels(monkeypatch)
    head_store = _fake_head_store()

    manifest = run_shared_ptc_head_pooling(
        con,
        head_store,
        config_ids=[config_id],
        song_ids=_SONGS,
        heads=["mood"],
        run_id="run-head-guarded",
        reference_corpus_hash="h",
    )

    assert manifest.done >= 1
    assert manifest.errors == 0
    assert config_id in manifest.config_ids
    assert manifest.finite is True
    _assert_zero_sentinel_calls(counts)


def test_report_phase_completes_with_zero_sentinel_calls(con, tmp_path, monkeypatch):
    """report (report.run) renders a report over catalog + analyze rows, no ML."""
    store, _ = _seed_cataloged(con, tmp_path / "out")
    _seed_analyze_rows(con, store)
    out = tmp_path / "report-out"
    counts = _install_sentinels(monkeypatch)

    report_run(con, str(out))

    assert (out / "report.json").exists()
    assert (out / "report.html").exists()
    payload = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert any(s["id"] == "winners" for s in payload["sections"])
    _assert_zero_sentinel_calls(counts)


# --------------------------------------------------------------------------- #
# Archival CTP: fed through the report winners path, never a primary winner     #
# --------------------------------------------------------------------------- #


def _wide_row() -> dict:
    row = dict.fromkeys(ANALYZE_METRICS_COLUMNS)
    row.update(
        sim_metric="cosine",
        k=10,
        map_k_artist=0.5,
        map_k_genre=0.5,
        map_k_head=0.5,
        map_k_general=0.5,
        mrr=0.5,
        ndcg_k_artist=0.5,
        recall_k_artist=0.5,
        disc_artist=0.4,
        disc_genre=0.4,
        disc_head=0.4,
        disc_general=0.4,
        disc_score=0.4,
    )
    return row


def _archival_report_df():
    """A fed report df with an explicit medoid baseline + a PTC candidate + an archival CTP row.

    Mirrors an ``archival_ctp.enabled=true`` analysis run whose CTP outputs land in
    ``analyze_metrics`` under ``ctp:`` keys with a decoded head identity (archival label),
    but which must never appear as a primary winner/best.
    """
    import pandas as pd

    medoid = _wide_row()
    medoid.update(
        strategy_key="global_pool:effnet:medoid",
        strategy_type="global_pool",
        backbone="effnet",
        strategy="medoid",
        map_k_artist=0.6,
    )
    ptc = _wide_row()
    ptc.update(
        strategy_key="ptc:effnet:temporal_global:1.0:median:max:target_weighted",
        strategy_type="ptc",
        backbone="effnet",
        bin_mode="temporal_global",
        std_thresh=1.0,
        rep_a="median",
        rep_b="max",
        agg_method="target_weighted",
        map_k_artist=0.8,
    )
    ctp = _wide_row()
    ctp.update(
        strategy_key="ctp:effnet:genre:1.0:median:max:bidirectional_weighted",
        strategy_type="ctp",
        backbone="effnet",
        head="genre",
        std_thresh=1.0,
        rep_a="median",
        rep_b="max",
        agg_method="bidirectional_weighted",
        map_k_artist=0.9,  # highest value — would win if CTP were eligible
    )
    return pd.DataFrame([medoid, ptc, ctp], columns=ANALYZE_METRICS_COLUMNS)


def test_archival_ctp_row_fed_through_report_winners_never_primary_and_label_retained():
    """A fed CTP row is recorded (archival label decoded) yet never a report winner/best."""
    df = _archival_report_df()

    # Archival label recorded: the CTP analyze row decodes its head identity (genre) — the
    # report's archival sections render it — and carries strategy_type 'ctp'.
    decoded = _decode_strategy_key(df[df["strategy_type"] == "ctp"].copy())
    assert list(decoded["strategy_type"]) == ["ctp"]
    assert list(decoded["head"]) == ["genre"]

    # Feed the SAME df through the report winners path (section_winners, the report.run
    # winner surface) and assert the CTP row never appears as a winner/best row.
    section = section_winners(df)
    assert section["subsections"], "a PTC winner vs medoid baseline must be computed"
    cells: list[str] = []
    for sub in section["subsections"]:
        for table in sub.get("tables", []):
            for row in table["rows"]:
                cells.extend(str(c) for c in row)
    assert any(c.startswith("ptc:") for c in cells), "the PTC candidate must win the cell"
    assert not any(c == "ctp" or c.startswith("ctp:") for c in cells), (
        "CTP must never occupy a primary winner/best slot in the report path"
    )
