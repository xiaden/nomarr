"""Unit tests for the embedding-research report layer."""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from scripts.embedding_research.db.head_phase import HeadPhaseProvenanceRow, write_head_phase_provenance
from scripts.embedding_research.report import _retrieval as retrieval_mod
from scripts.embedding_research.report._base import ANALYZE_METRICS_COLUMNS, _decode_strategy_key, empty_df
from scripts.embedding_research.report._binned import section_bin_mode_comparison, section_threshold_sweep
from scripts.embedding_research.report._corpus import disc_score_warning, section_corpus
from scripts.embedding_research.report._efficiency import section_efficiency
from scripts.embedding_research.report._heads import (
    section_head_output_shared_ptc_boundary,
    section_head_value,
)
from scripts.embedding_research.report._optimizer import section_optimizer
from scripts.embedding_research.report._retrieval import (
    query_analyze_metrics,
    section_per_backbone,
    section_unified_table,
)
from scripts.embedding_research.report._summary import section_summary
from scripts.embedding_research.report._winners import TRACE_SUMMARY_COLUMNS
from scripts.embedding_research.report._winners_report import section_winners

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_V2_KEYS = {
    "id",
    "title",
    "description",
    "stats",
    "charts",
    "tables",
    "panels",
    "subsections",
    "warnings",
    "headline",
    "empty_message",
}

_PIVOT_METRICS = [
    "disc_general",
    "disc_artist",
    "disc_genre",
    "disc_head",
    "disc_score",
    "mean_within",
    "mean_cross",
    "map_k",
    "mrr",
    "ndcg_k",
    "recall_k",
    "recall_k_genre",
    "precision_k_genre",
    "precision_k_head_mean",
    "flat_binned_spearman",
    "flat_binned_beneficial_reorder_rate",
]


def _empty_con():
    return duckdb.connect(":memory:")


def _minimal_unified_df(**overrides) -> pd.DataFrame:
    """Minimal unified result row with strategy_type='global_pool' by default."""
    row = dict.fromkeys(ANALYZE_METRICS_COLUMNS)
    row.update(
        strategy_key="global_pool:test_backbone:mean",
        strategy_type="global_pool",
        backbone="test_backbone",
        strategy="mean",
        sim_metric="cosine",
        k=10,
        disc_general=0.5,
        disc_artist=0.4,
        disc_genre=0.6,
        disc_head=0.3,
        disc_score=0.45,
        mean_within=0.7,
        mean_cross=0.4,
        map_k=0.5,
        mrr=0.55,
        ndcg_k=0.52,
        recall_k=0.6,
        recall_k_genre=0.65,
        precision_k_genre=0.58,
        precision_k_head_mean=0.5,
    )
    row.update(overrides)
    return pd.DataFrame([row], columns=ANALYZE_METRICS_COLUMNS)


def _minimal_ptc_df(**overrides) -> pd.DataFrame:
    """Minimal unified result row with strategy_type='ptc'."""
    row = dict.fromkeys(ANALYZE_METRICS_COLUMNS)
    row.update(
        strategy_key="ptc:test_backbone:temporal_global:1.0:mean:max:target_weighted",
        strategy_type="ptc",
        backbone="test_backbone",
        bin_mode="temporal_global",
        std_thresh=1.0,
        rep_a="mean",
        rep_b="max",
        agg_method="target_weighted",
        sim_metric="cosine",
        k=10,
        disc_general=0.5,
        disc_artist=0.4,
        disc_genre=0.65,
        disc_head=0.3,
        disc_score=0.45,
        mean_within=0.7,
        mean_cross=0.4,
        map_k=0.5,
        mrr=0.55,
        ndcg_k=0.52,
        recall_k=0.6,
        recall_k_genre=0.65,
        precision_k_genre=0.58,
        precision_k_head_mean=0.5,
        flat_binned_spearman=0.8,
        flat_binned_beneficial_reorder_rate=0.7,
    )
    row.update(overrides)
    return pd.DataFrame([row], columns=ANALYZE_METRICS_COLUMNS)


def _minimal_ctp_df(**overrides) -> pd.DataFrame:
    """Minimal unified result row with strategy_type='ctp'."""
    row = dict.fromkeys(ANALYZE_METRICS_COLUMNS)
    row.update(
        strategy_key="ctp:test_backbone:genre:1.0:median:max:bidirectional_weighted",
        strategy_type="ctp",
        backbone="test_backbone",
        std_thresh=1.0,
        rep_a="median",
        rep_b="max",
        agg_method="bidirectional_weighted",
        sim_metric="cosine",
        k=10,
        disc_general=0.55,
        disc_artist=0.42,
        disc_genre=0.68,
        disc_head=0.31,
        disc_score=0.48,
        mean_within=0.72,
        mean_cross=0.39,
        map_k=0.53,
        mrr=0.57,
        ndcg_k=0.54,
        recall_k=0.62,
        recall_k_genre=0.67,
        precision_k_genre=0.6,
        precision_k_head_mean=0.51,
        flat_binned_spearman=0.82,
        flat_binned_beneficial_reorder_rate=0.71,
    )
    row.update(overrides)
    return pd.DataFrame([row], columns=ANALYZE_METRICS_COLUMNS)


