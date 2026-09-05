"""Unit tests for scripts/embedding_research/db/ database layer.

All tests use an in-memory DuckDB connection -- no file I/O.
"""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from scripts.embedding_research.db import (
    LEGACY_RUN_ID,
    load_analyze_metrics,
    migrate_analyze_metrics_provenance,
    write_analyze_metrics,
)
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.db.flat import (
    clear_song_retrieval_metrics,
    write_song_retrieval_metrics,
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
    # Retained core experiment + provenance tables.  The obsolete copied-vector /
    # threshold / stratification tables were PHYSICALLY REMOVED at Plan E P1-S5
    # Wave 2b (zero live writers/readers after the hard-cut deletion of the legacy
    # report tables and db/stratify.py); they must never reappear.
    "songs",
    "analyze_metrics",
    "phase_timings",
    "song_retrieval_metrics",
    "head_phase_provenance",
    # Frozen observation stream registries (Plan B, Phase 1) — scalar metadata over float32
    # sidecars, no PK/UNIQUE (application-level identity).
    "stream_registry",
    "head_stream_registry",
    # Post-run phase/state surfaces (Plan B, Phase 2; Plan C Phase 4 adds catalog_metadata)
    # — no PK/UNIQUE.
    "run_provenance",
    "corpus_state",
    "catalog_metadata",
}

# The thirteen tables removed in the P1-S5 Wave 2b hard cut.  Asserted absent.
REMOVED_TABLES = frozenset(
    {
        "pooled_vecs",
        "head_results",
        "head_agreement_rows",
        "patch_features",
        "binned_pair_sims",
        "binned_classify_ctp",
        "binned_song_stats",
        "truncation_robustness_rows",
        "binned_ctp_vecs",
        "binned_ptc_ctp_metrics",
        "head_sim_corr_rows",
        "binned_calibration",
        "stratified_corpus",
    }
)


def test_schema_creates_all_tables(con):
    rows = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()
    actual = {r[0] for r in rows}
    assert actual == EXPECTED_TABLES, f"Missing: {EXPECTED_TABLES - actual}  Extra: {actual - EXPECTED_TABLES}"


def test_schema_has_no_removed_tables(con):
    """The P1-S5 Wave 2b hard cut physically removed the thirteen obsolete tables."""
    rows = con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()
    actual = {r[0] for r in rows}
    assert REMOVED_TABLES.isdisjoint(actual), f"Removed tables still present: {REMOVED_TABLES & actual}"


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
        def execute(self, sql, params=None):
            return con.execute(sql, params or [])

        def executemany(self, sql, params):
            captured["sql"] = sql
            return con.executemany(sql, params)

    write_analyze_metrics(_Recorder(), "bb/mean", "flat", "cosine", 10, {"disc_general": 0.42})
    assert "INSERT INTO analyze_metrics" in captured["sql"]
    assert "(run_id, strategy_key, strategy_type, sim_metric, k, metric, value)" in captured["sql"]
    assert captured["sql"].count("?") == 7


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


def test_write_analyze_metrics_run_scope_isolation(con):
    """P3-S3: a writer replaces only its own (run_id, scope); other runs + legacy baseline survive."""
    key = "ptc:bb:scope-isolation"
    write_analyze_metrics(con, key, "ptc", "cosine", 10, {"disc_general": 0.10}, run_id=LEGACY_RUN_ID)
    write_analyze_metrics(con, key, "ptc", "cosine", 10, {"disc_general": 0.50}, run_id="run-a")
    write_analyze_metrics(con, key, "ptc", "cosine", 10, {"disc_general": 0.90}, run_id="run-b")
    # Re-running run-a replaces only run-a's row for this scope.
    write_analyze_metrics(con, key, "ptc", "cosine", 10, {"disc_general": 0.70}, run_id="run-a")

    def _value(run_id: str) -> float:
        return float(
            con.execute(
                "SELECT value FROM analyze_metrics WHERE run_id=? AND strategy_key=? AND metric='disc_general'",
                [run_id, key],
            ).fetchone()[0]
        )

    assert _value(LEGACY_RUN_ID) == pytest.approx(0.10)
    assert _value("run-a") == pytest.approx(0.70)
    assert _value("run-b") == pytest.approx(0.90)
    # Whole-table (default) read still sees every generation.
    assert query_analysis_done(con) == {(key, "cosine", 10)}
    assert query_analysis_done(con, run_id="run-a") == {(key, "cosine", 10)}
    assert query_analysis_done(con, run_id="run-b") == {(key, "cosine", 10)}
    # The default load_analyze_metrics is a whole-table view (unchanged on a single generation).
    assert len(load_analyze_metrics(con)) == 1
    assert len(load_analyze_metrics(con, run_id="run-a")) == 1
    assert len(load_analyze_metrics(con, run_id="run-a")) == len(load_analyze_metrics(con, run_id="run-b"))


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


