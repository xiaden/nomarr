"""Geometry winners report section.

Renders class-scoped neighborhood evidence and the observed global-medoid baseline as two
distinct tables.  A refused/empty scope renders an explicit refusal instead of a
successful empty winners section.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ._base import make_section, make_table


def section_winners(result: Any = None) -> dict:
    """Render class-scoped neighborhoods and the baseline neighborhoods separately."""
    tables: list[dict] = []
    if result is not None:
        winner_rows = [asdict(row) for row in result.class_neighborhoods]
        baseline_rows = [asdict(row) for row in result.baseline_neighborhoods]
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
