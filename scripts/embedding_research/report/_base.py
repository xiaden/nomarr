"""Shared rendering primitives: formatting helpers and Plotly chart/table/section builders."""

from __future__ import annotations

import json as _json
from typing import TYPE_CHECKING, Any, cast

import pandas as pd

if TYPE_CHECKING:
    import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Plotly theme constants
# ---------------------------------------------------------------------------

_PLOT_BG = "#12131e"
_PAPER_BG = "#1a1b26"
_GRID_COLOR = "#555"
_FONT_COLOR = "#e0e0e8"
_H_SMALL = 320
_H_MED = 420
_H_LARGE = 560

# ---------------------------------------------------------------------------
# Plotly helpers
# ---------------------------------------------------------------------------


def apply_dark_theme(fig: go.Figure, *, grid: bool = True) -> None:
    """Apply standard dark-theme styling to a Plotly figure in-place."""
    axis_style: dict = {
        "showgrid": grid,
        "gridcolor": _GRID_COLOR,
        "gridwidth": 0.5,
        "linecolor": "#333",
        "tickfont": {"color": _FONT_COLOR, "size": 8},
        "zerolinecolor": "#333",
    }
    fig.update_layout(
        plot_bgcolor=_PLOT_BG,
        paper_bgcolor=_PAPER_BG,
        font={"color": _FONT_COLOR, "size": 10},
        xaxis=axis_style,
        yaxis=axis_style,
        margin={"l": 48, "r": 16, "t": 36, "b": 36},
    )


def figure_dict(fig: go.Figure) -> dict:
    """Return a Plotly figure as a JSON-serialisable dict.

    Uses ``fig.to_json()`` then ``json.loads`` to ensure all numpy types are
    converted to plain Python scalars before the dict is embedded in the payload.
    """
    return cast("dict[str, Any]", _json.loads(fig.to_json()))


def make_chart(fig: go.Figure, *, id: str = "", title: str = "") -> dict:
    """Build a chart descriptor dict from a Plotly figure."""
    return {"id": id, "title": title, "type": "plotly", "figure": figure_dict(fig)}


# ---------------------------------------------------------------------------
# Column name lists (single source of truth for query / display)
# ---------------------------------------------------------------------------

ANALYZE_METRICS_COLUMNS = [
    "strategy_key",
    "strategy_type",
    "sim_metric",
    "k",
    "backbone",
    "strategy",
    "head",
    "bin_mode",
    "std_thresh",
    "rep_a",
    "rep_b",
    "agg_method",
    "disc_general",
    "disc_artist",
    "disc_genre",
    "disc_head",
    "disc_score",
    "mean_within",
    "mean_cross",
    "map_k",
    "mrr",
    "ndcg_k",
    "recall_k",
    "recall_k_genre",
    "precision_k_genre",
    "map_k_artist",
    "ndcg_k_artist",
    "recall_k_artist",
    "map_k_genre",
    "mrr_genre",
    "ndcg_k_genre",
    "map_k_head",
    "mrr_head",
    "ndcg_k_head",
    "recall_k_head",
    "map_k_general",
    "mean_within_artist",
    "var_within_artist",
    "mean_cross_artist",
    "var_cross_artist",
    "mean_within_genre",
    "var_within_genre",
    "mean_cross_genre",
    "var_cross_genre",
    "mean_within_head",
    "var_within_head",
    "mean_cross_head",
    "var_cross_head",
    "var_ap_k_genre",
    "kurt_ap_k_genre",
    "var_ap_k_head",
    "kurt_ap_k_head",
    "var_mrr_genre",
    "kurt_mrr_genre",
    "var_mrr_head",
    "kurt_mrr_head",
    "flat_binned_spearman",
    "flat_binned_beneficial_reorder_rate",
]

STRATEGY_TYPES = ["global_pool", "ptc", "ctp"]

# ---------------------------------------------------------------------------
# Data formatting helpers
# ---------------------------------------------------------------------------


def empty_df(columns: list[str]) -> pd.DataFrame:
    """Return an empty DataFrame with the given columns."""
    return pd.DataFrame(columns=columns)


