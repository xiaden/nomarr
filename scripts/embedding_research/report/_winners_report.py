"""Geometry winners report section.

Renders class-scoped neighborhood evidence and the observed global-medoid baseline as two
distinct tables.  A refused/empty scope renders an explicit refusal instead of a
successful empty winners section.
"""

from __future__ import annotations

from typing import Any

from ._base import make_section, make_table
from ._winners import baseline_neighborhood_rows, class_neighborhood_rows


def section_winners(frames: Any = None) -> dict:
    """Render class-scoped neighborhoods and the single baseline neighborhood set separately."""
    tables: list[dict] = []
    winner_rows = class_neighborhood_rows(frames)
    baseline_rows = baseline_neighborhood_rows(frames)
    if winner_rows:
        tables.append(
            make_table(
                winner_rows,
                id="geometry_representations",
                title="Class-scoped geometry neighborhood evidence",
            )
        )
    if baseline_rows:
        tables.append(
            make_table(
                baseline_rows,
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
            "Class-scoped neighborhood evidence, with the single threshold-independent observed "
            "global-medoid baseline rendered separately. The baseline is never a winner candidate."
        ),
        tables=tables,
    )
