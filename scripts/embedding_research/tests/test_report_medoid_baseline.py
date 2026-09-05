"""Catalog baseline/winner/delta determinism tests (no obsolete flat baseline).

Research-only.  Verifies the active catalog baseline = lowest (canonical_config_id,
strategy_key) class after collapse, the winner = highest finite value with strategy_key
tie-break, delta = winner - baseline, per-backbone independence (EffNet / MusicNN never
cross-averaged), and that equal representations collapse to one scored class (aliases never
create duplicate rows).
"""

from __future__ import annotations

import pytest

from scripts.embedding_research.db.flat import write_analyze_metrics
from scripts.embedding_research.report._retrieval import query_analyze_metrics
from scripts.embedding_research.report._winners import (
    CATALOG_WINNER_DELTA_COLUMNS,
    build_winner_delta_rows,
)
from scripts.embedding_research.tests._report_seed import catalog_key, seed_catalog


def _winner_rows(con, backbone: str | None = None):
    df = query_analyze_metrics(con)
    rows = build_winner_delta_rows(df)
    if backbone is not None:
        rows = rows[rows["backbone"] == backbone]
    return rows


def test_baseline_is_lowest_canonical_config_not_lowest_value(con):
    # Class A has canonical config 2 but a LOW value (0.3); class B has canonical config 10 and
    # a HIGH value (0.9).  Baseline must be config 2 (canonical rule), winner must be B.
    seed_catalog(
        con,
        run_id="run-1",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "lowval"),
        k=5,
        metrics={"map_k": 0.3},
        config_ids=(2,),
    )
    seed_catalog(
        con,
        run_id="run-1",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "highval"),
        k=5,
        metrics={"map_k": 0.9},
        config_ids=(10,),
    )
    rows = _winner_rows(con, backbone="effnet")
    assert len(rows) == 1
    r = rows.iloc[0]
    assert r["baseline_strategy_key"] == catalog_key("effnet", "lowval")
    assert r["winner_strategy_key"] == catalog_key("effnet", "highval")
    assert r["winner_value"] == pytest.approx(0.9)
    assert r["baseline_value"] == pytest.approx(0.3)
    assert r["delta"] == pytest.approx(0.6)


def test_flat_baseline_never_synthesized(con):
    # A legacy flat row must never become any baseline.
    write_analyze_metrics(
        con,
        "global_pool:effnet:medoid",
        "global_pool",
        "cosine",
        5,
        {"map_k": 0.99},
        run_id="legacy",
    )
    seed_catalog(
        con,
        run_id="run-1",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "only"),
        k=5,
        metrics={"map_k": 0.6},
    )
    rows = _winner_rows(con)
    assert not rows.empty
    assert (rows["baseline_strategy_key"].astype(str).str.startswith("catalog:")).all()
    assert (rows["winner_strategy_key"].astype(str).str.startswith("catalog:")).all()


def test_effnet_musicnn_independent_never_cross_averaged(con):
    seed_catalog(
        con,
        run_id="run-1",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "e"),
        k=5,
        metrics={"map_k": 0.9},
    )
    seed_catalog(
        con,
        run_id="run-1",
        backbone="musicnn",
        strategy_key=catalog_key("musicnn", "m"),
        k=5,
        metrics={"map_k": 0.1},
    )
    rows = _winner_rows(con)
    assert set(rows["backbone"]) == {"effnet", "musicnn"}
    e = rows[rows["backbone"] == "effnet"].iloc[0]
    m = rows[rows["backbone"] == "musicnn"].iloc[0]
    assert e["winner_value"] == pytest.approx(0.9)
    assert m["winner_value"] == pytest.approx(0.1)


def test_winner_tie_breaks_to_lowest_strategy_key(con):
    # Two classes tied on value; deterministic winner = lexicographically lowest strategy_key.
    seed_catalog(
        con,
        run_id="run-1",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "bba"),
        k=5,
        metrics={"map_k": 0.7},
    )
    seed_catalog(
        con,
        run_id="run-1",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "aab"),
        k=5,
        metrics={"map_k": 0.7},
    )
    rows = _winner_rows(con, backbone="effnet")
    assert rows.iloc[0]["winner_strategy_key"] == catalog_key("effnet", "aab")
    assert rows.iloc[0]["delta"] == pytest.approx(0.0)


def test_equal_representation_collapse_single_class_no_duplicate_rows(con):
    # Writing the same class twice (equal representation, config_ids=(1,2)) collapses to a single
    # canonical class with alias 2 and never duplicates metric/score rows.
    for _ in range(2):
        seed_catalog(
            con,
            run_id="run-1",
            backbone="effnet",
            strategy_key=catalog_key("effnet", "same"),
            k=5,
            metrics={"map_k": 0.6, "mrr": 0.4},
            config_ids=(1, 2),
        )
    df = query_analyze_metrics(con)
    same = df[df["strategy_key"] == catalog_key("effnet", "same")]
    assert len(same) == 2  # one row per metric, not duplicated by the two writes
    assert sorted(int(x) for x in same.iloc[0]["alias_ids"]) == [2]
    rows = build_winner_delta_rows(df)
    assert len(rows) == 2  # two metric cells


def test_empty_analysis_yields_empty_winner_rows(con):
    df = query_analyze_metrics(con)
    assert df.empty
    rows = build_winner_delta_rows(df)
    assert rows.empty
    assert list(rows.columns) == list(CATALOG_WINNER_DELTA_COLUMNS)
