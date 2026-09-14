"""Run-scoped normalized geometry result-surface retrieval and analysis rendering.

Every query reads only the normalized Experiment One result surfaces for one exact
``run_id``: the fixed evaluation corpus, the threshold class map, the class/baseline
aggregate and per-query metrics, the class/baseline neighborhoods, and the ONE compact
result provenance row.  These run-scoped normalized surfaces are the only read path.
"""

from __future__ import annotations

from dataclasses import dataclass
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


# ---------------------------------------------------------------------------
# Nine run-scoped normalized surface queries
# ---------------------------------------------------------------------------


def query_threshold_class_map(con, *, run_id: str) -> tuple[dict[str, Any], ...]:
    """Read the run-scoped threshold-to-class map (one row per configured threshold)."""
    from scripts.embedding_research.db.identity_persistence import read_threshold_class_map

    return read_threshold_class_map(con, run_id=_require_run_id(run_id))


def query_class_aggregate_metrics(con, *, run_id: str) -> tuple[dict[str, Any], ...]:
    """Read the run-scoped class-scoped aggregate metrics surface."""
    from scripts.embedding_research.db.result_surfaces import read_class_aggregate_metrics

    return read_class_aggregate_metrics(con, run_id=_require_run_id(run_id))


def query_class_query_metrics(con, *, run_id: str) -> tuple[dict[str, Any], ...]:
    """Read the run-scoped class-scoped per-query metrics surface."""
    from scripts.embedding_research.db.result_surfaces import read_class_query_metrics

    return read_class_query_metrics(con, run_id=_require_run_id(run_id))


def query_class_neighborhoods(con, *, run_id: str) -> tuple[dict[str, Any], ...]:
    """Read the run-scoped class-scoped neighborhood surface."""
    from scripts.embedding_research.db.result_surfaces import read_class_neighborhoods

    return read_class_neighborhoods(con, run_id=_require_run_id(run_id))


def query_baseline_aggregate_metrics(con, *, run_id: str) -> tuple[dict[str, Any], ...]:
    """Read the run-scoped threshold-independent baseline aggregate metrics surface."""
    from scripts.embedding_research.db.result_surfaces import read_baseline_aggregate_metrics

    return read_baseline_aggregate_metrics(con, run_id=_require_run_id(run_id))


def query_baseline_query_metrics(con, *, run_id: str) -> tuple[dict[str, Any], ...]:
    """Read the run-scoped threshold-independent baseline per-query metrics surface."""
    from scripts.embedding_research.db.result_surfaces import read_baseline_query_metrics

    return read_baseline_query_metrics(con, run_id=_require_run_id(run_id))


def query_baseline_neighborhoods(con, *, run_id: str) -> tuple[dict[str, Any], ...]:
    """Read the run-scoped threshold-independent baseline neighborhood surface."""
    from scripts.embedding_research.db.result_surfaces import read_baseline_neighborhoods

    return read_baseline_neighborhoods(con, run_id=_require_run_id(run_id))


def query_evaluation_corpus(con, *, run_id: str) -> tuple[dict[str, Any], ...]:
    """Read the run-scoped fixed evaluation corpus membership."""
    from scripts.embedding_research.db.identity_persistence import read_evaluation_corpus

    return read_evaluation_corpus(con, run_id=_require_run_id(run_id))


def query_result_provenance(con, *, run_id: str) -> tuple[dict[str, Any], ...]:
    """Read the ONE run-scoped compact result provenance row (never blended)."""
    from scripts.embedding_research.db.result_surfaces import read_result_provenance

    exact_run = _require_run_id(run_id)
    rows = read_result_provenance(con, run_id=exact_run)
    if len(rows) != 1:
        raise ValueError("exact run must carry exactly one compact result provenance row")
    return rows


@dataclass(frozen=True)
class NormalizedFrames:
    """The normalized result surfaces for one exact run, as flat row mappings."""

    run_id: str
    provenance: dict[str, Any]
    evaluation_corpus: tuple[dict[str, Any], ...]
    threshold_class_map: tuple[dict[str, Any], ...]
    class_aggregate_metrics: tuple[dict[str, Any], ...]
    class_query_metrics: tuple[dict[str, Any], ...]
    class_neighborhoods: tuple[dict[str, Any], ...]
    baseline_aggregate_metrics: tuple[dict[str, Any], ...]
    baseline_query_metrics: tuple[dict[str, Any], ...]
    baseline_neighborhoods: tuple[dict[str, Any], ...]


