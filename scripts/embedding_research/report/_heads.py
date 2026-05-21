"""Head × embedding correlation sections: head_sim_corr and PTC/CTP alignment."""

from __future__ import annotations

import numpy as _np
import pandas as pd

from ._base import _HAS_MPL, png, table, table_exists

try:
    import matplotlib.pyplot as plt
    import matplotlib.cm as _cm
except ImportError:
    pass


def section_head_sim_corr(con) -> str:
    """PRIMARY section: per-head Spearman r between pairwise sim and head-score difference."""
    if not table_exists(con, "head_sim_corr_rows"):
        return """
<section id="head-sim-corr">
  <h2>Head &#215; Similarity Correlation (primary)</h2>
  <p>Run the <em>analyze</em> phase to populate this section.</p>
</section>
"""
    try:
        df = con.execute(
            """
            SELECT backbone, bin_mode, std_thresh, rep_a, rep_b,
                   sim_metric, agg_method, k, head, corr
            FROM head_sim_corr_rows
            ORDER BY backbone, head, bin_mode, std_thresh
            """
        ).df()
    except Exception as exc:
        return f"""
<section id="head-sim-corr">
  <h2>Head &#215; Similarity Correlation (primary)</h2>
  <p class="muted">Query error: {exc}</p>
</section>
"""

    if df.empty:
        return """
<section id="head-sim-corr">
  <h2>Head &#215; Similarity Correlation (primary)</h2>
  <p>No per-head correlation data yet. Run the <em>analyze</em> phase.</p>
</section>
"""

    # Collapse agg_method, rep_a, rep_b, sim_metric → take best |corr| per (backbone, bin_mode, std_thresh, head)
    df["abs_corr"] = df["corr"].abs()
    best = (
        df.groupby(["backbone", "bin_mode", "std_thresh", "head"], as_index=False)
        .apply(lambda g: g.loc[g["abs_corr"].idxmax()])
        .reset_index(drop=True)
    )

    parts = [
        """
<section id="head-sim-corr">
  <h2>Head &#215; Similarity Correlation (primary)</h2>
  <div class="card">
    <p class="muted">
      Spearman rank correlation between pairwise embedding similarity and the absolute
      difference in that head's activation score for each song pair.
      <strong>Positive = high-sim songs score the same on that head</strong> (good bunching).
      Best config across all pooling and aggregation variants is shown per point.
    </p>
  </div>
"""
    ]

    for backbone, bb_df in best.groupby("backbone", sort=True):
        heads = sorted(bb_df["head"].unique())
        bin_modes = sorted(bb_df["bin_mode"].unique())
        n_bm = len(bin_modes)

        if _HAS_MPL:
            cmap = _cm.get_cmap("tab20", len(heads))
            head_colors = {h: cmap(i) for i, h in enumerate(heads)}

            fig, axes = plt.subplots(1, n_bm, figsize=(7 * n_bm, 4.5), squeeze=False)
            fig.patch.set_facecolor("#1a1b26")

            for col, bin_mode in enumerate(bin_modes):
                ax = axes[0][col]
                bm_df = bb_df[bb_df["bin_mode"] == bin_mode]
                for head in heads:
                    h_df = bm_df[bm_df["head"] == head].sort_values("std_thresh")
                    if h_df.empty:
                        continue
                    ax.plot(
                        h_df["std_thresh"],
                        h_df["corr"],
                        marker="o",
                        markersize=3,
                        linewidth=1.4,
                        label=head,
                        color=head_colors[head],
                    )
                ax.axhline(0, color="#555", linewidth=0.8, linestyle="--")
                ax.set_xlabel("std_thresh", color="#999", fontsize=9)
                ax.set_ylabel("Spearman r", color="#999", fontsize=9)
                ax.set_title(f"{backbone} / {bin_mode}", color="#e0e0e8", fontsize=10)
                ax.legend(
                    fontsize=7,
                    facecolor="#1a1b26",
                    labelcolor="#ccc",
                    edgecolor="#333",
                    loc="upper right",
                    ncol=2 if len(heads) > 6 else 1,
                )
                ax.grid(True, alpha=0.12, color="#555")
                ax.spines[["top", "right"]].set_visible(False)
                for sp in ax.spines.values():
                    sp.set_color("#333")
                ax.set_facecolor("#12131e")
                ax.tick_params(colors="#aaa", labelsize=8)

            fig.tight_layout()
            chart_html = png(fig)
        else:
            rows_flat = best[best["backbone"] == backbone][
                ["bin_mode", "std_thresh", "head", "corr"]
            ].to_dict("records")
            chart_html = table(rows_flat)

        # Best config summary per head
        best_bb = bb_df.loc[bb_df.groupby("head")["abs_corr"].idxmax()]
        summary_rows = [
            {
                "head": row["head"],
                "best corr": round(row["corr"], 4),
                "bin_mode": row["bin_mode"],
                "std_thresh": row["std_thresh"],
            }
            for _, row in best_bb.sort_values("abs_corr", ascending=False).iterrows()
        ]
        summary_html = table(summary_rows)

        parts.append(
            f"""
<details open>
  <summary>{backbone}</summary>
  <div class="details-body">
    {chart_html}
    <h4 style="margin-top:16px;color:#c0c0e0;font-size:13px">Best config per head</h4>
    {summary_html}
  </div>
</details>
"""
        )

    parts.append("</section>")
    return "\n".join(parts)


