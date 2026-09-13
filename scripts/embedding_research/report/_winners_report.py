"""Geometry winners report section.

Renders winner representation evidence and the observed global-medoid baseline as two
distinct tables.  A refused/empty scope renders an explicit refusal instead of a
successful empty winners section.
"""

from __future__ import annotations

import pandas as pd

from ._base import make_section, make_table
from ._winners import baseline_rows, winner_rows


def section_winners(
    winners_df: pd.DataFrame | None,
    baseline_df: pd.DataFrame | None = None,
    *,
    corpus_evidence: dict | None = None,
) -> dict:
    """Render canonical winner and global-medoid baseline neighborhoods separately."""
    if corpus_evidence is not None:
        queries = corpus_evidence.get("queries") or []
        winners = pd.DataFrame(
            [
                {"query_song_id": q.get("song_id"), **entry}
                for q in queries
                if isinstance(q, dict)
                for entry in q.get("neighborhood") or []
            ]
        )
        baselines = pd.DataFrame(
            [
                {"query_song_id": q.get("song_id"), **entry}
                for q in queries
                if isinstance(q, dict)
                for entry in q.get("baseline_neighborhood") or []
            ]
        )
    else:
        winners = winner_rows(winners_df)
        baselines = baseline_rows(baseline_df)
    tables: list[dict] = []
    if not winners.empty:
        tables.append(
            make_table(
                winners.to_dict("records"),
                id="geometry_representations",
                title="Geometry winner representation evidence",
            )
        )
    if not baselines.empty:
        tables.append(
            make_table(
                baselines.to_dict("records"),
                id="observed_global_medoid_baseline",
                title="Observed global-medoid baseline (separate from winners)",
            )
        )
    if not tables:
        return make_section(
            "winners",
            "Geometry Winners & Observed Baseline",
            warnings=[{"level": "error", "message": "No winner or observed-baseline evidence; winners refused."}],
            empty_message="REFUSED: no geometry winner or observed-baseline evidence.",
        )
    return make_section(
        "winners",
        "Geometry Winners & Observed Baseline",
        description=(
            "Winner threshold representation evidence, with the mandatory observed global-medoid "
            "baseline rendered separately. The baseline is never a winner candidate."
        ),
        tables=tables,
    )
