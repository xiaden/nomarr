"""Deterministic storage / producer / report tests for Plan B P2 (atomic analyze diagnostics).

Research-only, deterministic (no corpus/model sweep).  Mirrors ``test_analyze_invocation_atomic.py``:
drives the real storage/report helpers directly over the conftest in-memory ``con`` (``ensure_schema``
already creates the ``analyze_incomplete_diagnostics`` table) — never a full catalog/stream build.

Contract under test (execution-reporting Plan B P2):

* A non-comparable (skipped) catalog representation is NEVER an ``analyze_metrics`` row and NEVER a
  complete ``analyze_scope_v2`` line.  Its only durable evidence is exactly ONE versioned diagnostic,
  written only after that backbone's MANDATORY observed ``global_pool:{backbone}:medoid`` baseline
  succeeds (baseline evidence present in the metric table => diagnostic is durable).
* The diagnostic carries version + run/backbone/strategy/sim/K + class/threshold identity + reason +
  representation/baseline corpus evidence + missing membership/count/digest; never omits the tested
  threshold/class membership.  Replacement is scoped to ``(run_id, strategy_key, sim_metric, k)`` and
  preserves unrelated runs exactly.
* The seven-section report renders the diagnostic VISIBLY INCOMPLETE (reason + corpus + missing
  evidence + class identity) with no winner/delta, and excludes a later-failed invocation's
  diagnostics from clean completed-report selection.
"""

from __future__ import annotations

import json

import pytest

from scripts.embedding_research.catalog_identity import EvaluationCorpusIdentity, SearchRepresentationClass
from scripts.embedding_research.common.catalog_analysis import CatalogAnalysisResult
from scripts.embedding_research.db import read_incomplete_analyze_diagnostics, write_analyze_metrics
from scripts.embedding_research.db.analyze_scope import run_row_scopes
from scripts.embedding_research.db.incomplete_diagnostics import (
    ANALYZE_SIM_METRIC,
    DIAGNOSTIC_VERSION,
    STATUS_INCOMPLETE,
    DiagnosticError,
    incomplete_diagnostic_columns,
    write_incomplete_analyze_diagnostic,
)
from scripts.embedding_research.report._retrieval import (
    query_incomplete_analyze_diagnostics,
    query_winners_metrics,
)
from scripts.embedding_research.report._summary import section_summary
from scripts.embedding_research.report._winners_report import section_winners

_BASE_RUN = "run-1"
_SIM = ANALYZE_SIM_METRIC  # "cosine"
_BASELINE_KEY = "global_pool:effnet:medoid"


# ---------------------------------------------------------------------------
# Constructors (deterministic synthetic identities + results)
# ---------------------------------------------------------------------------


def _identity(songs: tuple[str, ...] = ("s1", "s2", "s3"), corpus_hash: str = "HASHFULL"):
    return EvaluationCorpusIdentity(
        backbone="effnet",
        song_ids=songs,
        corpus_hash=corpus_hash,
        count=len(songs),
        eligible=True,
        comparable=True,
        missing_song_ids=(),
        missing_count=0,
        missing_digest=None,
        semantics_version=1,
    )


def _noncomparable(
    run_id: str = _BASE_RUN,
    skey: str = "catalog:effnet:v2:max_per_candidate_segment:k5:semhash1",
    config_ids: tuple[int, ...] = (10, 11),
    missing: tuple[str, ...] = ("s1",),
    semhash: str = "SEMHASH1",
    k: int = 5,
    corpus: EvaluationCorpusIdentity | None = None,
    missing_digest: str = "MISS",
) -> CatalogAnalysisResult:
    """A synthetic non-comparable (skipped) ``CatalogAnalysisResult`` for backbone 'effnet'."""
    cls = SearchRepresentationClass(
        search_representation_hash=semhash, canonical_config_id=config_ids[0], config_ids=config_ids
    )
    return CatalogAnalysisResult(
        run_id=run_id,
        backbone="effnet",
        config_ids=config_ids,
        representation_classes=(cls,),
        k=k,
        view_content_hash="VIEW1",
        score_variant="max_per_candidate_segment",
        scoring_semantics_version=2,
        strategy_key=skey,
        finite=True,
        metrics={},
        per_song={},
        per_query=(),
        n_queries=0,
        n_candidate_rows=len(config_ids),
        evaluation_corpus=corpus if corpus is not None else _identity(),
        comparable=False,
        missing_song_ids=missing,
        missing_count=len(missing),
        missing_digest=missing_digest,
    )