def section_ptc_ctp_alignment(con) -> str:
    if not table_exists(con, "binned_ptc_ctp_metrics"):
        return """
<section id="head-agreement">
  <h2>PTC / CTP Alignment</h2>
  <p class="empty"><em>Run the classify phase to compute alignment metrics.</em></p>
</section>
"""

    try:
        df = con.execute(
            """
            SELECT backbone, head, bin_mode, std_thresh,
                   ROUND(divergence_mean, 4)  AS divergence_mean,
                   ROUND(bin_count_var, 4)    AS bin_count_var,
                   ROUND(sim_align_corr, 4)   AS sim_align_corr
            FROM binned_ptc_ctp_metrics
            ORDER BY backbone, head, bin_mode, std_thresh
            """
        ).df()
    except Exception:
        return """
<section id="head-agreement">
  <h2>PTC / CTP Alignment</h2>
  <p class="empty"><em>No alignment data available.</em></p>
</section>
"""

    if df.empty:
        return """
<section id="head-agreement">
  <h2>PTC / CTP Alignment</h2>
  <p class="empty"><em>No alignment metrics computed yet.</em></p>
</section>
"""

    parts = [
        """
<section id="head-agreement">
  <h2>PTC / CTP Alignment</h2>
  <div class="card">
    <p class="muted">
      <strong>divergence_mean</strong>: probability divergence between PTC and CTP per bin
      (lower = the two methods agree on class distribution).
      <strong>sim_align_corr</strong>: Pearson r between PTC and CTP similarity rankings
      (1.0 = perfect agreement, 0 = unrelated). Higher std_thresh = coarser bins.
    </p>
  </div>
"""
    ]

    for (backbone, head), group in df.groupby(["backbone", "head"], sort=True):
        bin_modes = group["bin_mode"].unique().tolist()

        if _HAS_MPL:
            fig, axes = plt.subplots(1, 2, figsize=(10, 3.5))
            line_colors = {"temporal_global": "#7ec8e3", "temporal_perdim": "#a78bfa"}
            metrics = [("divergence_mean", "divergence_mean"), ("sim_align_corr", "sim_align_corr")]
            for ax, (col, ylabel) in zip(axes, metrics):
                for bm in sorted(bin_modes):
                    sub = group[group["bin_mode"] == bm].sort_values("std_thresh")
                    ax.plot(
                        sub["std_thresh"],
                        sub[col],
                        marker="o",
                        markersize=4,
                        label=bm,
                        color=line_colors.get(bm, "#999"),
                    )
                ax.set_xlabel("std_thresh", color="#999")
                ax.set_ylabel(ylabel, color="#999")
                ax.set_title(f"{ylabel}", color="#e0e0e8", fontsize=10)
                ax.legend(fontsize=8, facecolor="#1a1b26", labelcolor="#ccc", edgecolor="#333")
                ax.grid(True, alpha=0.15, color="#555")
                ax.spines[["top", "right"]].set_visible(False)
                for sp in ax.spines.values():
                    sp.set_color("#333")
                ax.set_facecolor("#12131e")
                ax.tick_params(colors="#aaa", labelsize=8)
            fig.suptitle(f"{backbone} / {head}", color="#e0e0e8", fontsize=11)
            fig.patch.set_facecolor("#1a1b26")
            fig.tight_layout()
            chart_html = png(fig)
        else:
            tbl_rows = group[
                ["bin_mode", "std_thresh", "divergence_mean", "bin_count_var", "sim_align_corr"]
            ].to_dict("records")
            chart_html = table(tbl_rows)

        tbl_rows = group[
            ["bin_mode", "std_thresh", "divergence_mean", "bin_count_var", "sim_align_corr"]
        ].to_dict("records")
        parts.append(
            f"<h3>{backbone} / {head}</h3>"
            + chart_html
            + '<details style="margin-top:10px"><summary>Table</summary>'
            + f'<div class="details-body">{table(tbl_rows)}</div></details>'
        )

    parts.append("</section>")
    return "\n".join(parts)