def _create_analyze_metrics_table(con) -> None:
    con.execute(
        """
        CREATE TABLE analyze_metrics (
            strategy_key VARCHAR,
            strategy_type VARCHAR,
            sim_metric VARCHAR,
            k INTEGER,
            metric VARCHAR,
            value DOUBLE
        )
        """
    )


def _insert_analyze_metrics_df(con, df: pd.DataFrame) -> None:
    rows: list[tuple[str, str, str, int, str, float]] = []
    for row in df.to_dict("records"):
        for metric in _PIVOT_METRICS:
            value = row.get(metric)
            if value is not None:
                rows.append(
                    (
                        str(row["strategy_key"]),
                        str(row["strategy_type"]),
                        str(row["sim_metric"]),
                        int(row["k"]),
                        metric,
                        float(value),
                    )
                )
    con.executemany("INSERT INTO analyze_metrics VALUES (?, ?, ?, ?, ?, ?)", rows)


# ---------------------------------------------------------------------------
# v2 schema / shared behavior
# ---------------------------------------------------------------------------


def test_all_sections_have_v2_keys():
    con = _empty_con()
    empty_metrics = empty_df(ANALYZE_METRICS_COLUMNS)

    sections = [
        ("corpus", section_corpus(con)),
        ("efficiency", section_efficiency(con)),
        ("optimizer", section_optimizer()),
        ("unified_table", section_unified_table(empty_metrics)),
        ("per_backbone", section_per_backbone(empty_metrics)),
        ("summary", section_summary(empty_metrics)),
        ("threshold_sweep", section_threshold_sweep(empty_metrics)),
        ("bin_mode_comparison", section_bin_mode_comparison(empty_metrics)),
    ]

    for name, result in sections:
        assert isinstance(result, dict), f"{name} did not return a dict"
        missing = _V2_KEYS - result.keys()
        assert not missing, f"{name} missing keys: {missing}"


# ---------------------------------------------------------------------------
# _decode_strategy_key
# ---------------------------------------------------------------------------


def test_decode_strategy_key_global_pool():
    decoded = _decode_strategy_key(_minimal_unified_df())
    row = decoded.iloc[0]

    assert row["backbone"] == "test_backbone"
    assert row["strategy"] == "mean"
    assert pd.isna(row["bin_mode"])
    assert pd.isna(row["std_thresh"])


def test_decode_strategy_key_ptc():
    decoded = _decode_strategy_key(_minimal_ptc_df())
    row = decoded.iloc[0]

    assert row["backbone"] == "test_backbone"
    assert row["bin_mode"] == "temporal_global"
    assert row["std_thresh"] == 1.0
    assert row["rep_a"] == "mean"
    assert row["rep_b"] == "max"
    assert row["agg_method"] == "target_weighted"


def test_decode_strategy_key_ctp():
    decoded = _decode_strategy_key(_minimal_ctp_df())
    row = decoded.iloc[0]

    assert row["backbone"] == "test_backbone"
    assert row["head"] == "genre"
    assert row["std_thresh"] == 1.0
    assert row["rep_a"] == "median"
    assert row["rep_b"] == "max"
    assert row["agg_method"] == "bidirectional_weighted"


def test_decode_strategy_key_empty_df():
    decoded = _decode_strategy_key(empty_df(ANALYZE_METRICS_COLUMNS))

    assert decoded.empty
    for column in ["backbone", "strategy", "bin_mode", "std_thresh", "rep_a", "rep_b", "agg_method"]:
        assert column in decoded.columns


def test_strategy_key_agg_method_roundtrips_weighted_name():
    """parts[6] (agg_method) round-trips a weighted aggregate name for ptc/ctp keys.

    Encodes a weighted aggregate at position 6 of both a ptc and a ctp strategy
    key, decodes via `_decode_strategy_key`, and asserts the name survives the
    round-trip (rep_a/rep_b positions remain representation TYPES).
    """
    df = pd.DataFrame(
        {
            "strategy_key": [
                "ptc:test_backbone:temporal_global:1.0:mean:max:target_weighted",
                "ctp:test_backbone:genre:1.0:median:max:bidirectional_weighted",
            ],
            "strategy_type": ["ptc", "ctp"],
        }
    )

    decoded = _decode_strategy_key(df)

    assert decoded.iloc[0]["agg_method"] == "target_weighted"
    assert decoded.iloc[1]["agg_method"] == "bidirectional_weighted"
    # Representation slots stay rep TYPES, not aggregation names.
    assert decoded.iloc[0]["rep_a"] == "mean"
    assert decoded.iloc[1]["rep_a"] == "median"


# ---------------------------------------------------------------------------
# query_analyze_metrics
# ---------------------------------------------------------------------------


def test_query_analyze_metrics_no_table():
    con = _empty_con()

    result = query_analyze_metrics(con)

    assert isinstance(result, pd.DataFrame)
    assert list(result.columns) == ANALYZE_METRICS_COLUMNS
    assert result.empty


