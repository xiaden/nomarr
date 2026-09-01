"""Top-line summary section: exact best-binned winner vs medoid baseline per backbone.

Phase 3 (Plan D) replaced the coarse disc-genre dominance-rate / tuning-sensitivity
composites (which collapsed configurations via ``first()`` / ``median`` / ``max`` and
hid winner identity) with an exact per-backbone winner row: the single binned
configuration with the highest disc_genre and its delta against the explicit
``global_pool:{backbone}:medoid`` baseline.  Only exact-row diagnostics are
retained; a previously contemplated corpus-mismatch warning was dropped because
``n_songs`` is not present in the decoded ``analyze_metrics`` pivot, so it could
never fire in the real report path.
"""

from __future__ import annotations

import pandas as pd

from ._base import binned_identity_label, flat_medoid_value, fmt, make_section, make_table

_DISC_COL = "disc_genre"


def _best_binned_row(binned_df: pd.DataFrame, backbone: str):
    """The exact binned row (per backbone) with the highest disc_genre, or None.

    References a single real row — the winning configuration — so its identity is
    never collapsed away.  None when there is no binned disc_genre data.
    """
    bb = binned_df[binned_df["backbone"] == backbone] if "backbone" in binned_df.columns else pd.DataFrame()
    if bb.empty or _DISC_COL not in bb.columns:
        return None
    valid = bb[bb[_DISC_COL].notna()]
    if valid.empty:
        return None
    return valid.loc[valid[_DISC_COL].idxmax()]


def section_summary(df: pd.DataFrame) -> dict:
    """Per-backbone exact best-binned winner and delta vs the explicit medoid baseline."""
    flat_df = df[df["strategy_type"] == "global_pool"]
    binned_df = df[df["strategy_type"].isin(["ptc", "ctp"])]
    flat_backbones = flat_df["backbone"].dropna().unique().tolist() if "backbone" in flat_df.columns else []
    binned_backbones = binned_df["backbone"].dropna().unique().tolist() if "backbone" in binned_df.columns else []
    all_backbones = sorted(set(flat_backbones) | set(binned_backbones))

    if not all_backbones:
        return make_section(
            "summary",
            "Summary",
            empty_message="No retrieval data yet. Run the eval phase first.",
        )

    rows: list[dict] = []
    section_warnings: list[dict] = []
    deltas: list[float] = []

    for backbone in all_backbones:
        medoid_val = flat_medoid_value(flat_df, backbone, _DISC_COL)
        best = _best_binned_row(binned_df, backbone)
        if best is not None:
            best_config = binned_identity_label(best)
            best_val = float(best[_DISC_COL])
        else:
            best_config = "—"
            best_val = None

        delta = (best_val - medoid_val) if (best_val is not None and medoid_val is not None) else None
        if delta is not None:
            deltas.append(delta)

        rows.append(
            {
                "backbone": backbone,
                "flat_medoid_disc_genre": fmt(medoid_val),
                "best_binned_config": best_config,
                "best_binned_disc_genre": fmt(best_val),
                "delta_vs_medoid": fmt(delta),
            }
        )

    positive = [d for d in deltas if d > 0]
    negative = [d for d in deltas if d < 0]
    if positive and not negative:
        headline = {
            "color": "#22c55e",
            "icon": "✓",
            "text": (
                "Every backbone's best binned configuration beats the explicit medoid flat baseline on disc_genre."
            ),
        }
    elif positive:
        headline = {
            "color": "#f59e0b",
            "icon": "⚠",
            "text": (
                "At least one backbone's best binned configuration beats the explicit "
                "medoid flat baseline on disc_genre."
            ),
        }
    else:
        headline = {
            "color": "#f87171",
            "icon": "✕",
            "text": ("No backbone's best binned configuration beats the explicit medoid flat baseline on disc_genre."),
        }

    return make_section(
        "summary",
        "Summary",
        description=(
            "Per-backbone, the single best binned configuration (full identity: pathway, "
            "head, bin mode, threshold, rep_a, rep_b, aggregate) and its disc_genre delta "
            "against the explicit medoid flat baseline (global_pool:{backbone}:medoid). "
            "delta_vs_medoid = best_binned_disc_genre - flat_medoid_disc_genre. Temporal "
            "weighting (the weighted directional reductions target-wtd / bidir-wtd / "
            "norm-pair-wtd) is distinct from representation choice (rep_a / rep_b)."
        ),
        stats=[],
        charts=[],
        tables=[make_table(rows, id="backbone_summary", title="Backbone summary")],
        panels=[],
        subsections=[],
        warnings=section_warnings,
        headline=headline,
        empty_message="",
    )
