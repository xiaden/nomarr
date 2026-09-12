"""Unit tests for scripts/embedding_research/db/ database layer.

All tests use an in-memory DuckDB connection -- no file I/O.
"""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from scripts.embedding_research.db import (
    load_analyze_metrics,
    write_analyze_metrics,
)
from scripts.embedding_research.db._schema import StaleSchemaError, ensure_schema
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
    # Wave 2b (zero live writers/readers after the hard-cut deletion of the old
    # report tables and db/stratify.py); they must never reappear.
    "songs",
    "analyze_metrics",
    "analyze_incomplete_diagnostics",
    "phase_timings",
    "song_retrieval_metrics",
    "head_phase_provenance",
    # Frozen observation stream registries (Plan B, Phase 1) — scalar metadata over float32
    # sidecars, no PK/UNIQUE (application-level identity).
    "stream_registry",
    "head_stream_registry",
    # Post-run phase/state surfaces (Plan B, Phase 2) — no PK/UNIQUE.
    "run_provenance",
    "corpus_state",
    "song_patch_geometry",
    # Exact geometry-era analysis + head evidence tables.
    "geometry_analysis_records",
    "geometry_head_evidence",
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
    write_analyze_metrics(con, "bb/mean", "flat", "cosine", 10, {"disc_general": 0.42, "map_10": 0.55}, run_id="run-1")
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

    write_analyze_metrics(_Recorder(), "bb/mean", "flat", "cosine", 10, {"disc_general": 0.42}, run_id="run-1")
    assert "INSERT INTO analyze_metrics" in captured["sql"]
    assert "(run_id, strategy_key, strategy_type, sim_metric, k, metric, value)" in captured["sql"]
    assert captured["sql"].count("?") == 7


def test_strategy_identity_retains_k_and_metric(con):
    """K and cosine-metric are part of the persistence identity (P1-S2), not folded into the key string.

    The strategy-key string carries backbone/pathway/threshold/rep_a/rep_b/aggregate; ``sim_metric``
    and ``k`` are retained as PK columns so distinct K / metric values never collide.
    """
    key = "ptc:bb:temporal_global:0.50:mean:max:target_weighted"
    write_analyze_metrics(con, key, "ptc", "cosine", 5, {"mrr": 0.4}, run_id="run-1")
    write_analyze_metrics(con, key, "ptc", "cosine", 10, {"mrr": 0.6}, run_id="run-1")
    rows = con.execute("SELECT sim_metric, k FROM analyze_metrics ORDER BY k").fetchall()
    assert rows == [("cosine", 5), ("cosine", 10)]
    df = load_analyze_metrics(con)
    assert len(df) == 2
    assert sorted(df["k"].tolist()) == [5, 10]
    assert (df["sim_metric"] == "cosine").all()


def test_write_analyze_metrics_skips_none_values(con):
    write_analyze_metrics(con, "bb/mean", "flat", "cosine", 10, {"disc_general": 0.42, "map_10": None}, run_id="run-1")
    rows = con.execute("SELECT metric FROM analyze_metrics").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "disc_general"


def test_write_analyze_metrics_insert_or_replace(con):
    write_analyze_metrics(con, "bb/mean", "flat", "cosine", 10, {"disc_general": 0.42}, run_id="run-1")
    write_analyze_metrics(con, "bb/mean", "flat", "cosine", 10, {"disc_general": 0.99}, run_id="run-1")
    rows = con.execute("SELECT value FROM analyze_metrics WHERE metric='disc_general'").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == pytest.approx(0.99)


def test_write_analyze_metrics_run_scope_isolation(con):
    """A writer replaces only its own (run_id, scope); other runs survive."""
    key = "ptc:bb:scope-isolation"
    write_analyze_metrics(con, key, "ptc", "cosine", 10, {"disc_general": 0.10}, run_id="run-a")
    write_analyze_metrics(con, key, "ptc", "cosine", 10, {"disc_general": 0.50}, run_id="run-b")
    write_analyze_metrics(con, key, "ptc", "cosine", 10, {"disc_general": 0.90}, run_id="run-c")
    # Re-running run-b replaces only run-b's row for this scope.
    write_analyze_metrics(con, key, "ptc", "cosine", 10, {"disc_general": 0.70}, run_id="run-b")

    def _value(run_id: str) -> float:
        return float(
            con.execute(
                "SELECT value FROM analyze_metrics WHERE run_id=? AND strategy_key=? AND metric='disc_general'",
                [run_id, key],
            ).fetchone()[0]
        )

    assert _value("run-a") == pytest.approx(0.10)
    assert _value("run-b") == pytest.approx(0.70)
    assert _value("run-c") == pytest.approx(0.90)
    # Whole-table (default) read still sees every generation.
    assert query_analysis_done(con) == {(key, "cosine", 10)}
    assert query_analysis_done(con, run_id="run-b") == {(key, "cosine", 10)}
    assert query_analysis_done(con, run_id="run-c") == {(key, "cosine", 10)}
    # The default load_analyze_metrics is a whole-table view.
    assert len(load_analyze_metrics(con)) == 1
    assert len(load_analyze_metrics(con, run_id="run-b")) == 1
    assert len(load_analyze_metrics(con, run_id="run-c")) == 1


