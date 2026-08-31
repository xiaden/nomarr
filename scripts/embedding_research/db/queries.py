"""Progress-check query helpers — return sets of already-completed work tuples.

Note: flat pooled vector status is no longer tracked in DuckDB. Use
``cache.flat_vecs.list_done_sids()`` / ``list_configs()`` instead.
"""

from __future__ import annotations

try:
    import duckdb

    _HAS_DUCKDB = True
except ImportError:
    _HAS_DUCKDB = False


def query_analysis_done(con) -> set[tuple[str, str, int]]:
    """Return completed analysis runs as `(strategy_key, sim_metric, k)` tuples.

    Returns:
        The distinct tuples already present in `analyze_metrics`, or an empty set when
        the table does not exist yet.
    """
    try:
        rows = con.execute("SELECT DISTINCT strategy_key, sim_metric, k FROM analyze_metrics").fetchall()
        return {(r[0], r[1], r[2]) for r in rows}
    except Exception:
        return set()


def query_classify_done() -> set[tuple[str, str, str, str, str]]:
    """Scan the filesystem cache and return (song_id, backbone, head, strategy, pathway) tuples."""
    from scripts.embedding_research.cache import flat_heads as _fh

    result: set[tuple[str, str, str, str, str]] = set()
    cache_root = _fh._CACHE_ROOT
    if not cache_root.exists():
        return result
    for bb_dir in cache_root.iterdir():
        if not bb_dir.is_dir() or bb_dir.name == "heads":
            continue
        heads_dir = bb_dir / "heads"
        if not heads_dir.is_dir():
            continue
        backbone = bb_dir.name
        for head_dir in heads_dir.iterdir():
            if not head_dir.is_dir():
                continue
            head = head_dir.name
            for strat_dir in head_dir.iterdir():
                if not strat_dir.is_dir():
                    continue
                strategy = strat_dir.name
                for pathway in ("ptc", "ctp"):
                    p_dir = strat_dir / pathway
                    if not p_dir.is_dir():
                        continue
                    for f in p_dir.glob("*.npy"):
                        result.add((f.stem, backbone, head, strategy, pathway))
    return result


def query_binned_embed_done() -> set[tuple[str, str, str, float]]:
    """Return (song_id, backbone, bin_mode, std_thresh) from the filesystem cache."""
    from scripts.embedding_research.cache.binned_ptc import list_done_keys as _list_cache_done

    return _list_cache_done()


def query_binned_configs(backbone: str | None = None) -> set[tuple[str, str, float]]:
    """Return (backbone, bin_mode, std_thresh) configs present in the filesystem cache."""
    from scripts.embedding_research.cache.binned_ptc import list_configs as _list_cache_configs

    return _list_cache_configs(backbone)


def query_head_sim_corr_done(con) -> set[tuple[str, str, float]]:
    """Return set of (backbone, bin_mode, std_thresh) that already have head_sim_corr data."""
    try:
        rows = con.execute("SELECT DISTINCT backbone, bin_mode, std_thresh FROM head_sim_corr_rows").fetchall()
    except duckdb.CatalogException:
        return set()
    return {(str(r[0]), str(r[1]), float(r[2])) for r in rows}


def query_binned_classify_done(con) -> set[tuple[str, str, str, str, float, int]]:
    try:
        rows = con.execute(
            "SELECT song_id, backbone, head, bin_mode, std_thresh, bin_id FROM binned_classify_ctp"
        ).fetchall()
    except duckdb.CatalogException:
        return set()
    return {(str(row[0]), str(row[1]), str(row[2]), str(row[3]), float(row[4]), int(row[5])) for row in rows}
