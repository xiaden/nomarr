"""Shared rendering primitives: formatting helpers and Plotly chart/table/section builders.

Research-only.  This module owns the pure rendering surface shared by every report
section plus the single source of truth for the active catalog identity vocabulary
(the ``catalog:{backbone}:{score_variant}:v{version}:{keyset}`` decode).  It carries NO
legacy strategy/head/bin/weighted vocabulary.
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


# ---------------------------------------------------------------------------
# Catalog identity vocabulary
# ---------------------------------------------------------------------------

#: strategy_type written by the catalog analyze pipeline for every active analysis row.
CATALOG_STRATEGY_TYPE = "catalog"

#: The enriched long-form columns produced by ``report._retrieval.query_analyze_metrics``.
#: Every row is one literal ``analyze_metrics`` (strategy_key, sim_metric, k, metric, value)
#: cell for a ``strategy_type == 'catalog'`` class, enriched with the decoded active
#: identity + provenance scope fields (canonical_config_id / alias_ids / view_content_hash).
CATALOG_ANALYSIS_COLUMNS: list[str] = [
    "run_id",
    "backbone",
    "strategy_key",
    "strategy_type",
    "sim_metric",
    "k",
    "score_variant",
    "scoring_semantics_version",
    "representation_hash",
    "canonical_config_id",
    "alias_ids",
    "view_content_hash",
    "metric",
    "value",
]


def decode_catalog_strategy_key(strategy_key: str) -> dict[str, Any] | None:
    """Decode an active ``catalog:{backbone}:{score_variant}:v{version}:{keyset}`` identity.

    Returns a dict with ``backbone``, ``score_variant``, ``scoring_semantics_version`` and
    ``keyset_hash`` (the trailing 16-hex search-representation marker), or ``None`` when the
    key is not a well-formed catalog identity.  The scoring-semantics version is parsed from
    the ``v<version>`` segment; a malformed segment yields ``None`` (never a silent 0).
    """
    if not isinstance(strategy_key, str) or not strategy_key.startswith("catalog:"):
        return None
    parts = strategy_key.split(":")
    if len(parts) != 5 or not parts[1] or not parts[2]:
        return None
    version_seg = parts[3]
    if not version_seg.startswith("v") or not version_seg[1:].isdigit():
        return None
    if not parts[4]:
        return None
    return {
        "backbone": parts[1],
        "score_variant": parts[2],
        "scoring_semantics_version": int(version_seg[1:]),
        "keyset_hash": parts[4],
    }


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


def _alias_text(alias_ids) -> str:
    """Render an ordered alias list as a compact comma-joined string ('—' when empty)."""
    if not alias_ids:
        return "—"
    return ",".join(str(a) for a in alias_ids)


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
