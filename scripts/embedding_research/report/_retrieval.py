"""Retrieval metrics sections and data loaders."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ._base import (
    _FONT_COLOR,
    _GRID_COLOR,
    _H_MED,
    _H_SMALL,
    ANALYZE_METRICS_COLUMNS,
    STRATEGY_TYPES,
    _decode_strategy_key,
    _pareto_front_indices,
    apply_dark_theme,
    binned_config_label,
    empty_df,
    fmt,
    make_chart,
    make_panel,
    make_section,
    make_table,
    table_exists,
)

_TOP_N = 15  # rows per backbone scatter/bar
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


# ---------------------------------------------------------------------------
# Data loaders (public)
# ---------------------------------------------------------------------------


def query_analyze_metrics(con) -> pd.DataFrame:
    """Load unified analyze metrics from DuckDB. Returns empty DataFrame on error."""
    if not table_exists(con, "analyze_metrics"):
        return empty_df(ANALYZE_METRICS_COLUMNS)
    try:
        df = con.execute(
            """
            PIVOT analyze_metrics
            ON metric
            USING FIRST(value)
            GROUP BY strategy_key, strategy_type, sim_metric, k
            ORDER BY disc_general DESC NULLS LAST
            """
        ).df()
        if "strategy_type" in df.columns:
            df = df[df["strategy_type"].isin(STRATEGY_TYPES)].copy()
        return _decode_strategy_key(df)
    except Exception:
        return empty_df(ANALYZE_METRICS_COLUMNS)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def section_unified_table(df: pd.DataFrame) -> dict:
    """Unified ranking table: top configs across all backbones, flat + binned."""
    flat_df = df[df["strategy_type"] == "global_pool"]
    binned_df = df[df["strategy_type"].isin(["ptc", "ctp"])]
    if flat_df.empty and binned_df.empty:
        return make_section(
            "unified-ranking",
            "Unified Ranking",
            empty_message="No retrieval results yet. Run the eval phase first.",
        )

    flat_columns = [
        "backbone",
        "strategy",
        "sim_metric",
        "k",
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
        "precision_k_head_mean",
    ]
    binned_columns = [
        "backbone",
        "bin_mode",
        "std_thresh",
        "rep_a",
        "rep_b",
        "sim_metric",
        "agg_method",
        "k",
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
        "precision_k_head_mean",
        "flat_binned_spearman",
        "flat_binned_beneficial_reorder_rate",
    ]

    def metric_or_zero(value) -> float:
        return float(value) if pd.notna(value) else 0.0

    combined_parts: list[pd.DataFrame] = []
    flat_ranked = pd.DataFrame()
    if not flat_df.empty:
        flat_ranked = flat_df.reindex(columns=flat_columns, fill_value=None).copy()
        flat_ranked["type"] = "flat"
        flat_ranked["config"] = "flat"
        combined_parts.append(flat_ranked)

    binned_ranked = pd.DataFrame()
    if not binned_df.empty:
        binned_ranked = binned_df.reindex(columns=binned_columns, fill_value=None).copy()
        binned_ranked["type"] = "binned"
        binned_ranked["config"] = binned_ranked.apply(
            lambda r: binned_config_label(
                bin_mode=r.get("bin_mode"),
                std_thresh=r.get("std_thresh"),
                rep_a=r.get("rep_a"),
                rep_b=r.get("rep_b"),
                agg_method=r.get("agg_method"),
            ),
            axis=1,
        )
        combined_parts.append(binned_ranked)

    if not combined_parts:
        return make_section(
            "unified-ranking",
            "Unified Ranking",
            empty_message="No results could be ranked.",
        )

    combined = pd.concat(combined_parts, ignore_index=True, sort=False)
    combined = combined.sort_values(
        ["disc_genre", "disc_artist"],
        ascending=False,
        na_position="last",
    )
    top20 = combined.head(20)

    chart_df_rows: list[dict] = []
    backbone_values = sorted({str(backbone) for backbone in combined["backbone"].dropna().tolist()})
    for backbone in backbone_values:
        if not flat_ranked.empty:
            best_flat = flat_ranked[flat_ranked["backbone"] == backbone].sort_values(
                "disc_genre",
                ascending=False,
                na_position="last",
            )
            if not best_flat.empty:
                best_flat_row = best_flat.iloc[0]
                chart_df_rows.append(
                    {
                        "label": f"{backbone}\nflat",
                        "disc_genre": metric_or_zero(best_flat_row.get("disc_genre")),
                        "type": "flat",
                    }
                )
        if not binned_ranked.empty:
            best_binned = binned_ranked[binned_ranked["backbone"] == backbone].sort_values(
                "disc_genre",
                ascending=False,
                na_position="last",
            )
            if not best_binned.empty:
                best_binned_row = best_binned.iloc[0]
                chart_df_rows.append(
                    {
                        "label": f"{backbone}\nbinned",
                        "disc_genre": metric_or_zero(best_binned_row.get("disc_genre")),
                        "type": "binned",
                    }
                )

    charts = []
    if chart_df_rows:
        labels = [r["label"] for r in chart_df_rows]
        disc_vals = [r["disc_genre"] for r in chart_df_rows]
        colors = ["#7aa2f7" if r["type"] == "flat" else "#f9a825" for r in chart_df_rows]
        fig = go.Figure([go.Bar(x=labels, y=disc_vals, marker_color=colors)])
        apply_dark_theme(fig, grid=False)
        fig.update_layout(
            title={"text": "Best disc_genre — flat vs binned per backbone", "font": {"color": _FONT_COLOR}},
            height=_H_MED,
            yaxis={"title": "disc_genre", "showgrid": True, "gridcolor": _GRID_COLOR, "gridwidth": 0.5},
        )
        charts.append(
            make_chart(
                fig,
                id="unified_disc_bar",
                title="Best disc_genre — flat vs binned",
            )
        )

    pooling_rows: list[dict] = []
    if not binned_ranked.empty:
        for (rep_a, rep_b, agg_method), grp in binned_ranked.groupby(
            ["rep_a", "rep_b", "agg_method"],
            dropna=False,
        ):
            pooling_rows.append(
                {
                    "rep_a": fmt(rep_a),
                    "rep_b": fmt(rep_b),
                    "agg_method": fmt(agg_method),
                    "n configs": str(len(grp)),
                    "best disc_genre": fmt(grp["disc_genre"].max()),
                }
            )

    panels = []
    if pooling_rows:
        panels.append(
            make_panel(
                id="pooling_variants",
                title="Visible binned pooling variants",
                tables=[make_table(pooling_rows, id="pooling_table", title="Pooling variants")],
            )
        )

    table_columns = [
        "type",
        "backbone",
        "config",
        "disc_general",
        "disc_artist",
        "disc_genre",
        "disc_head",
        "disc_score",
        "map_k",
        "mrr",
        "ndcg_k",
        "recall_k",
        "recall_k_genre",
        "precision_k_genre",
        "precision_k_head_mean",
        "flat_binned_spearman",
        "flat_binned_beneficial_reorder_rate",
    ]
    tbl_rows = [{column: row.get(column) for column in table_columns} for _, row in top20.iterrows()]

    return make_section(
        "unified-ranking",
        "Unified Ranking",
        description=(
            "Flat and binned configurations ranked together by `disc_genre` across all backbones. "
            "Available columns include `precision_k_genre`, `precision_k_head_mean`, "
            "`flat_binned_spearman`, and `flat_binned_beneficial_reorder_rate`. "
            "Blue bars = flat, amber bars = binned."
        ),
        charts=charts,
        tables=[
            make_table(
                tbl_rows,
                id="top20",
                collapsible=True,
                summary_text="Top-20 table (disc_genre)",
            )
        ],
        panels=panels,
    )


def section_per_backbone(df: pd.DataFrame) -> dict:
    """Per-backbone sections: scatter (disc vs MAP@k), delta bar chart, top-N table."""
    flat_df = df[df["strategy_type"] == "global_pool"]
    binned_df = df[df["strategy_type"].isin(["ptc", "ctp"])]
    all_backbones = sorted(
        set(flat_df["backbone"].unique() if not flat_df.empty else [])
        | set(binned_df["backbone"].unique() if not binned_df.empty else [])
    )
    if not all_backbones:
        return make_section(
            "per-backbone",
            "Per-Backbone Analysis",
            empty_message="No backbone data yet.",
        )

    disc_col_f = (
        "disc_general"
        if ("disc_general" in flat_df.columns and flat_df["disc_general"].notna().any())
        else "disc_score"
    )
    disc_col_b = (
        "disc_general"
        if ("disc_general" in binned_df.columns and binned_df["disc_general"].notna().any())
        else "disc_score"
    )

    subsections: list[dict] = []

    for backbone in all_backbones:
        flat_bb = flat_df[flat_df["backbone"] == backbone] if not flat_df.empty else pd.DataFrame()
        binned_bb = binned_df[binned_df["backbone"] == backbone] if not binned_df.empty else pd.DataFrame()

        # ── scatter: disc vs MAP@k ─────────────────────────────────────────
        scatter_rows_f: list[dict] = []
        if not flat_bb.empty and "map_k" in flat_bb.columns:
            for _, row in flat_bb.iterrows():
                scatter_rows_f.append(
                    {"x": row.get(disc_col_f, 0), "y": row.get("map_k", 0), "label": "flat", "type": "flat"}
                )

        scatter_rows_b: list[dict] = []
        if not binned_bb.empty and "map_k" in binned_bb.columns:
            for _, row in binned_bb.head(_TOP_N).iterrows():
                cfg = binned_config_label(
                    bin_mode=row.get("bin_mode"),
                    std_thresh=row.get("std_thresh"),
                    rep_a=row.get("rep_a"),
                    rep_b=row.get("rep_b"),
                    agg_method=row.get("agg_method"),
                )
                scatter_rows_b.append(
                    {"x": row.get(disc_col_b, 0), "y": row.get("map_k", 0), "label": cfg, "type": "binned"}
                )

        charts: list[dict] = []
        if scatter_rows_f or scatter_rows_b:
            fig_sc = go.Figure()
            if scatter_rows_f:
                xs = [r["x"] for r in scatter_rows_f]
                ys = [r["y"] for r in scatter_rows_f]
                pareto = _pareto_front_indices(xs, ys)
                fig_sc.add_trace(
                    go.Scatter(
                        x=xs,
                        y=ys,
                        mode="markers",
                        name="flat",
                        marker={
                            "color": "#7aa2f7",
                            "size": 7,
                            "symbol": ["star" if i in pareto else "circle" for i in range(len(xs))],
                        },
                    )
                )
            if scatter_rows_b:
                xs_b = [r["x"] for r in scatter_rows_b]
                ys_b = [r["y"] for r in scatter_rows_b]
                labels_b = [r["label"] for r in scatter_rows_b]
                color_b = [_PALETTE[i % len(_PALETTE)] for i in range(len(xs_b))]
                pareto_b = _pareto_front_indices(xs_b, ys_b)
                fig_sc.add_trace(
                    go.Scatter(
                        x=xs_b,
                        y=ys_b,
                        mode="markers",
                        name="binned",
                        text=labels_b,
                        hovertemplate="%{text}<br>disc=%{x:.4f}<br>map_k=%{y:.4f}",
                        marker={
                            "color": color_b,
                            "size": 7,
                            "symbol": ["star" if i in pareto_b else "circle" for i in range(len(xs_b))],
                        },
                    )
                )
            apply_dark_theme(fig_sc)
            fig_sc.update_layout(
                title={"text": f"{backbone} — {disc_col_f} vs MAP@k", "font": {"color": _FONT_COLOR}},
                height=_H_MED,
                xaxis={"title": disc_col_f, "showgrid": True, "gridcolor": _GRID_COLOR, "gridwidth": 0.5},
                yaxis={"title": "MAP@k", "showgrid": True, "gridcolor": _GRID_COLOR, "gridwidth": 0.5},
            )
            charts.append(make_chart(fig_sc, id=f"scatter_{backbone}", title=f"{backbone} — {disc_col_f} vs MAP@k"))

        # ── delta bar: binned - flat baseline ──────────────────────────────────
        if not flat_bb.empty and not binned_bb.empty:
            flat_ref = float(flat_bb[disc_col_f].median())
            bar_rows: list[dict] = []
            for (cfg_key,), grp in binned_bb.groupby(
                [
                    pd.Series(
                        binned_bb.apply(
                            lambda r: binned_config_label(
                                bin_mode=r.get("bin_mode"),
                                std_thresh=r.get("std_thresh"),
                                rep_a=r.get("rep_a"),
                                rep_b=r.get("rep_b"),
                                agg_method=r.get("agg_method"),
                            ),
                            axis=1,
                        ).rename("cfg")
                    )
                ]
            ):
                best_disc = float(grp[disc_col_b].max())
                bar_rows.append({"config": cfg_key, "delta": best_disc - flat_ref})

            bar_rows.sort(key=lambda r: r["delta"], reverse=True)
            bar_rows = bar_rows[:_TOP_N]
            if bar_rows:
                configs = [r["config"] for r in bar_rows][::-1]
                deltas = [r["delta"] for r in bar_rows][::-1]
                bar_colors = ["#4ade80" if d > 0 else "#f87171" for d in deltas]
                fig_bar = go.Figure([go.Bar(x=deltas, y=configs, orientation="h", marker_color=bar_colors)])
                apply_dark_theme(fig_bar, grid=False)
                fig_bar.add_vline(x=0, line_color="#555", line_width=0.8)
                fig_bar.update_layout(
                    title={"text": f"{backbone} — Δ{disc_col_f} vs flat baseline", "font": {"color": _FONT_COLOR}},
                    height=max(_H_SMALL, len(configs) * 22 + 80),
                    xaxis={"title": f"Δ{disc_col_f}", "showgrid": True, "gridcolor": _GRID_COLOR, "gridwidth": 0.5},
                )
                charts.append(make_chart(fig_bar, id=f"delta_bar_{backbone}", title=f"{backbone} — Δ{disc_col_f}"))

        # ── top-N table ────────────────────────────────────────────────────
        tables: list[dict] = []
        top_rows: list[dict] = []
        metric_cols = [disc_col_f, "map_k", "mrr", "ndcg_k", "recall_k"]

        if not flat_bb.empty:
            for _, row in flat_bb.head(5).iterrows():
                r: dict = {"type": "flat", "backbone": backbone, "config": "flat"}
                for mc in metric_cols:
                    r[mc] = fmt(row.get(mc))
                top_rows.append(r)

        if not binned_bb.empty:
            binned_bb2 = binned_bb.copy()
            binned_bb2["_disc_sort"] = binned_bb2[disc_col_b]
            for _, row in binned_bb2.nlargest(_TOP_N, "_disc_sort").iterrows():
                cfg = binned_config_label(
                    bin_mode=row.get("bin_mode"),
                    std_thresh=row.get("std_thresh"),
                    rep_a=row.get("rep_a"),
                    rep_b=row.get("rep_b"),
                    agg_method=row.get("agg_method"),
                )
                r = {"type": "binned", "backbone": backbone, "config": cfg}
                for mc in metric_cols:
                    r[mc] = fmt(row.get(mc))
                top_rows.append(r)

        if top_rows:
            tables.append(
                make_table(
                    top_rows,
                    id=f"top_configs_{backbone}",
                    collapsible=True,
                    summary_text=f"Top configurations — {backbone}",
                )
            )

        subsections.append(
            {
                "id": f"backbone-{backbone}",
                "title": backbone,
                "description": "",
                "stats": [],
                "charts": charts,
                "tables": tables,
                "panels": [],
                "subsections": [],
                "warnings": [],
                "headline": None,
                "empty_message": "",
            }
        )

    return make_section(
        "per-backbone",
        "Per-Backbone Analysis",
        description=(
            "Scatter: each point is one configuration — stars mark Pareto-optimal points. "
            "Δ bar: binned score minus flat median baseline (green = gain, red = loss)."
        ),
        subsections=subsections,
    )
