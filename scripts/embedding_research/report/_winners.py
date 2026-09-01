"""Exact per-(backbone, group, metric, K) winners, deltas, and factor summaries.

Phase 2 (Plan D) of the embedding-research repair: render an auditable benchmark
grid over every analysed configuration *without* averaging across groups, metric
families, K, backbones, or hidden strategy dimensions.

This module is research-only.  It defines three pure, deterministic row builders
consuming the *decoded* ``analyze_metrics`` pivot DataFrame (the output of
``_retrieval.query_analyze_metrics``):

* :func:`build_comparison_grid` — enumerate the comparison grid
  (backbone x retrieval group x metric family x K) over the available rows.
* :func:`build_winner_delta_rows` — per grid cell emit the deterministic winner
  (strategy key + value), the explicit global medoid baseline (key + value), and
  ``delta = winner - baseline`` for the *same* backbone x group x metric x K.
  The explicit baseline reference is never its own winner, so a negative delta
  means the best configuration is worse than the medoid baseline.
* :func:`build_factor_summary` — factor-level win counts / mean & best deltas
  grouped separately by backbone and by each configuration factor, retaining the
  group x metric x K dimensions and the contributing strategy keys.

The explicit medoid baseline policy is the single one established in Phase 1:
``global_pool:{backbone}:medoid`` resolved independently per backbone, never
max/median/mean across flat strategies and never a cross-backbone aggregate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd

from ._base import canonical_flat_baseline

if TYPE_CHECKING:
    from collections.abc import Iterable

# ---------------------------------------------------------------------------
# Grid vocabulary
# ---------------------------------------------------------------------------

# Retrieval groups, in deterministic report order.  ``general`` is included only
# when legitimately populated (see :func:`_general_cell_valid`).
GROUPS: tuple[str, ...] = ("artist", "genre", "head", "general")

# Canonical metric families, in deterministic report order.  Not every family is
# available for every group (general has no per-family MRR/NDCG/Recall column).
METRIC_FAMILIES: tuple[str, ...] = ("MAP", "MRR", "NDCG", "Recall", "discrimination")

# Canonical analyze-metrics column for each (group, metric family).
GROUP_METRIC_COLUMNS: dict[str, dict[str, str]] = {
    "artist": {
        "MAP": "map_k_artist",
        "MRR": "mrr",
        "NDCG": "ndcg_k_artist",
        "Recall": "recall_k_artist",
        "discrimination": "disc_artist",
    },
    "genre": {
        "MAP": "map_k_genre",
        "MRR": "mrr_genre",
        "NDCG": "ndcg_k_genre",
        "Recall": "recall_k_genre",
        "discrimination": "disc_genre",
    },
    "head": {
        "MAP": "map_k_head",
        "MRR": "mrr_head",
        "NDCG": "ndcg_k_head",
        "Recall": "recall_k_head",
        "discrimination": "disc_head",
    },
    "general": {
        "MAP": "map_k_general",
        "discrimination": "disc_general",
    },
}

# Documented tie-break order for winner selection.  When two eligible rows are
# tied on the metric value, the winner is the row that sorts *earliest* by this
# key (compared lexicographically in this exact order).  This is the source of
# truth referenced by the emitted ``tie_break_key``.
TIE_BREAK_ORDER: tuple[str, ...] = (
    "strategy_type",
    "pathway/head",
    "bin_mode",
    "threshold",
    "rep_a",
    "rep_b",
    "aggregate",
    "strategy_key",
)

# Strategy-type precedence for tie-breaking (global_pool < ptc < ctp).
STRATEGY_TYPE_RANK: dict[str, int] = {"global_pool": 0, "ptc": 1, "ctp": 2}

# Factors reported by :func:`build_factor_summary`, each mapped to the emitted
# winner row column that carries its value.
FACTOR_COLUMNS: dict[str, str] = {
    "strategy_type": "winner_strategy_type",
    "flat_strategy": "winner_flat_strategy",
    "pathway": "winner_pathway",
    "head": "winner_head",
    "bin_mode": "winner_bin_mode",
    "threshold": "winner_threshold",
    "rep_a": "winner_rep_a",
    "rep_b": "winner_rep_b",
    "aggregate": "winner_aggregate",
    "sim_metric": "winner_sim_metric",
}

# Columns emitted by :func:`build_winner_delta_rows`.
WINNER_DELTA_COLUMNS: list[str] = [
    "backbone",
    "group",
    "metric",
    "k",
    "winner_strategy_key",
    "winner_strategy_type",
    "winner_value",
    "winner_flat_strategy",
    "winner_pathway",
    "winner_head",
    "winner_bin_mode",
    "winner_threshold",
    "winner_rep_a",
    "winner_rep_b",
    "winner_aggregate",
    "winner_sim_metric",
    "baseline_strategy_key",
    "baseline_value",
    "delta",
    "tie_break_key",
    "corpus_hash",
    "corpus_size",
]

# Columns emitted by :func:`build_factor_summary`.
FACTOR_SUMMARY_COLUMNS: list[str] = [
    "backbone",
    "factor",
    "factor_value",
    "group",
    "metric",
    "k",
    "n_wins",
    "mean_delta",
    "best_delta",
    "config_ids",
]


# ---------------------------------------------------------------------------
# Value normalisation helpers
# ---------------------------------------------------------------------------


def _clean(value) -> Any:
    """Normalise None / NaN to None so it can be compared and grouped safely."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    return value


