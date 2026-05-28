"""Flat-embedding pipeline scalar tables and filesystem-backed caches.

Pooled vectors and head activations are no longer stored in DuckDB — they
live on the filesystem via cache modules. This module only handles
scalar/metadata tables plus unified analyze metrics.
"""

from __future__ import annotations

import logging

import numpy as np
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


def query_flat_head_labels(con, backbone: str, sids: list[str]) -> list[list[float]]:
    """Return per-head score matrix for ``sids`` from the ``flat_head_labels`` table.

    Args:
        con: DuckDB connection.
        backbone: Backbone identifier used to filter rows.
        sids: Ordered list of song IDs to include.

    Returns:
        A list of ``len(heads)`` rows, each of length ``len(sids)``, ordered by
        sorted head name. Missing songs default to ``0.0``.
    """
    rows = con.execute(
        "SELECT song_id, head, score FROM flat_head_labels WHERE backbone = ?",
        [backbone],
    ).fetchall()
    score_map: dict[str, dict[str, float]] = {}
    heads: set[str] = set()
    for song_id, head, score in rows:
        song_scores = score_map.setdefault(song_id, {})
        song_scores[head] = float(score)
        heads.add(head)

    if not heads:
        _log.warning(
            "[query_flat_head_labels] no head scores found in DB for backbone=%s — disc_head will be 0", backbone
        )
        return []
    missing_songs = [sid for sid in sids if sid not in score_map]
    if missing_songs:
        _log.warning(
            "[query_flat_head_labels] %d/%d songs have no head scores for backbone=%s — defaulting to 0.0 (classify ran partially?)",
            len(missing_songs),
            len(sids),
            backbone,
        )
    ordered_heads = sorted(heads)
    from scripts.embedding_research.config import HEADS as _HEADS

    config_heads = list(_HEADS.get(backbone, {}).keys())
    if config_heads and ordered_heads != config_heads:
        _log.warning(
            "[query_flat_head_labels] DB heads %s differ from config heads %s for backbone=%s — using DB order",
            ordered_heads,
            config_heads,
            backbone,
        )
    return [[score_map.get(song_id, {}).get(head, 0.0) for song_id in sids] for head in ordered_heads]


# ── analyze_metrics ───────────────────────────────────────────────────────────


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
        else:
            rows.append((strategy_key, strategy_type, sim_metric, k, name, value))
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


def upsert_flat_head_labels(con, song_id: str, backbone: str, head: str, score: float) -> None:
    con.execute(
        "INSERT INTO flat_head_labels (song_id, backbone, head, score) VALUES (?,?,?,?) ON CONFLICT (song_id, backbone, head) DO UPDATE SET score=excluded.score",
        [song_id, backbone, head, score],
    )
