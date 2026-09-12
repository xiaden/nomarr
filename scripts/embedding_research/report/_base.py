"""Shared rendering primitives: formatting helpers and Plotly chart/table/section builders.

Research-only.  This module owns the pure rendering surface shared by every report
    section plus shared geometry identity formatting helpers. It carries no earlier
    strategy/head/bin/weighted vocabulary.
"""

from __future__ import annotations

import json as _json
from typing import TYPE_CHECKING, Any, cast

import pandas as pd

if TYPE_CHECKING:
    import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Plotly theme constants
# ---------------------------------------------------------------------------

_PLOT_BG = "#12131e"
_PAPER_BG = "#1a1b26"
_GRID_COLOR = "#555"
_FONT_COLOR = "#e0e0e8"
_H_SMALL = 320
_H_MED = 420
_H_LARGE = 560


# ---------------------------------------------------------------------------
# Plotly helpers
# ---------------------------------------------------------------------------


def apply_dark_theme(fig: go.Figure, *, grid: bool = True) -> None:
    """Apply standard dark-theme styling to a Plotly figure in-place."""
    axis_style: dict = {
        "showgrid": grid,
        "gridcolor": _GRID_COLOR,
        "gridwidth": 0.5,
        "linecolor": "#333",
        "tickfont": {"color": _FONT_COLOR, "size": 8},
        "zerolinecolor": "#333",
    }
    fig.update_layout(
        plot_bgcolor=_PLOT_BG,
        paper_bgcolor=_PAPER_BG,
        font={"color": _FONT_COLOR, "size": 10},
        xaxis=axis_style,
        yaxis=axis_style,
        margin={"l": 48, "r": 16, "t": 36, "b": 36},
    )


def figure_dict(fig: go.Figure) -> dict:
    """Return a Plotly figure as a JSON-serialisable dict.

    Uses ``fig.to_json()`` then ``json.loads`` to ensure all numpy types are
    converted to plain Python scalars before the dict is embedded in the payload.
    """
    return cast("dict[str, Any]", _json.loads(fig.to_json()))


def make_chart(fig: go.Figure, *, id: str = "", title: str = "") -> dict:
    """Build a chart descriptor dict from a Plotly figure."""
    return {"id": id, "title": title, "type": "plotly", "figure": figure_dict(fig)}


def empty_df(columns: list[str]) -> pd.DataFrame:
    """Return an empty DataFrame with the given columns."""
    return pd.DataFrame(columns=columns)


# ---------------------------------------------------------------------------
# Data formatting helpers
# ---------------------------------------------------------------------------


def fmt(v) -> str:
    """Format a value for table display: '—' for None/NaN, 4 d.p. for floats, str otherwise."""
    if v is None:
        return "—"
    if isinstance(v, float):
        if pd.isna(v):
            return "—"
        return f"{v:.4f}"
    return str(v)


def table_exists(con, name: str) -> bool:
    """Return True if a table named *name* exists in the DuckDB connection."""
    try:
        rows = con.execute("SELECT 1 FROM information_schema.tables WHERE table_name = ? LIMIT 1", [name]).fetchall()
        return len(rows) > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Section / table / panel builders
# ---------------------------------------------------------------------------


def make_table(
    rows: list[dict],
    *,
    id: str = "",
    title: str = "",
    collapsible: bool = False,
    summary_text: str = "",
    open: bool = False,
) -> dict:
    """Build a table descriptor dict from a list of row dicts.

    Each row dict must have the same keys; values are formatted with :func:`fmt`.
    """
    if not rows:
        return {
            "id": id,
            "title": title,
            "columns": [],
            "rows": [],
            "collapsible": collapsible,
            "summary_text": summary_text,
            "open": open,
            "empty": True,
        }
    columns = list(rows[0].keys())
    data_rows = [[fmt(row.get(c)) for c in columns] for row in rows]
    return {
        "id": id,
        "title": title,
        "columns": columns,
        "rows": data_rows,
        "collapsible": collapsible,
        "summary_text": summary_text,
        "open": open,
        "empty": False,
    }


def make_panel(
    id: str,
    title: str,
    *,
    open: bool = False,
    charts: list[dict] | None = None,
    tables: list[dict] | None = None,
    text: str = "",
    subsections: list[dict] | None = None,
) -> dict:
    """Build a collapsible panel descriptor dict."""
    return {
        "id": id,
        "title": title,
        "open": open,
        "charts": charts or [],
        "tables": tables or [],
        "text": text,
        "subsections": subsections or [],
    }


def make_section(
    id: str,
    title: str,
    *,
    description: str = "",
    stats: list[dict] | None = None,
    charts: list[dict] | None = None,
    tables: list[dict] | None = None,
    panels: list[dict] | None = None,
    subsections: list[dict] | None = None,
    warnings: list[dict] | None = None,
    headline: dict | None = None,
    empty_message: str = "",
) -> dict:
    """Build a section descriptor dict suitable for the schema v2 payload."""
    return {
        "id": id,
        "title": title,
        "description": description,
        "stats": stats or [],
        "charts": charts or [],
        "tables": tables or [],
        "panels": panels or [],
        "subsections": subsections or [],
        "warnings": warnings or [],
        "headline": headline,
        "empty_message": empty_message,
    }
