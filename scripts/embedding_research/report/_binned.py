"""Binned analysis sections: threshold sweep, diversity, segment counts, mode comparison."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ._base import (
    _FONT_COLOR,
    _H_MED,
    _H_SMALL,
    agg_label,
    apply_dark_theme,
    flat_medoid_value,
    fmt,
    make_chart,
    make_panel,
    make_section,
    make_table,
    rep_label,
    table_exists,
)

# Color palette for (rep_a, rep_b, agg_method) combinations.
_REP_PALETTE = [
    "#7aa2f7",
    "#9ece6a",
    "#f7768e",
    "#e0af68",
    "#bb9af7",
    "#7dcfff",
    "#ff9e64",
    "#73daca",
    "#c0caf5",
    "#fab387",
]
# Dash style per bin_mode — distinguishes global vs perdim on the same chart.
_BM_DASH = {"temporal_global": "solid", "temporal_perdim": "dash"}
_LINE_COLORS_BM = {"temporal_global": "#7ec8e3", "temporal_perdim": "#a78bfa"}

# Groupby key for a full combinatorial: threshold stays as its own bin.
# `head` is included so CTP heads are treated as separate combinatorials.
_COMBO_COLS = ["bin_mode", "std_thresh", "rep_a", "rep_b", "agg_method", "head"]


def _kurt(series: pd.Series) -> float:
    """Fisher excess kurtosis; NaN when fewer than 4 data points."""
    s = series.dropna()
    return float(s.kurt()) if len(s) >= 4 else float("nan")


def section_threshold_sweep(df: pd.DataFrame) -> dict:
    """Mean/variance/kurtosis of disc per combinatorial vs std_thresh, per backbone.

    Each (backbone x bin_mode x rep_a x rep_b x agg_method x std_thresh) is its own
    bin — thresholds are never collapsed.  The statistics describe how the disc metric
    varies over evaluation settings (sim_metric x k) within that bin.

    When ``map_k_general`` data is available, an additional MAP@k sweep chart is
    rendered as the primary chart.  Disc mean/variance/kurtosis charts are grouped
    inside a collapsible "Discrimination Diagnostics" panel.
    """
    binned_df = df[df["strategy_type"] == "ptc"]
    flat_df = df[df["strategy_type"] == "global_pool"]
    if binned_df.empty:
        return make_section(
            "threshold-sweep",
            "Threshold Sweep",
            empty_message="No binned results yet.",
        )

    try:
        from scripts.embedding_research.helpers.binning import DIST_THRESHOLDS

        if DIST_THRESHOLDS:
            binned_df = binned_df[binned_df["std_thresh"].isin(DIST_THRESHOLDS)]
    except ImportError:
        pass

    disc_col = (
        "disc_general"
        if ("disc_general" in binned_df.columns and binned_df["disc_general"].notna().any())
        else "disc_score"
    )

    subsections: list[dict] = []
    for backbone, bb in binned_df.groupby("backbone", sort=True):
        # Flat baseline: the explicit medoid row for this backbone (never mean across flat strategies).
        flat_ref_mean: float | None = None
        if flat_df is not None and not flat_df.empty:
            flat_dc = (
                "disc_general"
                if ("disc_general" in flat_df.columns and flat_df["disc_general"].notna().any())
                else "disc_score"
            )
            flat_ref_mean = flat_medoid_value(flat_df, backbone, flat_dc)

        # Aggregate: each full combinatorial is its own bin.
        has_map_general = "map_k_general" in bb.columns and bb["map_k_general"].notna().any()
        agg_kwargs: dict = {
            "mean_disc": (disc_col, "mean"),
            "var_disc": (disc_col, "var"),
            "std_disc": (disc_col, "std"),
            "kurt_disc": (disc_col, _kurt),
            "n": (disc_col, "count"),
        }
        if has_map_general:
            agg_kwargs["mean_map_general"] = ("map_k_general", "mean")
            agg_kwargs["var_map_general"] = ("map_k_general", "var")
        agg = bb.groupby(_COMBO_COLS, as_index=False, dropna=False).agg(**agg_kwargs).sort_values(_COMBO_COLS)

        # Assign a stable color index per (rep_a, rep_b, agg_method) triple.
        rep_triples = (
            agg[["rep_a", "rep_b", "agg_method"]]
            .drop_duplicates()
            .sort_values(["rep_a", "rep_b", "agg_method"])
            .reset_index(drop=True)
        )
        triple_to_idx: dict = {(row["rep_a"], row["rep_b"], row["agg_method"]): i for i, row in rep_triples.iterrows()}

        fig_map = None
        fig_mean = go.Figure()
        fig_var = go.Figure()
        fig_kurt = go.Figure()

        def _trace_label(bm: str, head, ra: str, rb: str, am: str) -> str:
            """Build a human-readable trace name, including head when present."""
            base = f"{bm}/{rep_label(ra)}x{rep_label(rb)}/{agg_label(am)}"
            if head is not None and not (isinstance(head, float) and pd.isna(head)):
                return f"{head}/{base}"
            return base

        for (bm, ra, rb, am, head), grp in agg.groupby(
            ["bin_mode", "rep_a", "rep_b", "agg_method", "head"], sort=True, dropna=False
        ):
            g = grp.sort_values("std_thresh")
            color = _REP_PALETTE[triple_to_idx.get((ra, rb, am), 0) % len(_REP_PALETTE)]
            dash = _BM_DASH.get(str(bm), "solid")
            name = _trace_label(bm, head, ra, rb, am)

            # Mean with ±std error bars.
            fig_mean.add_trace(
                go.Scatter(
                    x=g["std_thresh"].tolist(),
                    y=g["mean_disc"].tolist(),
                    error_y={
                        "type": "data",
                        "array": g["std_disc"].fillna(0).tolist(),
                        "visible": True,
                        "thickness": 1.0,
                        "width": 4,
                        "color": color,
                    },
                    mode="lines+markers",
                    name=name,
                    line={"color": color, "width": 1.5, "dash": dash},
                    marker={"size": 5},
                )
            )
            fig_var.add_trace(
                go.Scatter(
                    x=g["std_thresh"].tolist(),
                    y=g["var_disc"].tolist(),
                    mode="lines+markers",
                    name=name,
                    line={"color": color, "width": 1.5, "dash": dash},
                    marker={"size": 5},
                )
            )
            fig_kurt.add_trace(
                go.Scatter(
                    x=g["std_thresh"].tolist(),
                    y=g["kurt_disc"].tolist(),
                    mode="lines+markers",
                    name=name,
                    line={"color": color, "width": 1.5, "dash": dash},
                    marker={"size": 5},
                )
            )

        if has_map_general and "mean_map_general" in agg.columns:
            fig_map = go.Figure()
            for (bm, ra, rb, am, head), grp in agg.groupby(
                ["bin_mode", "rep_a", "rep_b", "agg_method", "head"], sort=True, dropna=False
            ):
                g = grp.sort_values("std_thresh")
                color = _REP_PALETTE[triple_to_idx.get((ra, rb, am), 0) % len(_REP_PALETTE)]
                dash = _BM_DASH.get(str(bm), "solid")
                name = _trace_label(bm, head, ra, rb, am)
                fig_map.add_trace(
                    go.Scatter(
                        x=g["std_thresh"].tolist(),
                        y=g["mean_map_general"].tolist(),
                        error_y={
                            "type": "data",
                            "array": (g["var_map_general"].fillna(0) ** 0.5).tolist(),
                            "visible": True,
                            "thickness": 1.0,
                            "width": 4,
                            "color": color,
                        },
                        mode="lines+markers",
                        name=name,
                        line={"color": color, "width": 1.5, "dash": dash},
                        marker={"size": 5},
                    )
                )
            apply_dark_theme(fig_map)
            fig_map.update_layout(
                title={"text": f"{backbone} — mean MAP@k (general) vs threshold", "font": {"color": _FONT_COLOR}},
                height=_H_MED,
                xaxis_title="std_thresh",
                yaxis_title="mean map_k_general",
            )

        # Flat baseline on the mean chart.
        if flat_ref_mean is not None:
            fig_mean.add_hline(
                y=flat_ref_mean,
                line_dash="dash",
                line_color="#f59e0b",
                line_width=1.0,
                annotation_text=f"medoid baseline {flat_ref_mean:.4f}",
                annotation_font_color=_FONT_COLOR,
            )

        for fig, metric_label in [
            (fig_mean, f"mean {disc_col}"),
            (fig_var, f"variance {disc_col}"),
            (fig_kurt, f"kurtosis {disc_col}"),
        ]:
            apply_dark_theme(fig)
            fig.update_layout(
                title={"text": f"{backbone} \u2014 {metric_label} vs threshold", "font": {"color": _FONT_COLOR}},
                height=_H_MED,
                xaxis_title="std_thresh",
                yaxis_title=metric_label,
            )

        # Summary table.
        tbl_rows = [
            {
                "head": str(row.get("head", "")) if not pd.isna(row.get("head")) else "—",
                "bin_mode": str(row["bin_mode"]),
                "std_thresh": fmt(row["std_thresh"]),
                "rep_a": rep_label(row.get("rep_a")),
                "rep_b": rep_label(row.get("rep_b")),
                "agg_method": agg_label(row.get("agg_method")),
                "mean": fmt(row["mean_disc"]),
                "variance": fmt(row["var_disc"]),
                "kurtosis": fmt(row["kurt_disc"]),
                "n": str(int(row["n"])),
            }
            for _, row in agg.iterrows()
        ]

        charts: list[dict] = []
        if fig_map is not None:
            charts.append(make_chart(fig_map, id=f"sweep_map_{backbone}", title=f"{backbone} mean map_k_general"))

        disc_charts = [
            make_chart(fig_mean, id=f"sweep_mean_{backbone}", title=f"{backbone} mean {disc_col}"),
            make_chart(fig_var, id=f"sweep_var_{backbone}", title=f"{backbone} variance {disc_col}"),
            make_chart(fig_kurt, id=f"sweep_kurt_{backbone}", title=f"{backbone} kurtosis {disc_col}"),
        ]
        panels = [
            make_panel(id=f"disc_diag_{backbone}", title="Discrimination Diagnostics", charts=disc_charts),
            make_panel(
                id=f"sweep_tbl_{backbone}",
                title="Raw stats",
                tables=[
                    make_table(tbl_rows, id=f"sweep_tbl_data_{backbone}", title="Mean/var/kurtosis per combinatorial")
                ],
            ),
        ]

        subsections.append(
            {
                "id": f"sweep-{backbone}",
                "title": str(backbone),
                "description": "",
                "stats": [],
                "charts": charts,
                "tables": [],
                "panels": panels,
                "subsections": [],
                "warnings": [],
                "headline": None,
                "empty_message": "",
            }
        )

    return make_section(
        "threshold-sweep",
        "Threshold Sweep",
        description=(
            f"Mean/variance/kurtosis of {disc_col} per combinatorial "
            "(backbone x bin_mode x head x rep_a x rep_b x agg_method x std_thresh). "
            "Each threshold is its own bin — no collapsing across thresholds. "
            "Each CTP head is its own combinatorial — PTC rows show head as '—'. "
            "Statistics are computed over all (sim_metric x k) evaluation variants within each bin. "
            "When MAP@k general data is available, a mean MAP@k sweep chart is shown as the primary chart; "
            "disc charts (mean ±std, variance, kurtosis) are grouped in a 'Discrimination Diagnostics' panel. "
            "Error bars on the mean chart show ±1 std. "
            "Amber dashed line = the explicit flat medoid baseline (global_pool:{backbone}:medoid)."
        ),
        subsections=subsections,
    )


def section_bin_diversity(con) -> dict:
    """Bin diversity: distribution of n_bins per song for PTC and CTP streams."""
    has_ptc = table_exists(con, "binned_song_stats")
    has_ctp = table_exists(con, "binned_classify_ctp")

    if not has_ptc and not has_ctp:
        return make_section(
            "bin-diversity",
            "Bin Diversity",
            empty_message="No segment data available yet. Run the classify phase.",
        )

    try:
        from scripts.embedding_research.helpers.binning import DIST_THRESHOLDS

        thresh_sql = ", ".join(str(t) for t in DIST_THRESHOLDS) if DIST_THRESHOLDS else None
    except ImportError:
        thresh_sql = None

    ptc_df = pd.DataFrame()
    if has_ptc:
        try:
            q = (
                "SELECT backbone, bin_mode, std_thresh, "
                "ROUND(AVG(n_bins), 2) AS mean_bins, "
                "CAST(MEDIAN(n_bins) AS INT) AS median_bins, "
                "MIN(n_bins) AS min_bins, MAX(n_bins) AS max_bins "
                "FROM binned_song_stats "
                + (f"WHERE std_thresh IN ({thresh_sql}) " if thresh_sql else "")
                + "GROUP BY backbone, bin_mode, std_thresh "
                "ORDER BY backbone, bin_mode, std_thresh"
            )
            ptc_df = con.execute(q).df()
        except Exception:
            pass

    ctp_df = pd.DataFrame()
    if has_ctp:
        try:
            q = (
                "SELECT backbone, head, bin_mode, std_thresh, "
                "ROUND(AVG(n_bins), 2) AS mean_bins, "
                "CAST(MEDIAN(n_bins) AS INT) AS median_bins, "
                "MIN(n_bins) AS min_bins, MAX(n_bins) AS max_bins "
                "FROM ( "
                "  SELECT backbone, head, bin_mode, std_thresh, song_id, "
                "         MAX(bin_id) + 1 AS n_bins "
                "  FROM binned_classify_ctp "
                + (f"  WHERE std_thresh IN ({thresh_sql}) " if thresh_sql else "")
                + "  GROUP BY backbone, head, bin_mode, std_thresh, song_id "
                ") sub "
                "GROUP BY backbone, head, bin_mode, std_thresh "
                "ORDER BY backbone, head, bin_mode, std_thresh"
            )
            ctp_df = con.execute(q).df()
        except Exception:
            pass

    if ptc_df.empty and ctp_df.empty:
        return make_section(
            "bin-diversity",
            "Bin Diversity",
            empty_message="No segment data available yet.",
        )

    all_backbones = sorted(
        set(ptc_df["backbone"].unique() if not ptc_df.empty else [])
        | set(ctp_df["backbone"].unique() if not ctp_df.empty else [])
    )

    subsections: list[dict] = []
    for backbone in all_backbones:
        charts: list[dict] = []
        panels: list[dict] = []

        ptc_colors = {"temporal_global": "#7ec8e3", "temporal_perdim": "#a78bfa"}
        ctp_colors = ["#f9a825", "#ef5350", "#66bb6a", "#ab47bc", "#26c6da"]

        if not ptc_df.empty:
            fig_ptc = go.Figure()
            for bm, grp in ptc_df[ptc_df["backbone"] == backbone].groupby("bin_mode"):
                g = grp.sort_values("std_thresh")
                fig_ptc.add_trace(
                    go.Scatter(
                        x=g["std_thresh"].tolist(),
                        y=g["mean_bins"].tolist(),
                        mode="lines+markers",
                        name=f"PTC/{bm}",
                        line={"color": ptc_colors.get(str(bm), "#999"), "width": 1.5},
                        marker={"size": 5},
                    )
                )
            apply_dark_theme(fig_ptc)
            fig_ptc.update_layout(
                title={"text": f"{backbone} \u2014 PTC mean n_bins vs threshold", "font": {"color": _FONT_COLOR}},
                height=_H_SMALL,
                xaxis_title="std_thresh",
                yaxis_title="mean n_bins",
            )
            charts.append(make_chart(fig_ptc, id=f"ptc_bins_{backbone}", title=f"{backbone} PTC bins"))

        if not ctp_df.empty:
            fig_ctp = go.Figure()
            for i, (head, grp) in enumerate(ctp_df[ctp_df["backbone"] == backbone].groupby("head")):
                for bm, bgrp in grp.groupby("bin_mode"):
                    g = bgrp.sort_values("std_thresh")
                    fig_ctp.add_trace(
                        go.Scatter(
                            x=g["std_thresh"].tolist(),
                            y=g["mean_bins"].tolist(),
                            mode="lines+markers",
                            name=f"CTP/{head}/{bm}",
                            line={
                                "color": ctp_colors[i % len(ctp_colors)],
                                "width": 1.2,
                                "dash": "solid" if str(bm) == "temporal_global" else "dash",
                            },
                            marker={"size": 4, "symbol": "square"},
                            opacity=0.85,
                        )
                    )
            apply_dark_theme(fig_ctp)
            fig_ctp.update_layout(
                title={"text": f"{backbone} \u2014 CTP mean n_bins vs threshold", "font": {"color": _FONT_COLOR}},
                height=_H_SMALL,
                xaxis_title="std_thresh",
                yaxis_title="mean n_bins",
            )
            charts.append(make_chart(fig_ctp, id=f"ctp_bins_{backbone}", title=f"{backbone} CTP bins"))

        # Tables panel
        tbl_list: list[dict] = []
        ptc_rows = ptc_df[ptc_df["backbone"] == backbone].to_dict("records") if not ptc_df.empty else []
        ctp_rows = ctp_df[ctp_df["backbone"] == backbone].to_dict("records") if not ctp_df.empty else []
        if ptc_rows:
            tbl_list.append(make_table(ptc_rows, id=f"ptc_tbl_{backbone}", title="PTC segmentation stats"))
        if ctp_rows:
            tbl_list.append(make_table(ctp_rows, id=f"ctp_tbl_{backbone}", title="CTP segmentation stats"))
        if tbl_list:
            panels.append(make_panel(id=f"div_tables_{backbone}", title="Raw tables", tables=tbl_list))

        subsections.append(
            {
                "id": f"div-{backbone}",
                "title": str(backbone),
                "description": "",
                "stats": [],
                "charts": charts,
                "tables": [],
                "panels": panels,
                "subsections": [],
                "warnings": [],
                "headline": None,
                "empty_message": "",
            }
        )

    return make_section(
        "bin-diversity",
        "Bin Diversity",
        description=(
            "Mean number of segments per song at each threshold. "
            "PTC = embedding-stream segmentation; CTP = head-activation segmentation. "
            "Higher threshold \u2192 fewer, coarser segments."
        ),
        subsections=subsections,
    )


def section_segment_counts(con) -> dict:
    """Segment count comparison across PTC and CTP modes per backbone."""
    has_ptc = table_exists(con, "binned_song_stats")
    has_ctp = table_exists(con, "binned_classify_ctp")

    if not has_ptc and not has_ctp:
        return make_section(
            "segment-counts",
            "Segment Counts per Threshold",
            empty_message="No segment data available yet.",
        )

    try:
        from scripts.embedding_research.helpers.binning import DIST_THRESHOLDS

        thresh_sql = ", ".join(str(t) for t in DIST_THRESHOLDS) if DIST_THRESHOLDS else None
    except ImportError:
        thresh_sql = None

    ptc_df = pd.DataFrame()
    if has_ptc:
        try:
            q = (
                "SELECT backbone, bin_mode, std_thresh, "
                "ROUND(AVG(n_bins), 2) AS mean_bins, "
                "CAST(MEDIAN(n_bins) AS INT) AS median_bins, "
                "MIN(n_bins) AS min_bins, MAX(n_bins) AS max_bins "
                "FROM binned_song_stats "
                + (f"WHERE std_thresh IN ({thresh_sql}) " if thresh_sql else "")
                + "GROUP BY backbone, bin_mode, std_thresh "
                "ORDER BY backbone, bin_mode, std_thresh"
            )
            ptc_df = con.execute(q).df()
        except Exception:
            pass

    ctp_df = pd.DataFrame()
    if has_ctp:
        try:
            q = (
                "SELECT backbone, head, bin_mode, std_thresh, "
                "ROUND(AVG(n_bins), 2) AS mean_bins, "
                "CAST(MEDIAN(n_bins) AS INT) AS median_bins, "
                "MIN(n_bins) AS min_bins, MAX(n_bins) AS max_bins "
                "FROM ( "
                "  SELECT backbone, head, bin_mode, std_thresh, song_id, "
                "         MAX(bin_id) + 1 AS n_bins "
                "  FROM binned_classify_ctp "
                + (f"  WHERE std_thresh IN ({thresh_sql}) " if thresh_sql else "")
                + "  GROUP BY backbone, head, bin_mode, std_thresh, song_id "
                ") sub "
                "GROUP BY backbone, head, bin_mode, std_thresh "
                "ORDER BY backbone, head, bin_mode, std_thresh"
            )
            ctp_df = con.execute(q).df()
        except Exception:
            pass

    if ptc_df.empty and ctp_df.empty:
        return make_section(
            "segment-counts",
            "Segment Counts per Threshold",
            empty_message="No segment data available.",
        )

    all_backbones = sorted(
        set(ptc_df["backbone"].unique() if not ptc_df.empty else [])
        | set(ctp_df["backbone"].unique() if not ctp_df.empty else [])
    )

    ptc_colors = {"temporal_global": "#7ec8e3", "temporal_perdim": "#a78bfa"}
    ctp_colors = ["#f9a825", "#ef5350", "#66bb6a", "#ab47bc", "#26c6da"]

    subsections: list[dict] = []
    for backbone in all_backbones:
        fig = go.Figure()
        if not ptc_df.empty:
            for bm, grp in ptc_df[ptc_df["backbone"] == backbone].groupby("bin_mode"):
                g = grp.sort_values("std_thresh")
                fig.add_trace(
                    go.Scatter(
                        x=g["std_thresh"].tolist(),
                        y=g["mean_bins"].tolist(),
                        mode="lines+markers",
                        name=f"PTC/{bm}",
                        line={"color": ptc_colors.get(str(bm), "#999"), "width": 1.5},
                        marker={"size": 5, "symbol": "circle"},
                    )
                )
        if not ctp_df.empty:
            for i, (head, grp) in enumerate(ctp_df[ctp_df["backbone"] == backbone].groupby("head")):
                for bm, bgrp in grp.groupby("bin_mode"):
                    g = bgrp.sort_values("std_thresh")
                    fig.add_trace(
                        go.Scatter(
                            x=g["std_thresh"].tolist(),
                            y=g["mean_bins"].tolist(),
                            mode="lines+markers",
                            name=f"CTP/{head}/{bm}",
                            line={
                                "color": ctp_colors[i % len(ctp_colors)],
                                "width": 1.2,
                                "dash": "solid" if str(bm) == "temporal_global" else "dash",
                            },
                            marker={"size": 4, "symbol": "square"},
                            opacity=0.85,
                        )
                    )
        apply_dark_theme(fig)
        fig.update_layout(
            title={"text": f"{backbone} \u2014 segment counts", "font": {"color": _FONT_COLOR}},
            height=_H_MED,
            xaxis_title="std_thresh",
            yaxis_title="mean n_segments",
        )

        ptc_rows = ptc_df[ptc_df["backbone"] == backbone].to_dict("records") if not ptc_df.empty else []
        ctp_rows = ctp_df[ctp_df["backbone"] == backbone].to_dict("records") if not ctp_df.empty else []

        tables: list[dict] = []
        inner_tbls: list[dict] = []
        if ptc_rows:
            inner_tbls.append(make_table(ptc_rows, id=f"seg_ptc_{backbone}", title="PTC"))
        if ctp_rows:
            inner_tbls.append(make_table(ctp_rows, id=f"seg_ctp_{backbone}", title="CTP"))

        panels: list[dict] = []
        if inner_tbls:
            panels.append(make_panel(id=f"seg_tbls_{backbone}", title="Tables", tables=inner_tbls))

        subsections.append(
            {
                "id": f"seg-{backbone}",
                "title": str(backbone),
                "description": "",
                "stats": [],
                "charts": [make_chart(fig, id=f"seg_{backbone}", title=f"{backbone} segment counts")],
                "tables": tables,
                "panels": panels,
                "subsections": [],
                "warnings": [],
                "headline": None,
                "empty_message": "",
            }
        )

    return make_section(
        "segment-counts",
        "Segment Counts per Threshold",
        description=(
            "How many segments does each threshold produce? "
            "Higher thresholds \u2192 fewer, coarser segments; lower thresholds \u2192 more, finer segments. "
            "PTC segments via the embedding stream; CTP segments via the head activation score stream."
        ),
        subsections=subsections,
    )


def section_bin_mode_comparison(df: pd.DataFrame) -> dict:
    """Head-to-head: temporal_global vs temporal_perdim per backbone, using mean MAP@k general (falls back to disc)."""
    binned_df = df[df["strategy_type"] == "ptc"]
    flat_df = df[df["strategy_type"] == "global_pool"]
    if binned_df.empty:
        return make_section(
            "bin-mode-comparison",
            "Bin Mode Comparison",
            empty_message="No binned results yet.",
        )

    try:
        from scripts.embedding_research.helpers.binning import DIST_THRESHOLDS

        if DIST_THRESHOLDS:
            binned_df = binned_df[binned_df["std_thresh"].isin(DIST_THRESHOLDS)]
    except ImportError:
        pass

    modes = [m for m in binned_df["bin_mode"].unique() if m is not None and not (isinstance(m, float) and pd.isna(m))]
    if len(modes) < 2:
        return make_section(
            "bin-mode-comparison",
            "Bin Mode Comparison",
            empty_message="Only one bin mode found \u2014 need both temporal_global and temporal_perdim.",
        )

    # Filter out rows with no bin_mode (CTP rows after refactor).
    binned_df = binned_df[binned_df["bin_mode"].notna()]

    disc_col = (
        "disc_general"
        if ("disc_general" in binned_df.columns and binned_df["disc_general"].notna().any())
        else "disc_score"
    )
    map_col = disc_col
    if "map_k_general" in binned_df.columns and binned_df["map_k_general"].notna().any():
        map_col = "map_k_general"

    subsections: list[dict] = []
    for backbone, bb_full in binned_df.groupby("backbone", sort=True):
        flat_ref_mean: float | None = None
        if flat_df is not None and not flat_df.empty:
            flat_dc = (
                "disc_general"
                if ("disc_general" in flat_df.columns and flat_df["disc_general"].notna().any())
                else "disc_score"
            )
            flat_ref_mean = flat_medoid_value(flat_df, backbone, flat_dc)

        # Per explicit configuration: each (bin_mode x std_thresh x rep_a x rep_b x
        # agg_method) is its own configuration.  The mean below is only over the
        # (sim_metric x k) evaluation variants WITHIN that config — it never averages
        # across representation or aggregation dimensions.
        cfg_cols = ["bin_mode", "std_thresh", "rep_a", "rep_b", "agg_method"]
        present_cfg = [c for c in cfg_cols if c in bb_full.columns]
        config_mean = bb_full.groupby(present_cfg, as_index=False, dropna=False)[map_col].mean()

        # Pair temporal_global vs temporal_perdim per explicit configuration
        # (threshold + rep_a + rep_b + agg_method), so each threshold stays its own
        # configuration and every reduction/ambiguity variant stays visible.
        pair_cols = [c for c in ("std_thresh", "rep_a", "rep_b", "agg_method") if c in present_cfg]
        g_scores = config_mean[config_mean["bin_mode"] == "temporal_global"].set_index(pair_cols)[map_col]
        p_scores = config_mean[config_mean["bin_mode"] == "temporal_perdim"].set_index(pair_cols)[map_col]
        common = sorted(set(g_scores.index) & set(p_scores.index))
        g_wins = sum(1 for cfg in common if g_scores.get(cfg, 0) > p_scores.get(cfg, 0))
        p_wins = sum(1 for cfg in common if p_scores.get(cfg, 0) > g_scores.get(cfg, 0))
        ties = len(common) - g_wins - p_wins

        if not common:
            verdict = (
                "No matching (rep_a, rep_b, agg_method) configuration pairs found across bin "
                "modes; comparison requires identical config identities at each threshold."
            )
        elif g_wins > p_wins:
            verdict = "temporal_global wins for this backbone."
        elif p_wins > g_wins:
            verdict = "temporal_perdim wins for this backbone."
        else:
            verdict = "Both modes perform equivalently for this backbone."

        g_above = (
            sum(1 for val in g_scores.values if flat_ref_mean is not None and val > flat_ref_mean)
            if flat_ref_mean is not None
            else None
        )
        p_above = (
            sum(1 for val in p_scores.values if flat_ref_mean is not None and val > flat_ref_mean)
            if flat_ref_mean is not None
            else None
        )

        detail_parts = [
            f"global wins {g_wins}, perdim wins {p_wins}, ties {ties} "
            f"(out of {len(common)} matching per-config threshold pairs, compared by mean {map_col} "
            "per explicit configuration)"
        ]
        if flat_ref_mean is not None:
            detail_parts.append(
                f"global mean beats flat at {g_above}/{len(g_scores.index)} configurations; "
                f"perdim mean beats flat at {p_above}/{len(p_scores.index)} configurations"
            )
        detail_parts.append(verdict)

        fig = go.Figure()
        # One solid global + one dashed perdim trace per explicit (rep_a, rep_b,
        # agg_method) configuration, so every reduction/ambiguity variant stays visible
        # and no two configurations are averaged together.
        cfg_keys = (
            config_mean[["rep_a", "rep_b", "agg_method"]]
            .drop_duplicates()
            .sort_values(["rep_a", "rep_b", "agg_method"])
        )
        for i, (_, cfg) in enumerate(cfg_keys.iterrows()):
            ra, rb, am = cfg["rep_a"], cfg["rep_b"], cfg["agg_method"]
            color = _REP_PALETTE[i % len(_REP_PALETTE)]
            label = f"{rep_label(ra)}x{rep_label(rb)}/{agg_label(am)}"
            mask = (config_mean["rep_a"] == ra) & (config_mean["rep_b"] == rb) & (config_mean["agg_method"] == am)
            g_cfg = config_mean[mask & (config_mean["bin_mode"] == "temporal_global")].sort_values("std_thresh")
            p_cfg = config_mean[mask & (config_mean["bin_mode"] == "temporal_perdim")].sort_values("std_thresh")
            if not g_cfg.empty:
                fig.add_trace(
                    go.Scatter(
                        x=g_cfg["std_thresh"].tolist(),
                        y=g_cfg[map_col].tolist(),
                        mode="lines+markers",
                        name=f"global \u00b7 {label}",
                        line={"color": color, "width": 1.5, "dash": "solid"},
                        marker={"size": 6},
                    )
                )
            if not p_cfg.empty:
                fig.add_trace(
                    go.Scatter(
                        x=p_cfg["std_thresh"].tolist(),
                        y=p_cfg[map_col].tolist(),
                        mode="lines+markers",
                        name=f"perdim \u00b7 {label}",
                        line={"color": color, "width": 1.5, "dash": "dash"},
                        marker={"size": 6},
                    )
                )
        if flat_ref_mean is not None:
            fig.add_hline(
                y=flat_ref_mean,
                line_dash="dash",
                line_color="#f59e0b",
                line_width=1.0,
                annotation_text=f"medoid baseline {flat_ref_mean:.4f}",
                annotation_font_color=_FONT_COLOR,
            )
        apply_dark_theme(fig)
        fig.update_layout(
            title={"text": f"{backbone} \u2014 global vs perdim (mean {map_col})", "font": {"color": _FONT_COLOR}},
            height=_H_MED,
            xaxis_title="std_thresh",
            yaxis_title=f"mean {map_col}",
        )

        subsections.append(
            {
                "id": f"bmc-{backbone}",
                "title": str(backbone),
                "description": " \u2022 ".join(detail_parts),
                "stats": [],
                "charts": [make_chart(fig, id=f"bmc_{backbone}", title=f"{backbone} bin mode comparison")],
                "tables": [],
                "panels": [],
                "subsections": [],
                "warnings": [],
                "headline": None,
                "empty_message": "",
            }
        )

    return make_section(
        "bin-mode-comparison",
        "Bin Mode Comparison: global vs perdim",
        description=(
            "temporal_global: one std across all dimensions. "
            "temporal_perdim: per-dimension std, boundary where any dimension exceeds its own threshold. "
            f"Each (bin_mode x std_thresh x rep_a x rep_b x agg_method) is its own configuration; "
            f"the Y-axis shows mean {map_col} over the (sim_metric x k) evaluation variants within "
            "each configuration \u2014 never an average across representation or aggregation dimensions. "
            "Global vs perdim are compared only for matching explicit configurations at each threshold, "
            "so every reduction/ambiguity variant stays visible (solid = global, dashed = perdim per config). "
            "Amber dashed line = the explicit flat medoid baseline (global_pool:{backbone}:medoid)."
        ),
        subsections=subsections,
    )


def section_flat_binned_correlation(df: pd.DataFrame) -> dict:
    """Flat-binned rank correlation: does segmentation change the retrieval ranking?

    Shows ``flat_binned_spearman`` (Spearman rho between flat and binned retrieval rankings)
    and ``flat_binned_beneficial_reorder_rate`` (fraction of rank changes that are improvements)
    per backbone, grouped by strategy configuration.

    A Spearman close to 1.0 means the binned strategy preserves the flat ranking.
    A beneficial reorder rate > 0.5 means most rank changes are improvements.
    """
    binned_df = df[df["strategy_type"] == "ptc"]
    if binned_df.empty:
        return make_section(
            "flat-binned-corr",
            "Flat-Binned Rank Correlation",
            empty_message="No binned results yet.",
        )

    has_spearman = "flat_binned_spearman" in binned_df.columns and binned_df["flat_binned_spearman"].notna().any()
    has_reorder = (
        "flat_binned_beneficial_reorder_rate" in binned_df.columns
        and binned_df["flat_binned_beneficial_reorder_rate"].notna().any()
    )
    if not has_spearman and not has_reorder:
        return make_section(
            "flat-binned-corr",
            "Flat-Binned Rank Correlation",
            empty_message="No flat-binned correlation data available.",
        )

    try:
        from scripts.embedding_research.helpers.binning import DIST_THRESHOLDS

        if DIST_THRESHOLDS:
            binned_df = binned_df[binned_df["std_thresh"].isin(DIST_THRESHOLDS)]
    except ImportError:
        pass

    subsections: list[dict] = []
    for backbone, bb in binned_df.groupby("backbone", sort=True):
        combo_cols = ["strategy_type", "bin_mode", "head", "std_thresh", "rep_a", "rep_b", "agg_method"]
        present_cols = [c for c in combo_cols if c in bb.columns]
        agg_cols: dict = {}
        if has_spearman:
            agg_cols["mean_spearman"] = ("flat_binned_spearman", "mean")
            agg_cols["std_spearman"] = ("flat_binned_spearman", "std")
        if has_reorder:
            agg_cols["mean_reorder"] = ("flat_binned_beneficial_reorder_rate", "mean")
            agg_cols["std_reorder"] = ("flat_binned_beneficial_reorder_rate", "std")
        agg_cols["n"] = ("flat_binned_spearman", "count")

        agg = bb.groupby(present_cols, as_index=False, dropna=False).agg(**agg_cols).sort_values(present_cols)

        # Build table rows.
        tbl_rows = []
        for _, row in agg.iterrows():
            tbl_row: dict = {}
            for col in present_cols:
                val = row[col]
                if col == "head":
                    tbl_row[col] = (
                        str(val) if val is not None and not (isinstance(val, float) and pd.isna(val)) else "—"
                    )
                elif col == "std_thresh":
                    tbl_row[col] = fmt(val)
                else:
                    tbl_row[col] = str(val) if val is not None else "—"
            if has_spearman:
                tbl_row["spearman"] = fmt(row.get("mean_spearman"))
            if has_reorder:
                tbl_row["reorder_rate"] = fmt(row.get("mean_reorder"))
            tbl_row["n"] = str(int(row["n"]))
            tbl_rows.append(tbl_row)

        # Chart: spearman vs threshold, grouped by strategy type and head.
        charts: list[dict] = []
        if has_spearman:
            fig = go.Figure()
            for (st, head), grp in agg.groupby(["strategy_type", "head"], sort=True, dropna=False):
                g = grp.sort_values("std_thresh")
                label = str(st)
                if head is not None and not (isinstance(head, float) and pd.isna(head)):
                    label = f"{st}/{head}"
                fig.add_trace(
                    go.Scatter(
                        x=g["std_thresh"].tolist(),
                        y=g["mean_spearman"].tolist(),
                        error_y={
                            "type": "data",
                            "array": g["std_spearman"].fillna(0).tolist(),
                            "visible": True,
                            "thickness": 1.0,
                            "width": 4,
                        },
                        mode="lines+markers",
                        name=label,
                        marker={"size": 5},
                    )
                )
            apply_dark_theme(fig)
            fig.update_layout(
                title={
                    "text": f"{backbone} \u2014 flat-binned Spearman rho vs threshold",
                    "font": {"color": _FONT_COLOR},
                },
                height=_H_MED,
                xaxis_title="std_thresh",
                yaxis_title="Spearman rho",
            )
            charts.append(make_chart(fig, id=f"fb_corr_{backbone}", title=f"{backbone} flat-binned correlation"))

        panels: list[dict] = []
        if tbl_rows:
            panels.append(
                make_panel(
                    id=f"fb_corr_tbl_{backbone}",
                    title="Raw stats",
                    tables=[
                        make_table(
                            tbl_rows, id=f"fb_corr_tbl_data_{backbone}", title="Flat-binned correlation per config"
                        )
                    ],
                )
            )

        subsections.append(
            {
                "id": f"fbcorr-{backbone}",
                "title": str(backbone),
                "description": "",
                "stats": [],
                "charts": charts,
                "tables": [],
                "panels": panels,
                "subsections": [],
                "warnings": [],
                "headline": None,
                "empty_message": "",
            }
        )

    return make_section(
        "flat-binned-corr",
        "Flat-Binned Rank Correlation",
        description=(
            "Does segmentation change the retrieval ranking compared to flat pooling? "
            "Spearman rho close to 1.0 means the binned strategy preserves the flat ranking. "
            "Beneficial reorder rate > 0.5 means most rank changes are improvements. "
            "Statistics are computed over all (sim_metric x k) evaluation variants within each config."
        ),
        subsections=subsections,
    )
