"""Pipeline efficiency section: per-phase wall-clock timing across all runs."""

from __future__ import annotations

from ._base import _HAS_MPL, fmt, table, table_exists

try:
    import matplotlib.pyplot as plt
    import matplotlib.cm as _cm
except ImportError:
    pass


def section_efficiency(con) -> str:
    if not table_exists(con, "phase_timings"):
        return """
<section id="efficiency">
  <h2>Pipeline Efficiency</h2>
  <p class="empty"><em>No timing data yet. Run the pipeline to populate this section.</em></p>
</section>
"""
    try:
        df = con.execute(
            "SELECT run_ts, phase, ROUND(elapsed_s, 1) AS elapsed_s "
            "FROM phase_timings ORDER BY run_ts, phase"
        ).df()
    except Exception:
        return ""

    if df.empty:
        return """
<section id="efficiency">
  <h2>Pipeline Efficiency</h2>
  <p class="empty"><em>No timing data yet.</em></p>
</section>
"""

    # Latest run summary + historical table
    latest_ts = df["run_ts"].max()
    latest = df[df["run_ts"] == latest_ts]

    # Bar chart for the latest run
    if _HAS_MPL:
        phases = latest["phase"].tolist()
        secs = latest["elapsed_s"].tolist()
        # colour by phase name hash for consistency
        cmap = _cm.get_cmap("tab10", len(phases))
        colors = [cmap(i) for i in range(len(phases))]
        labels_with_time = [f"{p} ({s:.0f}s)" for p, s in zip(phases, secs)]

        fig, ax = plt.subplots(figsize=(7, max(2.5, len(phases) * 0.55)))
        ax.barh(labels_with_time[::-1], secs[::-1], color=colors[::-1], height=0.6)
        ax.set_xlabel("seconds", color="#999", fontsize=9)
        ax.set_title(f"Phase timing — {latest_ts}", color="#e0e0e8", fontsize=10)
        ax.grid(True, axis="x", alpha=0.12, color="#555")
        ax.spines[["top", "right"]].set_visible(False)
        for sp in ax.spines.values():
            sp.set_color("#333")
        ax.set_facecolor("#12131e")
        fig.patch.set_facecolor("#1a1b26")
        ax.tick_params(colors="#aaa", labelsize=8)
        fig.tight_layout()
        from ._base import png
        chart_html = png(fig)
    else:
        chart_html = table(latest.to_dict("records"))

    # Historical multi-run table (pivot: rows=run_ts, cols=phase)
    if df["run_ts"].nunique() > 1:
        pivot = df.pivot(index="run_ts", columns="phase", values="elapsed_s")
        pivot.columns.name = None
        pivot.index.name = "run"
        hist_rows = [{"run": idx, **row} for idx, row in pivot.iterrows()]
        hist_html = (
            '<details style="margin-top:14px"><summary>History (all runs)</summary>'
            + f'<div class="details-body">{table(hist_rows)}</div></details>'
        )
    else:
        hist_html = ""

    total_s = latest["elapsed_s"].sum()
    total_min = total_s / 60

    return f"""
<section id="efficiency">
  <h2>Pipeline Efficiency</h2>
  <div class="card">
    <p class="muted">
      Latest run <code>{latest_ts}</code> &mdash;
      total <strong>{total_s:.0f}s / {total_min:.1f} min</strong>
      across {len(latest)} phases.
      Useful for identifying bottlenecks when scaling corpus size or adding backbones.
    </p>
  </div>
  {chart_html}
  {hist_html}
</section>
"""
