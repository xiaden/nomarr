"""Head analysis sections: correlation heatmaps and CTP/PTC value."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as _np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ._base import (
    _FONT_COLOR,
    _GRID_COLOR,
    _H_MED,
    _H_SMALL,
    apply_dark_theme,
    binned_config_label,
    make_chart,
    make_panel,
    make_section,
    make_table,
    table_exists,
)

if TYPE_CHECKING:
    import pandas as pd

_PALETTE = [
    "#7aa2f7",
    "#9ece6a",
    "#f7768e",
    "#e0af68",
    "#bb9af7",
    "#7dcfff",
    "#ff9e64",
    "#73daca",
    "#c0caf5",
    "#b4f9f8",
    "#cba6f7",
    "#fab387",
    "#a6e3a1",
    "#f38ba8",
    "#89b4fa",
]

try:
    from scripts.embedding_research.helpers.binning import BIN_MODES, DIST_THRESHOLDS

    _THRESH_SQL = ", ".join(str(t) for t in DIST_THRESHOLDS) if DIST_THRESHOLDS else "1.0"
    _BIN_MODE_SQL = ", ".join(f"'{m}'" for m in BIN_MODES) if BIN_MODES else "'temporal_global'"
except ImportError:
    _THRESH_SQL = "1.0"
    _BIN_MODE_SQL = "'temporal_global'"


def section_head_sim_corr(con) -> dict:
    """Spearman rank correlation between head attention and embedding similarity."""
    if not table_exists(con, "head_sim_corr_rows"):
        return make_section(
            "head-sim-corr",
            "Head \u00d7 Embedding Similarity Correlation",
            empty_message=("Run the classify and analyze phases to populate this section."),
        )

    try:
        df = con.execute(
            "SELECT backbone, head, bin_mode, std_thresh, rep_a, rep_b, agg_method, "
            "ROUND(corr, 4) AS spearman_r "
            "FROM head_sim_corr_rows ORDER BY backbone, head, bin_mode, std_thresh"
        ).df()
    except Exception as exc:
        return make_section(
            "head-sim-corr",
            "Head \u00d7 Embedding Similarity Correlation",
            empty_message=f"Query error: {exc}",
        )

    if df.empty:
        return make_section(
            "head-sim-corr",
            "Head \u00d7 Embedding Similarity Correlation",
            empty_message="No correlation data yet.",
        )

    df["strategy"] = df.apply(
        lambda r: binned_config_label(
            bin_mode=r["bin_mode"],
            std_thresh=r["std_thresh"],
            rep_a=r["rep_a"],
            rep_b=r["rep_b"],
            agg_method=r["agg_method"],
        ),
        axis=1,
    )

    all_backbones = sorted(df["backbone"].unique())
    subsections: list[dict] = []

    for backbone in all_backbones:
        bb_df = df[df["backbone"] == backbone]
        all_heads = sorted(bb_df["head"].unique())
        all_strats = sorted(bb_df["strategy"].unique())

        pivot = bb_df.pivot_table(index="head", columns="strategy", values="spearman_r", aggfunc="mean").reindex(
            index=all_heads, columns=all_strats
        )

        data = pivot.values.astype(float)
        text = [[f"{v:.3f}" if not _np.isnan(v) else "" for v in row] for row in data]
        height = max(_H_SMALL, len(all_heads) * 40 + 100)

        max_abs = float(_np.nanmax(_np.abs(data))) if not _np.all(_np.isnan(data)) else 0.5
        max_abs = max(max_abs, 0.01)

        fig = go.Figure(
            go.Heatmap(
                z=data.tolist(),
                x=all_strats,
                y=all_heads,
                text=text,
                texttemplate="%{text}",
                textfont={"size": 9},
                colorscale="RdYlGn",
                zmid=0,
                zmin=-max_abs,
                zmax=max_abs,
                colorbar={"title": "Spearman r", "tickfont": {"color": "#aaa", "size": 9}},
            )
        )
        apply_dark_theme(fig, grid=False)
        fig.update_layout(
            title={"text": f"{backbone} \u2014 head\u00d7strategy Spearman r", "font": {"color": _FONT_COLOR}},
            height=height,
            xaxis={"tickfont": {"color": _FONT_COLOR, "size": 9}},
            yaxis={"tickfont": {"color": _FONT_COLOR, "size": 9}},
        )

        # Best config per head table
        best_rows = (
            bb_df.sort_values("spearman_r", ascending=False)
            .groupby("head", as_index=False)
            .first()[["head", "strategy", "spearman_r"]]
            .rename(columns={"strategy": "best strategy", "spearman_r": "best r"})
            .to_dict("records")
        )

        subsections.append(
            {
                "id": f"corr-{backbone}",
                "title": str(backbone),
                "description": "",
                "stats": [],
                "charts": [make_chart(fig, id=f"corr_{backbone}", title=f"{backbone} head\u00d7strategy Spearman r")],
                "tables": [
                    make_table(
                        best_rows, id=f"corr_best_{backbone}", collapsible=True, summary_text="Best strategy per head"
                    )
                ],
                "panels": [],
                "subsections": [],
                "warnings": [],
                "headline": None,
                "empty_message": "",
            }
        )

    return make_section(
        "head-sim-corr",
        "Head \u00d7 Embedding Similarity Correlation",
        description=(
            "Spearman rank correlation between head attention weights and embedding cosine similarity "
            "per song pair, aggregated per (backbone, head, strategy). "
            "Positive r = head attends to similar embeddings; negative r = head ignores similarity."
        ),
        subsections=subsections,
    )


def section_head_value(con, flat_df: pd.DataFrame | None = None) -> dict:
    """CTP vs PTC: does classifying before pooling add value over geometry alone?"""
    has_ptc_ctp = table_exists(con, "ptc_ctp_rows")

    if not has_ptc_ctp:
        return make_section(
            "head-value",
            "Head Value",
            empty_message="Run the classify and analyze phases to populate this section.",
        )

    try:
        df = con.execute(
            "SELECT backbone, head, strategy, "
            "ROUND(ptc_disc, 4) AS ptc_disc, ROUND(ctp_disc, 4) AS ctp_disc, "
            "ROUND(delta_disc, 4) AS delta_disc "
            "FROM ptc_ctp_rows ORDER BY backbone, head, strategy"
        ).df()
    except Exception as exc:
        return make_section("head-value", "Head Value", empty_message=f"Query error: {exc}")

    if df.empty:
        return make_section("head-value", "Head Value", empty_message="No head comparison data yet.")

    agg = (
        df.groupby(["backbone", "head"])
        .agg(
            median_delta=("delta_disc", "median"),
            dominance_rate=("delta_disc", lambda x: (x > 0).mean()),
        )
        .reset_index()
    )

    all_backbones = sorted(agg["backbone"].unique())
    all_heads = sorted(agg["head"].unique())

    pivot_delta = agg.pivot(index="head", columns="backbone", values="median_delta").reindex(
        index=all_heads, columns=all_backbones
    )
    pivot_dom = agg.pivot(index="head", columns="backbone", values="dominance_rate").reindex(
        index=all_heads, columns=all_backbones
    )

    data_delta = pivot_delta.values.astype(float)
    data_dom = pivot_dom.values.astype(float)
    text_delta = [[f"{v:+.3f}" if not _np.isnan(v) else "" for v in row] for row in data_delta]
    text_dom = [[f"{v * 100:.0f}%" if not _np.isnan(v) else "" for v in row] for row in data_dom]

    height = max(280, len(all_heads) * 44 + 100)
    max_abs = float(_np.nanmax(_np.abs(data_delta))) if not _np.all(_np.isnan(data_delta)) else 0.05
    max_abs = max(max_abs, 0.01)

    fig_delta = go.Figure(
        go.Heatmap(
            z=data_delta.tolist(),
            x=all_backbones,
            y=all_heads,
            text=text_delta,
            texttemplate="%{text}",
            textfont={"size": 10},
            colorscale="RdYlGn",
            zmid=0,
            zmin=-max_abs,
            zmax=max_abs,
            colorbar={"title": "\u0394disc", "tickfont": {"color": "#aaa", "size": 9}},
        )
    )
    apply_dark_theme(fig_delta, grid=False)
    fig_delta.update_layout(
        title={"text": "Median \u0394disc: CTP \u2212 PTC", "font": {"color": _FONT_COLOR}},
        height=height,
        xaxis={"tickfont": {"color": _FONT_COLOR, "size": 10}},
        yaxis={"tickfont": {"color": _FONT_COLOR, "size": 10}},
    )

    fig_dom = go.Figure(
        go.Heatmap(
            z=data_dom.tolist(),
            x=all_backbones,
            y=all_heads,
            text=text_dom,
            texttemplate="%{text}",
            textfont={"size": 10},
            colorscale="RdYlGn",
            zmin=0,
            zmax=1,
            colorbar={"title": "dom%", "tickfont": {"color": "#aaa", "size": 9}},
        )
    )
    apply_dark_theme(fig_dom, grid=False)
    fig_dom.update_layout(
        title={"text": "Dominance Rate: % strategies where CTP > PTC", "font": {"color": _FONT_COLOR}},
        height=height,
        xaxis={"tickfont": {"color": _FONT_COLOR, "size": 10}},
        yaxis={"tickfont": {"color": _FONT_COLOR, "size": 10}},
    )

    # Per-backbone breakdown panels
    flat_base: dict[str, float | None] = {}
    if flat_df is not None and not flat_df.empty:
        disc_col_f = (
            "disc_general"
            if ("disc_general" in flat_df.columns and flat_df["disc_general"].notna().any())
            else "disc_score"
        )
        for bb, bb_sub in flat_df.groupby("backbone"):
            v = bb_sub[disc_col_f].dropna()
            flat_base[str(bb)] = float(v.median()) if not v.empty else None

    bb_panels: list[dict] = []
    for backbone, bb_df in df.groupby("backbone", sort=True):
        flat_ref = flat_base.get(str(backbone))
        by_head = (
            bb_df.groupby("head")
            .agg(
                median_ptc=("ptc_disc", "median"),
                median_ctp=("ctp_disc", "median"),
                median_delta=("delta_disc", "median"),
            )
            .reset_index()
        )
        h_labels = by_head["head"].tolist()[::-1]
        ptc_vals = by_head["median_ptc"].tolist()[::-1]
        ctp_vals = by_head["median_ctp"].tolist()[::-1]
        delta_vals = by_head["median_delta"].tolist()[::-1]
        delta_colors = ["#4ade80" if v > 0 else "#f87171" for v in delta_vals]
        bheight = max(_H_MED, len(h_labels) * 32 + 100)

        fig_bb = make_subplots(rows=1, cols=2, subplot_titles=["Median disc by head", "\u0394disc (CTP \u2212 PTC)"])
        fig_bb.add_trace(
            go.Bar(x=ptc_vals, y=h_labels, orientation="h", name="PTC", marker_color="#7ec8e3"),
            row=1,
            col=1,
        )
        fig_bb.add_trace(
            go.Bar(x=ctp_vals, y=h_labels, orientation="h", name="CTP", marker_color="#a78bfa"),
            row=1,
            col=1,
        )
        if flat_ref is not None:
            fig_bb.add_vline(
                x=flat_ref,
                line_dash="dot",
                line_color="#f59e0b",
                line_width=1.2,
                annotation_text=f"flat {flat_ref:.4f}",
                annotation_font_color=_FONT_COLOR,
                row=1,
                col=1,
            )
        fig_bb.add_trace(
            go.Bar(
                x=delta_vals,
                y=h_labels,
                orientation="h",
                name="\u0394 disc",
                marker_color=delta_colors,
                showlegend=False,
            ),
            row=1,
            col=2,
        )
        fig_bb.add_vline(x=0, line_color="#555", line_width=0.8, row=1, col=2)
        apply_dark_theme(fig_bb, grid=False)
        fig_bb.update_xaxes(showgrid=True, gridcolor=_GRID_COLOR, gridwidth=0.5)
        fig_bb.update_layout(
            title={"text": str(backbone), "font": {"color": _FONT_COLOR}},
            height=bheight,
            barmode="group",
        )
        bb_panels.append(
            make_panel(
                id=f"hv_bb_{backbone}",
                title=str(backbone),
                charts=[make_chart(fig_bb, id=f"hv_bb_chart_{backbone}", title=str(backbone))],
            )
        )

    panels: list[dict] = []
    if bb_panels:
        panels.append(
            make_panel(
                id="head_value_per_backbone",
                title="Per-backbone breakdown",
                subsections=[
                    {
                        "id": p["id"],
                        "title": p["title"],
                        "description": "",
                        "stats": [],
                        "charts": p["charts"],
                        "tables": [],
                        "panels": [],
                        "subsections": [],
                        "warnings": [],
                        "headline": None,
                        "empty_message": "",
                    }
                    for p in bb_panels
                ],
            )
        )
    return make_section(
        "head-value",
        "Head Value",
        description=(
            "\u0394disc = CTP disc \u2212 PTC disc. Positive = head's own signal structure carves "
            "better-separated pools than embedding geometry alone. "
            "Dominance rate: fraction of strategies where CTP > PTC. "
            "Green = head adds value. Red = geometry alone is sufficient."
        ),
        charts=[
            make_chart(fig_delta, id="head_value_delta", title="Median \u0394disc: CTP \u2212 PTC"),
            make_chart(fig_dom, id="head_value_dom", title="Dominance Rate"),
        ],
        panels=panels,
    )