def section_head_heatmap(con) -> str:
    """Backbone \u00d7 Head heatmap: best |Spearman r| per cell, all configs collapsed."""
    if not table_exists(con, "head_sim_corr_rows"):
        return """
<section id="head-heatmap">
  <h2>Backbone &#215; Head Heatmap</h2>
  <p class="empty"><em>No correlation data yet.</em></p>
</section>
"""
    try:
        df = con.execute(
            "SELECT backbone, head, MAX(ABS(corr)) AS best_corr "
            "FROM head_sim_corr_rows GROUP BY backbone, head"
        ).df()
    except Exception:
        return ""

    if df.empty:
        return """
<section id="head-heatmap">
  <h2>Backbone &#215; Head Heatmap</h2>
  <p class="empty"><em>No correlation data yet.</em></p>
</section>
"""

    pivot = df.pivot(index="head", columns="backbone", values="best_corr")

    if _HAS_MPL:
        import numpy as np

        fig, ax = plt.subplots(
            figsize=(max(3.5, len(pivot.columns) * 1.8), max(2.5, len(pivot) * 0.55))
        )
        data = pivot.values.astype(float)
        im = ax.imshow(data, cmap="RdYlGn", aspect="auto", vmin=0, vmax=1)
        cbar = fig.colorbar(im, ax=ax, shrink=0.85)
        cbar.ax.tick_params(colors="#aaa", labelsize=8)
        cbar.set_label("best |r|", color="#ccc", fontsize=9)
        ax.set_xticks(range(len(pivot.columns)))
        ax.set_xticklabels(pivot.columns.tolist(), color="#ccc", fontsize=9)
        ax.set_yticks(range(len(pivot)))
        ax.set_yticklabels(pivot.index.tolist(), color="#ccc", fontsize=9)
        ax.set_title(
            "Best |Spearman r| per (backbone, head)", color="#e0e0e8", fontsize=10
        )
        for i in range(data.shape[0]):
            for j in range(data.shape[1]):
                v = data[i, j]
                if not np.isnan(v):
                    ax.text(
                        j, i, f"{v:.2f}",
                        ha="center", va="center",
                        color="#111" if v > 0.55 else "#eee",
                        fontsize=8,
                    )
        ax.set_facecolor("#12131e")
        fig.patch.set_facecolor("#1a1b26")
        ax.tick_params(colors="#aaa")
        for sp in ax.spines.values():
            sp.set_color("#333")
        fig.tight_layout()
        chart_html = png(fig)
    else:
        tbl_rows = [
            {"head": row["head"], "backbone": row["backbone"], "best |r|": round(row["best_corr"], 4)}
            for _, row in df.sort_values(["head", "backbone"]).iterrows()
        ]
        chart_html = table(tbl_rows)

    return f"""
<section id="head-heatmap">
  <h2>Backbone &#215; Head Heatmap</h2>
  <div class="card">
    <p class="muted">
      Best absolute Spearman rank correlation between pairwise embedding similarity and
      head-score delta across all pooling / threshold / aggregation configurations.
      High values (green) = that head &#39;s scores strongly predict similarity for that backbone.
      Compare backbones vertically to see which heads are universally strong.
    </p>
  </div>
  {chart_html}
</section>
"""


