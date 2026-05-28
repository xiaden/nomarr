"""Unit tests for global-pool analysis orchestration."""

from __future__ import annotations

import pytest

pytest.skip("Stale test file for removed strategy_global_pool internals.", allow_module_level=True)

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import Mock, call

import pytest

import scripts.embedding_research.db as db_mod

_tqdm_module: Any = ModuleType("tqdm")
_tqdm_module.tqdm = lambda iterable=None, **_kwargs: iterable
sys.modules.setdefault("tqdm", _tqdm_module)

_time_helper_module: Any = ModuleType("nomarr.helpers.time_helper")
_time_helper_module.internal_ms = lambda: SimpleNamespace(value=0)
_helpers_module: Any = sys.modules.setdefault("nomarr.helpers", ModuleType("nomarr.helpers"))
_helpers_module.time_helper = _time_helper_module
sys.modules.setdefault("nomarr.helpers.time_helper", _time_helper_module)

if not hasattr(db_mod, "upsert_retrieval"):
    db_mod.upsert_retrieval = db_mod.write_analyze_metrics

_GP_ANALYZE_PATH = Path(__file__).resolve().parents[1] / "strategy_global_pool" / "_analyze.py"
_GP_ANALYZE_SPEC = importlib.util.spec_from_file_location("test_strategy_global_pool_analyze", _GP_ANALYZE_PATH)
assert _GP_ANALYZE_SPEC is not None and _GP_ANALYZE_SPEC.loader is not None

gp_analyze_mod = importlib.util.module_from_spec(_GP_ANALYZE_SPEC)
_GP_ANALYZE_SPEC.loader.exec_module(gp_analyze_mod)
analyze = gp_analyze_mod.analyze


@pytest.mark.unit
def test_gp_analyze_no_work_is_noop(con, monkeypatch):
    """analyze() short-circuits when every required metric is already recorded."""
    bootstrap = Mock()
    analyze_strategy = Mock()
    analyze_ptc_vs_ctp = Mock()
    analyze_ann = Mock()

    monkeypatch.setattr(gp_analyze_mod, "_bootstrap_nomarr", bootstrap)
    monkeypatch.setattr(gp_analyze_mod, "_list_embedded_configs", lambda: {("bb", "mean")})
    monkeypatch.setattr(gp_analyze_mod, "_METRICS", {"cos": object(), "dot": object()}, raising=False)
    monkeypatch.setattr(
        gp_analyze_mod,
        "_query_analysis_done",
        lambda _con: {("bb/mean", "cos", 10), ("bb/mean", "dot", 10)},
    )
    monkeypatch.setattr(gp_analyze_mod, "_analyze_strategy", analyze_strategy)
    monkeypatch.setattr(gp_analyze_mod, "_analyze_ptc_vs_ctp", analyze_ptc_vs_ctp)
    monkeypatch.setattr(gp_analyze_mod, "_analyze_ann", analyze_ann)

    analyze(con, backbones=["bb"], strategies=["mean"], k=10, song_ids=frozenset({"song-1"}))

    bootstrap.assert_not_called()
    analyze_strategy.assert_not_called()
    analyze_ptc_vs_ctp.assert_not_called()
    analyze_ann.assert_not_called()


@pytest.mark.unit
def test_gp_analyze_drives_helpers_for_incomplete_pairs(con, monkeypatch):
    """analyze() fans out to per-strategy, PTC/CTP, and ANN helpers with filtered inputs."""
    bootstrap = Mock()
    analyze_strategy = Mock()
    analyze_ptc_vs_ctp = Mock()
    analyze_ann = Mock()
    song_ids = frozenset({"song-1", "song-2"})

    monkeypatch.setattr(gp_analyze_mod, "_bootstrap_nomarr", bootstrap)
    monkeypatch.setattr(
        gp_analyze_mod,
        "_list_embedded_configs",
        lambda: {("bb1", "mean"), ("bb1", "max"), ("bb2", "mean"), ("ignored", "mean")},
    )
    monkeypatch.setattr(gp_analyze_mod, "_METRICS", {"cos": object(), "dot": object()}, raising=False)
    monkeypatch.setattr(
        gp_analyze_mod,
        "_query_analysis_done",
        lambda _con: {
            ("bb1/max", "cos", 7),
            ("bb1/max", "dot", 7),
            ("bb2/mean", "cos", 99),
            ("bb2/mean", "dot", 99),
        },
    )
    monkeypatch.setattr(gp_analyze_mod, "_HEADS", {"bb1": {"genre": object()}, "bb2": {}}, raising=False)
    monkeypatch.setattr(gp_analyze_mod, "_analyze_strategy", analyze_strategy)
    monkeypatch.setattr(gp_analyze_mod, "_analyze_ptc_vs_ctp", analyze_ptc_vs_ctp)
    monkeypatch.setattr(gp_analyze_mod, "_analyze_ann", analyze_ann)

    analyze(
        con,
        backbones=["bb2", "bb1"],
        strategies=["mean", "max"],
        k=7,
        song_ids=song_ids,
    )

    bootstrap.assert_called_once_with()
    assert analyze_strategy.call_args_list == [
        call(con, "bb2", "mean", k=7, song_ids=song_ids),
        call(con, "bb1", "mean", k=7, song_ids=song_ids),
    ]
    analyze_ptc_vs_ctp.assert_called_once_with(con, "bb1", ["mean"], k=7, song_ids=song_ids)
    assert analyze_ann.call_args_list == [
        call(con, "bb2", strategy="mean", k=7, n_queries=200, song_ids=song_ids),
        call(con, "bb1", strategy="mean", k=7, n_queries=200, song_ids=song_ids),
    ]