def _str_key(value) -> str:
    return "" if _clean(value) is None else str(value)


def _num_key(value) -> float:
    clean = _clean(value)
    return float("-inf") if clean is None else float(clean)


# ---------------------------------------------------------------------------
# Grid enumeration (P2-S1)
# ---------------------------------------------------------------------------


def _general_cell_valid(rows: pd.DataFrame, backbone: str, k: int, metric_col: str) -> bool:
    """Validity rule for the ``general`` retrieval group.

    A general cell is included only when it is legitimately populated:

    * the general metric column has at least one non-null value among the
      eligible flat/binned rows for this backbone and K; **and**
    * for the MAP family, at least two of the per-group MAP components
      (``map_k_artist`` / ``map_k_genre`` / ``map_k_head``) that the general
      aggregate averages are themselves populated for this backbone and K
      (mirroring how ``map_k_general`` is derived in ``common/analyze.py``).
      If none of the component columns are present, validity falls back to the
      general value being non-null.
    """
    eligible = rows[(rows["backbone"] == backbone) & (rows["k"] == k)]
    if eligible.empty or metric_col not in eligible.columns or not eligible[metric_col].notna().any():
        return False
    if metric_col == "map_k_general":
        comps = [c for c in ("map_k_artist", "map_k_genre", "map_k_head") if c in eligible.columns]
        if comps:
            return sum(bool(eligible[c].notna().any()) for c in comps) >= 2
    return True


