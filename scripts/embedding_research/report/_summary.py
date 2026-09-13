"""Geometry analysis summary section (exact run-scoped evidence)."""

from __future__ import annotations

import pandas as pd

from ._base import make_section, make_table


def _group_counts(frame: pd.DataFrame, key: str) -> list[dict]:
    rows: list[dict] = []
    for value, group in frame.groupby(key, sort=True, dropna=False):
        rows.append(
            {
                key: str(value),
                "metric_cells": len(group),
                "finite_cells": int(group["value"].notna().sum()),
            }
        )
    return rows


def section_summary(
    analysis_df: pd.DataFrame,
    baseline_df: pd.DataFrame | None = None,
    *,
    corpus_evidence: dict | None = None,
) -> dict:
    """Summarize canonical winner hypotheses and the observed baseline separately."""
    if corpus_evidence is not None:
        queries = corpus_evidence.get("queries") or []
        analysis_df = pd.DataFrame(
            [entry for q in queries if isinstance(q, dict) for entry in q.get("neighborhood") or []]
        )
        baseline_df = pd.DataFrame(
            [entry for q in queries if isinstance(q, dict) for entry in q.get("baseline_neighborhood") or []]
        )
    has_analysis = analysis_df is not None and not analysis_df.empty
    has_baseline = baseline_df is not None and not baseline_df.empty
    if not has_analysis and not has_baseline:
        return make_section(
            "summary",
            "Geometry Result Status",
            warnings=[{"level": "error", "message": "No exact geometry analysis evidence; summary refused."}],
            empty_message="REFUSED: no exact geometry analysis or observed-baseline evidence.",
        )

    stats: list[dict] = []
    tables: list[dict] = []
    if has_analysis:
        stats.extend(
            [
                {"label": "analysis rows", "value": len(analysis_df)},
                {
                    "label": "geometry ids",
                    "value": int(analysis_df["geometry_id"].nunique()) if "geometry_id" in analysis_df else 0,
                },
                {
                    "label": "thresholds",
                    "value": int(analysis_df["threshold_id"].nunique()) if "threshold_id" in analysis_df else 0,
                },
                {"label": "metrics", "value": int(analysis_df["metric"].nunique()) if "metric" in analysis_df else 0},
                {
                    "label": "finite values",
                    "value": int(analysis_df["value"].notna().sum()) if "value" in analysis_df else 0,
                },
            ]
        )
        tables.append(
            make_table(
                _group_counts(analysis_df, "threshold_id"),
                id="geometry_threshold_summary",
                title="Winner threshold evidence summary",
            )
        )
    if has_baseline:
        stats.append({"label": "baseline rows", "value": len(baseline_df)})
        tables.append(
            make_table(
                _group_counts(baseline_df, "threshold_id"),
                id="observed_baseline_summary",
                title="Observed global-medoid baseline summary",
            )
        )

    return make_section(
        "summary",
        "Geometry Result Status",
        description=(
            "Exact run-scoped geometry evidence only. Winner threshold rows and the mandatory "
            "observed global-medoid baseline are counted separately; the baseline is never a winner."
        ),
        stats=stats,
        tables=tables,
    )
