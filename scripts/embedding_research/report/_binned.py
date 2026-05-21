"""Temporal-binned sections: threshold sweep."""

from __future__ import annotations

import pandas as pd

from ._base import _HAS_MPL, png, table, table_exists

try:
    import matplotlib.pyplot as plt
except ImportError:
    pass


def section_threshold_sweep(binned_df: pd.DataFrame, flat_df: pd.DataFrame | None = None) -> str:
    if binned_df.empty:
        return """
<section id="threshold-sweep">
  <h2>Threshold Sweep</h2>
  <p>No binned data yet.</p>
</section>
"""

    parts = [
        """
<section id="threshold-sweep">
  <h2>Threshold Sweep</h2>
  <div class="card">
    <p class="muted">Best <code>disc_score</code> per threshold for each backbone.
    Each line is a <code>bin_mode</code>. The dashed teal line is the flat baseline
    (industry standard, no binning). Higher is better; look for a peak threshold
    above which performance plateaus or degrades.</p>
  </div>
"""
    ]

    for backbone, bb_group in binned_df.groupby("backbone", sort=True):
        # Flat baseline for this backbone
        flat_best: float | None = None
        if flat_df is not None and not flat_df.empty:
            fb = flat_df[flat_df["backbone"] == backbone]["disc_score"].dropna()
            if not fb.empty:
                flat_best = float(fb.max())

        if _HAS_MPL:
            fig, ax = plt.subplots(figsize=(7, 3.5))
            line_colors = {"temporal_global": "#7ec8e3", "temporal_perdim": "#a78bfa"}
            for bin_mode, bm_group in bb_group.groupby("bin_mode", sort=True):
                rows = (
                    bm_group.groupby("std_thresh", as_index=False)["disc_score"]
                    .max()
                    .sort_values("std_thresh")
                )
                ax.plot(
                    rows["std_thresh"],
                    rows["disc_score"],
                    marker="o",
                    markersize=4,
                    label=bin_mode,
                    color=line_colors.get(bin_mode, "#999"),
                )
            if flat_best is not None:
                ax.axhline(
                    flat_best,
                    color="#7ec8e3",
                    linewidth=1.4,
                    linestyle="--",
                    label=f"flat best ({flat_best:.4f})",
                    alpha=0.75,
                    zorder=0,
                )
            ax.set_xlabel("std_thresh", color="#999")
            ax.set_ylabel("best disc_score", color="#999")
            ax.set_title(f"{backbone} — threshold sweep", color="#e0e0e8", fontsize=11)
            ax.legend(fontsize=9, facecolor="#1a1b26", labelcolor="#ccc", edgecolor="#333")
            ax.grid(True, alpha=0.15, color="#555")
            ax.spines[["top", "right"]].set_visible(False)
            for sp in ax.spines.values():
                sp.set_color("#333")
            ax.set_facecolor("#12131e")
            fig.patch.set_facecolor("#1a1b26")
            ax.tick_params(colors="#aaa", labelsize=8)
            fig.tight_layout()
            chart_html = png(fig)
        else:
            rows_tbl = (
                bb_group.groupby(["bin_mode", "std_thresh"], as_index=False)["disc_score"]
                .max()
                .sort_values(["bin_mode", "std_thresh"])
                .to_dict("records")
            )
            if flat_best is not None:
                for r in rows_tbl:
                    r["flat_best"] = round(flat_best, 4)
                    r["delta_vs_flat"] = round(float(r["disc_score"]) - flat_best, 4) if r["disc_score"] is not None else None
            chart_html = table(rows_tbl)

        parts.append(
            f"""
<details open>
  <summary>{backbone}</summary>
  <div class="details-body">{chart_html}</div>
</details>
"""
        )

    parts.append("</section>")
    return "\n".join(parts)



def section_bin_diversity(con) -> str:
    """binned_song_stats.bin_div_std: does binning produce meaningfully diverse segments?"""
    if not table_exists(con, "binned_song_stats"):
        return """
<section id="bin-diversity">
  <h2>Bin Diversity (bin_div_std)</h2>
  <p class="empty"><em>Run the <em>classify</em> phase to populate this section.</em></p>
</section>
"""
    try:
        df = con.execute(
            "SELECT backbone, bin_mode, std_thresh, bin_div_std "
            "FROM binned_song_stats WHERE bin_div_std IS NOT NULL"
        ).df()
    except Exception:
        return ""

    if df.empty:
        return """
<section id="bin-diversity">
  <h2>Bin Diversity (bin_div_std)</h2>
  <p class="empty"><em>No diversity data found.</em></p>
</section>
"""

    # Summarize: mean & std of bin_div_std per (backbone, bin_mode, std_thresh)
    stats = (
        df.groupby(["backbone", "bin_mode", "std_thresh"])["bin_div_std"]
        .agg(["mean", "std", "median"])
        .reset_index()
        .rename(columns={"mean": "mean_div", "std": "std_div", "median": "med_div"})
    )

    parts = [
        """
<section id="bin-diversity">
  <h2>Bin Diversity (bin_div_std)</h2>
  <div class="card">
    <p class="muted">
      <code>bin_div_std</code> is the standard deviation of pairwise L2 distances between
      a song&#39;s temporal bins. <strong>Higher = more diverse segments</strong>
      (binning is capturing real within-song variation, not noise).
      Low values at all thresholds suggest the backbone&#39;s embeddings are temporally stable
      and binning adds little information beyond the flat representation.
    </p>
  </div>
"""
    ]

    for backbone, bb in stats.groupby("backbone", sort=True):
        bin_modes = sorted(bb["bin_mode"].unique())

        if _HAS_MPL:
            import matplotlib.pyplot as plt

            line_colors = {"temporal_global": "#7ec8e3", "temporal_perdim": "#a78bfa"}
            fig, ax = plt.subplots(figsize=(7, 3.5))
            for bm in bin_modes:
                sub = bb[bb["bin_mode"] == bm].sort_values("std_thresh")
                color = line_colors.get(bm, "#999")
                ax.plot(
                    sub["std_thresh"],
                    sub["mean_div"],
                    marker="o",
                    markersize=4,
                    label=f"{bm} mean",
                    color=color,
                )
                ax.fill_between(
                    sub["std_thresh"],
                    sub["mean_div"] - sub["std_div"],
                    sub["mean_div"] + sub["std_div"],
                    alpha=0.15,
                    color=color,
                )
                ax.plot(
                    sub["std_thresh"],
                    sub["med_div"],
                    linestyle="--",
                    linewidth=1,
                    label=f"{bm} median",
                    color=color,
                    alpha=0.6,
                )
            ax.set_xlabel("std_thresh", color="#999", fontsize=9)
            ax.set_ylabel("bin_div_std", color="#999", fontsize=9)
            ax.set_title(f"{backbone}", color="#e0e0e8", fontsize=10)
            ax.legend(
                fontsize=8, facecolor="#1a1b26", labelcolor="#ccc",
                edgecolor="#333", ncol=2,
            )
            ax.grid(True, alpha=0.12, color="#555")
            ax.spines[["top", "right"]].set_visible(False)
            for sp in ax.spines.values():
                sp.set_color("#333")
            ax.set_facecolor("#12131e")
            fig.patch.set_facecolor("#1a1b26")
            ax.tick_params(colors="#aaa", labelsize=8)
            fig.tight_layout()
            chart_html = png(fig)
        else:
            chart_html = table(
                bb.round(4).to_dict("records")
            )

        parts.append(
            f"<details open><summary>{backbone}</summary>"
            + f'<div class="details-body">{chart_html}</div></details>'
        )

    parts.append("</section>")
    return "\n".join(parts)