def section_flat_head_comparison(con) -> str:
    """PTC vs CTP discrimination: ptc_ctp_rows — which pathway captures the head better?"""
    if not table_exists(con, "ptc_ctp_rows"):
        return """
<section id="flat-head-compare">
  <h2>PTC vs CTP Head Discrimination</h2>
  <p class="empty"><em>Run the <em>classify</em> phase to populate this section.</em></p>
</section>
"""
    try:
        df = con.execute(
            "SELECT backbone, head, strategy, "
            "ROUND(ptc_disc,4) AS ptc_disc, ROUND(ctp_disc,4) AS ctp_disc, "
            "ROUND(delta_disc,4) AS delta_disc, "
            "ROUND(ptc_map,4)  AS ptc_map,  ROUND(ctp_map,4)  AS ctp_map, "
            "ROUND(delta_map,4) AS delta_map "
            "FROM ptc_ctp_rows ORDER BY backbone, head, strategy"
        ).df()
    except Exception:
        return ""

    if df.empty:
        return """
<section id="flat-head-compare">
  <h2>PTC vs CTP Head Discrimination</h2>
  <p class="empty"><em>No data yet.</em></p>
</section>
"""

    parts = [
        """
<section id="flat-head-compare">
  <h2>PTC vs CTP Head Discrimination</h2>
  <div class="card">
    <p class="muted">
      <strong>PTC</strong> (pool-then-classify): one embedding per song, head runs on it.
      <strong>CTP</strong> (classify-then-pool): head runs on every patch, then pool.
      <code>delta_disc</code> = ctp_disc &#8722; ptc_disc
      (<strong>positive = CTP finds more discrimination</strong>; suggests the head
      captures within-song variation that pooling destroys).
    </p>
  </div>
"""
    ]

    for backbone, bb_df in df.groupby("backbone", sort=True):
        if _HAS_MPL:
            heads = bb_df["head"].unique().tolist()
            x = range(len(heads))
            fig, axes = plt.subplots(1, 2, figsize=(10, max(3, len(heads) * 0.5)))
            fig.patch.set_facecolor("#1a1b26")

            by_head = bb_df.groupby("head").agg(
                ptc_disc=("ptc_disc", "mean"),
                ctp_disc=("ctp_disc", "mean"),
                delta_disc=("delta_disc", "mean"),
                ptc_map=("ptc_map", "mean"),
                ctp_map=("ctp_map", "mean"),
            ).reindex(sorted(heads))

            ax0 = axes[0]
            ax0.barh(
                by_head.index.tolist()[::-1],
                by_head["ptc_disc"].tolist()[::-1],
                color="#7ec8e3", height=0.4, label="PTC",
            )
            ax0.barh(
                [h + "\u200b" for h in by_head.index.tolist()[::-1]],
                by_head["ctp_disc"].tolist()[::-1],
                color="#a78bfa", height=0.4, label="CTP",
            )
            ax0.set_xlabel("disc", color="#999", fontsize=9)
            ax0.set_title("disc per head (PTC vs CTP)", color="#e0e0e8", fontsize=10)
            ax0.legend(fontsize=8, facecolor="#1a1b26", labelcolor="#ccc", edgecolor="#333")

            ax1 = axes[1]
            delta_vals = by_head["delta_disc"].tolist()[::-1]
            delta_colors = ["#4ade80" if v > 0 else "#f87171" for v in delta_vals]
            ax1.barh(
                by_head.index.tolist()[::-1],
                delta_vals,
                color=delta_colors, height=0.55,
            )
            ax1.axvline(0, color="#555", linewidth=0.8)
            ax1.set_xlabel("\u0394 disc (CTP \u2212 PTC)", color="#999", fontsize=9)
            ax1.set_title("CTP improvement over PTC", color="#e0e0e8", fontsize=10)

            for ax in axes:
                ax.grid(True, axis="x", alpha=0.12, color="#555")
                ax.spines[["top", "right"]].set_visible(False)
                for sp in ax.spines.values():
                    sp.set_color("#333")
                ax.set_facecolor("#12131e")
                ax.tick_params(colors="#aaa", labelsize=8)

            fig.suptitle(backbone, color="#e0e0e8", fontsize=11)
            fig.tight_layout()
            chart_html = png(fig)
        else:
            chart_html = table(bb_df.to_dict("records"))

        tbl_html = table(bb_df.to_dict("records"))
        parts.append(
            f"<h3>{backbone}</h3>"
            + chart_html
            + f'<details style="margin-top:10px"><summary>Table</summary>'
            + f'<div class="details-body">{tbl_html}</div></details>'
        )

    parts.append("</section>")
    return "\n".join(parts)


