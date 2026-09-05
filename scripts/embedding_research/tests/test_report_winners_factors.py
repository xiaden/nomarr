"""Catalog winner/delta/factor row-builder tests.

Research-only.  Verifies the deterministic catalog winner/delta builder and the compact
active-dimension factor roster (alias lists preserved, no per-metric duplication).
"""

from __future__ import annotations

import pytest

from scripts.embedding_research.report._retrieval import query_analyze_metrics
from scripts.embedding_research.report._winners import (
    CATALOG_FACTOR_COLUMNS,
    CATALOG_WINNER_DELTA_COLUMNS,
    build_factor_rows,
    build_winner_delta_rows,
)
from scripts.embedding_research.tests._report_seed import catalog_key, seed_catalog


def test_winner_delta_columns_contract(con):
    seed_catalog(
        con,
        run_id="run-1",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "a"),
        k=5,
        metrics={"map_k": 0.6, "mrr": 0.4},
    )
    rows = build_winner_delta_rows(query_analyze_metrics(con))
    assert list(rows.columns) == list(CATALOG_WINNER_DELTA_COLUMNS)
    assert len(rows) == 2  # map_k + mrr cells


def test_winner_delta_arithmetic(con):
    seed_catalog(
        con,
        run_id="run-1",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "low"),
        k=5,
        metrics={"map_k": 0.2},
        config_ids=(1,),
    )
    seed_catalog(
        con,
        run_id="run-1",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "hi"),
        k=5,
        metrics={"map_k": 0.8},
        config_ids=(9,),
    )
    rows = build_winner_delta_rows(query_analyze_metrics(con))
    r = rows.iloc[0]
    assert r["baseline_value"] == pytest.approx(0.2)
    assert r["winner_value"] == pytest.approx(0.8)
    assert r["delta"] == pytest.approx(0.6)


def test_factor_rows_compact_no_metric_duplication(con):
    seed_catalog(
        con,
        run_id="run-1",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "a"),
        k=5,
        metrics={"map_k": 0.6, "mrr": 0.4, "recall_k": 0.7},
        config_ids=(1, 3),
    )
    factors = build_factor_rows(query_analyze_metrics(con))
    assert list(factors.columns) == list(CATALOG_FACTOR_COLUMNS)
    # One compact factor row per class x sim_metric x k — the 3 metrics do NOT multiply rows.
    assert len(factors) == 1
    f = factors.iloc[0]
    assert f["backbone"] == "effnet"
    assert f["canonical_config_id"] == 1
    assert sorted(int(x) for x in f["alias_ids"]) == [3]


def test_factor_rows_multiple_classes_deterministic(con):
    seed_catalog(
        con,
        run_id="run-1",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "b"),
        k=10,
        metrics={"map_k": 0.5},
    )
    seed_catalog(
        con,
        run_id="run-1",
        backbone="musicnn",
        strategy_key=catalog_key("musicnn", "m"),
        k=10,
        metrics={"map_k": 0.6},
    )
    factors = build_factor_rows(query_analyze_metrics(con))
    assert sorted(set(factors["backbone"])) == ["effnet", "musicnn"]
    assert len(factors) == 2
