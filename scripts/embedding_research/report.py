"""
Phase 4: generate markdown + CSV reports from DuckDB results.

Produces:
  report/embedding_metrics.md   -- strategy x metric x backbone retrieval table
  report/embedding_metrics.csv  -- same as CSV
  report/ptc_vs_ctp.md          -- PTC vs CTP disc/MAP per head x strategy
  report/ann_sweep.md           -- ANN recall@k vs ef_search
  report/summary.md             -- key findings in prose

Run from inside the devcontainer:
  python /workspace/scripts/embedding_research/report.py
"""

from __future__ import annotations

import argparse
import warnings

import pandas as pd
from tabulate import tabulate

from .config import BACKBONES, REPORT_DIR, bootstrap_nomarr
from .db import connect

# matplotlib is optional — skip charts if not installed
try:
    import matplotlib

    matplotlib.use("Agg")  # headless rendering
    import matplotlib.pyplot as plt
    import numpy as _np

    _HAS_MPL = True
except ImportError:
    _HAS_MPL = False
    warnings.warn("matplotlib not installed — charts will be skipped", stacklevel=1)


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def _df_to_md(df: pd.DataFrame, title: str) -> str:
    header = f"## {title}\n\n"
    return header + tabulate(df, headers="keys", tablefmt="github", showindex=False)


# ── Embedding metrics table ────────────────────────────────────────────────────


def report_embedding_metrics(con) -> tuple[str, pd.DataFrame]:
    df = con.execute(
        """
        SELECT
            backbone,
            strategy,
            sim_metric,
            k,
            ROUND(disc_score, 4)  AS disc_score,
            ROUND(mean_within, 4) AS mean_within,
            ROUND(mean_cross, 4)  AS mean_cross,
            ROUND(map_k, 4)       AS map_k,
            ROUND(mrr, 4)         AS mrr,
            ROUND(ndcg_k, 4)      AS ndcg_k,
            ROUND(recall_k, 4)    AS recall_k
        FROM retrieval_rows
        ORDER BY backbone, sim_metric, disc_score DESC
        """
    ).df()

    if df.empty:
        return "No retrieval metrics found — run analyze.py first.\n", df

    md_parts = ["# Embedding Retrieval Metrics\n\n"]
    for (bb, metric), grp in df.groupby(["backbone", "sim_metric"], sort=False):
        title = f"{bb} / {metric}"
        md_parts.append(_df_to_md(grp.drop(columns=["backbone", "sim_metric"]), title))
        md_parts.append("\n\n")

    return "".join(md_parts), df


# ── PTC vs CTP table ─────────────────────────────────────────────────────────


def report_ptc_vs_ctp(con) -> tuple[str, pd.DataFrame]:
    df = con.execute(
        """
        SELECT
            backbone,
            head,
            strategy,
            ROUND(ptc_disc,   4) AS ptc_disc,
            ROUND(ctp_disc,   4) AS ctp_disc,
            ROUND(delta_disc, 4) AS delta_disc,
            ROUND(ptc_map,    4) AS ptc_map,
            ROUND(ctp_map,    4) AS ctp_map,
            ROUND(delta_map,  4) AS delta_map
        FROM ptc_ctp_rows
        ORDER BY backbone, head, ABS(delta_disc) DESC
        """
    ).df()

    if df.empty:
        return "No PTC/CTP data found — run classify.py + analyze.py first.\n", df

    md_parts = ["# Pool-then-Classify (PTC) vs Classify-then-Pool (CTP)\n\n"]
    md_parts.append("> delta_disc = ptc_disc - ctp_disc  (positive = PTC wins, negative = CTP wins)\n\n")
    for (bb, head), grp in df.groupby(["backbone", "head"], sort=False):
        md_parts.append(_df_to_md(grp.drop(columns=["backbone", "head"]), f"{bb} / {head}"))
        md_parts.append("\n\n")

    return "".join(md_parts), df


# ── ANN sweep table ────────────────────────────────────────────────────────────


