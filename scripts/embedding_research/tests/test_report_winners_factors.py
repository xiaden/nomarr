"""Catalog winner/delta/factor row-builder tests.

Research-only.  Verifies the deterministic catalog winner/delta builder and the compact
active-dimension factor roster (alias lists preserved, no per-metric duplication).
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.embedding_research.baseline import (
    BASELINE_DELTA_COLUMNS,
    build_baseline_delta_rows,
    medoid_strategy_key_for,
)
from scripts.embedding_research.report._retrieval import query_analyze_metrics, query_winners_metrics
from scripts.embedding_research.report._winners import (
    CATALOG_FACTOR_COLUMNS,
    CATALOG_WINNER_DELTA_COLUMNS,
    build_factor_rows,
    build_winner_delta_rows,
)
from scripts.embedding_research.tests._report_seed import (
    catalog_key,
    seed_catalog,
    seed_medoid_baseline,
)


# --------------------------------------------------------------------------- #
# Observed global-medoid baseline delta builder (P1-S5/S6; report wired in S7) #
# --------------------------------------------------------------------------- #
def _delta_frame(rows: list[dict]) -> pd.DataFrame:
    """A decoded long frame carrying segmented class + medoid rows for the given backbones."""
    return pd.DataFrame(
        [
            {
                "sim_metric": "cosine",
                "k": 5,
                "metric": "map_k",
                "canonical_config_id": None,
                "alias_ids": [],
                **r,
            }
            for r in rows
        ]
    )


def _catalog_row(backbone: str, keyset: str, value: float, ccid: int, aliases: list[int]) -> dict:
    return {
        "backbone": backbone,
        "strategy_key": catalog_key(backbone, keyset),
        "value": value,
        "canonical_config_id": ccid,
        "alias_ids": aliases,
    }


def _medoid_row(backbone: str, value: float) -> dict:
    return {"backbone": backbone, "strategy_key": medoid_strategy_key_for(backbone), "value": value}


def test_baseline_delta_columns_contract():
    df = _delta_frame([_catalog_row("effnet", "a", 0.6, 1, []), _medoid_row("effnet", 0.4)])
    rows = build_baseline_delta_rows(df)
    assert list(rows.columns) == list(BASELINE_DELTA_COLUMNS)
    assert len(rows) == 1


def test_winner_delta_arithmetic_against_medoid_baseline():
    df = _delta_frame(
        [
            _catalog_row("effnet", "low", 0.2, 1, []),
            _catalog_row("effnet", "hi", 0.8, 9, []),
            _medoid_row("effnet", 0.55),
        ]
    )
    r = build_baseline_delta_rows(df).iloc[0]
    assert r["baseline_strategy_key"] == medoid_strategy_key_for("effnet")
    assert r["baseline_value"] == pytest.approx(0.55)
    assert r["winner_value"] == pytest.approx(0.8)
    assert r["delta"] == pytest.approx(0.8 - 0.55)


def test_winner_tie_breaks_to_lowest_strategy_key_against_medoid():
    df = _delta_frame(
        [
            _catalog_row("effnet", "bba", 0.7, 3, []),
            _catalog_row("effnet", "aab", 0.7, 4, []),
            _medoid_row("effnet", 0.7),
        ]
    )
    rows = build_baseline_delta_rows(df)
    r = rows.iloc[0]
    assert r["winner_strategy_key"] == catalog_key("effnet", "aab")
    assert r["delta"] == pytest.approx(0.0)


def test_medoid_baseline_per_backbone_identity_no_cross_backbone():
    # Each backbone's baseline is its OWN global_pool:{backbone}:medoid row; an effnet medoid row
    # never serves as a musicnn baseline (per-backbone independence preserved).
    df = _delta_frame(
        [
            _catalog_row("effnet", "e", 0.9, 1, []),
            _catalog_row("musicnn", "m", 0.3, 1, []),
            _medoid_row("effnet", 0.6),
            _medoid_row("musicnn", 0.1),
        ]
    )
    rows = build_baseline_delta_rows(df)
    assert set(rows["backbone"]) == {"effnet", "musicnn"}
    by = dict(zip(rows["backbone"], rows.to_dict("records"), strict=False))
    assert by["effnet"]["baseline_strategy_key"] == "global_pool:effnet:medoid"
    assert by["musicnn"]["baseline_strategy_key"] == "global_pool:musicnn:medoid"
    assert by["effnet"]["baseline_value"] == pytest.approx(0.6)
    assert by["musicnn"]["baseline_value"] == pytest.approx(0.1)


def test_winner_delta_columns_contract(con):
    seed_catalog(
        con,
        run_id="run-1",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "a"),
        k=5,
        metrics={"map_k": 0.6, "mrr": 0.4},
    )
    seed_medoid_baseline(con, run_id="run-1", backbone="effnet", k=5, metrics={"map_k": 0.5, "mrr": 0.3})
    rows = build_winner_delta_rows(query_winners_metrics(con))
    assert list(rows.columns) == list(CATALOG_WINNER_DELTA_COLUMNS)
    assert len(rows) == 2  # map_k + mrr cells
    assert set(rows["baseline_strategy_key"]) == {medoid_strategy_key_for("effnet")}


def test_winner_delta_arithmetic_against_medoid_loader(con):
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
    seed_medoid_baseline(con, run_id="run-1", backbone="effnet", k=5, metrics={"map_k": 0.55})
    rows = build_winner_delta_rows(query_winners_metrics(con))
    r = rows.iloc[0]
    # baseline is the observed medoid row, NOT the lowest-config class (low, 0.2).
    assert r["baseline_strategy_key"] == medoid_strategy_key_for("effnet")
    assert r["baseline_value"] == pytest.approx(0.55)
    assert r["winner_value"] == pytest.approx(0.8)
    assert r["delta"] == pytest.approx(0.8 - 0.55)


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
