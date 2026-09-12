"""Geometry-era flat metric persistence.

This module owns the small scalar metric tables used by the geometry corpus owner.  Strategy
keys are transient storage addresses only; semantic identity is persisted separately in the
  exact geometry evidence rows.  No alternate metric vocabulary is accepted here.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd


def _finite(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def clear_song_retrieval_metrics(con, strategy_key: str, sim_metric: str, k: int) -> None:
    """Remove one geometry winner-representation's transient per-song metrics."""
    if not strategy_key or not sim_metric:
        raise ValueError("strategy_key and sim_metric are required")
    con.execute(
        "DELETE FROM song_retrieval_metrics WHERE strategy_key=? AND sim_metric=? AND k=?",
        (str(strategy_key), str(sim_metric), int(k)),
    )


def write_song_retrieval_metrics(
    con,
    strategy_key: str,
    sim_metric: str,
    k: int,
    per_song: Mapping[str, Sequence[Any]],
) -> None:
    """Write finite per-song geometry metrics for one transient representation key."""
    song_ids = tuple(str(song_id) for song_id in per_song.get("song_ids", ()))
    fields = ("ap_k", "mrr", "recall_k", "disc_artist_contrib", "disc_genre_contrib", "disc_head_contrib")
    values = {field: tuple(per_song.get(field, ())) for field in fields}
    if any(len(values[field]) not in (0, len(song_ids)) for field in fields):
        raise ValueError("per-song metric arrays must be empty or match song_ids length")
    rows = []
    for index, song_id in enumerate(song_ids):
        row: list[Any] = [song_id]
        for field in fields:
            seq = values[field]
            row.append(None if not seq else _finite(seq[index], field))
        rows.append(tuple(row))
    if not rows:
        return
    con.executemany(
        "INSERT OR REPLACE INTO song_retrieval_metrics "
        "(strategy_key, sim_metric, k, song_id, ap_k, mrr, recall_k, "
        "disc_artist_contrib, disc_genre_contrib, disc_head_contrib) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(str(strategy_key), str(sim_metric), int(k), *row) for row in rows],
    )


def _flatten_metrics(value: Any, prefix: str = "") -> dict[str, float]:
    if isinstance(value, Mapping):
        out: dict[str, float] = {}
        for key in sorted(value):
            child = f"{prefix}_{key}" if prefix else str(key)
            out.update(_flatten_metrics(value[key], child))
        return out
    if isinstance(value, (list, tuple)):
        return {}
    try:
        return {prefix: _finite(value, prefix)} if prefix else {}
    except ValueError:
        return {}


def write_analyze_metrics(
    con,
    strategy_key: str,
    strategy_type: str,
    sim_metric: str,
    k: int,
    metrics: Mapping[str, Any],
    *,
    run_id: str,
) -> None:
    """Replace only one run-scoped geometry metric scope with finite scalar values."""
    if not run_id or not strategy_key or not strategy_type or not sim_metric:
        raise ValueError("run_id, strategy_key, strategy_type, and sim_metric are required")
    flat = _flatten_metrics(metrics)
    con.execute(
        "DELETE FROM analyze_metrics WHERE run_id=? AND strategy_key=? AND sim_metric=? AND k=?",
        (str(run_id), str(strategy_key), str(sim_metric), int(k)),
    )
    if flat:
        con.executemany(
            "INSERT INTO analyze_metrics "
            "(run_id, strategy_key, strategy_type, sim_metric, k, metric, value) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (str(run_id), str(strategy_key), str(strategy_type), str(sim_metric), int(k), metric, value)
                for metric, value in sorted(flat.items())
            ],
        )


def load_analyze_metrics(con, *, run_id: str | None = None):
    """Load scalar geometry metrics as a wide frame (one column per metric name).

    The returned frame is run-scoped when ``run_id`` is supplied, otherwise it spans the
    whole table.  Metric names become columns; rows are keyed by the storage keys
    (``run_id``, ``strategy_key``, ``strategy_type``, ``sim_metric``, ``k``).  When a
    ``disc_general`` column is present it orders rows descending; otherwise rows are
    returned in deterministic key order.
    """
    query = "SELECT run_id, strategy_key, strategy_type, sim_metric, k, metric, value FROM analyze_metrics"
    params: list[Any] = []
    if run_id is not None:
        query += " WHERE run_id=?"
        params.append(str(run_id))
    rows = [
        {
            "run_id": str(row[0]),
            "strategy_key": str(row[1]),
            "strategy_type": str(row[2]),
            "sim_metric": str(row[3]),
            "k": int(row[4]),
            "metric": str(row[5]),
            "value": float(row[6]),
        }
        for row in con.execute(query, params).fetchall()
    ]
    index = ["run_id", "strategy_key", "strategy_type", "sim_metric", "k"]
    if not rows:
        return pd.DataFrame(columns=index)
    frame = pd.DataFrame(rows).pivot_table(index=index, columns="metric", values="value", aggfunc="first")
    frame.columns.name = None
    frame = frame.reset_index()
    if run_id is None:
        # Whole-table view: one row per storage scope (strategy_key/type/sim_metric/k),
        # deterministic latest generation by run_id.  Per-run scoping stays exact when
        # ``run_id`` is supplied.
        frame = frame.sort_values("run_id").drop_duplicates(
            subset=["strategy_key", "strategy_type", "sim_metric", "k"], keep="last"
        )
    if "disc_general" in frame.columns:
        frame = frame.sort_values("disc_general", ascending=False).reset_index(drop=True)
    return frame


__all__ = [
    "clear_song_retrieval_metrics",
    "load_analyze_metrics",
    "write_analyze_metrics",
    "write_song_retrieval_metrics",
]
