"""Truncation robustness report section."""

from __future__ import annotations

import logging

from ._base import make_section, make_table, table_exists

_log = logging.getLogger(__name__)

_INTERPRETATION_GUIDE = (
    "<strong>δ &gt; 0</strong>: binning more robust to temporal truncation "
    "(temporal structure is being captured). "
    "<strong>δ &lt; 0</strong>: binning more sensitive to temporal position "
    "(segmentation instability or noise)."
)


def _delta_text(value: float | None) -> str:
    if value is None:
        return "—"
    if value > 0:
        return f"+{value:.4f} ↑"
    if value < 0:
        return f"{value:.4f} ↓"
    return f"{value:.4f}"


def section_truncation(con) -> dict:
    """Summarize flat vs. binned robustness under temporal truncation."""
    if not table_exists(con, "truncation_robustness_rows"):
        return make_section(
            "truncation",
            "Truncation Robustness",
            empty_message="No truncation data yet. Run the truncation phase to populate this section.",
        )

    try:
        df = con.execute(
            "SELECT backbone, bin_mode, std_thresh, flat_mean_sim, binned_mean_sim, "
            "truncation_robustness_delta "
            "FROM truncation_robustness_rows "
            "ORDER BY backbone, bin_mode, std_thresh"
        ).df()
    except Exception:
        _log.exception("Failed to load truncation robustness rows")
        return make_section(
            "truncation",
            "Truncation Robustness",
            empty_message="Could not load truncation robustness data.",
        )

    if df.empty:
        return make_section(
            "truncation",
            "Truncation Robustness",
            empty_message="No truncation data yet. Run the truncation phase to populate this section.",
        )

    subsections: list[dict] = []
    for backbone, group in df.groupby("backbone", sort=False):
        rows = [
            {
                "bin_mode": row["bin_mode"],
                "std_thresh": row["std_thresh"],
                "flat_mean_sim": row["flat_mean_sim"],
                "binned_mean_sim": row["binned_mean_sim"],
                "delta (δ)": _delta_text(row["truncation_robustness_delta"]),
            }
            for row in group.to_dict(orient="records")
        ]
        subsections.append(
            {
                "id": f"truncation-{str(backbone).lower().replace('/', '-').replace(' ', '-')}",
                "title": str(backbone),
                "description": _INTERPRETATION_GUIDE,
                "stats": [],
                "charts": [],
                "tables": [
                    make_table(
                        rows,
                        id=f"truncation-{str(backbone).lower().replace('/', '-').replace(' ', '-')}-table",
                    )
                ],
                "panels": [],
                "subsections": [],
                "warnings": [],
            }
        )

    mean_delta = float(df["truncation_robustness_delta"].mean()) if len(df) else 0.0
    headline = {
        "icon": "✂️",
        "color": "#4ade80" if mean_delta > 0 else "#f87171" if mean_delta < 0 else "#7ec8e3",
        "text": (
            f"Mean truncation delta across all configs: {mean_delta:+.4f}. "
            "Positive deltas favor binning; negative deltas favor flat pooling."
        ),
    }

    return make_section(
        "truncation",
        "Truncation Robustness",
        description=(
            "Compares flat and binned representatives under front/back temporal truncation. "
            "Higher binned similarity relative to flat indicates greater robustness to missing "
            "prefix/suffix patches."
        ),
        stats=[
            {"label": "rows", "value": len(df)},
            {"label": "backbones", "value": int(df["backbone"].nunique())},
            {"label": "mean δ", "value": f"{mean_delta:+.4f}"},
        ],
        subsections=subsections,
        headline=headline,
    )
