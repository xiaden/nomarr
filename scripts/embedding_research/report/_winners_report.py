"""Render the exact winner/delta and factor-summary rows as schema-v2 sections.

Phase 3 (Plan D) of the embedding-research repair: surface the auditable
benchmark grid computed by ``_winners.py`` in the generated report.  This module
wraps the pure row builders into schema-v2 ``section`` dicts so every backbone
gets its own exact winners-vs-medoid table and its own factor-summary table.

It consumes the *decoded* ``analyze_metrics`` pivot DataFrame (the output of
``_retrieval.query_analyze_metrics``), exactly like the other retrieval sections.

Research-only.  No production code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd

from ._base import make_section, make_table
from ._winners import (
    FACTOR_SUMMARY_COLUMNS,
    WINNER_DELTA_COLUMNS,
    build_factor_summary,
    build_winner_delta_rows,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


def _k_values(df: pd.DataFrame) -> Iterable[int] | None:
    """The K set actually present in the decoded rows, or None when absent."""
    if "k" not in df.columns or df["k"].dropna().empty:
        return None
    return sorted({int(v) for v in df["k"].dropna().tolist()})


def _corpus_identity(
    manifest: Any | None,
) -> tuple[str | None, int | None]:
    """Extract (corpus_hash, corpus_size) from a per-backbone matching-corpus manifest."""
    if manifest is None:
        return None, None
    return getattr(manifest, "corpus_hash", None), len(manifest)


def section_winners(
    df: pd.DataFrame,
    corpus_by_backbone: Mapping[str, Any] | None = None,
) -> dict:
    """Exact group x metric x K winners, deltas, and factor summaries.

    Builds one winner-delta table and one factor-summary table per backbone using
    the Phase 2 row builders, with the explicit ``global_pool:{backbone}:medoid``
    baseline policy.  ``corpus_by_backbone`` optionally maps backbone to its
    :class:`~scripts.embedding_research.corpus.MatchingCorpusManifest` so each
    winner-delta row carries the real corpus hash and corpus size for that
    backbone.  Returns a schema-v2 section whose subsections are separated by
    backbone.
    """
    if df is None or df.empty or "backbone" not in df.columns or "strategy_type" not in df.columns:
        return make_section(
            "winners",
            "Exact Winners & Deltas",
            empty_message="No retrieval data yet. Run the eval phase first.",
        )

    baseline_rows = df[df["strategy_type"] == "global_pool"]
    winners_by_backbone: list[pd.DataFrame] = []
    for backbone in sorted({str(b) for b in df["backbone"].dropna().tolist()}):
        bb_df = df[df["backbone"] == backbone]
        bb_baseline = (
            baseline_rows[baseline_rows["backbone"] == backbone]
            if "backbone" in baseline_rows.columns
            else baseline_rows
        )
        corpus_hash, corpus_size = _corpus_identity((corpus_by_backbone or {}).get(backbone))
        rows = build_winner_delta_rows(
            bb_df,
            bb_baseline,
            k_values=_k_values(bb_df),
            corpus_hash=corpus_hash,
            corpus_size=corpus_size,
        )
        if not rows.empty:
            winners_by_backbone.append(rows)

    if not winners_by_backbone:
        return make_section(
            "winners",
            "Exact Winners & Deltas",
            empty_message=(
                "No winner-delta rows could be computed. An explicit "
                "global_pool:{backbone}:medoid baseline row is required for each backbone."
            ),
        )

    winner_rows = pd.concat(winners_by_backbone, ignore_index=True)

    factor_summary = build_factor_summary(winner_rows)

    subsections: list[dict] = []
    for backbone in sorted({str(b) for b in winner_rows["backbone"].dropna().tolist()}):
        w = winner_rows[winner_rows["backbone"] == backbone]
        f = factor_summary[factor_summary["backbone"] == backbone] if not factor_summary.empty else pd.DataFrame()

        tables = [
            make_table(
                w.to_dict("records"),
                id=f"winner_delta_{backbone}",
                title="Winners & deltas vs global_pool:{backbone}:medoid",
            )
        ]
        if not f.empty:
            tables.append(
                make_table(
                    f.to_dict("records"),
                    id=f"factor_summary_{backbone}",
                    title="Factor summary",
                )
            )

        subsections.append(
            {
                "id": f"winners-{backbone}",
                "title": str(backbone),
                "description": "",
                "stats": [],
                "charts": [],
                "tables": tables,
                "panels": [],
                "subsections": [],
                "warnings": [],
                "headline": None,
                "empty_message": "",
            }
        )

    return make_section(
        "winners",
        "Exact Winners & Deltas",
        description=(
            "For every backbone x retrieval group x metric family x K, the deterministic "
            "winner (strategy key, type, value) and its delta against the explicit "
            "global_pool:{backbone}:medoid baseline for the *same* backbone x group x "
            "metric x K. No averaging across groups, metrics, K, backbones, or hidden "
            "configurations. delta = winner_value - medoid_baseline_value, so a negative "
            "delta means the best configuration is worse than the medoid reference. "
            "Factor summaries group wins by each configuration factor (strategy type, "
            "flat strategy, pathway, head, bin mode, threshold, rep_a, rep_b, aggregate, "
            "similarity metric) while retaining group x metric x K and the contributing "
            "strategy keys. Temporal weighting (the weighted directional reductions "
            "target-wtd / bidir-wtd / norm-pair-wtd) is distinct from representation "
            "choice (rep_a / rep_b, e.g. medoid vs median)."
        ),
        subsections=subsections,
    )


__all__ = ["FACTOR_SUMMARY_COLUMNS", "WINNER_DELTA_COLUMNS", "section_winners"]
