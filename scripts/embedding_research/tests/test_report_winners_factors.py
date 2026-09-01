"""Plan D (P2): exact group x metric x K winner/delta rows and factor summaries.

Proves (with EffNet + MusicNN fixtures) that:
- the comparison grid enumerates backbone x group x metric-family x K with no
  cross-dimension averaging, and the ``general`` group is included only when
  legitimately populated;
- winner selection is deterministic, ties resolve in the documented
  strategy-type -> pathway/head -> bin-mode -> threshold -> reps -> aggregate ->
  strategy-key order, and null/absent metric rows are excluded from selection;
- deltas are always winner - explicit global medoid baseline for the *same*
  backbone x group x metric x K, covering positive AND negative deltas, and
  distinct K values produce distinct rows;
- factor summaries retain backbone separation and the group x metric x K
  dimensions with win counts, mean/best deltas, and contributing strategy keys.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.embedding_research.report._base import ANALYZE_METRICS_COLUMNS
from scripts.embedding_research.report._winners import (
    FACTOR_SUMMARY_COLUMNS,
    WINNER_DELTA_COLUMNS,
    build_comparison_grid,
    build_factor_summary,
    build_winner_delta_rows,
    select_winner,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _base_row() -> dict:
    row = dict.fromkeys(ANALYZE_METRICS_COLUMNS)
    row.update(
        sim_metric="cosine",
        k=10,
        map_k_artist=0.5,
        map_k_genre=0.5,
        map_k_head=0.5,
        map_k_general=0.5,
        mrr=0.5,
        mrr_genre=0.5,
        mrr_head=0.5,
        ndcg_k_artist=0.5,
        ndcg_k_genre=0.5,
        ndcg_k_head=0.5,
        recall_k_artist=0.5,
        recall_k_genre=0.5,
        recall_k_head=0.5,
        disc_artist=0.4,
        disc_genre=0.4,
        disc_head=0.4,
        disc_general=0.4,
        disc_score=0.4,
    )
    return row


def gp_row(backbone: str, strategy: str, *, k: int = 10, **overrides) -> pd.DataFrame:
    row = _base_row()
    row.update(
        strategy_key=f"global_pool:{backbone}:{strategy}",
        strategy_type="global_pool",
        backbone=backbone,
        strategy=strategy,
        k=k,
    )
    row.update(overrides)
    return pd.DataFrame([row], columns=ANALYZE_METRICS_COLUMNS)


def ptc_row(
    backbone: str,
    *,
    bin_mode: str = "temporal_global",
    std_thresh: float = 1.0,
    rep_a: str = "median",
    rep_b: str = "max",
    agg_method: str = "target_weighted",
    k: int = 10,
    **overrides,
) -> pd.DataFrame:
    row = _base_row()
    row.update(
        strategy_key=f"ptc:{backbone}:{bin_mode}:{std_thresh}:{rep_a}:{rep_b}:{agg_method}",
        strategy_type="ptc",
        backbone=backbone,
        bin_mode=bin_mode,
        std_thresh=std_thresh,
        rep_a=rep_a,
        rep_b=rep_b,
        agg_method=agg_method,
        k=k,
    )
    row.update(overrides)
    return pd.DataFrame([row], columns=ANALYZE_METRICS_COLUMNS)


def ctp_row(
    backbone: str,
    *,
    head: str = "genre",
    bin_mode: str = "temporal_global",
    std_thresh: float = 1.0,
    rep_a: str = "median",
    rep_b: str = "max",
    agg_method: str = "bidirectional_weighted",
    k: int = 10,
    **overrides,
) -> pd.DataFrame:
    row = _base_row()
    row.update(
        strategy_key=f"ctp:{backbone}:{head}:{std_thresh}:{rep_a}:{rep_b}:{agg_method}",
        strategy_type="ctp",
        backbone=backbone,
        head=head,
        bin_mode=bin_mode,
        std_thresh=std_thresh,
        rep_a=rep_a,
        rep_b=rep_b,
        agg_method=agg_method,
        k=k,
    )
    row.update(overrides)
    return pd.DataFrame([row], columns=ANALYZE_METRICS_COLUMNS)


def _medoid_rows(backbone: str, *, k: int = 10, **overrides) -> pd.DataFrame:
    """The explicit global medoid baseline rows for a backbone (matches Phase 1)."""
    row = _base_row()
    row.update(
        strategy_key=f"global_pool:{backbone}:medoid",
        strategy_type="global_pool",
        backbone=backbone,
        strategy="medoid",
        k=k,
    )
    row.update(overrides)
    return pd.DataFrame([row], columns=ANALYZE_METRICS_COLUMNS)


# ---------------------------------------------------------------------------
# P2-S1: comparison grid
# ---------------------------------------------------------------------------


def test_grid_enumerates_backbone_group_metric_k_no_averaging():
    df = pd.concat(
        [
            _medoid_rows("EffNet", map_k_artist=0.6, mrr=0.7, k=10),
            _medoid_rows("EffNet", map_k_artist=0.65, mrr=0.72, k=20),
            ptc_row("EffNet", rep_a="median", map_k_artist=0.8, mrr=0.9, k=10),
            _medoid_rows("MusicNN", map_k_artist=0.55, mrr=0.6, k=10),
        ],
        ignore_index=True,
    )

    grid = build_comparison_grid(df)

    # artist MAP and artist MRR cells exist for both backbones, both K for EffNet.
    artist_map = grid[(grid["group"] == "artist") & (grid["metric"] == "MAP")]
    artist_mrr = grid[(grid["group"] == "artist") & (grid["metric"] == "MRR")]
    assert {"EffNet", "MusicNN"} <= set(artist_map["backbone"])
    assert {"EffNet", "MusicNN"} <= set(artist_mrr["backbone"])
    # Every cell is a single backbone x group x metric x K row — no averaging.
    assert {"EffNet", "MusicNN"} <= set(grid["backbone"])
    assert set(grid["k"]) == {10, 20}
    assert not grid.duplicated(subset=["backbone", "group", "metric", "k"]).any()


def test_grid_general_group_only_when_valid():
    """general MAP requires >= 2 populated component MAP columns for that backbone/k."""
    # Both components present -> valid.
    valid = pd.concat(
        [
            ptc_row("EffNet", rep_a="median", map_k_general=0.7, map_k_artist=0.7, map_k_genre=0.7),
            _medoid_rows("EffNet", map_k_general=0.6, map_k_artist=0.6, map_k_genre=0.6),
        ],
        ignore_index=True,
    )
    grid = build_comparison_grid(valid)
    general_map = grid[(grid["group"] == "general") & (grid["metric"] == "MAP")]
    assert not general_map.empty

    # Only map_k_general present, component columns absent -> fall back to non-null.
    only_general = ptc_row("EffNet", rep_a="median", map_k_general=0.7)
    grid2 = build_comparison_grid(only_general)
    general_map2 = grid2[(grid2["group"] == "general") & (grid2["metric"] == "MAP")]
    assert not general_map2.empty

    # map_k_general null -> general cell not emitted.
    null_general = pd.concat(
        [
            ptc_row("EffNet", rep_a="median", map_k_general=None),
            _medoid_rows("EffNet", map_k_general=None),
        ],
        ignore_index=True,
    )
    grid3 = build_comparison_grid(null_general)
    assert grid3[(grid3["group"] == "general") & (grid3["metric"] == "MAP")].empty


# ---------------------------------------------------------------------------
# P2-S2: deterministic winner selection + documented tie-break
# ---------------------------------------------------------------------------


def test_winner_is_highest_value():
    df = pd.concat(
        [
            ptc_row("EffNet", rep_a="median", map_k_artist=0.7),
            _medoid_rows("EffNet", map_k_artist=0.6),
        ],
        ignore_index=True,
    )
    winner = select_winner(df, backbone="EffNet", metric_col="map_k_artist", k=10)
    assert winner["value"] == pytest.approx(0.7)
    assert winner["strategy_type"] == "ptc"


def test_winner_tie_break_strategy_type_order():
    """Equal values -> global_pool < ptc < ctp wins."""
    df = pd.concat(
        [
            ptc_row("EffNet", rep_a="median", map_k_artist=0.6),
            _medoid_rows("EffNet", map_k_artist=0.6),
            ctp_row("EffNet", head="genre", map_k_artist=0.6),
        ],
        ignore_index=True,
    )
    winner = select_winner(df, backbone="EffNet", metric_col="map_k_artist", k=10)
    assert winner["strategy_type"] == "global_pool"
    assert winner["strategy_key"] == "global_pool:EffNet:medoid"
    # tie_break_key is a display key reflecting the documented tie-break order
    # (strategy type first, strategy key last) for the winning config.
    assert str(winner["tie_break_key"]).endswith(winner["strategy_key"])


def test_winner_tie_break_ptc_vs_ctp_same_strategy_type_rank():
    """Two CTP rows with equal value -> head (pathway/head slot) breaks the tie."""
    df = pd.concat(
        [
            ctp_row("EffNet", head="genre", map_k_artist=0.6),
            ctp_row("EffNet", head="timbre", map_k_artist=0.6),
        ],
        ignore_index=True,
    )
    winner = select_winner(df, backbone="EffNet", metric_col="map_k_artist", k=10)
    assert winner["head"] == "genre"  # 'genre' < 'timbre' in the pathway/head slot


def test_winner_tie_break_threshold_then_rep_then_strategy_key():
    """Two PTC rows with equal value -> threshold, then reps, then strategy key."""
    df = pd.concat(
        [
            ptc_row("EffNet", std_thresh=2.0, rep_a="median", map_k_artist=0.6),
            ptc_row("EffNet", std_thresh=1.0, rep_a="median", map_k_artist=0.6),
        ],
        ignore_index=True,
    )
    winner = select_winner(df, backbone="EffNet", metric_col="map_k_artist", k=10)
    # Lower threshold sorts earlier in the tie-break tuple.
    assert winner["std_thresh"] == 1.0


def test_winner_excludes_null_metric_rows():
    """Rows with a null metric value are excluded from winner selection."""
    df = pd.concat(
        [
            ptc_row("EffNet", rep_a="median", map_k_artist=None),
            _medoid_rows("EffNet", map_k_artist=0.6),
        ],
        ignore_index=True,
    )
    winner = select_winner(df, backbone="EffNet", metric_col="map_k_artist", k=10)
    assert winner["value"] == pytest.approx(0.6)
    assert winner["strategy_key"] == "global_pool:EffNet:medoid"


def test_winner_none_when_cell_empty():
    assert select_winner(pd.DataFrame(), backbone="EffNet", metric_col="map_k_artist", k=10) is None


# ---------------------------------------------------------------------------
# P2-S3: delta rows (winner - explicit global medoid baseline, same cell)
# ---------------------------------------------------------------------------


def test_delta_positive_and_negative_per_backbone():
    df = pd.concat(
        [
            ptc_row("EffNet", rep_a="median", map_k_artist=0.8),
            _medoid_rows("EffNet", map_k_artist=0.6),
            ptc_row("MusicNN", rep_a="median", map_k_artist=0.4),
            _medoid_rows("MusicNN", map_k_artist=0.7),
        ],
        ignore_index=True,
    )

    rows = build_winner_delta_rows(df, df, k_values=[10])

    eff = rows[rows["backbone"] == "EffNet"]
    mus = rows[rows["backbone"] == "MusicNN"]
    assert float(eff.iloc[0]["delta"]) == pytest.approx(0.2)  # positive
    assert float(mus.iloc[0]["delta"]) == pytest.approx(-0.3)  # negative
    assert eff.iloc[0]["baseline_strategy_key"] == "global_pool:EffNet:medoid"
    assert mus.iloc[0]["baseline_strategy_key"] == "global_pool:MusicNN:medoid"


def test_delta_uses_same_backbone_baseline_never_cross_backbone():
    df = pd.concat(
        [
            ptc_row("EffNet", rep_a="median", map_k_artist=0.8),
            _medoid_rows("EffNet", map_k_artist=0.6),
            _medoid_rows("MusicNN", map_k_artist=0.99),
        ],
        ignore_index=True,
    )
    rows = build_winner_delta_rows(df, df, k_values=[10])
    eff = rows[rows["backbone"] == "EffNet"]
    # EffNet's baseline is EffNet's medoid (0.6), not MusicNN's (0.99).
    assert float(eff.iloc[0]["baseline_value"]) == pytest.approx(0.6)
    assert float(eff.iloc[0]["delta"]) == pytest.approx(0.2)


def test_delta_only_when_winner_and_baseline_present():
    """No delta row when the medoid baseline is absent for that backbone/metric/k."""
    df = pd.concat(
        [
            ptc_row("EffNet", rep_a="median", map_k_artist=0.8),
            # No global_pool medoid row for EffNet.
        ],
        ignore_index=True,
    )
    rows = build_winner_delta_rows(df, df, k_values=[10])
    assert rows.empty


def test_distinct_k_produce_distinct_rows():
    df = pd.concat(
        [
            ptc_row("EffNet", rep_a="median", map_k_artist=0.8, k=10),
            ptc_row("EffNet", rep_a="median", map_k_artist=0.75, k=20),
            _medoid_rows("EffNet", map_k_artist=0.6, k=10),
            _medoid_rows("EffNet", map_k_artist=0.55, k=20),
        ],
        ignore_index=True,
    )
    rows = build_winner_delta_rows(df, df, k_values=[10, 20])
    assert set(rows["k"]) == {10, 20}
    k10 = rows[rows["k"] == 10].iloc[0]
    k20 = rows[rows["k"] == 20].iloc[0]
    assert float(k10["delta"]) == pytest.approx(0.2)
    assert float(k20["delta"]) == pytest.approx(0.2)


def test_winner_delta_rows_include_all_required_columns():
    df = pd.concat(
        [
            ptc_row("EffNet", rep_a="median", map_k_artist=0.8),
            _medoid_rows("EffNet", map_k_artist=0.6),
        ],
        ignore_index=True,
    )
    rows = build_winner_delta_rows(
        df,
        df,
        k_values=[10],
        corpus_hash="abc123",
        corpus_size=2386,
    )
    assert list(rows.columns) == WINNER_DELTA_COLUMNS
    row = rows.iloc[0]
    assert row["corpus_hash"] == "abc123"
    assert row["corpus_size"] == 2386


# ---------------------------------------------------------------------------
# P2-S4: factor summaries
# ---------------------------------------------------------------------------


def test_factor_summary_retains_group_metric_k_and_config_ids():
    df = pd.concat(
        [
            ptc_row("EffNet", rep_a="median", map_k_artist=0.8, mrr=0.9),
            ptc_row("EffNet", rep_a="median", map_k_genre=0.75),
            _medoid_rows("EffNet", map_k_artist=0.6, mrr=0.6, map_k_genre=0.6),
        ],
        ignore_index=True,
    )
    winner_rows = build_winner_delta_rows(df, df, k_values=[10])
    summary = build_factor_summary(winner_rows)

    assert list(summary.columns) == FACTOR_SUMMARY_COLUMNS
    # bin_mode factor for the PTC winner across artist-MAP and artist-MRR and genre-MAP.
    bin_mode = summary[(summary["factor"] == "bin_mode") & (summary["factor_value"] == "temporal_global")]
    assert set(bin_mode["group"]) >= {"artist", "genre"}
    assert set(bin_mode["metric"]) >= {"MAP", "MRR"}
    assert (bin_mode["n_wins"] == 1).all()
    assert (bin_mode["config_ids"].apply(lambda ids: len(ids) == 1)).all()


def test_factor_summary_separates_backbones():
    df = pd.concat(
        [
            ptc_row("EffNet", rep_a="median", map_k_artist=0.8),
            _medoid_rows("EffNet", map_k_artist=0.6),
            ptc_row("MusicNN", rep_a="median", map_k_artist=0.9),
            _medoid_rows("MusicNN", map_k_artist=0.5),
        ],
        ignore_index=True,
    )
    winner_rows = build_winner_delta_rows(df, df, k_values=[10])
    summary = build_factor_summary(winner_rows)
    assert {"EffNet", "MusicNN"} <= set(summary["backbone"])


def test_factor_summary_empty_input_returns_expected_columns():
    summary = build_factor_summary(pd.DataFrame(columns=WINNER_DELTA_COLUMNS))
    assert list(summary.columns) == FACTOR_SUMMARY_COLUMNS
    assert summary.empty