def build_comparison_grid(
    rows: pd.DataFrame,
    k_values: Iterable[int] | None = None,
) -> pd.DataFrame:
    """Enumerate the comparison grid as a deterministic DataFrame of cells.

    Each row is one ``backbone x group x metric-family x K`` cell that has at
    least one eligible (non-null metric) flat/binned row.  No dimension is
    averaged: every cell is its own row.  ``general`` cells obey the validity
    rule in :func:`_general_cell_valid`.

    Columns: ``backbone``, ``group``, ``metric`` (family name), ``metric_col``
    (the underlying analyze-metrics column), ``k``, ``n_eligible``.
    """
    if rows is None or rows.empty or "backbone" not in rows.columns or "k" not in rows.columns:
        return pd.DataFrame(columns=["backbone", "group", "metric", "metric_col", "k", "n_eligible"])

    requested = sorted({int(k) for k in (k_values or [])})
    cells: list[dict] = []
    for backbone in sorted({str(b) for b in rows["backbone"].dropna().tolist()}):
        present_ks = sorted({int(v) for v in rows.loc[rows["backbone"] == backbone, "k"].dropna().tolist()})
        for group in GROUPS:
            for family, metric_col in GROUP_METRIC_COLUMNS[group].items():
                if metric_col not in rows.columns:
                    continue
                for k in sorted(set(present_ks) | set(requested)):
                    if group == "general" and not _general_cell_valid(rows, backbone, k, metric_col):
                        continue
                    eligible = rows[(rows["backbone"] == backbone) & (rows["k"] == k) & rows[metric_col].notna()]
                    if eligible.empty:
                        continue
                    cells.append(
                        {
                            "backbone": backbone,
                            "group": group,
                            "metric": family,
                            "metric_col": metric_col,
                            "k": k,
                            "n_eligible": len(eligible),
                        }
                    )
    return pd.DataFrame(cells)


# ---------------------------------------------------------------------------
# Deterministic winner selection (P2-S2)
# ---------------------------------------------------------------------------


def _pathway(row) -> str:
    st = _clean(row.get("strategy_type"))
    return {"global_pool": "flat", "ptc": "ptc", "ctp": "ctp"}.get(str(st), str(st) if st is not None else "?")


def _tie_break_key(row) -> tuple:
    """Comparable tie-break tuple in :data:`TIE_BREAK_ORDER`.

    Lexicographically smaller = earlier in the documented tie-break order, so the
    winner among value-tied rows is the one with the smallest tuple.  The
    ``pathway/head`` slot folds the pathway in and appends the head for CTP rows.
    """
    head = _clean(row.get("head"))
    pathway = _pathway(row)
    pathway_head = f"{pathway}/{head}" if head is not None else pathway
    return (
        STRATEGY_TYPE_RANK.get(str(_clean(row.get("strategy_type"))), 99),
        pathway_head,
        _str_key(row.get("bin_mode")),
        _num_key(row.get("std_thresh")),
        _str_key(row.get("rep_a")),
        _str_key(row.get("rep_b")),
        _str_key(row.get("agg_method")),
        str(row.get("strategy_key", "")),
    )


def _tie_break_display(row) -> str:
    """Human-readable tie-break key in the documented order."""
    head = _clean(row.get("head"))
    pathway = _pathway(row)
    pathway_head = f"{pathway}/{head}" if head is not None else pathway
    threshold = _clean(row.get("std_thresh"))
    return " > ".join(
        [
            str(_clean(row.get("strategy_type"))),
            pathway_head,
            _str_key(row.get("bin_mode")) or "—",
            f"{threshold:g}" if threshold is not None else "—",
            _str_key(row.get("rep_a")) or "—",
            _str_key(row.get("rep_b")) or "—",
            _str_key(row.get("agg_method")) or "—",
            str(row.get("strategy_key", "")),
        ]
    )


def select_winner(rows: pd.DataFrame, *, backbone: str, metric_col: str, k: int) -> dict | None:
    """Deterministic winner for one grid cell over ALL eligible flat + binned rows.

    Null/absent metric rows are excluded from winner selection.  Among the
    remaining rows the highest value wins; value ties are broken by the smallest
    :data:`TIE_BREAK_ORDER` key.  Returns a dict of the winning row's decoded
    fields plus ``value`` (as float) and ``tie_break_key`` (display), or ``None``
    when the cell has no eligible row.
    """
    if rows is None or rows.empty or metric_col not in rows.columns:
        return None
    cell = rows[(rows["backbone"] == backbone) & (rows["k"] == k) & rows[metric_col].notna()]
    if cell.empty:
        return None
    cell = cell.copy()
    cell["_tb"] = cell.apply(_tie_break_key, axis=1)
    cell["_val"] = cell[metric_col].astype(float)
    cell = cell.sort_values(["_val", "_tb"], ascending=[False, True])
    winner = cell.iloc[0]
    out = winner.to_dict()
    out["value"] = float(winner["_val"])
    out["tie_break_key"] = _tie_break_display(winner)
    return out