def _seed_mandatory_baseline(con, run_id: str = _BASE_RUN, backbone: str = "effnet", k: int = 5):
    """Seed the backbone's MANDATORY observed medoid baseline metric evidence (as if it succeeded)."""
    write_analyze_metrics(
        con,
        f"global_pool:{backbone}:medoid",
        "global_pool",
        "cosine",
        k,
        {"map_k": 0.5},
        run_id=run_id,
    )


def _metric_count(con, run_id: str, strategy_key: str) -> int:
    return con.execute(
        "SELECT COUNT(*) FROM analyze_metrics WHERE run_id = ? AND strategy_key = ?",
        [run_id, strategy_key],
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# 1. Storage: durable versioned diagnostic round-trip with full evidence
# ---------------------------------------------------------------------------


def test_write_read_roundtrip_carries_full_evidence(con):
    _seed_mandatory_baseline(con)
    res = _noncomparable()
    write_incomplete_analyze_diagnostic(
        con, run_id=_BASE_RUN, result=res, baseline_corpus=_identity(), reason="song s1 lost its medoid"
    )

    rows = read_incomplete_analyze_diagnostics(con, run_id=_BASE_RUN)
    assert len(rows) == 1
    r = rows[0]
    assert r["diagnostic_version"] == DIAGNOSTIC_VERSION
    assert r["status"] == STATUS_INCOMPLETE
    assert r["run_id"] == _BASE_RUN
    assert r["backbone"] == "effnet"
    assert r["strategy_key"] == res.strategy_key
    assert r["sim_metric"] == _SIM
    assert r["k"] == 5
    assert r["reason"] == "song s1 lost its medoid"
    # class/threshold identity never omitted.
    assert r["search_representation_hash"] == "SEMHASH1"
    assert r["canonical_config_id"] == 10
    assert json.loads(r["config_ids_json"]) == [10, 11]
    # representation corpus evidence (incomplete) + mandatory baseline corpus evidence.
    assert r["evaluation_corpus_comparable"] is False
    assert r["baseline_evaluation_corpus_hash"] == "HASHFULL"
    assert r["baseline_evaluation_corpus_count"] == 3
    assert r["baseline_evaluation_corpus_comparable"] is True
    # missing membership/count/digest.
    assert json.loads(r["missing_song_ids_json"]) == ["s1"]
    assert r["missing_count"] == 1
    assert r["missing_digest"] == "MISS"
    # creation timestamp (INTEGER milliseconds).
    assert isinstance(r["created_at"], int) and r["created_at"] > 0
    # run-scoped read excludes unrelated runs.
    assert read_incomplete_analyze_diagnostics(con, run_id="run-other") == []


def test_read_returns_raw_rows_in_column_order(con):
    _seed_mandatory_baseline(con)
    write_incomplete_analyze_diagnostic(
        con, run_id=_BASE_RUN, result=_noncomparable(), baseline_corpus=_identity(), reason="r"
    )
    rows = read_incomplete_analyze_diagnostics(con)
    assert len(rows) == 1
    assert set(rows[0].keys()) == set(incomplete_diagnostic_columns)
    # every column present in the schema-consistent column contract.
    assert len(rows[0]) == len(incomplete_diagnostic_columns)


def test_scoped_replacement_preserves_unrelated_runs(con):
    _seed_mandatory_baseline(con)
    sk_a = "catalog:effnet:v2:max_per_candidate_segment:k5:a"
    sk_b = "catalog:effnet:v2:max_per_candidate_segment:k5:b"
    write_incomplete_analyze_diagnostic(
        con, run_id=_BASE_RUN, result=_noncomparable(skey=sk_a), baseline_corpus=_identity(), reason="first-A"
    )
    write_incomplete_analyze_diagnostic(
        con, run_id=_BASE_RUN, result=_noncomparable(skey=sk_b), baseline_corpus=_identity(), reason="first-B"
    )
    write_incomplete_analyze_diagnostic(
        con,
        run_id="run-2",
        result=_noncomparable(run_id="run-2", skey=sk_a),
        baseline_corpus=_identity(),
        reason="run2-A",
    )
    # Re-run of the SAME (run_id, strategy_key, sim_metric, k) scope replaces ONLY that diagnostic.
    write_incomplete_analyze_diagnostic(
        con, run_id=_BASE_RUN, result=_noncomparable(skey=sk_a), baseline_corpus=_identity(), reason="replaced-A"
    )
    rows = read_incomplete_analyze_diagnostics(con, run_id=_BASE_RUN)
    assert len(rows) == 2  # A replaced, B preserved.
    by_key = {r["strategy_key"]: r["reason"] for r in rows}
    assert by_key[sk_a] == "replaced-A"
    assert by_key[sk_b] == "first-B"
    # The unrelated run-2 diagnostic is untouched.
    run2 = read_incomplete_analyze_diagnostics(con, run_id="run-2")
    assert len(run2) == 1 and run2[0]["reason"] == "run2-A"


def test_write_refuses_comparable_result(con):
    _seed_mandatory_baseline(con)
    comparable = _noncomparable()
    # A COMPLETE result must never be recorded as an incomplete diagnostic (fail closed).
    comp = CatalogAnalysisResult(
        run_id=_BASE_RUN,
        backbone="effnet",
        config_ids=(10,),
        representation_classes=(SearchRepresentationClass("SEMHASH1", 10, (10,)),),
        k=5,
        view_content_hash="V",
        score_variant="max_per_candidate_segment",
        scoring_semantics_version=2,
        strategy_key=comparable.strategy_key,
        finite=True,
        metrics={"map_k": 0.5},
        per_song={},
        per_query=(),
        n_queries=7,
        n_candidate_rows=1,
        evaluation_corpus=_identity(),
        comparable=True,
    )
    with pytest.raises(DiagnosticError):
        write_incomplete_analyze_diagnostic(
            con, run_id=_BASE_RUN, result=comp, baseline_corpus=_identity(), reason="should refuse"
        )
    assert read_incomplete_analyze_diagnostics(con, run_id=_BASE_RUN) == []


# ---------------------------------------------------------------------------
# 2. Producer: zero metric rows, zero complete scope rows, ONE durable diagnostic
#    after the mandatory baseline succeeds.
# ---------------------------------------------------------------------------


def test_non_comparable_zero_metrics_zero_complete_scope_one_durable_diagnostic(con):
    # Backbone's MANDATORY observed baseline evidence is present (it succeeded) — the P2-S2 gate
    # under which the producer is allowed to persist diagnostics.
    _seed_mandatory_baseline(con)
    res = _noncomparable()
    write_incomplete_analyze_diagnostic(
        con, run_id=_BASE_RUN, result=res, baseline_corpus=_identity(), reason="not comparable"
    )

    # The skipped representation is NEVER an analyze_metrics row.
    assert _metric_count(con, _BASE_RUN, res.strategy_key) == 0
    # ... and never a complete analyze_scope_v2 line.
    assert run_row_scopes(con, run_id=_BASE_RUN) == frozenset()
    # Only the mandatory baseline metric rows exist for this run.
    total = con.execute("SELECT COUNT(*) FROM analyze_metrics WHERE run_id = ?", [_BASE_RUN]).fetchone()[0]
    assert total == 1
    # Exactly ONE durable diagnostic.
    rows = read_incomplete_analyze_diagnostics(con, run_id=_BASE_RUN)
    assert len(rows) == 1
    assert rows[0]["strategy_key"] == res.strategy_key
    # The diagnostic itself must not have introduced metric/scope rows (writer is diagnostic-only).
    assert _metric_count(con, _BASE_RUN, res.strategy_key) == 0
    assert run_row_scopes(con, run_id=_BASE_RUN) == frozenset()


# ---------------------------------------------------------------------------
# 3. Report path: visible reason/identity/corpus/missing evidence, incomplete,
#    no winner/delta.
# ---------------------------------------------------------------------------


def test_query_normalizes_to_report_incomplete_shape(con):
    _seed_mandatory_baseline(con)
    res = _noncomparable()
    write_incomplete_analyze_diagnostic(
        con, run_id=_BASE_RUN, result=res, baseline_corpus=_identity(), reason="not comparable"
    )
    diag = query_incomplete_analyze_diagnostics(con, run_id=_BASE_RUN)
    assert len(diag) == 1
    e = diag[0]
    # Representation-incomplete: metric '' (never a per-metric partial cell), comparable False.
    assert e["metric"] == ""
    assert e["strategy_key"] == res.strategy_key
    assert e["reason"] == "not comparable"
    assert e["backbone"] == "effnet"
    assert e["baseline_strategy_key"] == _BASELINE_KEY
    assert e["representation_evaluation_corpus_comparable"] is False
    assert e["representation_missing_count"] == 1
    assert e["representation_missing_digest"] == "MISS"
    # class identity enrichment rides on the entry.
    assert e["search_representation_hash"] == "SEMHASH1"
    assert e["canonical_config_id"] == 10
    assert e["config_ids"] == (10, 11)
    assert e["missing_song_ids"] == ("s1",)
    # unrelated-run read is empty.
    assert query_incomplete_analyze_diagnostics(con, run_id="run-other") == ()


def test_winners_section_renders_incomplete_without_winner_or_delta(con):
    _seed_mandatory_baseline(con)
    res = _noncomparable()
    write_incomplete_analyze_diagnostic(
        con, run_id=_BASE_RUN, result=res, baseline_corpus=_identity(), reason="not comparable"
    )
    wdf = query_winners_metrics(con, run_id=_BASE_RUN)
    assert len(wdf.attrs["persisted_incomplete_diagnostics"]) == 1
    section = section_winners(wdf)
    subs = section.get("subsections", [])
    assert len(subs) == 1 and "effnet" in subs[0]["title"]

    incomplete_tables = [
        t for s in subs for t in s.get("tables", []) if t["id"].startswith("incomplete_representations_")
    ]
    assert len(incomplete_tables) == 1
    table = incomplete_tables[0]
    cols = table["columns"]
    assert len(table["rows"]) == 1
    row = dict(zip(cols, table["rows"][0], strict=False))
    # visible reason + representation missing evidence.
    assert row["reason"] == "not comparable"
    assert row["representation_missing_count"] == "1"
    assert row["representation_missing_digest"] == "MISS"
    assert row["strategy_key"] == res.strategy_key
    assert row["representation_evaluation_corpus_comparable"] == "False"
    assert row["baseline_evaluation_corpus_comparable"] == "True"
    # visible class identity (tested threshold/class evidence never omitted).
    assert row["search_representation_hash"] == "SEMHASH1"
    assert row["config_ids"] == "10,11"
    assert row["missing_song_ids"] == "s1"
    # incomplete status: NO winner/delta columns appear anywhere in the section.
    for s in subs:
        for t in s.get("tables", []):
            assert not any(c.startswith("winner") or c == "delta" for c in t["columns"])
    assert not any(t["id"].startswith("winner_delta_") for s in subs for t in s.get("tables", []))


def test_summary_counts_incomplete_representation(con):
    _seed_mandatory_baseline(con)
    write_incomplete_analyze_diagnostic(
        con, run_id=_BASE_RUN, result=_noncomparable(), baseline_corpus=_identity(), reason="not comparable"
    )
    wdf = query_winners_metrics(con, run_id=_BASE_RUN)
    section = section_summary(wdf)
    table = next(t for t in section.get("tables", []) if t["id"] == "catalog_result_status")
    row = dict(zip(table["columns"], table["rows"][0], strict=False))
    assert int(row["incomplete_representations"]) == 1
    assert int(row["active_catalog_classes"]) == 0  # non-comparable class is not an active class.


def test_failed_invocation_diagnostics_excluded_from_clean_run_selection(con):
    # Two runs both persisted a diagnostic + mandatory baseline.  run-failed's invocation later
    # FAILED (Phase-1 veto), so clean completed-report selection must only surface run-clean's
    # diagnostics — a later-failed run's diagnostics are never rendered as a clean report.
    clean = _noncomparable(run_id="run-clean", skey="catalog:effnet:v2:max_per_candidate_segment:k5:clean")
    failed = _noncomparable(
        run_id="run-failed", skey="catalog:effnet:v2:max_per_candidate_segment:k5:failed", missing=("s9",)
    )
    _seed_mandatory_baseline(con, run_id="run-clean")
    _seed_mandatory_baseline(con, run_id="run-failed")
    write_incomplete_analyze_diagnostic(
        con, run_id="run-clean", result=clean, baseline_corpus=_identity(), reason="clean-run diag"
    )
    write_incomplete_analyze_diagnostic(
        con, run_id="run-failed", result=failed, baseline_corpus=_identity(), reason="failed-run diag"
    )
    # run_id-scoped read for the CLEAN run carries ONLY its own diagnostic.
    assert [e["strategy_key"] for e in query_incomplete_analyze_diagnostics(con, run_id="run-clean")] == [
        clean.strategy_key
    ]
    wdf = query_winners_metrics(con, run_id="run-clean")
    assert [e["strategy_key"] for e in wdf.attrs["persisted_incomplete_diagnostics"]] == [clean.strategy_key]
    section = section_winners(wdf)
    reason_texts = [row for s in section.get("subsections", []) for t in s.get("tables", []) for row in t["rows"]]
    assert "failed-run diag" not in reason_texts
