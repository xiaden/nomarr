"""Progress-check query helpers — return sets of already-completed work tuples.

Research-only, active-surface only.  Dead-table progress helpers (``query_head_sim_corr_done``
on ``head_sim_corr_rows``, ``query_binned_classify_done`` on ``binned_classify_ctp``) were
removed with the hard-cut deletion of the legacy report tables (Wave 2a).  The single
retained helper reads the active ``analyze_metrics`` table.
"""

from __future__ import annotations


def query_analysis_done(con, *, run_id: str | None = None) -> set[tuple[str, str, int]]:
    """Return completed analysis runs as `(strategy_key, sim_metric, k)` tuples.

    Args:
        con: DuckDB connection.
        run_id: Optional run-scoped filter (post-migration reader contract).  When given, only the
            distinct strategy scopes whose physical ``run_id`` column equals *run_id* are returned, so a
            caller can query "is this run's analysis done?" without seeing unrelated runs.  When ``None``,
            returns every distinct tuple already present in ``analyze_metrics`` (default read semantics).

    Returns:
        The distinct tuples already present in `analyze_metrics` (optionally restricted to *run_id*),
        or an empty set when the table does not exist yet.
    """
    if run_id is None:
        try:
            rows = con.execute("SELECT DISTINCT strategy_key, sim_metric, k FROM analyze_metrics").fetchall()
        except Exception:
            return set()
        return {(r[0], r[1], r[2]) for r in rows}
    try:
        rows = con.execute(
            "SELECT DISTINCT strategy_key, sim_metric, k FROM analyze_metrics WHERE run_id = ?", [run_id]
        ).fetchall()
    except Exception:
        return set()
    return {(r[0], r[1], r[2]) for r in rows}
