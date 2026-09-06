"""Catalog baseline/winner/delta determinism tests (observed global-medoid baseline).

Research-only.  Verifies the active catalog baseline = the observed global-medoid baseline
(``global_pool:{backbone}:medoid``) scored over the same corpus / sim_metric / k / metric,
never a winner candidate; the winner = highest finite catalog-class value with strategy_key
tie-break; delta = winner - baseline; per-backbone independence (EffNet / MusicNN never
cross-averaged); and that equal representations collapse to one scored class (aliases never
create duplicate rows).  These report-path tests exercise the real loaders: the catalog-only
``query_analyze_metrics`` frame is enriched with the run-scoped medoid baseline rows via
``query_winners_metrics`` before ``build_winner_delta_rows``.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.embedding_research.baseline import (
    BASELINE_DELTA_COLUMNS,
    build_baseline_delta_rows,
    medoid_strategy_key_for,
)
from scripts.embedding_research.db.flat import write_analyze_metrics
from scripts.embedding_research.report._retrieval import query_analyze_metrics, query_winners_metrics
from scripts.embedding_research.report._winners import (
    CATALOG_WINNER_DELTA_COLUMNS,
    build_winner_delta_rows,
)
from scripts.embedding_research.tests._report_seed import (
    catalog_key,
    seed_catalog,
    seed_medoid_baseline,
)

_EB = "effnet"
_ES = medoid_strategy_key_for(_EB)


def _frame(rows: list[dict]) -> pd.DataFrame:
    """A decoded long frame (analysis_df shape) carrying segmented classes + medoid rows."""
    return pd.DataFrame(
        [
            {
                "backbone": _EB,
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


def _seg(key: str, value: float, ccid: int) -> dict:
    return {
        "strategy_key": catalog_key(_EB, key),
        "value": value,
        "canonical_config_id": ccid,
        "alias_ids": [],
    }


def _medoid(value: float) -> dict:
    return {"strategy_key": _ES, "value": value}


def _baseline_rows(df: pd.DataFrame) -> pd.DataFrame:
    return build_baseline_delta_rows(df)


def _winner_rows(con, backbone: str | None = None):
    df = query_winners_metrics(con)
    rows = build_winner_delta_rows(df)
    if backbone is not None:
        rows = rows[rows["backbone"] == backbone]
    return rows


def test_baseline_is_observed_medoid_not_lowest_config_through_loader(con):
    # Two segmented classes are present (config 2 with a LOW value 0.3, config 10 with a HIGH
    # value 0.9).  Under the observed-medoid contract the baseline must be the run-scoped
    # global_pool:effnet:medoid row (0.5) — NOT the lowest (canonical_config_id, strategy_key)
    # class (config 2) that the obsolete rule selected.  Winner = the high class.
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
    seed_medoid_baseline(con, run_id="run-1", backbone="effnet", k=5, metrics={"map_k": 0.5})
    rows = _winner_rows(con, backbone="effnet")
    assert len(rows) == 1
    r = rows.iloc[0]
    assert r["baseline_strategy_key"] == _ES
    assert r["baseline_value"] == pytest.approx(0.5)
    assert r["baseline_canonical_config_id"] is None
    assert r["winner_strategy_key"] == catalog_key("effnet", "highval")
    assert r["winner_canonical_config_id"] == 10
    assert r["winner_value"] == pytest.approx(0.9)
    assert r["delta"] == pytest.approx(0.4)


def test_flat_medoid_row_is_baseline_when_run_scoped(con):
    # The observed global_pool medoid row is now the baseline when it is in the run's scope.
    # A DIFFERENT run's ("legacy") medoid row must stay out of the run-scoped winners loader,
    # and the catalog-only query_analyze_metrics loader must never return the medoid row.
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
    seed_medoid_baseline(con, run_id="run-1", backbone="effnet", k=5, metrics={"map_k": 0.6})
    # catalog-only loader never surfaces the medoid row (pinned forever in test_report.py).
    cat = query_analyze_metrics(con, run_id="run-1")
    assert (cat["strategy_type"] == "catalog").all()
    assert "global_pool" not in set(cat["strategy_key"])
    # run-scoped winners loader sees the run-1 medoid baseline (0.6), never the legacy 0.99 row.
    rows = build_winner_delta_rows(query_winners_metrics(con, run_id="run-1"))
    assert not rows.empty
    r = rows.iloc[0]
    assert r["baseline_strategy_key"] == _ES
    assert r["baseline_value"] == pytest.approx(0.6)
    assert r["winner_strategy_key"] == catalog_key("effnet", "only")
    assert r["winner_value"] == pytest.approx(0.6)
    assert r["delta"] == pytest.approx(0.0)


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
    seed_medoid_baseline(con, run_id="run-1", backbone="effnet", k=5, metrics={"map_k": 0.5})
    seed_medoid_baseline(con, run_id="run-1", backbone="musicnn", k=5, metrics={"map_k": 0.5})
    rows = _winner_rows(con)
    assert set(rows["backbone"]) == {"effnet", "musicnn"}
    e = rows[rows["backbone"] == "effnet"].iloc[0]
    m = rows[rows["backbone"] == "musicnn"].iloc[0]
    # Each backbone's baseline is its OWN global_pool:{backbone}:medoid row (never cross-used).
    assert e["baseline_strategy_key"] == medoid_strategy_key_for("effnet")
    assert m["baseline_strategy_key"] == medoid_strategy_key_for("musicnn")
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
    seed_medoid_baseline(con, run_id="run-1", backbone="effnet", k=5, metrics={"map_k": 0.5})
    rows = _winner_rows(con, backbone="effnet")
    assert rows.iloc[0]["winner_strategy_key"] == catalog_key("effnet", "aab")
    assert rows.iloc[0]["baseline_strategy_key"] == _ES
    assert rows.iloc[0]["delta"] == pytest.approx(0.7 - 0.5)


def test_equal_representation_collapse_single_class_no_duplicate_rows(con):
    # Writing the same class twice (equal representation, config_ids=(1,2)) collapses to a single
    # canonical class with alias 2 and never duplicates metric/score rows.  One row per metric.
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
    seed_medoid_baseline(con, run_id="run-1", backbone="effnet", k=5, metrics={"map_k": 0.5, "mrr": 0.3})
    df = query_analyze_metrics(con)
    same = df[df["strategy_key"] == catalog_key("effnet", "same")]
    assert len(same) == 2  # one row per metric, not duplicated by the two writes
    assert sorted(int(x) for x in same.iloc[0]["alias_ids"]) == [2]
    rows = build_winner_delta_rows(query_winners_metrics(con))
    assert len(rows) == 2  # two metric cells


def test_empty_analysis_yields_empty_winner_rows(con):
    df = query_analyze_metrics(con)
    assert df.empty
    rows = build_winner_delta_rows(df)
    assert rows.empty
    assert list(rows.columns) == list(CATALOG_WINNER_DELTA_COLUMNS)


# --------------------------------------------------------------------------- #
# Observed global-medoid baseline (P1-S5/S6; consumed by the report in P1-S7)  #
# --------------------------------------------------------------------------- #
def test_baseline_is_observed_global_medoid_not_lowest_class():
    # Class A (config 2) is LOW value; class B (config 10) is HIGH.  Under the restored
    # observed-baseline contract the baseline is the global_pool:effnet:medoid row (value 0.5),
    # NOT the lowest-canonical-config class.
    df = _frame([_seg("lowval", 0.3, 2), _seg("highval", 0.9, 10), _medoid(0.5)])
    rows = _baseline_rows(df)
    assert len(rows) == 1
    r = rows.iloc[0]
    assert r["baseline_strategy_key"] == _ES
    assert r["baseline_value"] == pytest.approx(0.5)
    assert r["winner_strategy_key"] == catalog_key(_EB, "highval")
    assert r["winner_value"] == pytest.approx(0.9)
    assert r["delta"] == pytest.approx(0.4)


def test_medoid_never_a_winner_cell():
    # The medoid baseline is never a winner candidate even when it beats every segmented class.
    df = _frame([_seg("only", 0.4, 7), _medoid(0.99)])
    rows = _baseline_rows(df)
    assert len(rows) == 1
    r = rows.iloc[0]
    assert r["baseline_strategy_key"] == _ES
    assert r["winner_strategy_key"] == catalog_key(_EB, "only")
    assert r["baseline_value"] == pytest.approx(0.99)
    assert r["winner_value"] == pytest.approx(0.4)
    assert r["delta"] == pytest.approx(0.4 - 0.99)


def test_delta_row_for_every_segmented_result_cell_same_scope():
    # Two metric cells sharing the identical (backbone, corpus, sim_metric, k) scope each get a
    # finite delta row when the medoid baseline is present for that same scope.
    df = _frame(
        [
            {**_seg("a", 0.6, 1), "metric": "map_k"},
            {**_seg("a", 0.4, 1), "metric": "mrr"},
            {**_medoid(0.5), "metric": "map_k"},
            {**_medoid(0.3), "metric": "mrr"},
        ]
    )
    rows = _baseline_rows(df)
    assert sorted(set(rows["metric"])) == ["map_k", "mrr"]
    assert len(rows) == 2
    mk = rows[rows["metric"] == "map_k"].iloc[0]
    mr = rows[rows["metric"] == "mrr"].iloc[0]
    assert mk["delta"] == pytest.approx(0.6 - 0.5)
    assert mr["delta"] == pytest.approx(0.4 - 0.3)
    # A delta is emitted only where a segmented result shares the baseline's exact scope.
    assert list(rows.columns) == list(BASELINE_DELTA_COLUMNS)


def test_cell_without_medoid_baseline_emits_nothing():
    # A segmented result with NO observed medoid baseline row for its scope (e.g. the backbone
    # has no medoid in scope) must not emit a phantom delta; likewise a lone medoid row with no
    # segmented result emits nothing.
    df = _frame([_seg("a", 0.6, 1)])
    assert _baseline_rows(df).empty
    df2 = _frame([_medoid(0.5)])
    assert _baseline_rows(df2).empty


def test_baseline_delta_non_finite_fails_closed():
    df = _frame([_seg("a", 0.6, 1), _medoid(float("nan"))])
    with pytest.raises(ValueError):
        _baseline_rows(df)
    inf_df = _frame([_seg("a", float("inf"), 1), _medoid(0.5)])
    with pytest.raises(ValueError):
        _baseline_rows(inf_df)


def test_empty_baseline_frame_columns():
    rows = _baseline_rows(pd.DataFrame())
    assert rows.empty
    assert list(rows.columns) == list(BASELINE_DELTA_COLUMNS)
    assert _ES == "global_pool:effnet:medoid"