def test_query_analyze_metrics_exception_path(monkeypatch):
    con = _empty_con()
    monkeypatch.setattr(retrieval_mod, "table_exists", lambda *_args, **_kwargs: True)

    result = query_analyze_metrics(con)

    assert isinstance(result, pd.DataFrame)
    assert list(result.columns) == ANALYZE_METRICS_COLUMNS
    assert result.empty


def test_query_analyze_metrics_data_path_filters_and_decodes():
    con = _empty_con()
    _create_analyze_metrics_table(con)
    valid_df = _minimal_unified_df()
    ignored_df = _minimal_unified_df(
        strategy_key="other:test_backbone:mean",
        strategy_type="other",
        disc_genre=0.91,
    )
    _insert_analyze_metrics_df(con, pd.concat([valid_df, ignored_df], ignore_index=True))

    result = query_analyze_metrics(con)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["strategy_type"] == "global_pool"
    assert row["backbone"] == "test_backbone"
    assert row["strategy"] == "mean"
    assert row["disc_genre"] == 0.6


def test_query_analyze_metrics_sort_order_multiple_rows():
    con = _empty_con()
    _create_analyze_metrics_table(con)
    lower_df = _minimal_unified_df(
        strategy_key="global_pool:test_backbone:mean",
        disc_general=0.3,
    )
    higher_df = _minimal_ptc_df(
        strategy_key="ptc:test_backbone:temporal_global:1.0:mean:max:normalized_mean_pair_weighted",
        disc_general=0.8,
    )
    _insert_analyze_metrics_df(con, pd.concat([lower_df, higher_df], ignore_index=True))

    result = query_analyze_metrics(con)

    assert len(result) == 2
    assert result["disc_general"].tolist() == [0.8, 0.3]
    assert result.iloc[0]["strategy_type"] == "ptc"
    assert result.iloc[1]["strategy_type"] == "global_pool"


def test_query_analyze_metrics_nulls_last_row_without_disc_general():
    con = _empty_con()
    _create_analyze_metrics_table(con)
    with_disc_general_df = _minimal_unified_df(
        strategy_key="global_pool:test_backbone:mean",
        disc_general=0.7,
    )
    null_disc_general_df = _minimal_ptc_df(
        strategy_key="ptc:test_backbone:temporal_global:1.0:mean:max:bidirectional_weighted",
        disc_general=None,
        map_k=0.9,
    )
    _insert_analyze_metrics_df(con, pd.concat([with_disc_general_df, null_disc_general_df], ignore_index=True))

    result = query_analyze_metrics(con)

    assert len(result) == 2
    assert result.iloc[0]["disc_general"] == 0.7
    assert pd.isna(result.iloc[1]["disc_general"])
    assert result.iloc[0]["strategy_type"] == "global_pool"
    assert result.iloc[1]["strategy_type"] == "ptc"


# ---------------------------------------------------------------------------
# section_unified_table
# ---------------------------------------------------------------------------


def test_section_unified_table_empty_returns_stub():
    result = section_unified_table(empty_df(ANALYZE_METRICS_COLUMNS))

    assert result["empty_message"]
    assert result["tables"] == []


def test_section_unified_table_with_global_pool_data():
    result = section_unified_table(_minimal_unified_df())

    assert not result["empty_message"]
    assert len(result["tables"]) >= 1


def test_section_unified_table_with_ptc_only_data():
    result = section_unified_table(_minimal_ptc_df())

    assert not result["empty_message"]
    assert len(result["tables"]) >= 1


def test_section_unified_table_with_mixed_data():
    df = pd.concat([_minimal_unified_df(), _minimal_ptc_df()], ignore_index=True)

    result = section_unified_table(df)
    table = result["tables"][0]
    type_idx = table["columns"].index("type")
    row_types = {row[type_idx] for row in table["rows"]}

    assert row_types == {"flat", "binned"}


def test_section_unified_table_sorts_by_map_k_general_then_artist():
    """Row with highest map_k_general should rank first in the top-20 table."""
    row_high_map_general = _minimal_unified_df(
        strategy_key="global_pool:bb_a:mean",
        backbone="bb_a",
        strategy="mean",
        map_k_general=0.91,
        map_k_artist=0.35,
        disc_genre=0.1,
        disc_score=0.95,
    )
    row_low_map_general = _minimal_unified_df(
        strategy_key="global_pool:bb_a:cls",
        backbone="bb_a",
        strategy="cls",
        map_k_general=0.42,
        map_k_artist=0.99,
        disc_genre=0.9,
        disc_score=0.1,
    )
    df = pd.concat([row_low_map_general, row_high_map_general], ignore_index=True)

    result = section_unified_table(df)
    table = result["tables"][0]
    map_k_general_idx = table["columns"].index("map_k_general")

    assert table["rows"][0][map_k_general_idx] == "0.9100"
    assert table["rows"][1][map_k_general_idx] == "0.4200"


# ---------------------------------------------------------------------------
# section_per_backbone
# ---------------------------------------------------------------------------


