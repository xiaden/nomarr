"""Active catalog winners & factors report section.

Research-only.  Renders the deterministic catalog winner/delta and factor rosters
(computed by ``_winners.py``) as per-backbone subsections of the ``winners`` schema-v2
section.  Populations are per-backbone and never cross-averaged.
"""

from __future__ import annotations

import pandas as pd

from ._base import make_section, make_table
from ._winners import build_factor_rows, build_winner_delta_rows


def _cell_rows(winner_df: pd.DataFrame, backbone: str) -> list[dict]:
    sub = winner_df[winner_df["backbone"] == backbone]
    rows: list[dict] = []
    for _, r in sub.iterrows():
        rows.append(
            {
                "sim_metric": r["sim_metric"],
                "k": int(r["k"]),
                "metric": r["metric"],
                "n_classes": int(r["n_classes"]),
                "baseline_strategy_key": r["baseline_strategy_key"],
                "baseline_canonical_config_id": _maybe_int(r.get("baseline_canonical_config_id")),
                "baseline_value": float(r["baseline_value"]),
                "winner_strategy_key": r["winner_strategy_key"],
                "winner_canonical_config_id": _maybe_int(r.get("winner_canonical_config_id")),
                "winner_alias_ids": _alias_text(r.get("winner_alias_ids")),
                "winner_value": float(r["winner_value"]),
                "delta": float(r["delta"]),
            }
        )
    return rows


def _factor_rows(factor_df: pd.DataFrame, backbone: str) -> list[dict]:
    sub = factor_df[factor_df["backbone"] == backbone]
    rows: list[dict] = []
    for _, r in sub.iterrows():
        rows.append(
            {
                "score_variant": r["score_variant"],
                "scoring_semantics_version": int(r["scoring_semantics_version"]),
                "strategy_key": r["strategy_key"],
                "sim_metric": r["sim_metric"],
                "k": int(r["k"]),
                "canonical_config_id": _maybe_int(r.get("canonical_config_id")),
                "alias_ids": _alias_text(r.get("alias_ids")),
                "representation_hash": r["representation_hash"],
            }
        )
    return rows


def _alias_text(v) -> str:
    if not v:
        return "—"
    return ",".join(str(a) for a in v)


def _maybe_int(v):
    if v is None or pd.isna(v):
        return None
    return int(v)


def section_winners(analysis_df: pd.DataFrame) -> dict:
    """Render deterministic catalog winner/delta and factor tables per backbone."""
    if analysis_df is None or analysis_df.empty:
        return make_section(
            "winners",
            "Catalog Winners & Deltas",
            empty_message="No active catalog analysis results. Run the analyze phase.",
        )

    winner_df = build_winner_delta_rows(analysis_df)
    factor_df = build_factor_rows(analysis_df)
    backbones = sorted({str(b) for b in analysis_df["backbone"].dropna().tolist()})
    subsections: list[dict] = []
    for backbone in backbones:
        cells = _cell_rows(winner_df, backbone)
        factors = _factor_rows(factor_df, backbone)
        tables = []
        if cells:
            tables.append(
                make_table(
                    cells,
                    id=f"winner_delta_{backbone}",
                    title=f"Exact winners, deltas & baselines ({backbone})",
                    summary_text=f"{len(cells)} winner cell(s)",
                )
            )
        if factors:
            tables.append(
                make_table(
                    factors,
                    id=f"factor_classes_{backbone}",
                    title=f"Active catalog class factors ({backbone})",
                    summary_text=f"{len(factors)} factor row(s)",
                    open=False,
                )
            )
        if not tables:
            continue
        subsections.append(
            {
                "id": f"winners-{backbone}",
                "title": str(backbone),
                "description": "",
                "stats": [{"label": "winner cells", "value": len(cells)}],
                "charts": [],
                "tables": tables,
                "panels": [],
                "subsections": [],
                "warnings": [],
                "headline": None,
                "empty_message": "",
            }
        )

    if not subsections:
        return make_section(
            "winners",
            "Catalog Winners & Deltas",
            empty_message="No finite winner cells across the active catalog results.",
        )

    return make_section(
        "winners",
        "Catalog Winners & Deltas",
        description=(
            "Deterministic per-(sim_metric, k, metric) winner/delta tables and per-class "
            "factor rosters, rendered separately for each backbone.  baseline = the active "
            "class with the lowest (canonical_config_id, strategy_key); winner = the highest "
            "finite value with strategy_key tie-break; delta = winner - baseline.  Equal "
            "representations were collapsed to one class by the analyze pipeline, so alias "
            "lists never create duplicate score rows."
        ),
        subsections=subsections,
    )
