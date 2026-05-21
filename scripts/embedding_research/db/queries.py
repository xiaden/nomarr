"""Progress-check query helpers — return sets of already-completed work tuples."""

from __future__ import annotations

try:
    import duckdb

    _HAS_DUCKDB = True
except ImportError:
    _HAS_DUCKDB = False


def query_embedded_configs(con, backbone: str | None = None) -> set[tuple[str, str]]:
    query = "SELECT DISTINCT backbone, strategy FROM pooled_vecs"
    params: list[str] = []
    if backbone is not None:
        query += " WHERE backbone=?"
        params.append(backbone)
    try:
        rows = con.execute(query, params).fetchall()
    except duckdb.CatalogException:
        return set()
    return {(str(row[0]), str(row[1])) for row in rows}


def query_analysis_done(con) -> set[tuple[str, str, str, int]]:
    try:
        rows = con.execute("SELECT backbone, strategy, sim_metric, k FROM retrieval_rows").fetchall()
    except duckdb.CatalogException:
        return set()
    return {(str(row[0]), str(row[1]), str(row[2]), int(row[3])) for row in rows}


def query_classify_done(con) -> set[tuple[str, str, str, str, str]]:
    try:
        rows = con.execute("SELECT song_id, backbone, head, strategy, pathway FROM head_results").fetchall()
    except duckdb.CatalogException:
        return set()
    return {(str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4])) for row in rows}


def query_binned_embed_done() -> set[tuple[str, str, str, float]]:
    """Return (song_id, backbone, bin_mode, std_thresh) from the filesystem cache."""
    from ..strategy_binned._cache import list_done_keys as _list_cache_done

    return _list_cache_done()


def query_binned_configs(backbone: str | None = None) -> set[tuple[str, str, float]]:
    """Return (backbone, bin_mode, std_thresh) configs present in the filesystem cache."""
    from ..strategy_binned._cache import list_configs as _list_cache_configs

    return _list_cache_configs(backbone)


def query_binned_analysis_done(con) -> set[tuple[str, str, float, str, str, str, str, int]]:
    try:
        rows = con.execute(
            "SELECT backbone, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k FROM binned_retrieval_rows"
        ).fetchall()
    except duckdb.CatalogException:
        return set()
    return {
        (
            str(row[0]),
            str(row[1]),
            float(row[2]),
            str(row[3]),
            str(row[4]),
            str(row[5]),
            str(row[6]),
            int(row[7]),
        )
        for row in rows
    }


def query_binned_classify_done(con) -> set[tuple[str, str, str, str, float, int]]:
    try:
        rows = con.execute(
            "SELECT song_id, backbone, head, bin_mode, std_thresh, bin_id FROM binned_classify_ctp"
        ).fetchall()
    except duckdb.CatalogException:
        return set()
    return {(str(row[0]), str(row[1]), str(row[2]), str(row[3]), float(row[4]), int(row[5])) for row in rows}