def section_head_agreement(con) -> str:
    """head_agreement_rows: how often does the binned decision match the flat PTC baseline?"""
    if not table_exists(con, "head_agreement_rows"):
        return """
<section id="head-agreement-rate">
  <h2>Binned Head Agreement Rate</h2>
  <p class="empty"><em>No agreement data yet.</em></p>
</section>
"""
    try:
        df = con.execute(
            "SELECT backbone, head, bin_mode, std_thresh, "
            "ROUND(agreement_rate, 4) AS agreement_rate, n_songs "
            "FROM head_agreement_rows ORDER BY backbone, head, bin_mode, std_thresh"
        ).df()
    except Exception:
        return ""

    if df.empty:
        return """
<section id="head-agreement-rate">
  <h2>Binned Head Agreement Rate</h2>
  <p class="empty"><em>No data yet.</em></p>
</section>
"""

    parts = [
        """
<section id="head-agreement-rate">
  <h2>Binned Head Agreement Rate</h2>
  <div class="card">
    <p class="muted">
      Fraction of songs where the binned weighted-majority head decision (CTP) matches
      the flat PTC/median single-vector decision. <strong>1.0 = perfect agreement</strong>;
      low values = binning changes the head classification for many songs, which could
      indicate the head is sensitive to within-song temporal variation.
    </p>
  </div>
"""
    ]

    for backbone, bb_df in df.groupby("backbone", sort=True):
        heads = sorted(bb_df["head"].unique())
        bin_modes = sorted(bb_df["bin_mode"].unique())

        if _HAS_MPL:
            cmap = _cm.get_cmap("tab10", len(heads))
            head_colors = {h: cmap(i) for i, h in enumerate(heads)}
            n_bm = len(bin_modes)
            fig, axes = plt.subplots(1, n_bm, figsize=(6 * n_bm, 3.5), squeeze=False)
            fig.patch.set_facecolor("#1a1b26")

            for col, bm in enumerate(bin_modes):
                ax = axes[0][col]
                bm_df = bb_df[bb_df["bin_mode"] == bm]
                for head in heads:
                    h_df = bm_df[bm_df["head"] == head].sort_values("std_thresh")
                    if h_df.empty:
                        continue
                    ax.plot(
                        h_df["std_thresh"],
                        h_df["agreement_rate"],
                        marker="o",
                        markersize=4,
                        label=head,
                        color=head_colors[head],
                    )
                ax.axhline(1.0, color="#555", linewidth=0.8, linestyle="--")
                ax.set_ylim(0, 1.05)
                ax.set_xlabel("std_thresh", color="#999", fontsize=9)
                ax.set_ylabel("agreement rate", color="#999", fontsize=9)
                ax.set_title(f"{backbone} / {bm}", color="#e0e0e8", fontsize=10)
                ax.legend(
                    fontsize=7, facecolor="#1a1b26", labelcolor="#ccc",
                    edgecolor="#333", loc="lower right",
                )
                ax.grid(True, alpha=0.12, color="#555")
                ax.spines[["top", "right"]].set_visible(False)
                for sp in ax.spines.values():
                    sp.set_color("#333")
                ax.set_facecolor("#12131e")
                ax.tick_params(colors="#aaa", labelsize=8)

            fig.tight_layout()
            chart_html = png(fig)
        else:
            chart_html = table(
                bb_df[["head", "bin_mode", "std_thresh", "agreement_rate", "n_songs"]]
                .to_dict("records")
            )

        parts.append(
            f"<details open><summary>{backbone}</summary>"
            + f'<div class="details-body">{chart_html}</div></details>'
        )

    parts.append("</section>")
    return "\n".join(parts)


