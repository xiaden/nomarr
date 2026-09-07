"""Active catalog summary section.

Research-only.  Per-backbone status of the active catalog results, derived from the decoded
catalog analysis frame and its deterministic winner/delta rows.  Renders an explicit
empty-active-results message when no active catalog rows exist.
"""

from __future__ import annotations

from collections import Counter

import pandas as pd

from ._base import make_section, make_table
from ._winners import build_winner_delta_rows


def _summary_rows(analysis_df: pd.DataFrame) -> list[dict]:
    winner_df = build_winner_delta_rows(analysis_df)
    backbones = sorted({str(b) for b in analysis_df["backbone"].dropna().tolist()})
    rows: list[dict] = []
    for bb in backbones:
        bb_a = analysis_df[analysis_df["backbone"] == bb]
        # active_catalog_classes / distinct_k count catalog classes only — an observed
        # ``global_pool:{bb}:medoid`` baseline row is a baseline, not a class.
        bb_catalog = bb_a[bb_a["strategy_key"].astype(str).str.startswith("catalog:")]
        classes = sorted({str(s) for s in bb_catalog["strategy_key"].dropna().tolist()})
        ks = sorted({int(k) for k in bb_catalog["k"].dropna().tolist()})
        cells = winner_df[winner_df["backbone"] == bb] if not winner_df.empty else pd.DataFrame()
        n_cells = len(cells)
        positive = 0
        best_delta = None
        delta_owners: dict[float, list[str]] = {}
        win_counts: Counter = Counter()
        if n_cells:
            for _, c in cells.iterrows():
                d = c["delta"]
                owner = c["winner_strategy_key"]
                win_counts[str(owner)] += 1
                if d > 0:
                    positive += 1
                if best_delta is None or d > best_delta:
                    best_delta = d
                    delta_owners = {d: [str(owner)]}
                elif d == best_delta:
                    delta_owners.setdefault(d, []).append(str(owner))
        most_cells_winner = min(win_counts, key=lambda k: (-win_counts[k], k)) if win_counts else None
        # Incomplete / non-comparable representations for this backbone (never a matched winner).
        incomplete_bb = [e for e in winner_df.attrs.get("baseline_incomplete", ()) if str(e.get("backbone")) == bb]
        rows.append(
            {
                "backbone": bb,
                "active_catalog_classes": len(classes),
                "distinct_k": len(ks),
                "evaluation_cells": n_cells,
                "positive_delta_cells": positive,
                "best_delta": best_delta if best_delta is not None else None,
                "most_cells_winner": most_cells_winner,
                "most_cells_won": win_counts.get(most_cells_winner, 0) if most_cells_winner else 0,
                "incomplete_representations": len(incomplete_bb),
            }
        )
    return rows


def section_summary(analysis_df: pd.DataFrame) -> dict:
    """Render the per-backbone active catalog status summary section."""
    if analysis_df is None or analysis_df.empty or "backbone" not in analysis_df.columns:
        return make_section(
            "summary",
            "Catalog Result Status",
            empty_message="No active catalog analysis results. Run the analyze phase.",
        )

    table_rows = _summary_rows(analysis_df)
    if not table_rows:
        return make_section(
            "summary",
            "Catalog Result Status",
            empty_message="No active catalog analysis results. Run the analyze phase.",
        )

    return make_section(
        "summary",
        "Catalog Result Status",
        description=(
            "Per-backbone status of the active catalog analysis.  Each backbone is an "
            "independent population (EffNet / MusicNN never cross-averaged).  "
            "evaluation_cells counts the (k x metric) cells with a finite observed-medoid baseline "
            "and a finite winner (cells without a run-scoped medoid baseline are absent, not zero); "
            "positive_delta_cells counts cells where the winner beats the observed "
            "global-medoid baseline (global_pool:{backbone}:medoid) over the same "
            "corpus / sim_metric / k / metric.  incomplete_representations counts the partial / "
            "non-comparable / unequal representations for the backbone that were excluded from "
            "matched deltas (surfaced per-cell in the winners section).  See the winners section "
            "for the full per-cell baseline/winner/delta tables."
        ),
        stats=[{"label": "backbones", "value": len(table_rows)}],
        tables=[
            make_table(
                table_rows,
                id="catalog_result_status",
                title="Active catalog result status per backbone",
            )
        ],
    )