def _winner_factors(winner: dict) -> dict:
    """Decode the winner's configuration-factor values from its decoded fields."""
    st = _clean(winner.get("strategy_type"))
    if st == "global_pool":
        return {
            "flat_strategy": _clean(winner.get("strategy")),
            "pathway": "flat",
            "head": None,
            "bin_mode": None,
            "threshold": None,
            "rep_a": None,
            "rep_b": None,
            "aggregate": None,
        }
    return {
        "flat_strategy": None,
        "pathway": _pathway(winner),
        "head": _clean(winner.get("head")),
        "bin_mode": _clean(winner.get("bin_mode")),
        "threshold": _clean(winner.get("std_thresh")),
        "rep_a": _clean(winner.get("rep_a")),
        "rep_b": _clean(winner.get("rep_b")),
        "aggregate": _clean(winner.get("agg_method")),
    }


# ---------------------------------------------------------------------------
# Winner-delta rows (P2-S3)
# ---------------------------------------------------------------------------


def build_winner_delta_rows(
    rows: pd.DataFrame,
    baseline_rows: pd.DataFrame,
    k_values: Iterable[int] | None = None,
    *,
    corpus_hash: str | None = None,
    corpus_size: int | None = None,
) -> pd.DataFrame:
    """Emit one exact winner-delta row per grid cell that has both a winner and a baseline.

    ``rows`` is the decoded analyze-metrics pivot (winner candidates).  The
    baseline for each cell is resolved from ``baseline_rows`` as exactly the
    ``global_pool:{backbone}:medoid`` rows for the same backbone and K — never a
    cross-strategy or cross-backbone aggregate.  A delta row is emitted only when
    the cell has both a non-null winner **and** a non-null medoid baseline value
    (per the null-handling rule).  ``k_values`` optionally pins the K set to
    enumerate; any K present in ``rows`` is also included.

    The explicit medoid baseline reference for a cell is excluded from winner
    candidacy (a configuration cannot "beat" its own reference), so ``delta`` is
    negative when every configuration is worse than the baseline, zero on a tie
    with the baseline, and positive only when a configuration beats it.

    Emitted columns: ``WINNER_DELTA_COLUMNS``.  ``corpus_hash`` / ``corpus_size``
    are carried through verbatim (None when not supplied).
    """
    grid = build_comparison_grid(rows, k_values=k_values)
    out: list[dict] = []
    for cell in grid.to_dict("records"):
        baseline_key = f"global_pool:{cell['backbone']}:medoid"
        # The explicit baseline reference never competes against itself, so the
        # winner is the best *other* configuration and a negative delta is possible.
        candidates = rows[~((rows["strategy_key"] == baseline_key) & (rows["strategy_type"] == "global_pool"))]
        winner = select_winner(
            candidates,
            backbone=cell["backbone"],
            metric_col=cell["metric_col"],
            k=cell["k"],
        )
        if winner is None:
            continue
        baseline = canonical_flat_baseline(baseline_rows, cell["backbone"], k=cell["k"])
        if baseline.empty or cell["metric_col"] not in baseline.columns:
            continue
        baseline_vals = baseline[cell["metric_col"]].dropna()
        if baseline_vals.empty:
            continue
        baseline_value = float(baseline_vals.max())
        factors = _winner_factors(winner)
        out.append(
            {
                "backbone": cell["backbone"],
                "group": cell["group"],
                "metric": cell["metric"],
                "k": cell["k"],
                "winner_strategy_key": winner.get("strategy_key"),
                "winner_strategy_type": winner.get("strategy_type"),
                "winner_value": winner["value"],
                "winner_flat_strategy": factors["flat_strategy"],
                "winner_pathway": factors["pathway"],
                "winner_head": factors["head"],
                "winner_bin_mode": factors["bin_mode"],
                "winner_threshold": factors["threshold"],
                "winner_rep_a": factors["rep_a"],
                "winner_rep_b": factors["rep_b"],
                "winner_aggregate": factors["aggregate"],
                "winner_sim_metric": _clean(winner.get("sim_metric")),
                "baseline_strategy_key": f"global_pool:{cell['backbone']}:medoid",
                "baseline_value": baseline_value,
                "delta": float(winner["value"] - baseline_value),
                "tie_break_key": winner["tie_break_key"],
                "corpus_hash": corpus_hash,
                "corpus_size": corpus_size,
            }
        )
    if not out:
        return pd.DataFrame(columns=WINNER_DELTA_COLUMNS)
    return pd.DataFrame(out, columns=WINNER_DELTA_COLUMNS)