def _decode_strategy_key(df: pd.DataFrame) -> pd.DataFrame:
    """Append derived strategy configuration columns decoded from ``strategy_key``."""
    decoded = df.copy()
    decoded = decoded.assign(
        backbone=None,
        strategy=None,
        head=None,
        bin_mode=None,
        std_thresh=None,
        rep_a=None,
        rep_b=None,
        agg_method=None,
    )
    if decoded.empty or "strategy_key" not in decoded.columns or "strategy_type" not in decoded.columns:
        return decoded

    parts = decoded["strategy_key"].astype(str).str.split(":")
    global_pool_mask = decoded["strategy_type"] == "global_pool"
    ptc_mask = decoded["strategy_type"] == "ptc"
    ctp_mask = decoded["strategy_type"] == "ctp"

    decoded.loc[global_pool_mask, "backbone"] = parts[global_pool_mask].str[1]
    decoded.loc[global_pool_mask, "strategy"] = parts[global_pool_mask].str[2]

    decoded.loc[ptc_mask, "backbone"] = parts[ptc_mask].str[1]
    decoded.loc[ptc_mask, "bin_mode"] = parts[ptc_mask].str[2]
    decoded.loc[ptc_mask, "std_thresh"] = pd.to_numeric(parts[ptc_mask].str[3], errors="coerce")
    decoded.loc[ptc_mask, "rep_a"] = parts[ptc_mask].str[4]
    decoded.loc[ptc_mask, "rep_b"] = parts[ptc_mask].str[5]
    decoded.loc[ptc_mask, "agg_method"] = parts[ptc_mask].str[6]

    decoded.loc[ctp_mask, "backbone"] = parts[ctp_mask].str[1]
    decoded.loc[ctp_mask, "head"] = parts[ctp_mask].str[2]
    decoded.loc[ctp_mask, "std_thresh"] = pd.to_numeric(parts[ctp_mask].str[3], errors="coerce")
    decoded.loc[ctp_mask, "rep_a"] = parts[ctp_mask].str[4]
    decoded.loc[ctp_mask, "rep_b"] = parts[ctp_mask].str[5]
    decoded.loc[ctp_mask, "agg_method"] = parts[ctp_mask].str[6]

    return decoded


def fmt(v) -> str:
    """Format a value for table display: '—' for None/NaN, 4 d.p. for floats, str otherwise."""
    if v is None:
        return "—"
    if isinstance(v, float):
        if pd.isna(v):
            return "—"
        return f"{v:.4f}"
    return str(v)


def rep_label(rep: str | None) -> str:
    """Human-readable pooling label for report tables."""
    if rep is None:
        return "—"
    rep_s = str(rep)
    if rep_s == "median":
        return "coord-median"
    if rep_s == "medoid":
        return "medoid"
    return rep_s


def agg_label(agg: str | None) -> str:
    """Human-readable aggregation / score-variant label for report tables.

    Position 6 of a ptc/ctp strategy key carries the explicit score-variant
    identity: the primary ``max_per_candidate_segment`` method or one of the
    opt-in legacy weighted hypotheses.  A generic mean/median/max/min/medoid
    aggregate is not a labelled scoring method and is never produced here.
    """
    if agg is None:
        return "—"
    agg_s = str(agg)
    if agg_s == "max_per_candidate_segment":
        return "max-per-candidate"
    if agg_s == "target_weighted":
        return "target-wtd"
    if agg_s == "bidirectional_weighted":
        return "bidir-wtd"
    if agg_s == "normalized_mean_pair_weighted":
        return "norm-pair-wtd"
    return agg_s


# Documented ambiguity (tie / collision) variants for the explicit score variants
# (Plan A scoring-primary contract).  The primary max-per-candidate-segment method
# uses the ``first_index + retain_all_candidate_segments`` variant (one contribution
# per candidate segment, denominator = sum of all candidate weights); the documented
# alternative is ``equal_tie_split + unique_source_max``.  Legacy weighted hypotheses
# are single formulas with no per-candidate tie/collision ambiguity and are labelled
# as such.
_PRIMARY_SCORE_VARIANT = "max_per_candidate_segment"
_PRIMARY_AMBIGUITY_VARIANT = "first_index + retain_all_candidate_segments"
_ALTERNATIVE_AMBIGUITY_VARIANT = "equal_tie_split + unique_source_max"
_LEGACY_WEIGHTED_HYPOTHESIS_VARIANT = "legacy_weighted_hypothesis"
_LEGACY_WEIGHTED_AGGS = ("target_weighted", "bidirectional_weighted", "normalized_mean_pair_weighted")


def ambiguity_variant_label(agg: str | None) -> str:
    """Human-readable ambiguity (tie/collision) variant for a score-variant label.

    Every ptc/ctp strategy key carries an explicit score-variant identity in
    position 6.  The primary ``max_per_candidate_segment`` variant always uses the
    documented ``first_index + retain_all_candidate_segments`` tie/collision policy;
    the legacy weighted hypotheses are single formulas with no per-candidate
    ambiguity.  Returns ``—`` for the flat baseline or an unknown label.
    """
    if agg is None:
        return "—"
    agg_s = str(agg)
    if agg_s == _PRIMARY_SCORE_VARIANT:
        return _PRIMARY_AMBIGUITY_VARIANT
    if agg_s in _LEGACY_WEIGHTED_AGGS:
        return _LEGACY_WEIGHTED_HYPOTHESIS_VARIANT
    return "—"


def binned_config_label(
    *,
    bin_mode: str | None,
    std_thresh,
    rep_a: str | None,
    rep_b: str | None,
    agg_method: str | None,
) -> str:
    """Stable human-readable binned config label used throughout the report."""
    t = f"{float(std_thresh):g}" if pd.notna(std_thresh) else "—"
    return f"{bin_mode}/{t}/{rep_label(rep_a)}x{rep_label(rep_b)}/{agg_label(agg_method)}"