def report_ann_sweep(con) -> tuple[str, pd.DataFrame]:
    df = con.execute(
        """
        SELECT
            backbone,
            strategy,
            ef_search,
            ROUND(recall_k, 4) AS recall_k,
            backend
        FROM ann_rows
        ORDER BY backbone, strategy, ef_search
        """
    ).df()

    if df.empty:
        return "No ANN sweep data found — run analyze.py first.\n", df

    md_parts = ["# ANN Recall@k vs ef_search (HNSW cosine)\n\n"]
    md_parts.append(
        "> recall_k: fraction of exact top-k neighbours recovered by the ANN index.\n"
        "> Higher ef_search = higher recall but slower queries.\n\n"
    )
    for (bb, strat), grp in df.groupby(["backbone", "strategy"], sort=False):
        md_parts.append(_df_to_md(grp.drop(columns=["backbone", "strategy"]), f"{bb} / {strat}"))
        md_parts.append("\n\n")

    return "".join(md_parts), df


# ── Summary ────────────────────────────────────────────────────────────────────


def report_summary(con) -> str:
    lines = ["# Embedding Research Summary\n\n"]

    # Best strategy per backbone (by cosine disc_score)
    best = con.execute(
        """
        SELECT backbone, strategy, sim_metric, disc_score, map_k
        FROM retrieval_rows
        WHERE sim_metric = 'cosine'
        QUALIFY ROW_NUMBER() OVER (PARTITION BY backbone ORDER BY disc_score DESC) = 1
        """
    ).fetchall()

    lines.append("## Best Pooling Strategy (cosine, artist discrimination)\n\n")
    for row in best:
        bb, strat, _metric, disc, mapk = row
        lines.append(f"- **{bb}**: `{strat}` — disc={disc:.4f}, MAP@k={mapk:.4f}\n")

    lines.append("\n## Metric Comparison (best strategy, cosine)\n\n")
    for bb in BACKBONES:
        rows = con.execute(
            """
            SELECT sim_metric, strategy, disc_score, map_k
            FROM retrieval_rows
            WHERE backbone = ?
            QUALIFY ROW_NUMBER() OVER (PARTITION BY sim_metric ORDER BY disc_score DESC) = 1
            ORDER BY sim_metric
            """,
            [bb],
        ).fetchall()
        if rows:
            lines.append(f"### {bb}\n\n")
            for r in rows:
                lines.append(f"- {r[0]}: best=`{r[1]}` disc={r[2]:.4f} map={r[3]:.4f}\n")
            lines.append("\n")

    # PTC vs CTP winner count
    ptc_wins = con.execute("SELECT COUNT(*) FROM ptc_ctp_rows WHERE delta_disc > 0").fetchone()[0]
    ctp_wins = con.execute("SELECT COUNT(*) FROM ptc_ctp_rows WHERE delta_disc < 0").fetchone()[0]
    total = ptc_wins + ctp_wins
    if total:
        lines.append("## PTC vs CTP\n\n")
        lines.append(
            f"PTC (pool-then-classify) wins: **{ptc_wins}/{total}** comparisons\n"
            f"CTP (classify-then-pool) wins: **{ctp_wins}/{total}** comparisons\n\n"
        )

    # ANN peak recall
    ann_peak = con.execute(
        """
        SELECT backbone, strategy, ef_search, recall_k, backend
        FROM ann_rows
        QUALIFY ROW_NUMBER() OVER (PARTITION BY backbone ORDER BY recall_k DESC) = 1
        """
    ).fetchall()
    if ann_peak:
        lines.append("## ANN Peak Recall@k\n\n")
        for r in ann_peak:
            lines.append(f"- **{r[0]}** (`{r[1]}`): recall@k={r[3]:.4f} at ef_search={r[2]} ({r[4]})\n")

    return "".join(lines)


# ── Charts ────────────────────────────────────────────────────────────────────


def _save_fig(name: str) -> str:
    path = REPORT_DIR / name
    plt.tight_layout()
    plt.savefig(str(path), dpi=150, bbox_inches="tight")
    plt.close()
    return name


