"""Flat-embedding pipeline scalar tables and filesystem-backed caches.

Pooled vectors and head activations are no longer stored in DuckDB — they
live on the filesystem via cache modules. This module only handles
scalar/metadata tables plus unified analyze metrics.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pandas as pd

_log = logging.getLogger(__name__)


# ── head activations (filesystem) ────────────────────────────────────────────
# head_results was a DuckDB table that stored flat PTC/CTP softmax outputs.
# All reads/writes now go through cache.flat_heads instead.


def upsert_head(
    song_id: str,
    backbone: str,
    head: str,
    strategy: str,
    pathway: str,
    act: list[float],
) -> None:
    """Write a single head activation to the filesystem cache."""
    import numpy as _np

    from scripts.embedding_research.cache import flat_heads as _fh

    _fh.save(backbone, head, strategy, pathway, song_id, _np.asarray(act, dtype=_np.float32))


def head_strategy_done(song_id: str, backbone: str, head: str, strategy: str) -> bool:
    """Return True iff both ptc and ctp activations are cached for this combination."""
    from scripts.embedding_research.cache import flat_heads as _fh

    return _fh.is_done(backbone, head, strategy, song_id)


def load_head_labels(
    sids: list[str],
    backbone: str,
    head: str,
    strategy: str,
    pathway: str,
    label_names: list[str],
) -> list[str] | None:
    """Return per-song majority-class label for (head, strategy, pathway).

    Returns None if >20% of songs are missing.
    """
    from scripts.embedding_research.cache import flat_heads as _fh

    act_map = _fh.load_bulk(backbone, head, strategy, pathway, sids)

    labels = []
    missing = 0
    for sid in sids:
        act = act_map.get(sid)
        if act is None:
            missing += 1
            labels.append("unknown")
        else:
            cls = int(np.argmax(act))
            labels.append(label_names[cls] if cls < len(label_names) else f"class_{cls}")

    if missing > 0.2 * len(sids):
        return None
    return labels


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
) -> None:
    """Insert non-`None` analysis metrics into `analyze_metrics`.

    Args:
        metrics: Metric values keyed by metric name; entries with `None` values are skipped.
    """
    rows: list[tuple] = []
    for name, value in metrics.items():
        if value is None:
            continue
        if isinstance(value, dict):
            for sub_name, sub_value in value.items():
                if sub_value is not None:
                    rows.append((strategy_key, strategy_type, sim_metric, k, f"{name}_{sub_name}", float(sub_value)))
        elif isinstance(value, (list, np.ndarray)):
            continue  # per-song lists are never written as aggregate metrics
        else:
            rows.append((strategy_key, strategy_type, sim_metric, k, name, float(value)))
    con.executemany("INSERT OR REPLACE INTO analyze_metrics VALUES (?,?,?,?,?,?)", rows)


def load_analyze_metrics(con) -> pd.DataFrame:
    """Load `analyze_metrics` as a wide DataFrame keyed by strategy and query settings.

    Returns:
        A DataFrame pivoted on `metric` so each metric name becomes a column, sorted by
        `disc_general` descending when that column is present.
    """
    df = con.execute("SELECT * FROM analyze_metrics").df()
    if df.empty:
        return df
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