def test_section_per_backbone_empty():
    result = section_per_backbone(empty_df(ANALYZE_METRICS_COLUMNS))

    assert result["empty_message"]
    assert result["subsections"] == []


def test_section_per_backbone_with_data():
    df = pd.concat([_minimal_unified_df(), _minimal_ptc_df()], ignore_index=True)

    result = section_per_backbone(df)

    assert not result["empty_message"]
    assert len(result["subsections"]) == 1
    assert result["subsections"][0]["charts"] or result["subsections"][0]["tables"]


# ---------------------------------------------------------------------------
# section_summary
# ---------------------------------------------------------------------------


def test_section_summary_empty_returns_stub():
    result = section_summary(empty_df(ANALYZE_METRICS_COLUMNS))

    assert isinstance(result, dict)
    assert result.keys() >= _V2_KEYS
    assert result["empty_message"]


def test_section_summary_with_global_pool_and_binned_rows():
    df = pd.concat([_minimal_unified_df(), _minimal_ptc_df()], ignore_index=True)

    result = section_summary(df)

    assert not result["empty_message"]
    assert len(result["tables"]) == 1
    assert result["headline"] is not None


# ---------------------------------------------------------------------------
# binned sections
# ---------------------------------------------------------------------------


def test_section_threshold_sweep_empty():
    result = section_threshold_sweep(empty_df(ANALYZE_METRICS_COLUMNS))

    assert result["empty_message"]
    assert result["subsections"] == []


def test_section_threshold_sweep_with_data():
    df = pd.concat([_minimal_unified_df(), _minimal_ptc_df()], ignore_index=True)

    result = section_threshold_sweep(df)

    assert not result["empty_message"]
    assert len(result["subsections"]) == 1
    assert result["subsections"][0]["charts"] == []
    disc_diag_panels = [
        panel for panel in result["subsections"][0]["panels"] if "Discrimination Diagnostics" in panel["title"]
    ]

    assert len(disc_diag_panels) == 1
    assert {chart["id"] for chart in disc_diag_panels[0]["charts"]} == {
        "sweep_mean_test_backbone",
        "sweep_var_test_backbone",
        "sweep_kurt_test_backbone",
    }


def test_section_bin_mode_comparison_empty():
    result = section_bin_mode_comparison(empty_df(ANALYZE_METRICS_COLUMNS))

    assert result["empty_message"]
    assert result["subsections"] == []


def test_section_bin_mode_comparison_with_data():
    df = pd.concat(
        [
            _minimal_unified_df(),
            _minimal_ptc_df(bin_mode="temporal_global", disc_general=0.61),
            _minimal_ptc_df(
                strategy_key="ptc:test_backbone:temporal_perdim:1.0:mean:max:target_weighted",
                bin_mode="temporal_perdim",
                disc_general=0.59,
            ),
        ],
        ignore_index=True,
    )

    result = section_bin_mode_comparison(df)

    assert not result["empty_message"]
    assert len(result["subsections"]) == 1
    assert len(result["subsections"][0]["charts"]) == 1


# ---------------------------------------------------------------------------
# section_corpus / disc_score_warning (unchanged coverage)
# ---------------------------------------------------------------------------


def test_section_corpus_with_data():
    con = _empty_con()
    con.execute("CREATE TABLE songs (id VARCHAR, artist VARCHAR, album VARCHAR, title VARCHAR)")
    con.execute(
        """
        INSERT INTO songs VALUES
            ('1', 'Artist A', 'Album 1', 'Song 1'),
            ('2', 'Artist A', 'Album 1', 'Song 2'),
            ('3', 'Artist B', 'Album 2', 'Song 3'),
            ('4', 'Artist C', 'Album 3', 'Song 4'),
            ('5', 'Artist C', 'Album 3', 'Song 5')
        """
    )

    result = section_corpus(con)

    assert isinstance(result, dict)
    assert not result.get("empty_message"), (
        f"Expected populated corpus result, got empty_message={result['empty_message']!r}"
    )
    assert len(result["stats"]) > 0


def test_disc_score_warning_triggers_single_artist():
    """All songs from one artist → 'single_artist' error warning."""
    con = _empty_con()
    con.execute("CREATE TABLE songs (id VARCHAR, artist VARCHAR, album VARCHAR, title VARCHAR)")
    con.execute(
        """
        INSERT INTO songs VALUES
            ('1', 'Only Artist', 'Album 1', 'Song 1'),
            ('2', 'Only Artist', 'Album 1', 'Song 2'),
            ('3', 'Only Artist', 'Album 2', 'Song 3')
        """
    )

    warnings = disc_score_warning(con)

    assert isinstance(warnings, list)
    assert len(warnings) > 0
    assert any(w["id"] == "single_artist" for w in warnings)


def test_disc_score_warning_triggers_no_within_artist_pairs():
    """Every artist has exactly 1 song → 'no_within_artist_pairs' warning."""
    con = _empty_con()
    con.execute("CREATE TABLE songs (id VARCHAR, artist VARCHAR, album VARCHAR, title VARCHAR)")
    con.execute(
        """
        INSERT INTO songs VALUES
            ('1', 'Artist A', 'Album 1', 'Song 1'),
            ('2', 'Artist B', 'Album 2', 'Song 2'),
            ('3', 'Artist C', 'Album 3', 'Song 3')
        """
    )

    warnings = disc_score_warning(con)

    assert isinstance(warnings, list)
    assert len(warnings) > 0
    assert any(w["id"] == "no_within_artist_pairs" for w in warnings)