def generate_charts(emb_df: pd.DataFrame, ptc_df: pd.DataFrame, ann_df: pd.DataFrame) -> list[str]:
    """Generate PNG charts. Returns list of filenames that were saved."""
    if not _HAS_MPL:
        return []

    STRATEGIES = ["mean", "trimmed_10", "trimmed_20", "median", "max_norm", "l2norm_mean"]
    METRICS = ["cosine", "l2", "dot"]
    files = []

    # ── Chart 1: disc_score heatmap per backbone (strategy x sim_metric) ─────
    for bb in emb_df["backbone"].unique():
        sub = emb_df[emb_df["backbone"] == bb]
        pivot = sub.pivot_table(index="strategy", columns="sim_metric", values="disc_score", aggfunc="first")
        # Reorder rows/cols for readability
        row_order = [s for s in STRATEGIES if s in pivot.index]
        col_order = [m for m in METRICS if m in pivot.columns]
        pivot = pivot.reindex(index=row_order, columns=col_order)

        fig, ax = plt.subplots(figsize=(6, 4))
        im = ax.imshow(pivot.values, cmap="YlGn", aspect="auto", vmin=0)
        ax.set_xticks(range(len(pivot.columns)))
        ax.set_xticklabels(pivot.columns, fontsize=10)
        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels(pivot.index, fontsize=9)
        plt.colorbar(im, ax=ax, label="disc_score")
        for i in range(len(pivot.index)):
            for j in range(len(pivot.columns)):
                val = pivot.values[i, j]
                if not _np.isnan(val):
                    ax.text(
                        j,
                        i,
                        f"{val:.3f}",
                        ha="center",
                        va="center",
                        fontsize=8,
                        color="black" if val < 0.6 else "white",
                    )
        ax.set_title(f"{bb}: Artist Discrimination (disc_score)\nby pooling strategy × similarity metric")
        fname = f"chart_{bb}_disc_heatmap.png"
        files.append(_save_fig(fname))

    # ── Chart 2: MAP@k bar chart per backbone ─────────────────────────────────
    for bb in emb_df["backbone"].unique():
        sub = emb_df[(emb_df["backbone"] == bb) & (emb_df["sim_metric"] == "cosine")]
        if sub.empty:
            continue
        sub = sub.sort_values("map_k", ascending=True)
        fig, ax = plt.subplots(figsize=(7, 4))
        colors = ["#2196F3" if s == sub["strategy"].iloc[-1] else "#90CAF9" for s in sub["strategy"]]
        ax.barh(sub["strategy"], sub["map_k"], color=colors)
        ax.set_xlabel("MAP@k (cosine)")
        ax.set_title(f"{bb}: MAP@k by Pooling Strategy (cosine)")
        ax.set_xlim(0, max(sub["map_k"].max() * 1.2, 0.05))
        for i, (_, row) in enumerate(sub.iterrows()):
            ax.text(row["map_k"] + 0.001, i, f"{row['map_k']:.4f}", va="center", fontsize=8)
        fname = f"chart_{bb}_mapk_bar.png"
        files.append(_save_fig(fname))

    # ── Chart 3: PTC vs CTP comparison per backbone ────────────────────────────
    for bb in ptc_df["backbone"].unique():
        sub = ptc_df[ptc_df["backbone"] == bb]
        if sub.empty:
            continue
        grouped = sub.groupby("head")[["ptc_disc", "ctp_disc"]].mean().reset_index()
        x = range(len(grouped))
        w = 0.35
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.bar([xi - w / 2 for xi in x], grouped["ptc_disc"], w, label="PTC (pool→classify)", color="#4CAF50")
        ax.bar([xi + w / 2 for xi in x], grouped["ctp_disc"], w, label="CTP (classify→pool)", color="#FF9800")
        ax.set_xticks(list(x))
        ax.set_xticklabels(grouped["head"], rotation=30, ha="right", fontsize=8)
        ax.set_ylabel("disc_score (mean across strategies)")
        ax.set_title(f"{bb}: PTC vs CTP — Artist Discrimination by Head")
        ax.legend()
        fname = f"chart_{bb}_ptc_ctp.png"
        files.append(_save_fig(fname))

    # ── Chart 4: ANN recall vs ef_search ──────────────────────────────────────
    for bb in ann_df["backbone"].unique():
        sub = ann_df[ann_df["backbone"] == bb]
        if sub.empty:
            continue
        for strat, grp in sub.groupby("strategy"):
            grp_sorted = grp.sort_values("ef_search")
            plt.plot(grp_sorted["ef_search"], grp_sorted["recall_k"], marker="o", label=strat)
        plt.xlabel("ef_search")
        plt.ylabel("Recall@k")
        plt.title(f"{bb}: ANN HNSW Recall@k vs ef_search")
        plt.legend(fontsize=8)
        plt.ylim(0, 1.05)
        fname = f"chart_{bb}_ann_recall.png"
        files.append(_save_fig(fname))

    # ── Chart 5: within-class vs cross-class similarity ───────────────────────
    for bb in emb_df["backbone"].unique():
        sub = emb_df[(emb_df["backbone"] == bb) & (emb_df["sim_metric"] == "cosine")]
        if sub.empty:
            continue
        sub = sub.sort_values("disc_score", ascending=False)
        _fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(sub["strategy"], sub["mean_within"], "o-", color="#4CAF50", label="within-artist")
        ax.plot(sub["strategy"], sub["mean_cross"], "s-", color="#F44336", label="cross-artist")
        ax.fill_between(range(len(sub)), sub["mean_within"], sub["mean_cross"], alpha=0.1, color="blue")
        ax.set_xticklabels(sub["strategy"], rotation=25, ha="right", fontsize=8)
        ax.set_xticks(range(len(sub)))
        ax.set_ylabel("Mean cosine similarity")
        ax.set_title(f"{bb}: Within-Artist vs Cross-Artist Similarity by Strategy")
        ax.legend()
        fname = f"chart_{bb}_within_cross.png"
        files.append(_save_fig(fname))

    return files


