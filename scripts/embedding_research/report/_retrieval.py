"""Flat and unified retrieval sections: per-backbone comparison and unified ranking."""

from __future__ import annotations

import pandas as pd

from ..config import BACKBONES
from ..db import load_retrieval_binned, load_retrieval_flat
from ._base import (
    BINNED_COLUMNS,
    FLAT_COLUMNS,
    _HAS_MPL,
    bar_chart,
    empty_df,
    fmt,
    scatter_chart,
    table,
    table_exists,
)

try:
    import matplotlib.pyplot as plt
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def query_flat(con) -> pd.DataFrame:
    if not table_exists(con, "retrieval_rows"):
        return empty_df(FLAT_COLUMNS)
    return load_retrieval_flat(con)


def query_binned(con) -> pd.DataFrame:
    if not table_exists(con, "binned_retrieval_rows"):
        return empty_df(BINNED_COLUMNS)
    return load_retrieval_binned(con)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sort_backbones(flat_df: pd.DataFrame, binned_df: pd.DataFrame) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for bb in BACKBONES:
        if ((not flat_df.empty) and (flat_df["backbone"] == bb).any()) or (
            (not binned_df.empty) and (binned_df["backbone"] == bb).any()
        ):
            ordered.append(bb)
            seen.add(bb)
    extras = set(flat_df.get("backbone", pd.Series(dtype=str)).dropna().tolist())
    extras.update(set(binned_df.get("backbone", pd.Series(dtype=str)).dropna().tolist()))
    ordered.extend(sorted(extras - seen))
    return ordered


def binned_config(row: pd.Series) -> str:
    thresh = row.get("std_thresh")
    t = f"{float(thresh):g}" if pd.notna(thresh) else "—"
    return f"{row.get('bin_mode')}/{t}/{row.get('rep_a')}x{row.get('rep_b')}/{row.get('agg_method')}"


# ---------------------------------------------------------------------------
# Section: Unified Ranking
# ---------------------------------------------------------------------------


def section_unified_table(flat_df: pd.DataFrame, binned_df: pd.DataFrame) -> str:
    frames: list[pd.DataFrame] = []

    if not flat_df.empty:
        flat = flat_df.copy()
        flat["type"] = "flat"
        flat["config"] = flat["strategy"]
        frames.append(
            flat[
                [
                    "backbone",
                    "type",
                    "config",
                    "sim_metric",
                    "k",
                    "disc_artist",
                    "disc_album",
                    "disc_genre",
                    "disc_head",
                    "disc_score",
                    "mean_within",
                    "mean_cross",
                    "map_k",
                    "mrr",
                    "ndcg_k",
                ]
            ]
        )

    if not binned_df.empty:
        binned = binned_df.copy()
        binned["type"] = "binned"
        binned["config"] = binned.apply(binned_config, axis=1)
        frames.append(
            binned[
                [
                    "backbone",
                    "type",
                    "config",
                    "sim_metric",
                    "k",
                    "disc_artist",
                    "disc_album",
                    "disc_genre",
                    "disc_head",
                    "disc_score",
                    "mean_within",
                    "mean_cross",
                    "map_k",
                    "mrr",
                    "ndcg_k",
                ]
            ]
        )

    if not frames:
        return """
<section id="unified-table">
  <h2>Unified Ranking</h2>
  <p class="empty">No retrieval data is available yet.</p>
</section>
"""

    combined = pd.concat(frames, ignore_index=True).sort_values(
        "disc_score", ascending=False, na_position="last"
    )

    chart_html = ""
    if _HAS_MPL:
        backbones = combined["backbone"].dropna().unique().tolist()
        labels, vals, colors = [], [], []
        for bb in sorted(backbones):
            sub = combined[combined["backbone"] == bb]
            best_flat = (
                sub[sub["type"] == "flat"]["disc_score"].max()
                if not sub[sub["type"] == "flat"].empty
                else None
            )
            best_binned = (
                sub[sub["type"] == "binned"]["disc_score"].max()
                if not sub[sub["type"] == "binned"].empty
                else None
            )
            if best_flat is not None:
                labels.append(f"{bb} flat")
                vals.append(float(best_flat))
                colors.append("#7ec8e3")
            if best_binned is not None:
                labels.append(f"{bb} binned")
                vals.append(float(best_binned))
                colors.append("#a78bfa")
        if labels:
            chart_html = bar_chart(
                labels, vals, colors, "Best disc_score — flat vs binned per backbone", "disc_score"
            )

    top20 = combined.head(20).to_dict("records")
    return f"""
<section id="unified-table">
  <h2>Unified Ranking</h2>
  <div class="card">
    <p class="muted">All flat and temporal-binned configurations ranked together by <code>disc_score</code>
    (within-artist similarity minus cross-artist similarity). Columns <code>disc_artist</code>,
    <code>disc_artist</code>, <code>disc_album</code>, <code>disc_genre</code>, and <code>disc_head</code> show the four discrimination axes.
    Blue bars are flat configs; purple are binned.</p>
  </div>
  {chart_html}
  <details style="margin-top:18px">
    <summary>Top-20 table</summary>
    <div class="details-body">{table(top20)}</div>
  </details>
</section>
"""