# ---------------------------------------------------------------------------
# Factor summaries (P2-S4)
# ---------------------------------------------------------------------------


def build_factor_summary(winner_delta_rows: pd.DataFrame) -> pd.DataFrame:
    """Summarize factor-level wins/deltas grouped separately by backbone and factor.

    For every factor in :data:`FACTOR_COLUMNS`, group the winner rows by
    (backbone, factor value, group, metric, K) and emit:

    * ``n_wins`` — number of grid cells where this factor value was the winner;
    * ``mean_delta`` / ``best_delta`` — over those winning cells' deltas;
    * ``config_ids`` — the distinct contributing configuration identities
      (winner strategy keys), not just counts.

    Backbone separation and the full group x metric x K dimensions are retained;
    no averaging across hidden configurations.
    """
    if winner_delta_rows is None or winner_delta_rows.empty:
        return pd.DataFrame(columns=FACTOR_SUMMARY_COLUMNS)
    out: list[dict] = []
    for factor, col in FACTOR_COLUMNS.items():
        if col not in winner_delta_rows.columns:
            continue
        group_cols = ["backbone", col, "group", "metric", "k"]
        present_group_cols = [c for c in group_cols if c in winner_delta_rows.columns]
        for keys, grp in winner_delta_rows.groupby(present_group_cols, dropna=False):
            deltas = grp["delta"].dropna() if "delta" in grp.columns else pd.Series(dtype=float)
            if deltas.empty:
                continue
            configs = sorted(
                {str(v) for v in grp["winner_strategy_key"].dropna().unique()}
                if "winner_strategy_key" in grp.columns
                else []
            )
            keys_dict = keys if isinstance(keys, dict) else dict(zip(present_group_cols, keys, strict=False))
            out.append(
                {
                    "backbone": keys_dict.get("backbone"),
                    "factor": factor,
                    "factor_value": keys_dict.get(col),
                    "group": keys_dict.get("group"),
                    "metric": keys_dict.get("metric"),
                    "k": keys_dict.get("k"),
                    "n_wins": len(grp),
                    "mean_delta": float(deltas.mean()),
                    "best_delta": float(deltas.max()),
                    "config_ids": configs,
                }
            )
    if not out:
        return pd.DataFrame(columns=FACTOR_SUMMARY_COLUMNS)
    df = pd.DataFrame(out, columns=FACTOR_SUMMARY_COLUMNS)
    sort_cols = [c for c in ["backbone", "factor", "factor_value", "group", "metric", "k"] if c in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols, na_position="first")
    return df


__all__ = [
    "FACTOR_COLUMNS",
    "FACTOR_SUMMARY_COLUMNS",
    "GROUPS",
    "GROUP_METRIC_COLUMNS",
    "METRIC_FAMILIES",
    "TIE_BREAK_ORDER",
    "WINNER_DELTA_COLUMNS",
    "build_comparison_grid",
    "build_factor_summary",
    "build_winner_delta_rows",
    "select_winner",
]