def canonical_flat_baseline(
    rows: pd.DataFrame,
    backbone: str,
    *,
    k: int | None = None,
) -> pd.DataFrame:
    """Resolve exactly the ``global_pool:{backbone}:medoid`` rows.

    This is the single explicit medoid baseline per backbone. It never falls back to
    max/median/mean across flat strategies and never mixes backbones. A missing medoid
    row yields an empty DataFrame — callers must not substitute another aggregation.
    ``k`` optionally narrows to one evaluation K.
    """
    out = rows.iloc[0:0].copy()
    if rows.empty or "strategy_key" not in rows.columns or "strategy_type" not in rows.columns:
        return out
    expected = f"global_pool:{backbone}:medoid"
    mask = (rows["strategy_type"] == "global_pool") & (rows["strategy_key"] == expected)
    if "backbone" in rows.columns:
        mask &= rows["backbone"] == backbone
    if "strategy" in rows.columns:
        mask &= rows["strategy"] == "medoid"
    if k is not None and "k" in rows.columns:
        mask &= rows["k"] == k
    return rows.loc[mask].copy()


def flat_medoid_value(
    rows: pd.DataFrame,
    backbone: str,
    col: str,
    *,
    k: int | None = None,
) -> float | None:
    """Return the medoid-baseline value for *col* on *backbone*, or None if absent.

    Picks one deterministic value from the medoid rows (they differ only by evaluation
    K when multiple K are present); never aggregates across flat strategies.
    """
    medoid = canonical_flat_baseline(rows, backbone, k=k)
    if medoid.empty or col not in medoid.columns:
        return None
    vals = medoid[col].dropna()
    if vals.empty:
        return None
    return float(vals.max())


def binned_identity_label(row) -> str:
    """Full-identity binned label: pathway + head + bin/rep/agg configuration."""
    st = row.get("strategy_type")
    pathway = {"ptc": "PTC", "ctp": "CTP"}.get(str(st), str(st) if st is not None else "?")
    head = row.get("head")
    head_part = ""
    if head is not None and not (isinstance(head, float) and pd.isna(head)):
        head_part = f"/head={head}"
    base = binned_config_label(
        bin_mode=row.get("bin_mode"),
        std_thresh=row.get("std_thresh"),
        rep_a=row.get("rep_a"),
        rep_b=row.get("rep_b"),
        agg_method=row.get("agg_method"),
    )
    return f"{pathway}{head_part}/{base}"


def table_exists(con, name: str) -> bool:
    """Return True if a table named *name* exists in the DuckDB connection."""
    try:
        rows = con.execute("SELECT 1 FROM information_schema.tables WHERE table_name = ? LIMIT 1", [name]).fetchall()
        return len(rows) > 0
    except Exception:
        return False


def _pareto_front_indices(x: list[float], y: list[float]) -> set[int]:
    """Return indices of Pareto-optimal points (not dominated on both axes, higher = better)."""
    n = len(x)
    dominated: set[int] = set()
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if x[j] >= x[i] and y[j] >= y[i] and (x[j] > x[i] or y[j] > y[i]):
                dominated.add(i)
                break
    return set(range(n)) - dominated


# ---------------------------------------------------------------------------
# Section / table / panel builders
# ---------------------------------------------------------------------------


def make_table(
    rows: list[dict],
    *,
    id: str = "",
    title: str = "",
    collapsible: bool = False,
    summary_text: str = "",
    open: bool = False,
) -> dict:
    """Build a table descriptor dict from a list of row dicts.

    Each row dict must have the same keys; values are formatted with :func:`fmt`.
    """
    if not rows:
        return {
            "id": id,
            "title": title,
            "columns": [],
            "rows": [],
            "collapsible": collapsible,
            "summary_text": summary_text,
            "open": open,
            "empty": True,
        }
    columns = list(rows[0].keys())
    data_rows = [[fmt(row.get(c)) for c in columns] for row in rows]
    return {
        "id": id,
        "title": title,
        "columns": columns,
        "rows": data_rows,
        "collapsible": collapsible,
        "summary_text": summary_text,
        "open": open,
        "empty": False,
    }


def make_panel(
    id: str,
    title: str,
    *,
    open: bool = False,
    charts: list[dict] | None = None,
    tables: list[dict] | None = None,
    text: str = "",
    subsections: list[dict] | None = None,
) -> dict:
    """Build a collapsible panel descriptor dict."""
    return {
        "id": id,
        "title": title,
        "open": open,
        "charts": charts or [],
        "tables": tables or [],
        "text": text,
        "subsections": subsections or [],
    }


def make_section(
    id: str,
    title: str,
    *,
    description: str = "",
    stats: list[dict] | None = None,
    charts: list[dict] | None = None,
    tables: list[dict] | None = None,
    panels: list[dict] | None = None,
    subsections: list[dict] | None = None,
    warnings: list[dict] | None = None,
    headline: dict | None = None,
    empty_message: str = "",
) -> dict:
    """Build a section descriptor dict suitable for the schema v2 payload."""
    return {
        "id": id,
        "title": title,
        "description": description,
        "stats": stats or [],
        "charts": charts or [],
        "tables": tables or [],
        "panels": panels or [],
        "subsections": subsections or [],
        "warnings": warnings or [],
        "headline": headline,
        "empty_message": empty_message,
    }