# ---------------------------------------------------------------------------
# Section: Per-Backbone Comparison
# ---------------------------------------------------------------------------


def section_per_backbone(flat_df: pd.DataFrame, binned_df: pd.DataFrame) -> str:
    backbones = sort_backbones(flat_df, binned_df)
    if not backbones:
        return """
<section id="per-backbone">
  <h2>Per-Backbone Comparison</h2>
  <p class="empty">No backbone comparisons are available yet.</p>
</section>
"""

    TOP_N = 5

    parts = [
        """
<section id="per-backbone">
  <h2>Per-Backbone Comparison</h2>
  <div class="card">
    <p class="muted">
      For each backbone, the top flat configurations are shown alongside the top binned
      configurations (up to 5 each), ranked by <code>disc_score</code>.
      <strong>disc_artist</strong> = within-artist vs cross-artist similarity gap;
      <strong>disc_artist</strong> = within-artist vs cross-artist similarity gap;
      <strong>disc_album</strong> = within-album vs cross-album gap;
      <strong>disc_genre</strong> = within-genre vs cross-genre gap (from audio tags);
      <strong>disc_head</strong> = Spearman &#961; of sim vs head-score distance.
      <strong>mean_within</strong> / <strong>mean_cross</strong> reveal absolute cosine levels
      (collapse = both near 1.0 with tiny gap).
      The <strong>&#916; disc</strong> column for binned rows shows the difference relative to
      the best flat baseline (<em>positive = improvement, negative = regression</em>).
    </p>
  </div>
"""
    ]

    for backbone in backbones:
        flat_rows = (
            flat_df[flat_df["backbone"] == backbone] if not flat_df.empty else empty_df(FLAT_COLUMNS)
        )
        binned_rows = (
            binned_df[binned_df["backbone"] == backbone]
            if not binned_df.empty
            else empty_df(BINNED_COLUMNS)
        )

        best_flat_score = (
            float(
                flat_rows.sort_values("disc_score", ascending=False, na_position="last").iloc[0][
                    "disc_score"
                ]
            )
            if not flat_rows.empty
            else None
        )

        table_rows: list[dict] = []

        for _, r in (
            flat_rows.sort_values("disc_score", ascending=False, na_position="last")
            .head(TOP_N)
            .iterrows()
        ):
            table_rows.append(
                {
                    "type": "flat",
                    "config": r["strategy"],
                    "sim_metric": r["sim_metric"],
                    "k": r["k"],
                    "disc_artist": fmt(r.get("disc_artist", r["disc_score"])),                    "disc_album": fmt(r.get("disc_album", 0.0)),                    "disc_genre": fmt(r.get("disc_genre", 0.0)),
                    "disc_head": fmt(r.get("disc_head", 0.0)),
                    "disc_score": fmt(r["disc_score"]),                    "mean_within": fmt(r.get("mean_within", 0.0)),
                    "mean_cross": fmt(r.get("mean_cross", 0.0)),                    "\u0394 disc": "—",
                    "map_k": fmt(r["map_k"]),
                    "mrr": fmt(r["mrr"]),
                    "ndcg_k": fmt(r["ndcg_k"]),
                }
            )

        for _, r in (
            binned_rows.sort_values("disc_score", ascending=False, na_position="last")
            .head(TOP_N)
            .iterrows()
        ):
            delta = (
                f"{float(r['disc_score']) - best_flat_score:+.4f}"
                if best_flat_score is not None and r["disc_score"] is not None
                else "—"
            )
            table_rows.append(
                {
                    "type": "binned",
                    "config": binned_config(r),
                    "sim_metric": r["sim_metric"],
                    "k": r["k"],
                    "disc_artist": fmt(r.get("disc_artist", r["disc_score"])),                    "disc_album": fmt(r.get("disc_album", 0.0)),                    "disc_genre": fmt(r.get("disc_genre", 0.0)),
                    "disc_head": fmt(r.get("disc_head", 0.0)),
                    "disc_score": fmt(r["disc_score"]),
                    "mean_within": fmt(r.get("mean_within", 0.0)),
                    "mean_cross": fmt(r.get("mean_cross", 0.0)),
                    "\u0394 disc": delta,
                    "map_k": fmt(r["map_k"]),
                    "mrr": fmt(r["mrr"]),
                    "ndcg_k": fmt(r["ndcg_k"]),
                }
            )

        charts_html = ""
        if _HAS_MPL:
            # Scatter: disc_score vs MAP@k
            sx, sy, slabels, scolors = [], [], [], []
            for _, r in flat_rows.iterrows():
                if pd.notna(r["disc_score"]) and pd.notna(r["map_k"]):
                    sx.append(float(r["disc_score"]))
                    sy.append(float(r["map_k"]))
                    slabels.append(str(r["strategy"]))
                    scolors.append("#7ec8e3")
            for _, r in binned_rows.iterrows():
                if pd.notna(r["disc_score"]) and pd.notna(r["map_k"]):
                    sx.append(float(r["disc_score"]))
                    sy.append(float(r["map_k"]))
                    slabels.append(binned_config(r)[:30])
                    scolors.append("#a78bfa")
            if sx:
                charts_html += scatter_chart(
                    sx,
                    sy,
                    slabels,
                    scolors,
                    f"{backbone} — disc_score vs MAP@k",
                    "disc_score",
                    "MAP@k",
                )

            # Δ bar: best binned configs vs flat baseline
            if best_flat_score is not None and not binned_rows.empty:
                top_binned = binned_rows.sort_values(
                    "disc_score", ascending=False, na_position="last"
                ).head(8)
                b_labels = [binned_config(r)[:40] for _, r in top_binned.iterrows()]
                b_vals = [
                    float(r["disc_score"]) - best_flat_score if pd.notna(r["disc_score"]) else 0.0
                    for _, r in top_binned.iterrows()
                ]
                b_colors = ["#4ade80" if v > 0 else "#f87171" for v in b_vals]
                charts_html += bar_chart(
                    b_labels,
                    b_vals,
                    b_colors,
                    f"{backbone} — \u0394 disc_score vs flat baseline",
                    "\u0394 disc_score (positive = improvement)",
                )

        parts.append(
            f"<h3>{backbone}</h3>"
            + (f'<div class="charts-row">{charts_html}</div>' if charts_html else "")
            + f'<details style="margin-top:12px"><summary>Top-{TOP_N} table</summary>'
            + f'<div class="details-body">{table(table_rows)}</div></details>'
        )

    parts.append("</section>")
    return "\n".join(parts)
