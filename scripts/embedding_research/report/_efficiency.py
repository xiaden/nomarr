"""Pipeline efficiency (phase timing) section."""

from __future__ import annotations

import plotly.graph_objects as go

from ._base import (
    _FONT_COLOR,
    _GRID_COLOR,
    _H_SMALL,
    apply_dark_theme,
    make_chart,
    make_section,
    make_table,
    table_exists,
)


def section_efficiency(con) -> dict:
    """Wall-clock phase timing: latest-run bar chart + historical pivot table."""
    if not table_exists(con, "phase_timings"):
        return make_section(
            "efficiency",
            "Pipeline Efficiency",
            empty_message=("No timing data yet. Run the pipeline to populate this section."),
        )

    try:
        df = con.execute(
            "SELECT run_ts, phase, ROUND(elapsed_s, 1) AS elapsed_s FROM phase_timings ORDER BY run_ts, phase"
        ).df()
    except Exception:
        return make_section("efficiency", "Pipeline Efficiency", empty_message="Could not load timing data.")

    if df.empty:
        return make_section("efficiency", "Pipeline Efficiency", empty_message="No timing data yet.")

    latest_ts = df["run_ts"].max()
    latest = df[df["run_ts"] == latest_ts]

    tab10 = [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
        "#17becf",
    ]
    phases = latest["phase"].tolist()
    secs = latest["elapsed_s"].tolist()
    bar_colors = [tab10[i % len(tab10)] for i in range(len(phases))]
    labels_with_time = [f"{p} ({s:.0f}s)" for p, s in zip(phases, secs, strict=False)]
    height = max(_H_SMALL, len(phases) * 36 + 80)

    fig = go.Figure(
        [
            go.Bar(
                x=secs[::-1],
                y=labels_with_time[::-1],
                orientation="h",
                marker_color=bar_colors[::-1],
            )
        ]
    )
    apply_dark_theme(fig, grid=False)
    fig.update_layout(
        title={"text": f"Phase timing \u2014 {latest_ts}", "font": {"color": _FONT_COLOR}},
        height=height,
        xaxis={"title": "seconds", "showgrid": True, "gridcolor": _GRID_COLOR, "gridwidth": 0.5},
    )

    tables = []
    if df["run_ts"].nunique() > 1:
        pivot = df.pivot(index="run_ts", columns="phase", values="elapsed_s")
        pivot.columns.name = None
        pivot.index.name = "run"
        hist_rows = [{"run": str(idx), **row.to_dict()} for idx, row in pivot.iterrows()]
        tables.append(
            make_table(
                hist_rows,
                id="timing_history",
                collapsible=True,
                summary_text="History (all runs)",
            )
        )

    total_s = float(latest["elapsed_s"].sum())
    total_min = total_s / 60

    return make_section(
        "efficiency",
        "Pipeline Efficiency",
        description=(
            f"Latest run {latest_ts} \u2014 total {total_s:.0f}s / {total_min:.1f} min "
            f"across {len(latest)} phases. "
            "Useful for identifying bottlenecks when scaling corpus size or adding backbones."
        ),
        charts=[make_chart(fig, id="phase_timing", title=f"Phase timing \u2014 {latest_ts}")],
        tables=tables,
    )
