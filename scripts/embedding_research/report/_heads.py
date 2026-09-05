"""Active head-analysis section builder.

Research-only.  Reads ONLY the canonical ``head_phase_provenance`` rows (via
``db.head_phase.load_head_phase_provenance``) and renders them as the ``head-analysis``
section.  There are no dead-table readers and no retired-boundary prose: the canonical rows
already carry the active ``boundary_source='catalog'`` /
``head_pool_variant='shared_catalog_boundary'`` labels written by the head-analysis phase.
"""

from __future__ import annotations

from scripts.embedding_research.db.head_phase import load_head_phase_provenance

from ._base import fmt, make_section, make_table

_HEAD_ANALYSIS_DISPLAY_COLUMNS = [
    "backbone",
    "config_id",
    "head",
    "semantics",
    "threshold_effective",
    "status",
    "finite",
    "n_songs",
    "n_pooled",
    "coverage",
    "boundary_source",
    "head_pool_variant",
    "scoring_semantics_version",
    "reference_corpus_hash",
]


def _row_dict(r) -> dict:
    coverage = None
    if r.n_pooled > 0:
        coverage = r.n_pooled / r.n_songs if r.n_songs else 0.0
    return {
        "backbone": r.backbone,
        "config_id": r.config_id,
        "head": r.head or "—",
        "semantics": fmt(r.semantics),
        "threshold_effective": fmt(r.threshold_effective),
        "status": r.status,
        "finite": r.finite,
        "n_songs": r.n_songs,
        "n_pooled": r.n_pooled,
        "coverage": coverage if coverage is not None else None,
        "boundary_source": r.boundary_source,
        "head_pool_variant": r.head_pool_variant,
        "scoring_semantics_version": r.scoring_semantics_version,
        "reference_corpus_hash": fmt(r.reference_corpus_hash),
    }


def section_head_analysis(con) -> dict:
    """Render the canonical ``head_phase_provenance`` rows as the head-analysis section."""
    try:
        rows = load_head_phase_provenance(con)
    except Exception:
        rows = []

    if not rows:
        return make_section(
            "head-analysis",
            "Head Analysis",
            empty_message="No canonical head-phase provenance recorded. Run the head-analysis phase.",
        )

    per_backbone: dict[str, list[dict]] = {}
    for r in rows:
        per_backbone.setdefault(str(r.backbone), []).append(_row_dict(r))

    subsections = []
    for backbone in sorted(per_backbone):
        table_rows = per_backbone[backbone]
        n_done = sum(1 for d in table_rows if d["status"] == "done")
        n_finite = sum(1 for d in table_rows if d["finite"] is True)
        table_rows_sorted = sorted(
            table_rows,
            key=lambda d: (
                d["config_id"] if d["config_id"] is not None else 10**12,
                str(d["head"]),
            ),
        )
        subsections.append(
            {
                "id": f"head-analysis-{backbone}",
                "title": str(backbone),
                "description": "",
                "stats": [
                    {"label": "canonical rows", "value": len(table_rows)},
                    {"label": "done", "value": n_done},
                    {"label": "finite", "value": n_finite},
                ],
                "charts": [],
                "tables": [
                    make_table(
                        table_rows_sorted,
                        id=f"head_phase_provenance_{backbone}",
                        title=f"Canonical head-phase provenance ({backbone})",
                        collapsible=True,
                        summary_text=f"{len(table_rows_sorted)} canonical row(s)",
                    )
                ],
                "panels": [],
                "subsections": [],
                "warnings": [],
                "headline": None,
                "empty_message": "",
            }
        )

    return make_section(
        "head-analysis",
        "Head Analysis",
        description=(
            "Canonical head-phase provenance per backbone, read directly from "
            "head_phase_provenance.  coverage = n_pooled / n_songs.  Canonical rows carry the "
            "active catalog boundary identity (boundary_source='catalog', "
            "head_pool_variant='shared_catalog_boundary')."
        ),
        subsections=subsections,
    )
