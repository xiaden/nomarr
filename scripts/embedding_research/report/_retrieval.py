"""Geometry-era report retrieval.

Rows are read from the exact run-scoped ``geometry_analysis_records`` table and retain
only the complete geometry/observation/threshold/evaluation/scoring/execution identity
evidence written by the geometry owner.  There is no strategy decoder, no runtime
resolution of evidence from any other scope, and no inferred provenance; a non-exact or
mixed scope is refused rather than silently blended.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from ._base import make_section, make_table

#: The complete exact geometry-era identity axes carried by every evidence row.
IDENTITY_COLUMNS = [
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
]

GEOMETRY_ANALYSIS_COLUMNS = ["run_id", *IDENTITY_COLUMNS, "metric", "value", "evidence_json"]

#: Evidence role marking the mandatory observed global-medoid baseline row.  Baseline rows
#: are rendered separately from winner representations and are never winner candidates.
BASELINE_EVIDENCE_ROLE = "mandatory-observed-baseline"


def _require_run_id(run_id: str | None) -> str:
    if not run_id:
        raise ValueError("exact run_id is required; the report never blends runs")
    return str(run_id)


def query_analyze_metrics(con, *, run_id: str) -> pd.DataFrame:
    """Read every exact geometry analysis evidence row for one run scope."""
    exact_run = _require_run_id(run_id)
    columns = ", ".join(GEOMETRY_ANALYSIS_COLUMNS)
    rows = con.execute(
        f"SELECT {columns} FROM geometry_analysis_records WHERE run_id=? ORDER BY geometry_id, threshold_id, metric",
        (exact_run,),
    ).fetchall()
    return pd.DataFrame(rows, columns=GEOMETRY_ANALYSIS_COLUMNS)


def query_geometry_identity(con, *, run_id: str) -> pd.DataFrame:
    """Read the distinct exact identity axis tuples persisted for one run scope.

    Absence is explicit refusal evidence (an empty frame); another run is never
    substituted.
    """
    exact_run = _require_run_id(run_id)
    query = (
        "SELECT run_id, geometry_id, observation_id, geometry_semantics_version, "
        "numerical_profile_digest, threshold_id, structural_identity, "
        "search_representation_id, evaluation_id, scoring_semantics_version, execution_id "
        "FROM geometry_analysis_records WHERE run_id=? "
        "ORDER BY run_id, geometry_id, threshold_id, metric"
    )
    rows = con.execute(query, (exact_run,)).fetchall()
    return pd.DataFrame(rows, columns=["run_id", *IDENTITY_COLUMNS]).drop_duplicates().reset_index(drop=True)


def _baseline_mask(frame: pd.DataFrame) -> pd.Series:
    return frame["evidence_json"].astype(str).str.contains(BASELINE_EVIDENCE_ROLE, regex=False)


def query_observed_baselines(con, *, run_id: str) -> pd.DataFrame:
    """Read only the mandatory observed global-medoid baseline evidence rows."""
    frame = query_analyze_metrics(con, run_id=run_id)
    if frame.empty:
        return frame
    return frame[_baseline_mask(frame)].reset_index(drop=True)


def query_geometry_winners(con, *, run_id: str) -> pd.DataFrame:
    """Read only the winner threshold representation evidence rows (never baselines)."""
    frame = query_analyze_metrics(con, run_id=run_id)
    if frame.empty:
        return frame
    return frame[~_baseline_mask(frame)].reset_index(drop=True)


def query_winners_metrics(con, *, run_id: str) -> pd.DataFrame:
    """Winner evidence with the persisted incomplete diagnostics attached as frame attrs."""
    frame = query_geometry_winners(con, run_id=run_id)
    frame.attrs["persisted_incomplete_diagnostics"] = query_incomplete_analyze_diagnostics(con, run_id=run_id)
    return frame


def query_incomplete_analyze_diagnostics(con, *, run_id: str) -> tuple[dict[str, Any], ...]:
    """Read the exact run-scoped refusal/incomplete diagnostics (no inferred lineage)."""
    exact_run = _require_run_id(run_id)
    rows = con.execute(
        "SELECT * FROM analyze_incomplete_diagnostics WHERE run_id=? ORDER BY created_at", (exact_run,)
    ).fetchall()
    names = [item[0] for item in con.description]
    return tuple(dict(zip(names, row, strict=False)) for row in rows)


def section_analysis(df: pd.DataFrame, identity: pd.DataFrame | None = None) -> dict:
    """Render the exact analysis identity evidence and metric rows, or refuse visibly."""
    tables = []
    if identity is not None and not identity.empty:
        tables.append(
            make_table(identity.to_dict("records"), id="geometry_identity", title="Exact geometry identity evidence")
        )
    if df is not None and not df.empty:
        tables.append(make_table(df.to_dict("records"), id="geometry_analysis", title="Geometry analysis metrics"))
    if not tables:
        return make_section(
            "analysis",
            "Geometry Analysis",
            warnings=[{"level": "error", "message": "Geometry identity evidence unavailable; analysis refused."}],
            empty_message="REFUSED: no exact geometry identity evidence.",
        )
    return make_section("analysis", "Geometry Analysis", tables=tables)


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

    exact_run = _require_run_id(run_id)
    rows = con.execute("SELECT evidence_json FROM geometry_analysis_records WHERE run_id=?", (exact_run,)).fetchall()
    corpus_evidence = None
    for row in rows:
        raw = row[0]
        if not raw:
            continue
        try:
            doc = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("role") == "corpus":
            corpus_evidence = doc
            break
    if corpus_evidence is None:
        # Runs without a persisted corpus axis payload (for example a threshold-only synthetic
        # scope) carry no geometry axes to rebind; there is nothing to verify here.
        return
    axes = corpus_evidence.get("geometry_axes")
    if not isinstance(axes, list) or not axes:
        raise GeometryRefusal("INTEGRITY_REFUSED: report corpus geometry axes are missing")
    for axis in axes:
        identity = GeometryIdentity(
            str(axis["song_id"]),
            str(axis["backbone"]),
            str(axis["observation_id"]),
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
    "GEOMETRY_ANALYSIS_COLUMNS",
    "IDENTITY_COLUMNS",
    "query_analyze_metrics",
    "query_geometry_identity",
    "query_geometry_winners",
    "query_incomplete_analyze_diagnostics",
    "query_observed_baselines",
    "query_winners_metrics",
    "section_analysis",
    "verify_geometry_bindings_for_run",
]