def section_ptc_ctp_retrieval_comparison(con, flat_df: pd.DataFrame | None = None) -> str:
    """Compare PTC vs CTP retrieval quality (disc_score, MAP@k, MRR, NDCG@k) side-by-side.

    PTC segments come from embedding-space STD-binning (binned_retrieval_rows).
    CTP segments come from head score-stream STD-binning (binned_ctp_retrieval_rows).

    A positive delta (CTP > PTC) means the head carves out embedding segments that
    are better separated than embedding-space distance alone.
    """
    has_ptc = table_exists(con, "binned_retrieval_rows")
    has_ctp = table_exists(con, "binned_ctp_retrieval_rows")

    if not has_ptc and not has_ctp:
        return """
<section id="ptc-ctp-retrieval">
  <h2>PTC vs CTP Retrieval Quality</h2>
  <p class="empty"><em>Run the <em>analyze</em> phase to populate this section.</em></p>
</section>
"""

    parts = [
        """
<section id="ptc-ctp-retrieval">
  <h2>PTC vs CTP Retrieval Quality</h2>
  <div class="card">
    <p class="muted">
      <strong>PTC (pool-then-classify)</strong>: embedding segments defined by
      embedding-space distance STD-binning, independent of any head.<br>
      <strong>CTP (classify-then-pool)</strong>: embedding segments defined by the head&#39;s
      own score-stream STD-binning. One result set per head.<br>
      Best configuration across all (rep_a, rep_b, sim_metric, agg_method) variants is
      shown per threshold. A positive &#916; (CTP &minus; PTC) means the head&#39;s
      dynamics yield better-separated embedding pools than embedding geometry alone.
    </p>
  </div>
"""
    ]

    if not has_ctp:
        parts.append(
            '<p class="muted" style="padding:0 16px">CTP data not yet available. '
            "Run <em>analyze</em> phase after the <em>classify</em> phase completes.</p>"
        )
        parts.append("</section>")
        return "\n".join(parts)

    METRICS = ["disc_score", "map_k", "mrr", "ndcg_k"]

    def _best_per_thresh(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame()
        return df.groupby(group_cols, dropna=False)[METRICS].max().reset_index()

    try:
        df_ptc = con.execute(
            "SELECT backbone, bin_mode, std_thresh, rep_a, rep_b, "
            "sim_metric, agg_method, k, disc_score, map_k, mrr, ndcg_k "
            "FROM binned_retrieval_rows"
        ).df() if has_ptc else pd.DataFrame()

        df_ctp = con.execute(
            "SELECT backbone, head, bin_mode, std_thresh, rep_a, rep_b, "
            "sim_metric, agg_method, k, disc_score, map_k, mrr, ndcg_k "
            "FROM binned_ctp_retrieval_rows"
        ).df()

        # Flat baseline passed in from the caller (already queried once at report start)
        flat_best: dict[str, dict[str, float | None]] = {}
        if flat_df is not None and not flat_df.empty:
            for _bb, _fbb in flat_df.groupby("backbone"):
                flat_best[str(_bb)] = {
                    "disc_score": float(_fbb["disc_score"].dropna().max()) if not _fbb["disc_score"].dropna().empty else None,
                    "map_k": float(_fbb["map_k"].dropna().max()) if not _fbb["map_k"].dropna().empty else None,
                }
    except Exception as exc:
        parts.append(f'<p class="muted">Query error: {exc}</p>')
        parts.append("</section>")
        return "\n".join(parts)

    if df_ctp.empty:
        parts.append(
            '<p class="muted" style="padding:0 16px">CTP retrieval table is empty. '
            "Run the <em>analyze</em> phase.</p>"
        )
        parts.append("</section>")
        return "\n".join(parts)

    best_ptc = _best_per_thresh(df_ptc, ["backbone", "bin_mode", "std_thresh", "k"])
    best_ctp = _best_per_thresh(df_ctp, ["backbone", "head", "bin_mode", "std_thresh", "k"])

    for backbone in sorted(df_ctp["backbone"].unique()):
        ctp_bb = best_ctp[best_ctp["backbone"] == backbone]
        ptc_bb = best_ptc[best_ptc["backbone"] == backbone] if not best_ptc.empty else pd.DataFrame()
        heads = sorted(ctp_bb["head"].unique())

        for head in heads:
            ctp_head = ctp_bb[ctp_bb["head"] == head].sort_values(["bin_mode", "std_thresh"])
            bin_modes = sorted(ctp_head["bin_mode"].unique())

            if _HAS_MPL:
                n_bm = len(bin_modes)
                fig, axes = plt.subplots(1, n_bm, figsize=(8 * n_bm, 4), squeeze=False)
                fig.patch.set_facecolor("#1a1b26")

                for col, bm in enumerate(bin_modes):
                    ax = axes[0][col]
                    ctp_bm = ctp_head[ctp_head["bin_mode"] == bm].sort_values("std_thresh")
                    ptc_bm = (
                        ptc_bb[ptc_bb["bin_mode"] == bm].sort_values("std_thresh")
                        if not ptc_bb.empty else pd.DataFrame()
                    )
                    thresholds = ctp_bm["std_thresh"].values

                    for metric, label, color_ptc, color_ctp, color_flat in [
                        ("disc_score", "disc", "#7ec8e3", "#a78bfa", "#e2e240"),
                        ("map_k", "MAP@k", "#4ade80", "#f97316", "#f472b6"),
                    ]:
                        ctp_vals = ctp_bm[metric].values
                        if not ptc_bm.empty:
                            ptc_vals = (
                                ptc_bm.set_index("std_thresh")
                                .reindex(thresholds)[metric]
                                .values
                            )
                        else:
                            ptc_vals = _np.full_like(ctp_vals, float("nan"))

                        ax.plot(
                            thresholds, ptc_vals,
                            marker="s", markersize=4, linewidth=1.4, linestyle="--",
                            color=color_ptc, label=f"PTC {label}", alpha=0.85,
                        )
                        ax.plot(
                            thresholds, ctp_vals,
                            marker="o", markersize=4, linewidth=1.4,
                            color=color_ctp, label=f"CTP {label}",
                        )

                        # Flat baseline — horizontal dashed line
                        _fb = flat_best.get(str(backbone), {}).get(metric)
                        if _fb is not None:
                            ax.axhline(
                                _fb,
                                color=color_flat,
                                linewidth=1.2,
                                linestyle=":",
                                label=f"flat {label} ({_fb:.4f})",
                                alpha=0.7,
                                zorder=0,
                            )

                    ax.set_xlabel("std_thresh", color="#999", fontsize=9)
                    ax.set_ylabel("metric value", color="#999", fontsize=9)
                    ax.set_title(f"{backbone} / {head} / {bm}", color="#e0e0e8", fontsize=10)
                    ax.legend(
                        fontsize=7, facecolor="#1a1b26", labelcolor="#ccc",
                        edgecolor="#333", loc="best", ncol=2,
                    )
                    ax.grid(True, alpha=0.12, color="#555")
                    ax.spines[["top", "right"]].set_visible(False)
                    for sp in ax.spines.values():
                        sp.set_color("#333")
                    ax.set_facecolor("#12131e")
                    ax.tick_params(colors="#aaa", labelsize=8)

                fig.tight_layout()
                chart_html = png(fig)
            else:
                tbl_rows = [
                    {
                        "bin_mode": row["bin_mode"],
                        "std_thresh": row["std_thresh"],
                        "CTP disc": round(row["disc_score"], 4) if pd.notna(row["disc_score"]) else None,
                        "CTP map_k": round(row["map_k"], 4) if pd.notna(row["map_k"]) else None,
                        "CTP mrr": round(row["mrr"], 4) if pd.notna(row["mrr"]) else None,
                    }
                    for _, row in ctp_head.iterrows()
                ]
                chart_html = table(tbl_rows)

            # Delta table
            delta_rows = []
            if not ptc_bb.empty:
                for bm in bin_modes:
                    ctp_bm = ctp_head[ctp_head["bin_mode"] == bm].set_index("std_thresh")
                    ptc_bm_idx = (
                        ptc_bb[ptc_bb["bin_mode"] == bm].set_index("std_thresh")
                        if not ptc_bb.empty else pd.DataFrame()
                    )
                    for thresh in sorted(ctp_bm.index):
                        c_row = ctp_bm.loc[thresh]
                        p_row = ptc_bm_idx.loc[thresh] if (not ptc_bm_idx.empty and thresh in ptc_bm_idx.index) else None

                        def _d(a, b):
                            if a is not None and b is not None and pd.notna(a) and pd.notna(b):
                                return round(float(a) - float(b), 4)
                            return None

                        delta_rows.append({
                            "bin_mode": bm,
                            "std_thresh": thresh,
                            "CTP disc": round(float(c_row["disc_score"]), 4) if pd.notna(c_row["disc_score"]) else None,
                            "PTC disc": round(float(p_row["disc_score"]), 4) if p_row is not None and pd.notna(p_row["disc_score"]) else None,
                            "\u0394 disc": _d(c_row["disc_score"], p_row["disc_score"] if p_row is not None else None),
                            "CTP MAP@k": round(float(c_row["map_k"]), 4) if pd.notna(c_row["map_k"]) else None,
                            "PTC MAP@k": round(float(p_row["map_k"]), 4) if p_row is not None and pd.notna(p_row["map_k"]) else None,
                            "\u0394 MAP@k": _d(c_row["map_k"], p_row["map_k"] if p_row is not None else None),
                        })

            tbl_html = (
                table(delta_rows)
                if delta_rows
                else "<p class='muted'>No PTC baseline available for delta computation.</p>"
            )

            parts.append(
                f"<details open><summary>{backbone} / {head}</summary>"
                + '<div class="details-body">'
                + chart_html
                + '<h4 style="margin-top:16px;color:#c0c0e0;font-size:13px">Delta table (CTP &#8722; PTC)</h4>'
                + tbl_html
                + "</div></details>"
            )

    parts.append("</section>")
    return "\n".join(parts)