def test_analyze_metrics_columns_excludes_precision_k_head_mean():
    assert "precision_k_head_mean" not in ANALYZE_METRICS_COLUMNS


def test_analyze_metrics_columns_includes_new_map_metrics():
    expected_columns = {
        "map_k_artist",
        "map_k_genre",
        "map_k_head",
        "map_k_general",
        "var_ap_k_genre",
        "kurt_ap_k_genre",
        "var_mrr_genre",
        "kurt_mrr_genre",
    }

    assert expected_columns <= set(ANALYZE_METRICS_COLUMNS)


def test_analyze_metrics_columns_has_no_duplicates():
    assert len(ANALYZE_METRICS_COLUMNS) == len(set(ANALYZE_METRICS_COLUMNS))


def test_section_unified_table_columns_order_map_before_disc():
    result = section_unified_table(_minimal_unified_df(strategy_type="global_pool"))
    columns = result["tables"][0]["columns"]

    assert columns.index("map_k_general") < columns.index("disc_general")
    assert columns.index("map_k_artist") < columns.index("disc_artist")


def test_section_unified_table_backwards_compat_no_map_k_general():
    df = pd.concat(
        [
            _minimal_unified_df(strategy_key="global_pool:test_backbone:mean"),
            _minimal_unified_df(strategy_key="global_pool:test_backbone:cls", strategy="cls"),
        ],
        ignore_index=True,
    )

    result = section_unified_table(df)

    assert isinstance(result, dict)
    assert result.keys() >= _V2_KEYS
    assert not result["empty_message"]
    assert len(result["tables"]) == 1


def test_section_unified_table_output_excludes_precision_k_head_mean():
    """precision_k_head_mean was removed from table_columns even though flat_columns still lists it.

    This verifies the backward-compat contract: the intermediate reindex includes
    precision_k_head_mean (so old data won't crash), but the rendered table column
    list intentionally omits it.
    """
    result = section_unified_table(_minimal_unified_df())
    table = result["tables"][0]
    assert "precision_k_head_mean" not in table["columns"]


def test_section_threshold_sweep_map_chart_present_when_map_k_general_available():
    df = pd.concat(
        [empty_df(ANALYZE_METRICS_COLUMNS), _minimal_ptc_df(map_k_general=0.72)],
        ignore_index=True,
    )

    result = section_threshold_sweep(df)

    assert len(result["subsections"]) == 1
    assert len(result["subsections"][0]["charts"]) == 1
    assert result["subsections"][0]["charts"][0]["id"] == "sweep_map_test_backbone"


def test_section_bin_mode_comparison_uses_disc_col_as_fallback_when_no_map():
    df = pd.concat(
        [
            _minimal_ptc_df(map_k_general=None),
            _minimal_ptc_df(
                strategy_key="ptc:test_backbone:temporal_perdim:1.0:mean:max:target_weighted",
                bin_mode="temporal_perdim",
                map_k_general=None,
            ),
        ],
        ignore_index=True,
    )

    result = section_bin_mode_comparison(df)

    assert not result["empty_message"]
    assert "disc_" in result["description"]


def test_section_bin_mode_comparison_uses_map_k_general_when_available():
    df = pd.concat(
        [
            _minimal_ptc_df(map_k_general=0.65),
            _minimal_ptc_df(
                strategy_key="ptc:test_backbone:temporal_perdim:1.0:mean:max:target_weighted",
                bin_mode="temporal_perdim",
                map_k_general=0.58,
            ),
        ],
        ignore_index=True,
    )

    result = section_bin_mode_comparison(df)

    assert not result["empty_message"]
    assert "map_k_general" in result["description"]


# ---------------------------------------------------------------------------
# Phase 3 (Plan B) report adaptations
# ---------------------------------------------------------------------------


def _winner_delta_table(section: dict, backbone: str) -> dict:
    """The winner_delta table for a backbone subsection, for table-row extraction."""
    sub = next(s for s in section["subsections"] if s["id"] == f"winners-{backbone}")
    return next(t for t in sub["tables"] if t["id"] == f"winner_delta_{backbone}")


def _table_dicts(table: dict) -> list[dict]:
    """Convert a make_table descriptor back into a list of row dicts."""
    return [dict(zip(table["columns"], row, strict=False)) for row in table["rows"]]


