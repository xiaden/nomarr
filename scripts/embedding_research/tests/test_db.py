"""Unit tests for scripts/embedding_research/db/ database layer.

All tests use an in-memory DuckDB connection -- no file I/O.
"""

from __future__ import annotations

import logging

import duckdb
import pandas as pd
import pytest

from scripts.embedding_research.db import load_analyze_metrics, write_analyze_metrics
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.db.flat import (
    head_strategy_done,
    query_flat_head_labels,
    upsert_flat_head_labels,
    upsert_head,
)
from scripts.embedding_research.db.queries import query_analysis_done

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def con():
    """In-memory DuckDB connection with schema initialised."""
    c = duckdb.connect(":memory:")
    ensure_schema(c)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# 1. Schema
# ---------------------------------------------------------------------------


EXPECTED_TABLES = {
    "songs",
    "pooled_vecs",
    "head_results",
    "flat_head_labels",
    "analyze_metrics",
    "binned_calibration",
    "head_agreement_rows",
    "patch_features",
    "binned_pair_sims",
    "binned_song_stats",
    "binned_classify_ctp",
    "truncation_robustness_rows",
    "binned_ctp_vecs",
    "binned_ptc_ctp_metrics",
    "head_sim_corr_rows",
    "phase_timings",
}


def test_schema_creates_all_tables(con):
    rows = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()
    actual = {r[0] for r in rows}
    assert actual == EXPECTED_TABLES, f"Missing: {EXPECTED_TABLES - actual}  Extra: {actual - EXPECTED_TABLES}"


# ---------------------------------------------------------------------------
# 2-4. head_results / head_strategy_done
# ---------------------------------------------------------------------------


def test_upsert_head_roundtrip(con, tmp_flat_head_cache):
    from scripts.embedding_research.cache import flat_heads

    act = [0.3, 0.7]
    upsert_head("s1", "bb", "hd", "mean", "ptc", act)
    result = flat_heads.load("bb", "hd", "mean", "ptc", "s1")
    assert result is not None
    assert list(result) == pytest.approx(act)


def test_head_strategy_done_false_when_missing(con, tmp_flat_head_cache):
    result = head_strategy_done("s_none", "bb", "hd", "mean")
    assert result is False


def test_head_strategy_done_true_when_both_pathways(con, tmp_flat_head_cache):
    upsert_head("s2", "bb", "hd", "mean", "ptc", [0.4, 0.6])
    assert head_strategy_done("s2", "bb", "hd", "mean") is False
    upsert_head("s2", "bb", "hd", "mean", "ctp", [0.55, 0.45])
    assert head_strategy_done("s2", "bb", "hd", "mean") is True


# ---------------------------------------------------------------------------
# 5-7. flat_head_labels / query_flat_head_labels
# ---------------------------------------------------------------------------


def test_upsert_flat_head_labels_roundtrip(con):
    upsert_flat_head_labels(con, "s1", "bb", "genre", 0.85)
    row = con.execute(
        "SELECT score FROM flat_head_labels WHERE song_id='s1' AND backbone='bb' AND head='genre'"
    ).fetchone()
    assert row is not None
    assert row[0] == pytest.approx(0.85)


def test_query_flat_head_labels_empty_returns_empty_list(con):
    result = query_flat_head_labels(con, "bb", ["s1", "s2"])
    assert result == []


def test_query_flat_head_labels_partial_songs_warns(con, caplog):
    upsert_flat_head_labels(con, "s1", "bb", "genre", 0.9)
    upsert_flat_head_labels(con, "s2", "bb", "genre", 0.8)
    sids = ["s1", "s2", "s3", "s4"]  # s3, s4 are missing
    with caplog.at_level(logging.WARNING, logger="scripts.embedding_research.db.flat"):
        query_flat_head_labels(con, "bb", sids)
    assert any("2/4" in m for m in caplog.messages), f"Expected partial-songs warning, got: {caplog.messages}"


# ---------------------------------------------------------------------------
# 8-10. write_analyze_metrics / load_analyze_metrics
# ---------------------------------------------------------------------------


def test_write_analyze_metrics_inserts_rows(con):
    write_analyze_metrics(con, "bb/mean", "flat", "cosine", 10, {"disc_general": 0.42, "map_10": 0.55})
    rows = con.execute("SELECT metric, value FROM analyze_metrics ORDER BY metric").fetchall()
    assert len(rows) == 2
    metric_map = dict(rows)
    assert metric_map["disc_general"] == pytest.approx(0.42)
    assert metric_map["map_10"] == pytest.approx(0.55)


def test_write_analyze_metrics_skips_none_values(con):
    write_analyze_metrics(con, "bb/mean", "flat", "cosine", 10, {"disc_general": 0.42, "map_10": None})
    rows = con.execute("SELECT metric FROM analyze_metrics").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "disc_general"


def test_write_analyze_metrics_insert_or_replace(con):
    write_analyze_metrics(con, "bb/mean", "flat", "cosine", 10, {"disc_general": 0.42})
    write_analyze_metrics(con, "bb/mean", "flat", "cosine", 10, {"disc_general": 0.99})
    rows = con.execute("SELECT value FROM analyze_metrics WHERE metric='disc_general'").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == pytest.approx(0.99)


def test_write_analyze_metrics_roundtrip(con):
    write_analyze_metrics(
        con,
        strategy_key="bb/mean",
        strategy_type="flat",
        sim_metric="cosine",
        k=10,
        metrics={"map_k": 0.55, "disc_general": 0.42},
    )
    df = load_analyze_metrics(con)
    assert len(df) >= 1
    row = df[(df["sim_metric"] == "cosine") & (df["strategy_key"] == "bb/mean")].iloc[0]
    assert row["disc_general"] == pytest.approx(0.42)


def test_load_analyze_metrics_empty_returns_empty_df(con):
    df = load_analyze_metrics(con)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 0


def test_load_analyze_metrics_sorted_by_disc_general_desc(con):
    write_analyze_metrics(con, "bb/mean", "flat", "cosine", 10, {"disc_general": 0.30})
    write_analyze_metrics(con, "bb/max", "flat", "cosine", 10, {"disc_general": 0.80})
    write_analyze_metrics(con, "bb/min", "flat", "cosine", 10, {"disc_general": 0.55})
    df = load_analyze_metrics(con)
    assert list(df["disc_general"]) == pytest.approx([0.80, 0.55, 0.30])


# ---------------------------------------------------------------------------
# 11-13. query_analysis_done
# ---------------------------------------------------------------------------


def test_query_analysis_done_returns_tuples(con):
    write_analyze_metrics(con, "bb/mean", "flat", "cosine", 10, {"disc_general": 0.42})
    write_analyze_metrics(con, "bb/max", "flat", "l2", 5, {"disc_general": 0.55})
    result = query_analysis_done(con)
    assert ("bb/mean", "cosine", 10) in result
    assert ("bb/max", "l2", 5) in result
    assert len(result) == 2


def test_query_analysis_done_returns_empty_set_on_empty_table(con):
    result = query_analysis_done(con)
    assert result == set()


def test_query_analysis_done_returns_empty_set_on_missing_table(con):
    con.execute("DROP TABLE analyze_metrics")
    result = query_analysis_done(con)
    assert result == set()
