"""Normalized geometry result-surface retrieval."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ._base import make_section, make_table

#: Retained as documentation of the observed-baseline evidence role; the retired nested
#: evidence table that used to carry it was hard-cut in favour of the normalized surfaces.
BASELINE_EVIDENCE_ROLE = "mandatory-observed-baseline"

IDENTITY_COLUMNS = [
    "geometry_id",
    "observation_group_sha256",
    "geometry_semantics_version",
    "numerical_profile_digest",
    "threshold_id",
    "structural_identity",
    "search_representation_id",
    "evaluation_id",
    "scoring_semantics_version",
    "execution_id",
]


def _require_run_id(run_id: str | None) -> str:
    if not run_id:
        raise ValueError("exact run_id is required; the report never blends runs")
    return str(run_id)


def query_incomplete_analyze_diagnostics(con, *, run_id: str) -> tuple[dict[str, Any], ...]:
    """Read the exact run-scoped refusal/incomplete diagnostics (no inferred lineage)."""
    exact_run = _require_run_id(run_id)
    rows = con.execute(
        "SELECT * FROM analyze_incomplete_diagnostics WHERE run_id=? ORDER BY created_at", (exact_run,)
    ).fetchall()
    names = [item[0] for item in con.description]
    return tuple(dict(zip(names, row, strict=False)) for row in rows)


def query_normalized_result(con, *, run_id: str) -> Any:
    """Read the exact run's class-scoped result from the Phase 6 normalized surfaces."""
    from scripts.embedding_research.common.geometry_analysis import (
        corpus_result_identity_from_provenance,
        read_geometry_corpus_analysis_normalized,
    )
    from scripts.embedding_research.db.result_surfaces import read_result_provenance

    exact_run = _require_run_id(run_id)
    rows = read_result_provenance(con, run_id=exact_run)
    if len(rows) != 1:
        raise ValueError("exact run must carry exactly one compact result provenance row")
    identity = corpus_result_identity_from_provenance(rows[0])
    return read_geometry_corpus_analysis_normalized(con, run_id=exact_run, identity=identity)


def _identity_rows(result: Any) -> list[dict[str, Any]]:
    """Render the persisted per-representation identity axes as full ten-axis rows."""
    provenance = result.provenance
    rows: list[dict[str, Any]] = []
    for axis in provenance.geometry_axes:
        row = dict.fromkeys(IDENTITY_COLUMNS)
        row.update(
            {
                "geometry_id": str(axis["geometry_id"]),
                "observation_group_sha256": str(axis["observation_group_sha256"]),
                "geometry_semantics_version": str(provenance.geometry_semantics_version),
                "numerical_profile_digest": str(axis["numerical_profile_digest"]),
                "threshold_id": "corpus",
                "structural_identity": f"{provenance.experiment}:corpus",
                "search_representation_id": "corpus",
                "evaluation_id": str(provenance.evaluation_id),
                "scoring_semantics_version": int(provenance.scoring_semantics_version),
                "execution_id": str(provenance.execution_id),
            }
        )
        rows.append(row)
    return rows


def _threshold_class_rows(result: Any) -> list[dict[str, Any]]:
    return [
        {
            "threshold_index": row.threshold_index,
            "threshold_id": row.threshold_id,
            "threshold_value": row.threshold_value,
            "corpus_search_class_id": row.corpus_search_class_id,
            "comparable": row.comparable,
            "reasons": ", ".join(row.reasons),
        }
        for row in result.threshold_class_map
    ]


def section_analysis(result: Any = None) -> dict:
    """Render the normalized class-scoped result or refuse visibly."""
    if result is None:
        return make_section(
            "analysis",
            "Geometry Analysis",
            warnings=[{"level": "error", "message": "Geometry identity evidence unavailable; analysis refused."}],
            empty_message="REFUSED: no exact geometry identity evidence.",
        )
    tables = [
        make_table(_identity_rows(result), id="geometry_identity", title="Exact geometry identity evidence"),
        make_table(
            [asdict(row) for row in result.class_aggregate_metrics],
            id="geometry_analysis",
            title="Class-scoped geometry analysis metrics",
        ),
        make_table(_threshold_class_rows(result), id="geometry_threshold_map", title="Threshold-to-class map"),
    ]
    section = make_section("analysis", "Geometry Analysis", tables=tables)
    warnings: list[dict[str, str]] = []
    if not result.provenance.comparable:
        reasons = ", ".join(result.provenance.reasons) or "unspecified"
        warnings.append(
            {
                "level": "error",
                "message": f"Non-comparable geometry corpus published with explicit reasons: {reasons}",
            }
        )
    if warnings:
        section["warnings"] = warnings
    return section


def verify_geometry_bindings_for_run(con, *, run_id: str, stream_store: Any, profile: Any) -> None:
    """Re-verify every persisted geometry axis against the CURRENT committed observation.

    Raises the typed geometry refusal (``STALE_REFUSED`` / ``INTEGRITY_REFUSED``) when any
    persisted axis is stale, missing, duplicate, or corrupt.  Report retrieval/render must
    not proceed after a binding mismatch, and never falls back to a current/latest scope.
    """
    from scripts.embedding_research.db.geometry import (
        GeometryIdentity,
        GeometryRefusal,
        verify_geometry_current,
    )
    from scripts.embedding_research.db.result_surfaces import read_result_provenance

    exact_run = _require_run_id(run_id)
    rows = read_result_provenance(con, run_id=exact_run)
    if not rows:
        # Runs without a persisted provenance row (for example a threshold-only synthetic
        # scope) carry no geometry axes to rebind; there is nothing to verify here.
        return
    if bool(rows[0].get("synthetic_only")):
        # Synthetic-only scopes publish no committed real observation groups to rebind.
        return
    axes = tuple(rows[0].get("geometry_axes") or ())
    if not axes:
        raise GeometryRefusal("INTEGRITY_REFUSED: report corpus geometry axes are missing")
    for axis in axes:
        identity = GeometryIdentity(
            str(axis["song_id"]),
            str(axis["backbone"]),
            str(axis["observation_group_sha256"]),
            str(axis["geometry_semantics_version"]),
            str(axis["numerical_profile_digest"]),
        )
        if profile is not None and str(identity.numerical_profile_digest) != str(getattr(profile, "digest", "")):
            raise GeometryRefusal("INTEGRITY_REFUSED: report geometry profile does not match the current profile")
        observation = stream_store.load_committed_observation(identity.song_id, identity.backbone)
        record = verify_geometry_current(con, observation, exact_identity=identity)
        if record is None or str(record.geometry_id) != str(axis.get("geometry_id", "")):
            raise GeometryRefusal("INTEGRITY_REFUSED: report geometry axis binding mismatch")


__all__ = [
    "BASELINE_EVIDENCE_ROLE",
    "IDENTITY_COLUMNS",
    "query_incomplete_analyze_diagnostics",
    "query_normalized_result",
    "section_analysis",
    "verify_geometry_bindings_for_run",
]