def test_winners_excludes_ctp_primary_rows():
    # CTP row has the HIGHEST disc_general so, were it eligible, it would win the
    # general/discrimination cell. The narrowed primary grid must exclude it.
    df = pd.concat(
        [
            _minimal_unified_df(
                strategy_key="global_pool:EffNet:medoid",
                backbone="EffNet",
                strategy="medoid",
                disc_general=0.4,
            ),
            _minimal_ptc_df(
                strategy_key="ptc:EffNet:temporal_global:1.0:medoid:medoid:max_per_candidate_segment",
                backbone="EffNet",
                std_thresh=1.0,
                rep_a="medoid",
                rep_b="medoid",
                agg_method="max_per_candidate_segment",
                disc_general=0.6,
            ),
            _minimal_ctp_df(
                strategy_key="ctp:EffNet:genre:1.0:median:max:target_weighted",
                backbone="EffNet",
                head="genre",
                disc_general=0.99,
            ),
        ],
        ignore_index=True,
    )

    section = section_winners(df)

    rows = _table_dicts(_winner_delta_table(section, "EffNet"))
    assert rows, "expected at least one winner-delta row"
    assert all(r["winner_strategy_type"] != "ctp" for r in rows)
    assert all("ctp:" not in str(r["winner_strategy_key"]) for r in rows)
    # The general discrimination cell is won by the best PTC row, not the CTP row.
    general_disc = [r for r in rows if r["group"] == "general" and r["metric"] == "discrimination"]
    assert general_disc, "expected a general discrimination cell"
    assert (
        general_disc[0]["winner_strategy_key"]
        == "ptc:EffNet:temporal_global:1.0:medoid:medoid:max_per_candidate_segment"
    )


def test_winners_each_threshold_identity_present():
    # Two PTC thresholds each win a different cell: threshold identity is never
    # collapsed into an averaged configuration.
    df = pd.concat(
        [
            _minimal_unified_df(
                strategy_key="global_pool:EffNet:medoid",
                backbone="EffNet",
                strategy="medoid",
                disc_artist=0.2,
                disc_genre=0.2,
            ),
            _minimal_ptc_df(
                strategy_key="ptc:EffNet:temporal_global:1.0:medoid:medoid:max_per_candidate_segment",
                backbone="EffNet",
                std_thresh=1.0,
                rep_a="medoid",
                rep_b="medoid",
                agg_method="max_per_candidate_segment",
                disc_artist=0.7,
                disc_genre=0.4,
            ),
            _minimal_ptc_df(
                strategy_key="ptc:EffNet:temporal_global:2.0:medoid:medoid:max_per_candidate_segment",
                backbone="EffNet",
                std_thresh=2.0,
                rep_a="medoid",
                rep_b="medoid",
                agg_method="max_per_candidate_segment",
                disc_artist=0.4,
                disc_genre=0.7,
            ),
        ],
        ignore_index=True,
    )

    section = section_winners(df)

    rows = _table_dicts(_winner_delta_table(section, "EffNet"))
    keys = {str(r["winner_strategy_key"]) for r in rows}
    assert "ptc:EffNet:temporal_global:1.0:medoid:medoid:max_per_candidate_segment" in keys
    assert "ptc:EffNet:temporal_global:2.0:medoid:medoid:max_per_candidate_segment" in keys


def test_winners_exact_trace_columns():
    ptc = _minimal_ptc_df(
        strategy_key="ptc:EffNet:temporal_global:1.0:medoid:medoid:max_per_candidate_segment",
        backbone="EffNet",
        std_thresh=1.0,
        rep_a="medoid",
        rep_b="medoid",
        agg_method="max_per_candidate_segment",
        disc_general=0.6,
    )
    for col in TRACE_SUMMARY_COLUMNS:
        ptc[col] = 0
    ptc["trace_collision_count"] = 3
    ptc["trace_winner_count"] = 5
    ptc["trace_retained_contributions"] = 8
    ptc["trace_dropped_contributions"] = 1
    medoid = _minimal_unified_df(
        strategy_key="global_pool:EffNet:medoid",
        backbone="EffNet",
        strategy="medoid",
        disc_general=0.3,
    )
    df = pd.concat([medoid, ptc], ignore_index=True)

    section = section_winners(df)

    table = _winner_delta_table(section, "EffNet")
    for col in TRACE_SUMMARY_COLUMNS:
        assert col in table["columns"], f"missing trace column {col}"
    rows = _table_dicts(table)
    ptc_rows = [
        r
        for r in rows
        if r["winner_strategy_key"] == "ptc:EffNet:temporal_global:1.0:medoid:medoid:max_per_candidate_segment"
    ]
    assert ptc_rows, "expected the PTC row to win a cell"
    assert ptc_rows[0]["trace_collision_count"] == "3.0000"
    assert ptc_rows[0]["trace_retained_contributions"] == "8.0000"
    assert ptc_rows[0]["winner_ambiguity_variant"] == "first_index + retain_all_candidate_segments"