def collect_report_frames(con, *, run_id: str) -> NormalizedFrames:
    """Compose every run-scoped normalized surface for the report renderers."""
    exact_run = _require_run_id(run_id)
    return NormalizedFrames(
        run_id=exact_run,
        provenance=query_result_provenance(con, run_id=exact_run)[0],
        evaluation_corpus=query_evaluation_corpus(con, run_id=exact_run),
        threshold_class_map=query_threshold_class_map(con, run_id=exact_run),
        class_aggregate_metrics=query_class_aggregate_metrics(con, run_id=exact_run),
        class_query_metrics=query_class_query_metrics(con, run_id=exact_run),
        class_neighborhoods=query_class_neighborhoods(con, run_id=exact_run),
        baseline_aggregate_metrics=query_baseline_aggregate_metrics(con, run_id=exact_run),
        baseline_query_metrics=query_baseline_query_metrics(con, run_id=exact_run),
        baseline_neighborhoods=query_baseline_neighborhoods(con, run_id=exact_run),
    )


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _identity_rows(frames: NormalizedFrames) -> list[dict[str, Any]]:
    """Render the persisted per-representation identity axes as full ten-axis rows."""
    provenance = frames.provenance
    rows: list[dict[str, Any]] = []
    for axis in provenance.get("geometry_axes") or ():
        row = dict.fromkeys(IDENTITY_COLUMNS)
        row.update(
            {
                "geometry_id": str(axis["geometry_id"]),
                "observation_group_sha256": str(axis["observation_group_sha256"]),
                "geometry_semantics_version": str(provenance["geometry_semantics_version"]),
                "numerical_profile_digest": str(axis["numerical_profile_digest"]),
                "threshold_id": "corpus",
                "structural_identity": f"{provenance['experiment']}:corpus",
                "search_representation_id": "corpus",
                "evaluation_id": str(provenance["evaluation_id"]),
                "scoring_semantics_version": int(provenance["scoring_semantics_version"]),
                "execution_id": str(provenance["execution_id"]),
            }
        )
        rows.append(row)
    return rows


def _class_metric_rows(frames: NormalizedFrames) -> list[dict[str, Any]]:
    """Project the class-scoped per-query metrics surface for rendering."""
    columns = ("corpus_search_class_id", "query_song_id", "ruler", "metric", "k", "value", "status")
    return [{column: row[column] for column in columns} for row in frames.class_query_metrics]


def _threshold_join_rows(frames: NormalizedFrames) -> list[dict[str, Any]]:
    """JOIN threshold -> class -> comparable state -> class metrics -> fixed-baseline delta.

    The threshold-independent baseline is keyed by its execution so the delta is always
    taken against the ONE fixed global-medoid baseline for this exact run.
    """
    execution_id = frames.provenance.get("execution_id")
    class_values: dict[tuple[str, str, str, int], dict[str, Any]] = {
        (row["corpus_search_class_id"], row["ruler"], row["metric"], row["k"]): row
        for row in frames.class_aggregate_metrics
    }
    baseline_values: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in frames.baseline_aggregate_metrics:
        if execution_id is not None and row.get("execution_id") != execution_id:
            continue
        baseline_values[(row["ruler"], row["metric"], row["k"])] = row

    rows: list[dict[str, Any]] = []
    ordered_thresholds = sorted(
        frames.threshold_class_map, key=lambda row: (row["threshold_index"], row["threshold_id"])
    )
    for threshold in ordered_thresholds:
        class_id = threshold["corpus_search_class_id"]
        for key in sorted(class_values):
            if key[0] != class_id:
                continue
            aggregate = class_values[key]
            baseline = baseline_values.get((key[1], key[2], key[3]))
            baseline_value = baseline["value"] if baseline is not None else None
            delta = (aggregate["value"] - baseline_value) if baseline_value is not None else None
            rows.append(
                {
                    "threshold_index": threshold["threshold_index"],
                    "threshold_id": threshold["threshold_id"],
                    "threshold_value": threshold["threshold_value"],
                    "corpus_search_class_id": class_id,
                    "comparable": threshold["comparable"],
                    "reasons": ", ".join(threshold["reasons"]),
                    "ruler": key[1],
                    "metric": key[2],
                    "k": key[3],
                    "class_value": aggregate["value"],
                    "evaluable_query_count": aggregate["evaluable_query_count"],
                    "undefined_query_count": aggregate["undefined_query_count"],
                    "baseline_value": baseline_value,
                    "delta": delta,
                }
            )
    return rows


def _per_ruler_counts(frames: NormalizedFrames) -> dict[str, tuple[int, int]]:
    counts: dict[str, list[int]] = {}
    for row in frames.class_aggregate_metrics:
        bucket = counts.setdefault(row["ruler"], [0, 0])
        bucket[0] += int(row["evaluable_query_count"])
        bucket[1] += int(row["undefined_query_count"])
    return {ruler: (values[0], values[1]) for ruler, values in counts.items()}