# ── Main ───────────────────────────────────────────────────────────────────────


def run() -> None:
    bootstrap_nomarr()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    with connect() as con:
        print("Generating embedding metrics report ...")
        emb_md, emb_df = report_embedding_metrics(con)
        (REPORT_DIR / "embedding_metrics.md").write_text(emb_md, encoding="utf-8")
        if not emb_df.empty:
            emb_df.to_csv(REPORT_DIR / "embedding_metrics.csv", index=False)

        print("Generating PTC vs CTP report ...")
        ptc_md, ptc_df = report_ptc_vs_ctp(con)
        (REPORT_DIR / "ptc_vs_ctp.md").write_text(ptc_md, encoding="utf-8")
        if not ptc_df.empty:
            ptc_df.to_csv(REPORT_DIR / "ptc_vs_ctp.csv", index=False)

        print("Generating ANN sweep report ...")
        ann_md, ann_df = report_ann_sweep(con)
        (REPORT_DIR / "ann_sweep.md").write_text(ann_md, encoding="utf-8")
        if not ann_df.empty:
            ann_df.to_csv(REPORT_DIR / "ann_sweep.csv", index=False)

        print("Generating summary ...")
        summary = report_summary(con)
        (REPORT_DIR / "summary.md").write_text(summary, encoding="utf-8")

    print("Generating charts ...")
    chart_files = generate_charts(emb_df, ptc_df, ann_df)
    if chart_files:
        print(f"  Saved {len(chart_files)} charts: {chart_files}")
    else:
        print("  No charts generated (matplotlib not installed or no data).")

    print(f"\nReports written to {REPORT_DIR}/")
    for f in sorted(REPORT_DIR.glob("*")):
        print(f"  {f.name}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 4: generate markdown/CSV reports")
    ap.parse_args()  # no args yet, reserved for future filters
    run()


if __name__ == "__main__":
    main()
