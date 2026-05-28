"""Unit tests for the embedding-research analysis layer.

These tests cover the currently untested analysis entrypoints and helpers in:
- scripts.embedding_research.classify
- scripts.embedding_research.common.analyze

The focus is on deterministic, in-memory behaviors that do not require ONNX,
audio files, or filesystem cache payloads beyond explicit early-exit checks.
"""

from __future__ import annotations

import sys
import types

import numpy as np

from scripts.embedding_research import classify as classify_mod
from scripts.embedding_research.classify import run_binned, run_flat
from scripts.embedding_research.common import analyze as common_analyze_mod
from scripts.embedding_research.common.analyze import AnalyzeCfg
from scripts.embedding_research.common.analyze import analyze as analyze_common
from scripts.embedding_research.db import load_analyze_metrics
from scripts.embedding_research.similarity import compute_retrieval_metrics
from scripts.embedding_research.vector_types import RawTensor, UnitVector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_rows(con, table_name: str) -> int:
    return int(con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


def _raw_tensor(rows: list[list[float]]) -> RawTensor:
    return RawTensor(np.asarray(rows, dtype=np.float32))


def _sim_matrix() -> np.ndarray:
    """4x4 similarity matrix with two clearly separated artist/genre groups."""
    return np.array(
        [
            [1.0, 0.95, 0.10, 0.10],
            [0.95, 1.0, 0.10, 0.10],
            [0.10, 0.10, 1.0, 0.92],
            [0.10, 0.10, 0.92, 1.0],
        ],
        dtype=np.float32,
    )


def _stub_psutil(monkeypatch) -> None:
    """Provide a lightweight psutil stub for lazy imports in classify smoke tests."""
    monkeypatch.setitem(sys.modules, "psutil", types.ModuleType("psutil"))


def _stub_ml_session_comp(monkeypatch) -> None:
    """Provide a minimal ml_session_comp stub so no-head smoke tests avoid nomarr imports."""
    ml_mod = types.ModuleType("nomarr.components.ml")
    onnx_mod = types.ModuleType("nomarr.components.ml.onnx")
    session_mod = types.ModuleType("nomarr.components.ml.onnx.ml_session_comp")
    session_mod._BACKBONE_BATCH_SIZE = 8
    session_mod._run_in_batches = lambda *_args, **_kwargs: None
    session_mod.create_session = lambda *_args, **_kwargs: object()
    ml_mod.onnx = onnx_mod
    onnx_mod.ml_session_comp = session_mod
    monkeypatch.setitem(sys.modules, "nomarr.components.ml", ml_mod)
    monkeypatch.setitem(sys.modules, "nomarr.components.ml.onnx", onnx_mod)
    monkeypatch.setitem(sys.modules, "nomarr.components.ml.onnx.ml_session_comp", session_mod)


# ---------------------------------------------------------------------------
# 1. classify.py
# ---------------------------------------------------------------------------


def test_run_flat_no_cache_files_writes_no_rows(con, monkeypatch):
    """run_flat is a no-op for a backbone with no configured heads."""
    _stub_psutil(monkeypatch)
    _stub_ml_session_comp(monkeypatch)
    monkeypatch.setattr(classify_mod, "bootstrap_nomarr", lambda: None)
    monkeypatch.setattr(classify_mod, "discover_audio", list)
    monkeypatch.setattr(classify_mod, "HEADS", {}, raising=False)

    run_flat(con, backbones=["missing_backbone"])

    assert _count_rows(con, "head_results") == 0
    assert _count_rows(con, "analyze_metrics") == 0


def test_classify_song_missing_returns_false_without_patch_cache(con, monkeypatch, tmp_path):
    """_classify_song_missing returns False when the patch sidecar does not exist."""
    song_path = tmp_path / "artist - title.mp3"
    song_path.write_bytes(b"")

    monkeypatch.setattr(classify_mod, "patches_path", lambda _sid, _bb: tmp_path / "missing_sidecar.npy")

    result = classify_mod._classify_song_missing(
        path=song_path,
        backbone_name="bb",
        head_name="genre",
        head_session=object(),
        run_in_batches_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected inference")),
        batch_size=8,
        con=con,
        pooled_map={"mean": None},
        missing_strats=frozenset({"mean"}),
    )

    assert result is False
    assert _count_rows(con, "head_results") == 0


def test_run_binned_no_cache_files_writes_no_rows(con, monkeypatch):
    """run_binned is a no-op for a backbone with no configured heads."""
    _stub_psutil(monkeypatch)
    _stub_ml_session_comp(monkeypatch)
    monkeypatch.setattr(classify_mod, "bootstrap_nomarr", lambda: None)
    monkeypatch.setattr(classify_mod, "discover_audio", list)
    monkeypatch.setattr(classify_mod, "HEADS", {}, raising=False)
    monkeypatch.setattr(classify_mod, "thresholds", [], raising=False)
    monkeypatch.setattr(classify_mod, "compute_metrics", lambda *_args, **_kwargs: 0)

    run_binned(con, backbones=["missing_backbone"])

    assert _count_rows(con, "binned_classify_ctp") == 0
    assert _count_rows(con, "binned_ctp_vecs") == 0


# ---------------------------------------------------------------------------
# 2. common/analyze.py + similarity metrics pipeline
# ---------------------------------------------------------------------------


def test_analyze_no_flat_cache_data_leaves_analyze_metrics_empty(con, monkeypatch):
    """common.analyze() leaves analyze_metrics empty when fewer than two songs are available."""
    cfg: AnalyzeCfg = {
        "strategy_names": ["mean"],
        "load_vecs_fn": lambda _bb, _strategy, _con, _extra: (
            _raw_tensor([[1.0, 0.0, 0.0]]),
            ["s1"],
            ["A"],
            ["Album A"],
            ["Rock"],
        ),
        "db_write_fn": common_analyze_mod.db.write_analyze_metrics,
        "strategy_key_fn": lambda backbone, strategy_name, _extra: f"{backbone}:{strategy_name}",
        "strategy_type": "global_pool",
        "extra_cfg": {},
    }

    monkeypatch.setattr(common_analyze_mod.db, "query_analysis_done", lambda _con: set())
    monkeypatch.setattr(common_analyze_mod, "_load_head_scores_and_names", lambda _con, _bb, _sids: (None, None))

    analyze_common(con, cfg, backbones=["bb"], k=2)

    assert _count_rows(con, "analyze_metrics") == 0


def test_analyze_writes_analyze_metrics_with_expected_identifiers(con, monkeypatch):
    """common.analyze() writes analyze_metrics rows with the expected identifiers."""
    sids = ["s1", "s2", "s3", "s4"]
    vecs = _raw_tensor(
        [
            [1.0, 0.0, 0.0],
            [0.9, 0.1, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.9, 0.1],
        ]
    )
    artists = ["A", "A", "B", "B"]
    albums = ["Album A", "Album A", "Album B", "Album B"]
    genres = ["Rock", "Rock", "Jazz", "Jazz"]

    cfg: AnalyzeCfg = {
        "strategy_names": ["mean"],
        "load_vecs_fn": lambda _bb, _strategy, _con, _extra: (
            vecs,
            list(sids),
            list(artists),
            list(albums),
            list(genres),
        ),
        "db_write_fn": common_analyze_mod.db.write_analyze_metrics,
        "strategy_key_fn": lambda backbone, strategy_name, extra_cfg: f"{backbone}:{strategy_name}:{extra_cfg['tag']}",
        "strategy_type": "global_pool",
        "extra_cfg": {"tag": "base"},
    }

    monkeypatch.setattr(common_analyze_mod.db, "query_analysis_done", lambda _con: set())
    monkeypatch.setattr(common_analyze_mod, "_load_head_scores_and_names", lambda _con, _bb, _sids: (None, None))
    monkeypatch.setattr(
        common_analyze_mod.similarity,
        "compute_retrieval_metrics",
        lambda *_args, **_kwargs: {"disc_general": 0.5, "map_k": 0.25},
    )

    analyze_common(con, cfg, backbones=["bb"], k=2)

    df = load_analyze_metrics(con)

    assert not df.empty
    assert set(df["sim_metric"]) == set(common_analyze_mod.similarity.METRICS)
    assert df["strategy_key"].str.contains("bb").all()


def test_compute_retrieval_metrics_populates_per_head_corr():
    """per_head_corr is populated when head_names are supplied."""
    sim_matrix = _sim_matrix()
    labels = ["A", "A", "B", "B"]
    genres = ["Rock", "Rock", "Jazz", "Jazz"]
    head_scores = [[0.1, 0.2, 0.8, 0.9], [0.2, 0.1, 0.9, 0.8]]
    head_names = ["mood", "energy"]

    metrics = compute_retrieval_metrics(
        sim_matrix,
        labels,
        k=2,
        genres=genres,
        head_scores=head_scores,
        head_names=head_names,
    )

    assert set(metrics["per_head_corr"]) == set(head_names)
    assert all(np.isfinite(value) for value in metrics["per_head_corr"].values())


def test_compute_retrieval_metrics_zero_optional_components_without_inputs():
    """Missing optional inputs degrade to zero discrimination cleanly."""
    metrics = compute_retrieval_metrics(_sim_matrix(), ["A", "A", "B", "B"], k=2, genres=None, head_scores=None)

    np.testing.assert_allclose(metrics["disc_genre"], 0.0, rtol=1e-5)
    np.testing.assert_allclose(metrics["disc_head"], 0.0, rtol=1e-5)


def test_compute_retrieval_metrics_disc_general_positive_when_all_components_present():
    """disc_general is positive when artist, genre, and head components are all positive."""
    metrics = compute_retrieval_metrics(
        _sim_matrix(),
        ["A", "A", "B", "B"],
        k=2,
        genres=["Rock", "Rock", "Jazz", "Jazz"],
        head_scores=[[0.1, 0.1, 0.9, 0.9]],
        head_names=["genre_head"],
    )

    assert metrics["disc_artist"] > 0.0
    assert metrics["disc_genre"] > 0.0
    assert metrics["disc_head"] > 0.0
    assert metrics["disc_general"] > 0.0
    np.testing.assert_allclose(
        metrics["disc_general"],
        np.mean([metrics["disc_artist"], metrics["disc_genre"], metrics["disc_head"]]),
        rtol=1e-5,
    )


# ---------------------------------------------------------------------------
# 4. General import / regression invariants
# ---------------------------------------------------------------------------


def test_analysis_modules_and_vector_types_import():
    """Analysis entrypoints and UnitVector remain importable."""
    assert callable(run_flat)
    assert callable(run_binned)
    assert callable(analyze_common)
    assert UnitVector.__name__ == "UnitVector"