def test_winner_rows_carry_score_and_ambiguity_variant_factors():
    df = pd.concat(
        [
            _minimal_unified_df(
                strategy_key="global_pool:EffNet:medoid",
                backbone="EffNet",
                strategy="medoid",
                disc_general=0.3,
            ),
            _minimal_ptc_df(
                strategy_key="ptc:EffNet:temporal_global:1.0:medoid:medoid:max_per_candidate_segment",
                backbone="EffNet",
                std_thresh=1.0,
                rep_a="medoid",
                rep_b="medoid",
                agg_method="max_per_candidate_segment",
                disc_general=0.6,
            ),
        ],
        ignore_index=True,
    )

    section = section_winners(df)

    rows = _table_dicts(_winner_delta_table(section, "EffNet"))
    for r in rows:
        assert r["winner_aggregate"] == "max_per_candidate_segment"
        assert r["winner_ambiguity_variant"] == "first_index + retain_all_candidate_segments"
    # The factor summary table groups by score-variant and ambiguity-variant factors.
    sub = next(s for s in section["subsections"] if s["id"] == "winners-EffNet")
    factor_table = next(t for t in sub["tables"] if t["id"] == "factor_summary_EffNet")
    factor_rows = _table_dicts(factor_table)
    assert any(r["factor"] == "score_variant" and r["factor_value"] == "max_per_candidate_segment" for r in factor_rows)
    assert any(
        r["factor"] == "ambiguity_variant" and r["factor_value"] == "first_index + retain_all_candidate_segments"
        for r in factor_rows
    )


def test_explicit_lens_wording_in_sections():
    df = pd.concat(
        [
            _minimal_unified_df(
                strategy_key="global_pool:test_backbone:medoid",
                strategy="medoid",
                disc_general=0.3,
            ),
            _minimal_ptc_df(disc_general=0.6),
        ],
        ignore_index=True,
    )

    summary = section_summary(df)
    assert "evaluation lens" in summary["description"]
    assert "not an optimization objective" in summary["description"]

    winners = section_winners(df)
    assert "evaluation lens" in winners["description"]
    assert "not optimization objectives" in winners["description"]

    unified = section_unified_table(df)
    assert "evaluation lens" in unified["description"]


def test_head_value_archival_ctp_note():
    con = _empty_con()
    con.execute(
        "CREATE TABLE ptc_ctp_rows (backbone VARCHAR, head VARCHAR, strategy VARCHAR, "
        "ptc_disc DOUBLE, ctp_disc DOUBLE, delta_disc DOUBLE)"
    )
    con.execute("INSERT INTO ptc_ctp_rows VALUES ('effnet', 'genre', 's1', 0.5, 0.6, 0.1)")

    section = section_head_value(con)

    assert section["id"] == "head-value"
    assert "Archival" in section["title"]
    assert section["warnings"], "archival CTP note must carry a warning"
    assert "archival" in section["description"].lower()
    # It must not present CTP as a primary winner/delta surface.
    assert "winner" not in section["description"].lower() or "never a primary winner" in section["description"].lower()


def test_head_output_shared_ptc_boundary_subsections():
    con = _empty_con()
    con.execute(
        "CREATE TABLE head_phase_provenance (backbone VARCHAR, head VARCHAR, bin_mode VARCHAR, "
        "threshold DOUBLE, boundary_source VARCHAR, head_pool_variant VARCHAR, status VARCHAR, "
        "reason VARCHAR, n_songs INTEGER, n_pooled INTEGER, finite INTEGER, "
        "scoring_semantics_version INTEGER, reference_corpus_hash VARCHAR, "
        "UNIQUE (backbone, head, bin_mode, threshold, boundary_source, head_pool_variant))"
    )
    write_head_phase_provenance(
        con,
        [
            HeadPhaseProvenanceRow(
                backbone="effnet",
                head="genre",
                bin_mode="temporal_global",
                threshold=1.0,
                status="done",
                n_songs=100,
                n_pooled=95,
            )
        ],
    )

    section = section_head_output_shared_ptc_boundary(con)

    assert section["id"] == "head-output-shared-ptc-boundary"
    assert section["tables"], "expected a provenance table"
    table = next(t for t in section["tables"] if t["id"] == "head_phase_provenance")
    rows = _table_dicts(table)
    assert rows
    assert rows[0]["boundary_source"] == "effnet_ptc"
    assert rows[0]["coverage"] == "95.0%"
    assert rows[0]["n_pooled"] == "95"

    # No head-phase data -> empty section with a missing-data warning.
    empty_con = _empty_con()
    empty_section = section_head_output_shared_ptc_boundary(empty_con)
    assert empty_section["empty_message"]
    assert empty_section["warnings"]


def test_head_output_shared_ptc_boundary_manifest_done_zero_warning():
    class _Manifest:
        errors = 0
        done = 0
        skipped = 2
        results = ()  # no records at all => sum(n_pooled) == 0

    empty_con = _empty_con()
    section = section_head_output_shared_ptc_boundary(empty_con, manifest=_Manifest())

    assert section["id"] == "head-output-shared-ptc-boundary"
    assert any("no pooled output" in w["message"] for w in section["warnings"])


