"""Corrective Gram-geometry report/evidence surface coverage (Plans A-G, Round 1).

Fills the confirmed coverage gaps left by the corrective repair:

* ``report._retrieval.section_analysis`` corpus-evidence rendering and
  ``report._retrieval.query_corpus_evidence`` run-scoped retrieval.
* ``validate_fixture_report.validate_report`` corrective-evidence fail-closed checks.
* ``tools.emit_corrective_evidence.main`` deterministic Plan F summary emission.
* ``helpers.corpus_identity`` validation/refusal error paths.

Every test is synthetic and deterministic: no audio, ONNX, CUDA, real corpus, or
source-control reads.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pandas as pd
import pytest

from scripts.embedding_research.generate_fixture_report import main as generate_report
from scripts.embedding_research.helpers.corpus_identity import (
    RepresentationState,
    classify_representation,
    search_representation_id,
    structural_identity,
)
from scripts.embedding_research.report._retrieval import (
    query_corpus_evidence,
    section_analysis,
)
from scripts.embedding_research.tools.emit_corrective_evidence import (
    main as emit_corrective_evidence,
)
from scripts.embedding_research.validate_fixture_report import validate_report

pytestmark = pytest.mark.unit


# ── G1: report._retrieval corpus-evidence rendering ───────────────────────────


def _analysis_frame() -> pd.DataFrame:
    """A small synthetic analyze-metrics frame with one real threshold-map row."""
    return pd.DataFrame(
        [
            {
                "evidence_json": json.dumps(
                    {"role": "threshold", "song_id": "s1", "backbone": "effnet", "comparable": True}
                ),
                "threshold_id": "t-000",
                "structural_identity": "struct-1",
                "search_representation_id": "rep-1",
            },
            {
                "evidence_json": "",
                "threshold_id": "t-001",
                "structural_identity": "struct-2",
                "search_representation_id": "rep-2",
            },
        ]
    )


def _membership_row() -> dict[str, Any]:
    return {
        "song_id": "s1",
        "backbone": "effnet",
        "observation_group_sha256": "a" * 64,
        "geometry_id": "g1",
        "numerical_profile_digest": "b" * 64,
        "comparable": True,
        "defined": True,
        "eligible": True,
        "reasons": [],
        "searchable_count": 3,
    }


def _query_doc() -> dict[str, Any]:
    return {
        "song_id": "s1",
        "backbone": "effnet",
        "comparable": True,
        "defined": True,
        "eligible": True,
        "reasons": [],
        "winner_score": 0.9,
        "baseline_score": 0.4,
        "baseline_delta": 0.5,
        "searchable_count": 3,
        "neighborhood": [
            {
                "rank": 0,
                "song_id": "s2",
                "backbone": "effnet",
                "search_representation_id": "rep-2",
                "score": 0.9,
            }
        ],
        "baseline_neighborhood": [
            {
                "rank": 0,
                "song_id": "s2",
                "backbone": "effnet",
                "search_representation_id": "rep-2",
                "score": 0.4,
            }
        ],
    }


def _corpus_evidence(
    *,
    comparable: bool = True,
    reasons: list[str] | None = None,
    missing_searchable: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "role": "corpus",
        "comparable": comparable,
        "reasons": list(reasons or []),
        "membership": [_membership_row()],
        "missing_searchable": list(missing_searchable or []),
        "queries": [_query_doc()],
    }


def _table_ids(section: dict) -> list[str]:
    return [table["id"] for table in section["tables"]]


def _messages(section: dict, level: str | None = None) -> list[str]:
    return [
        warning["message"] for warning in section.get("warnings", []) if level is None or warning.get("level") == level
    ]


def test_section_analysis_renders_corpus_membership_queries_and_neighborhoods() -> None:
    section = section_analysis(_analysis_frame(), corpus_evidence=_corpus_evidence())

    ids = _table_ids(section)
    assert "geometry_analysis" in ids
    assert "geometry_threshold_map" in ids
    assert "geometry_membership" in ids
    assert "geometry_queries" in ids
    assert "geometry_neighborhoods" in ids
    assert "geometry_baseline_neighborhoods" in ids
    assert section["empty_message"] == ""
    assert _messages(section) == []


def test_section_analysis_warns_on_missing_searchable_representations() -> None:
    section = section_analysis(
        _analysis_frame(),
        corpus_evidence=_corpus_evidence(missing_searchable=["s9", "s10"]),
    )

    warnings = _messages(section, level="warning")
    assert any("Songs without any searchable representation" in message for message in warnings)
    assert any("s9" in message and "s10" in message for message in warnings)


def test_section_analysis_errors_on_non_comparable_corpus_with_reasons() -> None:
    section = section_analysis(
        _analysis_frame(),
        corpus_evidence=_corpus_evidence(comparable=False, reasons=["no_searchable"]),
    )

    errors = _messages(section, level="error")
    assert any("Non-comparable geometry corpus published with explicit reasons" in message for message in errors)
    assert any("no_searchable" in message for message in errors)


def test_section_analysis_errors_when_corpus_evidence_unavailable() -> None:
    section = section_analysis(_analysis_frame(), corpus_evidence=None)

    errors = _messages(section, level="error")
    assert any("Corpus comparability/neighborhood evidence unavailable" in message for message in errors)


_ANALYSIS_COLUMNS = (
    "run_id, geometry_id, observation_id, geometry_semantics_version, numerical_profile_digest,"
    " threshold_id, structural_identity, search_representation_id, evaluation_id,"
    " scoring_semantics_version, execution_id, metric, value, evidence_json, created_at_ms"
)


def _insert_analysis_row(con, *, run_id: str, evidence_json: str | None, metric: str = "corpus") -> None:
    con.execute(
        f"INSERT INTO geometry_analysis_records ({_ANALYSIS_COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            run_id,
            "g1",
            "obs-1",
            "gram-v1",
            "profile-digest",
            "corpus",
            "struct-1",
            "rep-1",
            "eval-1",
            1,
            "exec-1",
            metric,
            0.0,
            evidence_json,
            1,
        ],
    )


def test_query_corpus_evidence_returns_first_corpus_document(con) -> None:
    corpus_doc = {"role": "corpus", "comparable": True, "membership": []}
    # Malformed and empty evidence_json rows must be skipped without raising.
    _insert_analysis_row(con, run_id="run-a", evidence_json="{not json")
    _insert_analysis_row(con, run_id="run-a", evidence_json="", metric="other")
    _insert_analysis_row(con, run_id="run-a", evidence_json=json.dumps({"role": "threshold"}))
    _insert_analysis_row(con, run_id="run-a", evidence_json=json.dumps(corpus_doc))

    assert query_corpus_evidence(con, run_id="run-a") == corpus_doc


def test_query_corpus_evidence_returns_none_without_a_corpus_row(con) -> None:
    _insert_analysis_row(con, run_id="run-b", evidence_json="{not json")
    _insert_analysis_row(con, run_id="run-b", evidence_json="", metric="other")

    assert query_corpus_evidence(con, run_id="run-b") is None
    assert query_corpus_evidence(con, run_id="run-absent") is None


# ── G2: validate_report corrective-evidence fail-closed checks ─────────────────


def _generate_and_mutate(tmp_path, mutate) -> Any:
    report_path = generate_report(tmp_path)
    data = json.loads(report_path.read_text(encoding="utf-8"))
    mutate(data)
    mutated = tmp_path / "mutated_report.json"
    mutated.write_text(json.dumps(data), encoding="utf-8")
    return mutated


def _delete_corrective_evidence(data: dict) -> None:
    del data["corrective_evidence"]


def _set_self_candidate_count(data: dict) -> None:
    data["corrective_evidence"]["retrieval"]["self_candidate_count"] = 1


def _set_segmentation_from_scorer_count(data: dict) -> None:
    data["corrective_evidence"]["retrieval"]["segmentation_from_scorer_count"] = 1


def _disable_leave_one_out(data: dict) -> None:
    data["corrective_evidence"]["retrieval"]["corpus_wide_leave_one_out"] = False


def _truncate_threshold_map(data: dict) -> None:
    data["corrective_evidence"]["threshold_map"]["count"] = 170


def _drop_hash_retention(data: dict) -> None:
    data["corrective_evidence"]["scientific_hash_retention"] = False


def _enable_source_commit_traceability(data: dict) -> None:
    data["corrective_evidence"]["source_commit_traceability"] = True


def _non_dict_benchmark(data: dict) -> None:
    data["corrective_evidence"]["benchmark"] = []


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (_delete_corrective_evidence, "corrective_evidence is missing"),
        (_set_self_candidate_count, "retrieval self_candidate_count must be zero"),
        (_set_segmentation_from_scorer_count, "retrieval segmentation_from_scorer_count must be zero"),
        (_disable_leave_one_out, "corpus-wide leave-one-out evidence is missing"),
        (_truncate_threshold_map, "threshold map must contain all 171 hypotheses"),
        (_drop_hash_retention, "scientific artifact-hash retention is missing"),
        (_enable_source_commit_traceability, "source-commit traceability must be absent"),
        (_non_dict_benchmark, "fixtures-only benchmark metadata is missing"),
    ],
    ids=[
        "missing-corrective-evidence",
        "self-candidate-count",
        "segmentation-from-scorer-count",
        "leave-one-out",
        "threshold-map-count",
        "hash-retention",
        "source-commit-traceability",
        "benchmark-not-dict",
    ],
)
def test_validate_report_rejects_corrective_evidence_violations(tmp_path, mutate, expected: str) -> None:
    mutated = _generate_and_mutate(tmp_path, mutate)

    problems = validate_report(mutated)
    assert any(expected in problem for problem in problems), problems


def test_generated_report_validates_clean(tmp_path) -> None:
    report_path = generate_report(tmp_path)

    assert validate_report(report_path) == []


# ── G3: Plan F corrective-evidence emitter ─────────────────────────────────────


def test_emit_corrective_evidence_writes_plan_f_summary(tmp_path) -> None:
    report_path = generate_report(tmp_path)
    out_path = tmp_path / "corrective-evidence.json"

    assert emit_corrective_evidence(["--report", str(report_path), "--output", str(out_path)]) == 0
    assert out_path.is_file()

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["evidence_kind"] == "corrective-gram-geometry-plan-f"
    assert payload["synthetic_only"] is True
    assert payload["real_corpus_run"] is False
    assert payload["source_commit_traceability"] is False
    proof = payload["architecture_proof"]
    assert proof["self_candidate_count"] == 0
    assert proof["segmentation_from_scorer_count"] == 0
    assert proof["threshold_count"] == 171
    assert payload["benchmark"]["fixtures_only"] is True
    assert payload["scientific_hashes"]["report_json_sha256"] == hashlib.sha256(report_path.read_bytes()).hexdigest()


#: Benchmark fields the emitter observes from the live process (wall-clock and
#: allocation/rss high-water measurements).  These are genuine environment-observed
#: fixture measurements rather than derived evidence, so they legitimately vary run to
#: run; every other payload field must be byte-stable.
_MEASURED_BENCHMARK_FIELDS = ("elapsed_ms", "peak_rss_bytes", "peak_tracemalloc_bytes")


def test_emit_corrective_evidence_is_deterministic(tmp_path) -> None:
    report_path = generate_report(tmp_path)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    assert emit_corrective_evidence(["--report", str(report_path), "--output", str(first)]) == 0
    assert emit_corrective_evidence(["--report", str(report_path), "--output", str(second)]) == 0

    first_payload = json.loads(first.read_text(encoding="utf-8"))
    second_payload = json.loads(second.read_text(encoding="utf-8"))
    for payload in (first_payload, second_payload):
        for field in _MEASURED_BENCHMARK_FIELDS:
            payload["benchmark"].pop(field, None)

    # Everything except the environment-observed benchmark measurements is identical.
    assert first_payload == second_payload


# ── G4: helpers.corpus_identity validation/refusal error paths ─────────────────


_BASE_REPRESENTATION_ID_KWARGS: dict[str, Any] = {
    "experiment": "temporal_global",
    "scoring_semantics_version": 1,
    "geometry_semantics_version": "gram-v1",
    "numerical_profile_digest": "a" * 64,
    "observation_group_sha256": "b" * 64,
    "mask_identity": "c" * 64,
    "ordered_corpus_song_ids": ("s1", "s2", "s3"),
    "medoid_source_indices": (0, 2, 5),
    "normalized_searchable_weights": (0.5, 0.25, 0.25),
    "searchable_count": 3,
}


def _representation_id(**overrides: Any) -> str:
    return search_representation_id(**{**_BASE_REPRESENTATION_ID_KWARGS, **overrides})


def test_representation_id_accepts_the_canonical_representative_shape() -> None:
    assert len(_representation_id()) == 64


@pytest.mark.parametrize(
    "overrides",
    [
        {"experiment": ""},
        {"searchable_count": True},
        {"searchable_count": -1},
        {"searchable_count": "1"},
        {"ordered_corpus_song_ids": "s1"},
        {"normalized_searchable_weights": (float("nan"),)},
        {"normalized_searchable_weights": (float("inf"),)},
        {"medoid_source_indices": (True,)},
    ],
    ids=[
        "empty-experiment",
        "bool-searchable-count",
        "negative-searchable-count",
        "string-searchable-count",
        "string-corpus-sequence",
        "nan-weight",
        "inf-weight",
        "bool-medoid-index",
    ],
)
def test_search_representation_id_rejects_invalid_inputs(overrides: dict) -> None:
    with pytest.raises(ValueError):
        _representation_id(**overrides)


def test_representation_state_rejects_non_boolean_comparable() -> None:
    with pytest.raises(ValueError):
        RepresentationState(1, True, True, ())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "alignment_ok": "yes",
            "searchable_count": 1,
            "medoid_defined": True,
            "candidate_count": 1,
            "label_defined": True,
        },
        {
            "alignment_ok": True,
            "searchable_count": "1",
            "medoid_defined": True,
            "candidate_count": 1,
            "label_defined": True,
        },
        {
            "alignment_ok": True,
            "searchable_count": 1,
            "medoid_defined": True,
            "candidate_count": True,
            "label_defined": True,
        },
        {
            "alignment_ok": True,
            "searchable_count": 1,
            "medoid_defined": True,
            "candidate_count": "1",
            "label_defined": True,
        },
    ],
    ids=[
        "non-bool-alignment",
        "string-searchable-count",
        "bool-candidate-count",
        "string-candidate-count",
    ],
)
def test_classify_representation_rejects_non_boolean_or_non_integer_inputs(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        classify_representation(**kwargs)


def test_structural_identity_rejects_empty_threshold_id() -> None:
    with pytest.raises(ValueError):
        structural_identity(threshold_id="", boundaries=(), absorbed_locations=())
