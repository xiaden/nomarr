"""Geometry head-analysis report section.

Renders the exact complete head identity evidence persisted for the run, or an explicit
refusal.  Only the exact geometry/observation/threshold/evaluation/scoring/execution
identities are read; no other scope resolution or inferred lineage is consulted.
"""

from __future__ import annotations

from scripts.embedding_research.db.identity_persistence import IdentityRefusal, read_head_evidence_for_run

from ._base import make_section, make_table

_HEAD_IDENTITY_COLUMNS = (
    "geometry_id",
    "observation_id",
    "geometry_semantics_version",
    "numerical_profile_digest",
    "threshold_id",
    "structural_identity",
    "search_representation_id",
    "evaluation_id",
    "scoring_semantics_version",
    "execution_id",
)


def section_head_analysis(con, *, run_id: str | None = None):
    """Render exact head identity evidence, or a visible refusal section when incomplete."""
    rows: list[dict] = []
    if run_id:
        try:
            rows = list(read_head_evidence_for_run(con, run_id=run_id))
        except IdentityRefusal:
            rows = []
    if not rows:
        return make_section(
            "head-analysis",
            "Head Analysis",
            warnings=[{"level": "error", "message": "Head identity evidence unavailable; head analysis refused."}],
            empty_message="REFUSED: no exact head identity evidence.",
        )
    missing = [column for column in _HEAD_IDENTITY_COLUMNS if any(not row.get(column) for row in rows)]
    if missing:
        return make_section(
            "head-analysis",
            "Head Analysis",
            warnings=[{"level": "error", "message": f"Head identity evidence incomplete: {', '.join(missing)}"}],
            empty_message="REFUSED: incomplete head identity evidence.",
        )
    return make_section(
        "head-analysis",
        "Head Analysis",
        tables=[make_table(rows, id="geometry_head_identity", title="Exact head identity evidence")],
    )
