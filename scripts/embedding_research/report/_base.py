"""Shared rendering primitives: CSS, formatting helpers, and matplotlib chart builders."""

from __future__ import annotations

import base64
import io

import pandas as pd

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _HAS_MPL = True
except ImportError:
    _HAS_MPL = False


# ---------------------------------------------------------------------------
# Column lists (single source of truth for query / display)
# ---------------------------------------------------------------------------

FLAT_COLUMNS = [
    "backbone",
    "strategy",
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
    "recall_k",
    "recall_k_album",
    "recall_k_genre",
]

BINNED_COLUMNS = [
    "backbone",
    "bin_mode",
    "std_thresh",
    "rep_a",
    "rep_b",
    "sim_metric",
    "agg_method",
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
    "recall_k",
    "recall_k_album",
    "recall_k_genre",
]

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: #0f1117;
  color: #e0e0e8;
  display: flex;
  min-height: 100vh;
}
nav {
  position: fixed;
  top: 0;
  left: 0;
  width: 220px;
  height: 100vh;
  background: #1a1b26;
  border-right: 1px solid #2a2b3d;
  overflow-y: auto;
  padding: 24px 0;
  z-index: 100;
}
nav h3 {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #666;
  padding: 0 16px 12px;
}
nav a {
  display: block;
  padding: 7px 16px;
  color: #9090b0;
  text-decoration: none;
  font-size: 13px;
  border-left: 3px solid transparent;
  transition: all 0.15s;
}
nav a:hover {
  color: #c0c0e0;
  background: #22233a;
  border-left-color: #5c6bc0;
}
main {
  margin-left: 220px;
  padding: 40px 48px;
  max-width: 1200px;
  width: 100%;
}
h1 {
  font-size: 28px;
  font-weight: 700;
  color: #fff;
  margin-bottom: 6px;
}
.subtitle {
  color: #666;
  font-size: 14px;
  margin-bottom: 18px;
}
.lead {
  color: #aab4d4;
  font-size: 14px;
  line-height: 1.65;
  margin-bottom: 48px;
  max-width: 920px;
}
section {
  margin-bottom: 64px;
  padding-top: 16px;
}
section h2 {
  font-size: 20px;
  font-weight: 600;
  color: #c0c8ff;
  border-bottom: 1px solid #2a2b3d;
  padding-bottom: 10px;
  margin-bottom: 20px;
}
section h3 {
  font-size: 15px;
  font-weight: 600;
  color: #a0a8d0;
  margin: 20px 0 10px;
}
section h4 {
  font-size: 13px;
  color: #8090a8;
  margin: 14px 0 6px;
}
p {
  line-height: 1.65;
}
.muted {
  color: #8f96b6;
}
.card {
  background: #1a1b26;
  border: 1px solid #2a2b3d;
  border-radius: 8px;
  padding: 16px 20px;
  margin-bottom: 20px;
}
.grid {
  display: grid;
  gap: 18px;
}
details {
  background: #1a1b26;
  border: 1px solid #2a2b3d;
  border-radius: 8px;
  margin-bottom: 14px;
  overflow: hidden;
}
summary {
  cursor: pointer;
  list-style: none;
  padding: 14px 18px;
  font-weight: 600;
  color: #d0d8ff;
  background: #171824;
}
summary::-webkit-details-marker {
  display: none;
}
details[open] summary {
  border-bottom: 1px solid #2a2b3d;
}
.details-body {
  padding: 16px 18px 18px;
}
img {
  width: 100%;
  max-width: 760px;
  height: auto;
  display: block;
  border-radius: 6px;
  border: 1px solid #2a2b3d;
  background: #12131e;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  margin-top: 8px;
}
thead {
  background: #12131e;
}
th {
  text-align: left;
  padding: 9px 12px;
  color: #8090a8;
  font-weight: 600;
  border-bottom: 2px solid #2a2b3d;
}
td {
  padding: 8px 12px;
  border-bottom: 1px solid #1e1f2e;
  color: #c0c8d8;
  vertical-align: top;
}
tr:hover td {
  background: #1a1b26;
}
code {
  background: #12131e;
  border: 1px solid #2a2b3d;
  border-radius: 3px;
  padding: 1px 5px;
  font-size: 12px;
  color: #7ec8e3;
}
.empty {
  color: #b7bdd6;
  font-style: italic;
}
@media (max-width: 1000px) {
  body {
    display: block;
  }
  nav {
    position: static;
    width: 100%;
    height: auto;
    border-right: 0;
    border-bottom: 1px solid #2a2b3d;
  }
  main {
    margin-left: 0;
    padding: 24px 20px 40px;
  }
}
"""

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def empty_df(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def fmt(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def table(rows: list[dict]) -> str:
    if not rows:
        return '<p class="empty"><em>No data.</em></p>'
    headers = list(rows[0].keys())
    head_html = "".join(f"<th>{h}</th>" for h in headers)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{fmt(row.get(h))}</td>" for h in headers) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{head_html}</tr></thead><tbody>{body_html}</tbody></table>"


def table_exists(con, name: str) -> bool:
    try:
        rows = con.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ? LIMIT 1", [name]
        ).fetchall()
        return len(rows) > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Chart helpers (require matplotlib)
# ---------------------------------------------------------------------------


def png(fig) -> str:
    """Encode a matplotlib figure as a data-URI PNG and close it."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=96, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return f'<img src="data:image/png;base64,{base64.b64encode(buf.read()).decode()}" />'


def bar_chart(labels: list[str], values: list[float], colors: list[str], title: str, xlabel: str) -> str:
    fig, ax = plt.subplots(figsize=(max(5, len(labels) * 0.7), 3.5))
    bars = ax.barh(labels, values, color=colors)
    ax.axvline(0, color="#555", linewidth=0.8)
    val_range = max(values) - min(values) if values else 1.0
    for bar, v in zip(bars, values):
        ax.text(
            v + val_range * 0.01 if v >= 0 else v - val_range * 0.01,
            bar.get_y() + bar.get_height() / 2,
            f"{v:.4f}",
            va="center",
            ha="left" if v >= 0 else "right",
            fontsize=8,
            color="#ccc",
        )
    ax.set_title(title, color="#e0e0e8", fontsize=11)
    ax.set_xlabel(xlabel, color="#999")
    ax.tick_params(colors="#aaa", labelsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    for sp in ax.spines.values():
        sp.set_color("#333")
    ax.set_facecolor("#12131e")
    fig.patch.set_facecolor("#1a1b26")
    fig.tight_layout()
    return png(fig)


def scatter_chart(
    x: list[float],
    y: list[float],
    labels: list[str],
    colors: list[str],
    title: str,
    xlabel: str,
    ylabel: str,
) -> str:
    fig, ax = plt.subplots(figsize=(5.5, 4))
    for xi, yi, lbl, c in zip(x, y, labels, colors):
        ax.scatter(xi, yi, color=c, s=60, zorder=3)
        ax.annotate(lbl, (xi, yi), fontsize=7, color="#aaa", xytext=(4, 3), textcoords="offset points")
    ax.set_title(title, color="#e0e0e8", fontsize=11)
    ax.set_xlabel(xlabel, color="#999")
    ax.set_ylabel(ylabel, color="#999")
    ax.tick_params(colors="#aaa", labelsize=8)
    ax.grid(True, alpha=0.15, color="#555")
    ax.spines[["top", "right"]].set_visible(False)
    for sp in ax.spines.values():
        sp.set_color("#333")
    ax.set_facecolor("#12131e")
    fig.patch.set_facecolor("#1a1b26")
    fig.tight_layout()
    return png(fig)