def test_write_analyze_metrics_roundtrip(con):
    write_analyze_metrics(
        con,
        strategy_key="bb/mean",
        strategy_type="flat",
        sim_metric="cosine",
        k=10,
        metrics={"map_k": 0.55, "disc_general": 0.42},
        run_id="run-1",
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
    write_analyze_metrics(con, "bb/mean", "flat", "cosine", 10, {"disc_general": 0.30}, run_id="run-1")
    write_analyze_metrics(con, "bb/max", "flat", "cosine", 10, {"disc_general": 0.80}, run_id="run-1")
    write_analyze_metrics(con, "bb/min", "flat", "cosine", 10, {"disc_general": 0.55}, run_id="run-1")
    df = load_analyze_metrics(con)
    assert list(df["disc_general"]) == pytest.approx([0.80, 0.55, 0.30])


# ---------------------------------------------------------------------------
# 11-13. query_analysis_done
# ---------------------------------------------------------------------------


def test_query_analysis_done_returns_tuples(con):
    write_analyze_metrics(con, "bb/mean", "flat", "cosine", 10, {"disc_general": 0.42}, run_id="run-1")
    write_analyze_metrics(con, "bb/max", "flat", "cosine", 5, {"disc_general": 0.55}, run_id="run-1")
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
# Hard cut: one current run-scoped analyze_metrics schema
# ---------------------------------------------------------------------------

_PRECUT_ANALYZE_METRICS_DDL = """
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


def _run_id_column_default(con):
    row = con.execute(
        "SELECT column_default, is_nullable FROM information_schema.columns "
        "WHERE table_name='analyze_metrics' AND column_name='run_id'"
    ).fetchone()
    return (row[0], row[1]) if row else None


def test_write_analyze_metrics_requires_run_id(con):
    """P1-S4 spec: write_analyze_metrics REQUIRES the current run id (no default)."""
    with pytest.raises(TypeError):
        write_analyze_metrics(con, "bb/mean", "flat", "cosine", 10, {"disc_general": 0.42})


def test_analyze_metrics_current_schema_run_id_required_no_default(con):
    """P1-S4 spec: the current schema creates run_id TEXT NOT NULL with NO DEFAULT."""
    default, nullable = _run_id_column_default(con)
    assert default is None  # the current run_id column carries no default
    assert nullable == "NO"
    # An unscoped INSERT omitting run_id is refused (the current run identity is required).
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            "INSERT INTO analyze_metrics (strategy_key, strategy_type, sim_metric, k, metric, value) "
            "VALUES ('bb/mean', 'flat', 'cosine', 10, 'disc_general', 0.42)"
        )


def test_analyze_metrics_no_pk_duplicate_run_rows_accepted(con):
    """No PK/UNIQUE/index: duplicate scope rows across distinct runs are accepted at the storage
    layer (application-level uniqueness is asserted on write within a run_id)."""
    write_analyze_metrics(con, "bb/mean", "flat", "cosine", 10, {"disc_general": 0.42}, run_id="run-1")
    write_analyze_metrics(con, "bb/mean", "flat", "cosine", 10, {"disc_general": 0.42}, run_id="run-2")
    assert int(con.execute("SELECT COUNT(*) FROM analyze_metrics").fetchone()[0]) == 2


def test_current_schema_has_no_partition_or_backup(con):
    """P1-S4 spec: writing a current run never produces a partition or a backup table."""
    write_analyze_metrics(con, "bb/mean", "flat", "cosine", 10, {"disc_general": 0.42}, run_id="run-1")
    rows = con.execute("SELECT run_id FROM analyze_metrics").fetchall()
    assert rows and all(r[0] == "run-1" for r in rows)
    n_backup = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='analyze_metrics_backup'"
    ).fetchone()[0]
    assert not n_backup


def test_ensure_schema_creates_current_schema_fresh():
    """P1-S4 spec: a fresh connection gets the current run-scoped analyze_metrics table."""
    c = duckdb.connect(":memory:")
    ensure_schema(c)
    assert _run_id_column_default(c)[0] is None
    c.close()


def test_ensure_schema_refuses_precut_table_without_run_id():
    """P1-S4 spec: a stale pre-cut analyze_metrics (no run_id) is refused, never migrated."""
    stale = duckdb.connect(":memory:")
    stale.execute(_PRECUT_ANALYZE_METRICS_DDL)
    with pytest.raises(StaleSchemaError):
        ensure_schema(stale)
    # Nothing was relabeled / copied into an executable partition.
    assert _run_id_column_default(stale) is None
    stale.close()


def test_ensure_schema_refuses_mixed_analyze_metrics_columns():
    """P1-S4 spec: an analyze_metrics table that has the run_id column but a non-current
    column set (an unexpected/mixed shape) is refused rather than silently accepted."""
    stale = duckdb.connect(":memory:")
    stale.execute(
        "CREATE TABLE analyze_metrics (run_id TEXT NOT NULL, strategy_key TEXT NOT NULL, "
        "strategy_type TEXT NOT NULL, sim_metric TEXT NOT NULL, k INTEGER NOT NULL, "
        "metric TEXT NOT NULL)"
    )
    with pytest.raises(StaleSchemaError):
        ensure_schema(stale)
    stale.close()


def test_ensure_schema_accepts_current_schema_idempotent(con):
    """P1-S4 spec: re-running ensure_schema on a current schema is a no-op (CREATE IF NOT EXISTS)."""
    write_analyze_metrics(con, "bb/mean", "flat", "cosine", 10, {"disc_general": 0.42}, run_id="run-1")
    ensure_schema(con)  # must not raise
    assert con.execute("SELECT COUNT(*) FROM analyze_metrics").fetchone()[0] == 1


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