def test_head_output_shared_ptc_boundary_no_warning_when_cached_rerun_has_coverage():
    """A fully-cached rerun (done==0) with n_pooled==n_songs>0 must NOT warn.

    ``manifest.done == 0`` alone used to trigger the "outputs are unavailable"
    warning even when every row's cached output was still available (100% coverage).
    Now the warning only fires when there is genuinely no pooled output
    (sum(n_pooled) == 0).
    """
    import types

    rec = types.SimpleNamespace(head="genre", n_songs=50, n_pooled=50)

    class _Manifest:
        errors = 0
        done = 0
        skipped = 0
        results = (rec,)

    empty_con = _empty_con()
    section = section_head_output_shared_ptc_boundary(empty_con, manifest=_Manifest())

    assert section["id"] == "head-output-shared-ptc-boundary"
    assert not any("no pooled output" in w["message"] for w in section["warnings"])


# ---------------------------------------------------------------------------
# section_bin_mode_comparison — explicit per-configuration grouping
# ---------------------------------------------------------------------------


def test_bin_mode_comparison_keeps_configs_separate():
    """Configs sharing bin_mode/std_thresh but differing in rep_a/agg_method stay separate.

    A regression to naive per-bin-mode averaging would collapse the two rep_a/agg_method
    configs into a single global + single perdim trace. This test requires one labeled
    trace per explicit (rep_a, rep_b, agg_method) configuration.
    """
    df = pd.concat(
        [
            _minimal_ptc_df(
                strategy_key="ptc:test_backbone:temporal_global:1.0:mean:max:target_weighted",
                bin_mode="temporal_global",
                rep_a="mean",
                agg_method="target_weighted",
                disc_general=0.8,
            ),
            _minimal_ptc_df(
                strategy_key="ptc:test_backbone:temporal_perdim:1.0:mean:max:target_weighted",
                bin_mode="temporal_perdim",
                rep_a="mean",
                agg_method="target_weighted",
                disc_general=0.3,
            ),
            _minimal_ptc_df(
                strategy_key="ptc:test_backbone:temporal_global:1.0:median:max:target_weighted",
                bin_mode="temporal_global",
                rep_a="median",
                agg_method="target_weighted",
                disc_general=0.2,
            ),
            _minimal_ptc_df(
                strategy_key="ptc:test_backbone:temporal_perdim:1.0:median:max:target_weighted",
                bin_mode="temporal_perdim",
                rep_a="median",
                agg_method="target_weighted",
                disc_general=0.7,
            ),
        ],
        ignore_index=True,
    )

    result = section_bin_mode_comparison(df)
    sub = result["subsections"][0]
    figure = sub["charts"][0]["figure"]
    trace_names = [t["name"] for t in figure["data"]]

    global_traces = [n for n in trace_names if n.startswith("global")]
    assert len(global_traces) == 2, f"expected 2 distinct global config traces, got {global_traces}"
    assert any("meanxmax/target-wtd" in n for n in global_traces)
    assert any("coord-medianxmax/target-wtd" in n for n in global_traces)


def test_bin_mode_comparison_no_matching_config_pairs_verdict():
    """When global/perdim config identities never align, the verdict says so explicitly."""
    df = pd.concat(
        [
            _minimal_ptc_df(
                strategy_key="ptc:test_backbone:temporal_global:1.0:mean:max:target_weighted",
                bin_mode="temporal_global",
                rep_a="mean",
                disc_general=0.8,
            ),
            _minimal_ptc_df(
                strategy_key="ptc:test_backbone:temporal_perdim:1.0:median:max:target_weighted",
                bin_mode="temporal_perdim",
                rep_a="median",
                disc_general=0.7,
            ),
        ],
        ignore_index=True,
    )

    result = section_bin_mode_comparison(df)
    sub = result["subsections"][0]
    assert "No matching (rep_a, rep_b, agg_method) configuration pairs found" in sub["description"]
    assert "comparison requires identical config identities" in sub["description"]


def test_bin_mode_comparison_opposing_winners_per_config():
    """Global wins one config, perdim wins another -> both counted (1v1), never collapsed."""
    df = pd.concat(
        [
            # Config A (mean): global wins (0.8 > 0.3)
            _minimal_ptc_df(
                strategy_key="ptc:test_backbone:temporal_global:1.0:mean:max:target_weighted",
                bin_mode="temporal_global",
                rep_a="mean",
                disc_general=0.8,
            ),
            _minimal_ptc_df(
                strategy_key="ptc:test_backbone:temporal_perdim:1.0:mean:max:target_weighted",
                bin_mode="temporal_perdim",
                rep_a="mean",
                disc_general=0.3,
            ),
            # Config B (median): perdim wins (0.2 < 0.7)
            _minimal_ptc_df(
                strategy_key="ptc:test_backbone:temporal_global:1.0:median:max:target_weighted",
                bin_mode="temporal_global",
                rep_a="median",
                disc_general=0.2,
            ),
            _minimal_ptc_df(
                strategy_key="ptc:test_backbone:temporal_perdim:1.0:median:max:target_weighted",
                bin_mode="temporal_perdim",
                rep_a="median",
                disc_general=0.7,
            ),
        ],
        ignore_index=True,
    )

    result = section_bin_mode_comparison(df)
    sub = result["subsections"][0]
    # Both explicit configs are counted as comparison pairs; each wins one.
    assert "global wins 1, perdim wins 1, ties 0" in sub["description"]
    assert "Both modes perform equivalently for this backbone." in sub["description"]
