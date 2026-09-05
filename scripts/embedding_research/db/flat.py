"""Analyze/retrieval-metrics persistence tables.

The flat-pipeline filesystem head/activation caches (``upsert_head``,
``head_strategy_done``, ``load_head_labels``) were deleted with the cache layer
in the corrective-pass hard cut. This module now only hosts the active
``analyze_metrics`` and ``song_retrieval_metrics`` persistence used by the
catalog-analysis writer (``db.analyze_scope.write_catalog_analyze_rows``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pandas as pd


# ── analyze_metrics ───────────────────────────────────────────────────────────


def clear_song_retrieval_metrics(con, strategy_key: str, sim_metric: str, k: int) -> None:
    """Delete all per-song retrieval metric rows for the given (strategy_key, sim_metric, k) combination."""
    con.execute(
        "DELETE FROM song_retrieval_metrics WHERE strategy_key = ? AND sim_metric = ? AND k = ?",
        [strategy_key, sim_metric, k],
    )


def write_song_retrieval_metrics(
    con,
    strategy_key: str,
    sim_metric: str,
    k: int,
    per_song: dict,
) -> None:
    """Write per-song retrieval metrics into the ``song_retrieval_metrics`` table.

    Args:
        con: DuckDB connection.
        strategy_key: Strategy identifier.
        sim_metric: Similarity metric name (e.g. ``"cosine"``).
        k: Retrieval cut-off.
        per_song: Dict returned by ``compute_retrieval_metrics`` under key ``"per_song"``.
            Expected keys: ``song_ids``, ``ap_k``, ``mrr``, ``recall_k``,
            ``disc_artist_contrib``, ``disc_genre_contrib``, ``disc_head_contrib``.
    """
    song_ids = per_song.get("song_ids", [])
    ap_k = per_song.get("ap_k", [])
    mrr = per_song.get("mrr", [])
    recall_k = per_song.get("recall_k", [])
    disc_artist_contrib = per_song.get("disc_artist_contrib", [])
    disc_genre_contrib = per_song.get("disc_genre_contrib", [])
    disc_head_contrib = per_song.get("disc_head_contrib", [])

    rows = [
        (
            strategy_key,
            sim_metric,
            k,
            song_id,
            ap_k[idx] if idx < len(ap_k) else None,
            mrr[idx] if idx < len(mrr) else None,
            recall_k[idx] if idx < len(recall_k) else None,
            disc_artist_contrib[idx] if idx < len(disc_artist_contrib) else None,
            disc_genre_contrib[idx] if idx < len(disc_genre_contrib) else None,
            disc_head_contrib[idx] if idx < len(disc_head_contrib) else None,
        )
        for idx, song_id in enumerate(song_ids)
    ]
    if rows:
        con.executemany(
            "INSERT OR REPLACE INTO song_retrieval_metrics (strategy_key, sim_metric, k, song_id, ap_k, mrr, recall_k, disc_artist_contrib, disc_genre_contrib, disc_head_contrib) VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )


def write_analyze_metrics(
    con,
    strategy_key: str,
    strategy_type: str,
    sim_metric: str,
    k: int,
    metrics: dict,
    *,
    run_id: str = "legacy",
) -> None:
    """Write non-`None` aggregate analysis metrics for one ``(run_id, strategy_key, sim_metric, k)`` scope.

    Since migration the table carries no PRIMARY KEY (DuckDB ART/WAL policy) so uniqueness is
    asserted here at the application layer: within *run_id*, writing a strategy scope REPLACES
    that run's prior rows for the same ``(strategy_key, sim_metric, k)`` (delete-then-insert in
    the caller's transaction).  It never deletes or modifies rows of any other ``run_id``, so
    Tier 1/2 baseline/corpus results (``run_id='legacy'``) and unrelated/retained runs are
    preserved.  A call with no runnable rows is a no-op (nothing is deleted).

    Args:
        con: DuckDB connection.
        strategy_key: Strategy identifier.
        strategy_type: Strategy type label (e.g. ``"catalog"``).
        sim_metric: Similarity metric name (e.g. ``"cosine"``).
        k: Retrieval cut-off.
        metrics: Metric values keyed by metric name; entries with `None` (or list/array)
            values are skipped.  The default ``run_id='legacy'`` tags pre-migration / baseline
            rows; run-scoped callers pass their own ``run_id``.
    """
    rows: list[tuple] = []
    for name, value in metrics.items():
        if value is None:
            continue
        if isinstance(value, dict):
            for sub_name, sub_value in value.items():
                if sub_value is not None:
                    rows.append(
                        (run_id, strategy_key, strategy_type, sim_metric, k, f"{name}_{sub_name}", float(sub_value))
                    )
        elif isinstance(value, (list, np.ndarray)):
            continue  # per-song lists are never written as aggregate metrics
        else:
            rows.append((run_id, strategy_key, strategy_type, sim_metric, k, name, float(value)))
    if not rows:
        return
    # Replace only this run's own scope — never another run's (or the legacy baseline's) rows.
    con.execute(
        "DELETE FROM analyze_metrics WHERE run_id = ? AND strategy_key = ? AND sim_metric = ? AND k = ?",
        [run_id, strategy_key, sim_metric, k],
    )
    con.executemany(
        "INSERT INTO analyze_metrics (run_id, strategy_key, strategy_type, sim_metric, k, metric, value) "
        "VALUES (?,?,?,?,?,?,?)",
        rows,
    )


def load_analyze_metrics(con, *, run_id: str | None = None) -> pd.DataFrame:
    """Load `analyze_metrics` as a wide DataFrame keyed by strategy and query settings.

    Args:
        con: DuckDB connection.
        run_id: Optional run-scoped filter (post-migration reader contract).  When given, only rows
            whose physical ``run_id`` column equals *run_id* are loaded (the row-level realization
            of the Plan C/D scope bookkeeping).  When ``None``, the full table is loaded (default
            read semantics — on a single-generation DB this is exactly the pre-migration view).

    Returns:
        A DataFrame pivoted on `metric` so each metric name becomes a column, sorted by
        `disc_general` descending when that column is present.
    """
    df = con.execute("SELECT * FROM analyze_metrics").df()
    if df.empty:
        return df
    if run_id is not None:
        df = df[df["run_id"] == run_id]
        if df.empty:
            return df.iloc[0:0].copy()
    df = df.drop(columns=["run_id"])
    df = df.pivot_table(
        index=["strategy_key", "strategy_type", "sim_metric", "k"],
        columns="metric",
        values="value",
        aggfunc="first",
    )
    df.columns.name = None
    df = df.reset_index()
    if "disc_general" in df.columns:
        df = df.sort_values("disc_general", ascending=False, na_position="last")
    return df
