"""Corrective Gram-geometry report/evidence surface coverage (Plans A-G, Round 1).

Fills the confirmed coverage gaps left by the corrective repair:

* ``report._retrieval.section_analysis`` normalized result-surface rendering and
  ``report._retrieval.collect_report_frames`` run-scoped retrieval.
* ``validate_fixture_report.validate_report`` corrective-evidence fail-closed checks.
* ``tools.emit_corrective_evidence.main`` deterministic Plan F summary emission.
* ``helpers.corpus_identity`` validation/refusal error paths.

Every test is synthetic and deterministic: no audio, ONNX, CUDA, real corpus, or
source-control reads.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any

import pytest

from scripts.embedding_research.generate_fixture_report import main as generate_report
from scripts.embedding_research.helpers.corpus_identity import (
    CorpusSongSearchInput,
    RepresentationState,
    classify_representation,
    search_representation_id,
    structural_identity,
)
from scripts.embedding_research.report._retrieval import (
    collect_report_frames,
    section_analysis,
)
from scripts.embedding_research.report._summary import section_summary
from scripts.embedding_research.tests._report_seed import RUN_ID, build_seeded_con
from scripts.embedding_research.tools import _evidence
from scripts.embedding_research.tools.emit_corrective_evidence import (
    main as emit_corrective_evidence,
)
from scripts.embedding_research.validate_fixture_report import validate_report

pytestmark = pytest.mark.unit


# ── G1: report._retrieval corpus-evidence rendering ───────────────────────────

# ── G1: normalized report rendering ───────────────────────────────────────────


def _table_ids(section: dict) -> list[str]:
    return [table["id"] for table in section["tables"]]


def _messages(section: dict, level: str | None = None) -> list[str]:
    return [
        warning["message"] for warning in section.get("warnings", []) if level is None or warning.get("level") == level
    ]


def test_section_summary_separates_class_and_observed_baseline_evidence() -> None:
    con = build_seeded_con()
    try:
        frames = collect_report_frames(con, run_id=RUN_ID)
        section = section_summary(frames)
    finally:
        con.close()

    stats = {stat["label"]: stat["value"] for stat in section["stats"]}
    assert stats["class metric rows"] > 0
    assert stats["baseline rows"] > 0
    assert {table["id"] for table in section["tables"]} == {
        "geometry_threshold_summary",
        "observed_baseline_summary",
    }
    winner_table = next(table for table in section["tables"] if table["id"] == "geometry_threshold_summary")
    baseline_table = next(table for table in section["tables"] if table["id"] == "observed_baseline_summary")
    assert winner_table["rows"]
    assert baseline_table["rows"]
    assert "backbone" in baseline_table["columns"]
    assert "backbone" not in winner_table["columns"]


def test_section_summary_refuses_without_normalized_result() -> None:
    section = section_summary(None)

    assert section["empty_message"] == "REFUSED: no exact geometry analysis or observed-baseline evidence."
    assert section["warnings"] == [
        {"level": "error", "message": "No exact geometry analysis evidence; summary refused."}
    ]
    assert section["stats"] == []
    assert section["tables"] == []


def test_section_analysis_renders_identity_threshold_map_and_class_metrics() -> None:
    con = build_seeded_con()
    try:
        frames = collect_report_frames(con, run_id=RUN_ID)
        section = section_analysis(frames)
    finally:
        con.close()

    ids = _table_ids(section)
    assert {"geometry_identity", "geometry_analysis", "geometry_threshold_map"} <= set(ids)
    identity_table = next(table for table in section["tables"] if table["id"] == "geometry_identity")
    assert identity_table["rows"]
    assert section["empty_message"] == ""
    assert _messages(section) == []


def test_section_analysis_errors_on_non_comparable_result() -> None:
    con = build_seeded_con()
    try:
        frames = collect_report_frames(con, run_id=RUN_ID)
    finally:
        con.close()
    non_comparable = replace(
        frames,
        provenance={**frames.provenance, "comparable": False, "reasons": ("zero_searchable",)},
    )

    section = section_analysis(non_comparable)

    errors = _messages(section, level="error")
    assert any("Non-comparable geometry corpus published with explicit reasons" in message for message in errors)
    assert any("zero_searchable" in message for message in errors)


def test_section_analysis_errors_when_result_unavailable() -> None:
    section = section_analysis(None)

    errors = _messages(section, level="error")
    assert any("Geometry identity evidence unavailable" in message for message in errors)


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
    data["corrective_evidence"]["class_scoped_neighborhood_uniqueness"]["self_candidate_count"] = 1


def _truncate_threshold_map(data: dict) -> None:
    data["corrective_evidence"]["threshold_map"]["count"] = 0
    section = next(section for section in data["sections"] if section["id"] == "analysis")
    table = next(table for table in section["tables"] if table["id"] == "geometry_threshold_map")
    table["rows"] = []


def _drop_hash_retention(data: dict) -> None:
    data["corrective_evidence"]["scientific_hash_retention"] = False


def _non_dict_benchmark(data: dict) -> None:
    data["corrective_evidence"]["benchmark"] = []


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (_delete_corrective_evidence, "corrective_evidence is missing"),
        (_set_self_candidate_count, "class-scoped neighborhoods contain self candidates"),
        (_truncate_threshold_map, "normalized threshold-to-class evidence is missing"),
        (_drop_hash_retention, "scientific artifact-hash retention is missing"),
        (_non_dict_benchmark, "fixtures-only benchmark metadata is missing"),
    ],
    ids=[
        "missing-corrective-evidence",
        "self-candidate-count",
        "threshold-map-count",
        "hash-retention",
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


def test_validator_rejects_missing_baseline_block(tmp_path) -> None:
    report_path = _generate_and_mutate(tmp_path, lambda data: data["corrective_evidence"].pop("baseline_once"))
    assert any("exactly one fixed baseline block" in problem for problem in validate_report(report_path))


def test_validator_rejects_duplicate_class_neighborhood(tmp_path) -> None:
    def mutate(data):
        section = next(section for section in data["sections"] if section["id"] == "winners")
        table = next(table for table in section["tables"] if table["id"] == "geometry_representations")
        table["rows"].append(table["rows"][0])

    report_path = _generate_and_mutate(tmp_path, mutate)
    assert any("duplicate neighborhood key" in problem for problem in validate_report(report_path))


def test_validator_rejects_unknown_reason(tmp_path) -> None:
    def mutate(data):
        section = next(section for section in data["sections"] if section["id"] == "analysis")
        table = next(table for table in section["tables"] if table["id"] == "geometry_threshold_map")
        table["rows"][0][5] = "unknown_reason"

    report_path = _generate_and_mutate(tmp_path, mutate)
    assert any("non-canonical reasons" in problem for problem in validate_report(report_path))


# ── G3: Plan F corrective-evidence emitter ─────────────────────────────────────


def test_emit_corrective_evidence_writes_json_only_evidence(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(_evidence, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(_evidence, "EVIDENCE_ROOT", tmp_path)
    report_path = generate_report(tmp_path)
    out_path = tmp_path / "corrective-evidence.json"

    assert emit_corrective_evidence(["--report", str(report_path), "--output", str(out_path)]) == 0
    assert out_path.is_file()

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["evidence_kind"] == "corrective-gram-geometry-plan-f"
    assert not list(out_path.parent.glob("*.md"))
    assert payload["synthetic_only"] is True
    assert payload["real_corpus_run"] is False
    proof = payload["architecture_proof"]
    assert proof["self_candidate_count"] == 0
    assert proof["segmentation_from_scorer_count"] == 0
    assert proof["threshold_count"] == 171
    # The static corpus-wide leave-one-out proof claim is only sound if the report it
    # summarizes actually contains no self-referential class-scoped neighborhoods.
    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    uniqueness = report_data["corrective_evidence"]["class_scoped_neighborhood_uniqueness"]
    assert proof["corpus_wide_leave_one_out"] is (uniqueness["self_candidate_count"] == 0)
    assert payload["benchmark"]["fixtures_only"] is True
    assert payload["scientific_hashes"]["report_json_sha256"] == hashlib.sha256(report_path.read_bytes()).hexdigest()


#: Benchmark fields the emitter observes from the live process (wall-clock and
#: allocation/rss high-water measurements).  These are genuine environment-observed
#: fixture measurements rather than derived evidence, so they legitimately vary run to
#: run; every other payload field must be byte-stable.
_MEASURED_BENCHMARK_FIELDS = ("elapsed_ms", "peak_rss_bytes", "peak_tracemalloc_bytes")


def test_emit_corrective_evidence_is_deterministic(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(_evidence, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(_evidence, "EVIDENCE_ROOT", tmp_path)
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
    "ordered_song_inputs": (
        CorpusSongSearchInput("s1", "b" * 64, "c" * 64, (0,), (0.5,), 1),
        CorpusSongSearchInput("s2", "d" * 64, "e" * 64, (2,), (0.25,), 1),
        CorpusSongSearchInput("s3", "f" * 64, "g" * 64, (5,), (0.25,), 1),
    ),
}


def _representation_id(**overrides: Any) -> str:
    return search_representation_id(**{**_BASE_REPRESENTATION_ID_KWARGS, **overrides})


def test_representation_id_accepts_the_canonical_representative_shape() -> None:
    assert len(_representation_id()) == 64


@pytest.mark.parametrize(
    "overrides",
    [
        {"experiment": ""},
        {"ordered_song_inputs": (CorpusSongSearchInput("s1", "b" * 64, "c" * 64, (0,), (0.5,), True),)},
        {"ordered_song_inputs": (CorpusSongSearchInput("s1", "b" * 64, "c" * 64, (0,), (0.5,), -1),)},
        {"ordered_song_inputs": (CorpusSongSearchInput("s1", "b" * 64, "c" * 64, (0,), (0.5,), "1"),)},
        {"ordered_song_inputs": "s1"},
        {"ordered_song_inputs": (CorpusSongSearchInput("s1", "b" * 64, "c" * 64, (0,), (float("nan"),), 1),)},
        {"ordered_song_inputs": (CorpusSongSearchInput("s1", "b" * 64, "c" * 64, (0,), (float("inf"),), 1),)},
        {"ordered_song_inputs": (CorpusSongSearchInput("s1", "b" * 64, "c" * 64, (True,), (0.5,), 1),)},
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
