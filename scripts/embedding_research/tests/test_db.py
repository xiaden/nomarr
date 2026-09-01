"""Unit tests for scripts/embedding_research/db/ database layer.

All tests use an in-memory DuckDB connection -- no file I/O.
"""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from scripts.embedding_research.db import load_analyze_metrics, write_analyze_metrics
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.db.flat import (
    clear_song_retrieval_metrics,
    head_strategy_done,
    upsert_head,
    write_song_retrieval_metrics,
)
from scripts.embedding_research.db.queries import query_analysis_done
from scripts.embedding_research.db.stratify import (
    clear_stale_stratification,
    load_stratified_sids,
    write_stratified_sids,
)

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
    "song_retrieval_metrics",
    "stratified_corpus",
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
# 5. write_analyze_metrics / load_analyze_metrics
# ---------------------------------------------------------------------------


def test_write_analyze_metrics_inserts_rows(con):
    write_analyze_metrics(con, "bb/mean", "flat", "cosine", 10, {"disc_general": 0.42, "map_10": 0.55})
    rows = con.execute("SELECT metric, value FROM analyze_metrics ORDER BY metric").fetchall()
    assert len(rows) == 2
    metric_map = dict(rows)
    assert metric_map["disc_general"] == pytest.approx(0.42)
    assert metric_map["map_10"] == pytest.approx(0.55)


def test_write_analyze_metrics_uses_named_columns(con):
    """The DTO/DDL column order can differ; writes must use named columns (P1-S4 contract)."""
    captured = {}

    class _Recorder:
        def executemany(self, sql, params):
            captured["sql"] = sql
            return con.executemany(sql, params)

    write_analyze_metrics(_Recorder(), "bb/mean", "flat", "cosine", 10, {"disc_general": 0.42})
    assert "INSERT OR REPLACE INTO analyze_metrics" in captured["sql"]
    assert "(strategy_key, strategy_type, sim_metric, k, metric, value)" in captured["sql"]
    assert captured["sql"].count("?") == 6


def test_strategy_identity_retains_k_and_metric(con):
    """K and cosine-metric are part of the persistence identity (P1-S2), not folded into the key string.

    The strategy-key string carries backbone/pathway/threshold/rep_a/rep_b/aggregate; ``sim_metric``
    and ``k`` are retained as PK columns so distinct K / metric values never collide.
    """
    key = "ptc:bb:temporal_global:0.50:mean:max:target_weighted"
    write_analyze_metrics(con, key, "ptc", "cosine", 5, {"mrr": 0.4})
    write_analyze_metrics(con, key, "ptc", "cosine", 10, {"mrr": 0.6})
    rows = con.execute("SELECT sim_metric, k FROM analyze_metrics ORDER BY k").fetchall()
    assert rows == [("cosine", 5), ("cosine", 10)]
    df = load_analyze_metrics(con)
    assert len(df) == 2
    assert sorted(df["k"].tolist()) == [5, 10]
    assert (df["sim_metric"] == "cosine").all()


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
    write_analyze_metrics(con, "bb/max", "flat", "cosine", 5, {"disc_general": 0.55})
    result = query_analysis_done(con)
    assert ("bb/mean", "cosine", 10) in result
    assert ("bb/max", "cosine", 5) in result
    assert len(result) == 2


def test_query_analysis_done_returns_empty_set_on_empty_table(con):
    result = query_analysis_done(con)
    assert result == set()


def test_query_analysis_done_returns_empty_set_on_missing_table(con):
    con.execute("DROP TABLE analyze_metrics")
    result = query_analysis_done(con)
    assert result == set()


def test_load_stratified_sids_returns_empty_frozenset_when_no_rows(con):
    result = load_stratified_sids(con, "hash-empty")

    assert result == frozenset()


def test_load_stratified_sids_returns_only_rows_for_matching_hash(con):
    con.executemany(
        "INSERT INTO stratified_corpus (config_hash, song_id) VALUES (?, ?)",
        [("hash-a", "s001"), ("hash-a", "s002"), ("hash-b", "s999")],
    )

    result = load_stratified_sids(con, "hash-a")

    assert result == frozenset({"s001", "s002"})


def test_write_stratified_sids_inserts_rows(con):
    write_stratified_sids(con, "hash-write", frozenset({"s003", "s001", "s002"}))

    rows = con.execute(
        "SELECT song_id FROM stratified_corpus WHERE config_hash = ? ORDER BY song_id",
        ["hash-write"],
    ).fetchall()

    assert rows == [("s001",), ("s002",), ("s003",)]


def test_write_stratified_sids_ignores_duplicate_inserts(con):
    song_ids = frozenset({"s010", "s011"})

    write_stratified_sids(con, "hash-dup", song_ids)
    write_stratified_sids(con, "hash-dup", song_ids)

    rows = con.execute(
        "SELECT song_id FROM stratified_corpus WHERE config_hash = ? ORDER BY song_id",
        ["hash-dup"],
    ).fetchall()

    assert rows == [("s010",), ("s011",)]


def test_clear_stale_stratification_deletes_rows_with_different_hash_only(con):
    con.executemany(
        "INSERT INTO stratified_corpus (config_hash, song_id) VALUES (?, ?)",
        [("keep-hash", "s001"), ("keep-hash", "s002"), ("stale-hash", "s999")],
    )

    clear_stale_stratification(con, "keep-hash")

    rows = con.execute("SELECT config_hash, song_id FROM stratified_corpus ORDER BY config_hash, song_id").fetchall()

    assert rows == [("keep-hash", "s001"), ("keep-hash", "s002")]


def test_clear_song_retrieval_metrics_deletes_only_matching_rows(con):
    write_song_retrieval_metrics(
        con,
        "strategy-a",
        "cosine",
        10,
        {
            "song_ids": ["s1", "s2"],
            "ap_k": [1.0, 0.5],
            "mrr": [1.0, 0.5],
            "recall_k": [1.0, 1.0],
            "disc_artist_contrib": [0.8, 0.6],
            "disc_genre_contrib": [0.7, 0.4],
            "disc_head_contrib": [0.3, 0.1],
        },
    )
    write_song_retrieval_metrics(
        con,
        "strategy-b",
        "cosine",
        5,
        {
            "song_ids": ["s3"],
            "ap_k": [0.25],
            "mrr": [0.25],
            "recall_k": [1.0],
            "disc_artist_contrib": [0.2],
            "disc_genre_contrib": [0.15],
            "disc_head_contrib": [0.05],
        },
    )

    clear_song_retrieval_metrics(con, "strategy-a", "cosine", 10)

    cleared_rows = con.execute(
        "SELECT song_id FROM song_retrieval_metrics WHERE strategy_key = ? AND sim_metric = ? AND k = ?",
        ["strategy-a", "cosine", 10],
    ).fetchall()
    remaining_rows = con.execute(
        "SELECT strategy_key, sim_metric, k, song_id FROM song_retrieval_metrics ORDER BY strategy_key, sim_metric, k, song_id"
    ).fetchall()

    assert cleared_rows == []
    assert remaining_rows == [("strategy-b", "cosine", 5, "s3")]
