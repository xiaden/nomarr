"""Focused tests for durable non-comparable geometry diagnostics (Plan M).

The ``analyze_incomplete_diagnostics`` table carries the ONLY durable evidence for a geometry
representation the analyze pass could not score completely.  These tests pin the writer/reader
contract: complete exact geometry identity, fail-closed refusal of a comparable result, app-scoped
replacement (so re-running one scope never touches unrelated runs), and strict separation from
``geometry_analysis_records`` (a diagnostic is never an analysis metric row).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.embedding_research.db.incomplete_diagnostics import (
    ANALYZE_SIM_METRIC,
    DIAGNOSTIC_VERSION,
    STATUS_INCOMPLETE,
    DiagnosticError,
    read_incomplete_analyze_diagnostics,
    write_incomplete_analyze_diagnostic,
)

_TEXT_IDENTITY_FIELDS = (
    "geometry_id",
    "observation_id",
    "geometry_semantics_version",
    "numerical_profile_digest",
    "threshold_id",
    "structural_identity",
    "search_representation_id",
    "evaluation_id",
    "execution_id",
)


def _identity(**overrides):
    values = {
        "geometry_id": "g",
        "observation_id": "o",
        "geometry_semantics_version": "gram-v1",
        "numerical_profile_digest": "p",
        "threshold_id": "t",
        "structural_identity": "struct",
        "search_representation_id": "s",
        "evaluation_id": "e",
        "scoring_semantics_version": 1,
        "execution_id": "x",
    }
    values.update(overrides)
    return values


def _write(con, *, run_id="r", identity=None, **kwargs):
    write_incomplete_analyze_diagnostic(
        con,
        run_id=run_id,
        identity=identity if identity is not None else _identity(),
        reason="lost eligible whole-song observation",
        backbone="effnet",
        experiment="temporal_global",
        baseline_corpus=SimpleNamespace(corpus_hash="baseline-hash", count=3, comparable=True),
        evaluation_corpus=SimpleNamespace(corpus_hash="evaluation-hash", count=2),
        missing_song_ids=("song-b", "song-a"),
        **kwargs,
    )


def test_diagnostic_roundtrip_exact_identity_and_baseline_ordering(con) -> None:
    _write(con)
    rows = read_incomplete_analyze_diagnostics(con, run_id="r")
    assert len(rows) == 1
    row = rows[0]
    assert row["run_id"] == "r"
    assert row["status"] == STATUS_INCOMPLETE
    assert row["diagnostic_version"] == DIAGNOSTIC_VERSION
    assert row["sim_metric"] == ANALYZE_SIM_METRIC
    assert row["geometry_id"] == "g"
    assert row["observation_id"] == "o"
    assert row["structural_identity"] == "struct"
    assert row["scoring_semantics_version"] == 1
    assert row["baseline_strategy_key"] == "global_pool:effnet:medoid"
    assert row["baseline_evaluation_corpus_hash"] == "baseline-hash"
    assert row["baseline_evaluation_corpus_count"] == 3
    assert row["baseline_evaluation_corpus_comparable"] is True
    assert row["evaluation_corpus_comparable"] is False
    assert row["missing_count"] == 2
    assert row["missing_song_ids_json"] == '["song-a","song-b"]'
    # A diagnostic is NEVER an analysis metric row.
    assert con.execute("SELECT count(*) FROM geometry_analysis_records").fetchone()[0] == 0


def test_comparable_result_is_refused(con) -> None:
    with pytest.raises(DiagnosticError, match="COMPARABLE"):
        _write(con, comparable=True)
    assert read_incomplete_analyze_diagnostics(con, run_id="r") == []


@pytest.mark.parametrize("field", _TEXT_IDENTITY_FIELDS)
def test_incomplete_text_identity_is_refused(con, field: str) -> None:
    with pytest.raises(DiagnosticError, match="required"):
        _write(con, identity=_identity(**{field: ""}))


def test_scoring_semantics_version_must_be_integer(con) -> None:
    with pytest.raises(DiagnosticError, match="scoring_semantics_version must be an integer"):
        _write(con, identity=_identity(scoring_semantics_version="not-an-int"))


def test_same_scope_replaces_and_unrelated_scopes_survive(con) -> None:
    _write(con, run_id="r", identity=_identity(evaluation_id="e1"))
    _write(con, run_id="r", identity=_identity(evaluation_id="e1"))  # replacement, not a second row
    _write(con, run_id="r", identity=_identity(evaluation_id="e2"))
    _write(con, run_id="other", identity=_identity(evaluation_id="e1"))

    run_rows = read_incomplete_analyze_diagnostics(con, run_id="r")
    assert len(run_rows) == 2
    assert {row["evaluation_id"] for row in run_rows} == {"e1", "e2"}
    assert len(read_incomplete_analyze_diagnostics(con, run_id="other")) == 1
    assert len(read_incomplete_analyze_diagnostics(con)) == 3