# ---------------------------------------------------------------------------
# P3-S3: analyze_metrics run_id migration
# ---------------------------------------------------------------------------


_LEGACY_ANALYZE_METRICS_DDL = """
CREATE TABLE IF NOT EXISTS analyze_metrics (
    strategy_key  TEXT NOT NULL,
    strategy_type TEXT NOT NULL,
    sim_metric    TEXT NOT NULL,
    k             INTEGER NOT NULL,
    metric        TEXT NOT NULL,
    value         DOUBLE,
    PRIMARY KEY (strategy_key, sim_metric, k, metric)
);
"""


def test_migrate_analyze_metrics_provenance_preserves_legacy_rows_and_drops_pk():
    """P3-S3: backup-first migration copies rows as run_id='legacy' and drops the legacy PK."""
    legacy = duckdb.connect(":memory:")
    legacy.execute(_LEGACY_ANALYZE_METRICS_DDL)
    legacy.execute(
        "INSERT INTO analyze_metrics (strategy_key, strategy_type, sim_metric, k, metric, value) VALUES "
        "('global_pool:bb:mean', 'global_pool', 'cosine', 10, 'disc_general', 0.42),"
        "('global_pool:bb:mean', 'global_pool', 'cosine', 10, 'map_10', 0.55)"
    )
    n = migrate_analyze_metrics_provenance(legacy)
    assert n == 2
    cols = {"run_id", "strategy_key", "strategy_type", "sim_metric", "k", "metric", "value"}
    actual = {
        row[0]
        for row in legacy.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='analyze_metrics'"
        ).fetchall()
    }
    assert cols == actual
    # Every migrated row is the read-only legacy baseline.
    rows = legacy.execute("SELECT run_id, metric, value FROM analyze_metrics ORDER BY metric").fetchall()
    assert rows == [("legacy", "disc_general", 0.42), ("legacy", "map_10", 0.55)]
    # The legacy PRIMARY KEY is gone: a duplicate legacy identity is accepted at the storage layer
    # (application-level uniqueness is enforced on write, not by a constraint).
    legacy.execute(
        "INSERT INTO analyze_metrics (run_id, strategy_key, strategy_type, sim_metric, k, metric, value) VALUES "
        "('legacy', 'global_pool:bb:mean', 'global_pool', 'cosine', 10, 'disc_general', 0.99)"
    )
    assert (
        int(
            legacy.execute(
                "SELECT COUNT(*) FROM analyze_metrics "
                "WHERE strategy_key='global_pool:bb:mean' AND metric='disc_general'"
            ).fetchone()[0]
        )
        == 2
    )
    # A full pre-migration snapshot is retained as the recorded backup.
    assert "analyze_metrics_backup" in {
        r[0]
        for r in legacy.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_name='analyze_metrics_backup'"
        ).fetchall()
    }
    # Idempotent / guarded: a second migration is a no-op returning 0.
    assert migrate_analyze_metrics_provenance(legacy) == 0
    legacy.close()


def test_migrate_analyze_metrics_provenance_missing_table_is_noop():
    fresh = duckdb.connect(":memory:")
    assert migrate_analyze_metrics_provenance(fresh) == 0
    fresh.close()


def test_fresh_schema_analyze_metrics_has_run_id_and_no_pk(con):
    cols = {
        row[0]
        for row in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='analyze_metrics'"
        ).fetchall()
    }
    assert "run_id" in cols
    # A duplicate legacy identity is permitted by the storage layer (no PK/UNIQUE/index).
    write_analyze_metrics(con, "bb/mean", "flat", "cosine", 10, {"disc_general": 0.42})
    con.execute(
        "INSERT INTO analyze_metrics (run_id, strategy_key, strategy_type, sim_metric, k, metric, value) "
        "VALUES ('legacy', 'bb/mean', 'flat', 'cosine', 10, 'disc_general', 0.99)"
    )
    assert int(con.execute("SELECT COUNT(*) FROM analyze_metrics").fetchone()[0]) == 2


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