def section_analysis(frames: NormalizedFrames | None = None) -> dict:
    """Render the normalized class-scoped result or refuse visibly."""
    if frames is None:
        return make_section(
            "analysis",
            "Geometry Analysis",
            warnings=[{"level": "error", "message": "Geometry identity evidence unavailable; analysis refused."}],
            empty_message="REFUSED: no exact geometry identity evidence.",
        )
    tables = [
        make_table(_identity_rows(frames), id="geometry_identity", title="Exact geometry identity evidence"),
        make_table(_class_metric_rows(frames), id="geometry_analysis", title="Class-scoped per-query geometry metrics"),
        make_table(
            _threshold_join_rows(frames),
            id="geometry_threshold_map",
            title="Threshold -> class -> metrics -> delta vs the single fixed baseline",
        ),
    ]

    warnings: list[dict[str, str]] = []
    provenance = frames.provenance
    if not provenance.get("comparable", True):
        reasons = ", ".join(provenance.get("reasons") or ()) or "unspecified"
        warnings.append(
            {
                "level": "error",
                "message": f"Non-comparable geometry corpus published with explicit reasons: {reasons}",
            }
        )
    for threshold in frames.threshold_class_map:
        if not threshold["comparable"]:
            reasons = ", ".join(threshold["reasons"]) or "unspecified"
            warnings.append(
                {
                    "level": "error",
                    "message": (
                        f"Non-comparable threshold {threshold['threshold_id']} "
                        f"(class {threshold['corpus_search_class_id']}) published with reasons: {reasons}"
                    ),
                }
            )
    for ruler, (evaluable, undefined) in sorted(_per_ruler_counts(frames).items()):
        if undefined:
            warnings.append(
                {
                    "level": "warning",
                    "message": f"Ruler {ruler}: {evaluable} evaluable / {undefined} undefined query metrics.",
                }
            )

    section = make_section("analysis", "Geometry Analysis", tables=tables)
    if warnings:
        section["warnings"] = warnings
    return section


def verify_geometry_bindings_for_run(con, *, run_id: str, stream_store: Any, profile: Any) -> None:
    """Re-verify every persisted evaluation-corpus axis against the CURRENT committed observation.

    Reads the compact provenance row plus the fixed ``geometry_evaluation_corpus`` membership
    (never the retired corpus-evidence row) and re-verifies the numerical profile digest and
    :func:`verify_geometry_current` for each member.  Raises the typed geometry refusal
    (``STALE_REFUSED`` / ``INTEGRITY_REFUSED``) when any persisted axis is stale, missing,
    duplicate, or corrupt.  Report retrieval/render must not proceed after a binding mismatch,
    and never falls back to a current/latest scope.
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
        # scope) carry no geometry bindings to rebind; there is nothing to verify here.
        return
    provenance = rows[0]
    if bool(provenance.get("synthetic_only")):
        # Synthetic-only scopes publish no committed real observation groups to rebind.
        return
    corpus = query_evaluation_corpus(con, run_id=exact_run)
    if not corpus:
        raise GeometryRefusal("INTEGRITY_REFUSED: report evaluation corpus membership is missing")
    semantics_version = str(provenance["geometry_semantics_version"])
    for entry in corpus:
        identity = GeometryIdentity(
            str(entry["song_id"]),
            str(entry["backbone"]),
            str(entry["observation_group_sha256"]),
            semantics_version,
            str(entry["numerical_profile_digest"]),
        )
        if profile is not None and str(identity.numerical_profile_digest) != str(getattr(profile, "digest", "")):
            raise GeometryRefusal("INTEGRITY_REFUSED: report geometry profile does not match the current profile")
        observation = stream_store.load_committed_observation(identity.song_id, identity.backbone)
        record = verify_geometry_current(con, observation, exact_identity=identity)
        if record is None or str(record.geometry_id) != str(entry["geometry_id"]):
            raise GeometryRefusal("INTEGRITY_REFUSED: report geometry axis binding mismatch")


__all__ = [
    "BASELINE_EVIDENCE_ROLE",
    "IDENTITY_COLUMNS",
    "NormalizedFrames",
    "collect_report_frames",
    "query_baseline_aggregate_metrics",
    "query_baseline_neighborhoods",
    "query_baseline_query_metrics",
    "query_class_aggregate_metrics",
    "query_class_neighborhoods",
    "query_class_query_metrics",
    "query_evaluation_corpus",
    "query_incomplete_analyze_diagnostics",
    "query_result_provenance",
    "query_threshold_class_map",
    "section_analysis",
    "verify_geometry_bindings_for_run",
]
