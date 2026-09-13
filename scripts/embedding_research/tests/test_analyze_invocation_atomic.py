"""Spec-first tests for the obligation-backed analyze invocation terminal state (Plan M).

Research-only.  Pins the execution-reporting "atomic analyze" contract (CONTRACTS.md): an analyze
invocation is ``running`` (its obligations record present) until every requested backbone's MANDATORY
observed baseline geometry identity resolves; evidence scopes are append-only EVIDENCE and never
terminalize the invocation; only exactly one clean terminal ``completed`` outcome is reportable; any
later failure (after an earlier class or on a later backbone) makes the invocation ``failed`` and
excludes it from completed-report selection.

These tests drive the real producer helper surface (``db.analyze_scope.record_analyze_invocation`` /
``terminalize_analyze_completed`` / ``invocation_state``) and the grouped report-completion predicate
(``run._completed_analyze_run_ids`` / ``_resolve_report_run_id`` / ``_run_report``) so a failed or
incomplete-obligation run is never a completed analyze scope.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.embedding_research import run as run_mod
from scripts.embedding_research.db.analyze_scope import (
    AnalyzeInvocationError,
    AnalyzeInvocationIncompleteError,
    invocation_state,
    record_analyze_invocation,
    terminalize_analyze_completed,
)
from scripts.embedding_research.db.identity_persistence import write_analysis_rows
from scripts.embedding_research.db.provenance import write_run_provenance

_BASE = 1_700_000_000_000


def _geometry_id(backbone: str) -> str:
    """The exact geometry identity a backbone's mandatory observed baseline resolves under."""
    return f"geometry:{backbone}"


def _obligation(backbone: str) -> tuple[str, str]:
    """The ``(backbone, geometry_id)`` obligation pair recorded by an analyze invocation."""
    return (backbone, _geometry_id(backbone))


def _baseline_identity(backbone: str) -> SimpleNamespace:
    return SimpleNamespace(
        geometry_id=_geometry_id(backbone),
        observation_group_sha256=f"observation:{backbone}",
        geometry_semantics_version="gram-v1",
        numerical_profile_digest="profile-digest",
        threshold_id=f"observed-baseline:{backbone}",
        structural_identity=f"temporal_global:observed-medoid:{backbone}",
        search_representation_id=f"observed-medoid:{backbone}",
        evaluation_id="evaluation",
        scoring_semantics_version=1,
        execution_id="execution",
    )


def _seed_baseline_evidence(con, run_id: str, backbone: str) -> str:
    """Persist the MANDATORY observed baseline under its exact geometry identity."""
    write_analysis_rows(
        con,
        run_id=run_id,
        identity=_baseline_identity(backbone),
        metrics={"baseline_present": 1.0},
        evidence={"role": "mandatory-observed-baseline", "backbone": backbone},
    )
    return _geometry_id(backbone)


def _seed_failed_analyze_row(con, run_id: str) -> None:
    """Append a ``failed`` analyze provenance row (what ``_run_single_phase`` writes on exception)."""
    write_run_provenance(
        con,
        run_id=run_id,
        phase="analyze",
        status="failed",
        started_at=_BASE + 1,
        finished_at=_BASE + 2,
        output_artifact_hashes="",
    )


def _count_analyze_rows(con, run_id: str) -> int:
    return con.execute("SELECT count(*) FROM run_provenance WHERE run_id=? AND phase='analyze'", (run_id,)).fetchone()[
        0
    ]


def _count_geometry_evidence(con, run_id: str) -> int:
    return con.execute("SELECT count(*) FROM geometry_analysis_records WHERE run_id=?", (run_id,)).fetchone()[0]


# ── failure after the first class ─────────────────────────────────────────────


def test_failure_after_first_class_leaves_open_invocation_and_partial_evidence(con) -> None:
    """An exception after an earlier class records no terminal; partial evidence is retained, not reportable."""
    rid = "r-fail1class"
    record_analyze_invocation(con, run_id=rid, backbones=[_obligation("effnet")])
    _seed_baseline_evidence(con, rid, "effnet")  # first class already emitted its baseline (partial)
    _seed_failed_analyze_row(con, rid)  # the later-class exception

    state = invocation_state(con, run_id=rid)
    assert state["obligations_present"] is True
    assert state["terminal_completed"] is False  # scope/baseline evidence NEVER terminalized it

    # Append-only: the partial evidence is NOT deleted, and the run is NOT a completed scope.
    # The invocation obligations rode the SAME row as the scope evidence; the only second analyze
    # row is the ``failed`` provenance row `_run_single_phase` writes on exception (pre-existing).
    assert _count_geometry_evidence(con, rid) > 0
    assert _count_analyze_rows(con, rid) == 2  # invocation/scope row + the failed row
    assert rid not in run_mod._completed_analyze_run_ids(con)


def test_second_backbone_failure_leaves_open_invocation_fail_closed(con) -> None:
    """A failure on a later backbone (2nd of two) leaves the whole invocation failed / not reportable."""
    rid = "r-fail2bb"
    record_analyze_invocation(
        con,
        run_id=rid,
        backbones=[_obligation("effnet"), _obligation("musicnn")],
    )
    _seed_baseline_evidence(con, rid, "effnet")  # first backbone done
    # second backbone never emitted its baseline before the failure:
    _seed_failed_analyze_row(con, rid)

    assert _count_geometry_evidence(con, rid) > 0  # partial evidence retained
    assert rid not in run_mod._completed_analyze_run_ids(con)

    # Terminalizing now would refuse (the musicnn baseline obligation is unresolved): fail closed.
    with pytest.raises(AnalyzeInvocationIncompleteError):
        terminalize_analyze_completed(con, run_id=rid)


# ── missing obligations (scopes must never terminalize) ───────────────────────


def test_missing_obligation_baseline_never_terminalizes_invocation(con) -> None:
    """Scope/complete evidence with an unresolved obligation is not a completed invocation."""
    rid = "r-missing"
    record_analyze_invocation(con, run_id=rid, backbones=[_obligation("effnet")])
    # NO baseline evidence for effnet -> the mandatory obligation is unresolved.
    state = invocation_state(con, run_id=rid)
    assert state["obligations_present"] is True
    assert state["terminal_completed"] is False
    assert rid not in run_mod._completed_analyze_run_ids(con)  # scopes alone never terminalize

    with pytest.raises(AnalyzeInvocationIncompleteError):
        terminalize_analyze_completed(con, run_id=rid)


def test_terminalize_without_obligations_record_is_refused(con) -> None:
    """A run with no obligations-start record cannot be terminalized completed."""
    rid = "r-neverstarted"
    with pytest.raises(AnalyzeInvocationIncompleteError):
        terminalize_analyze_completed(con, run_id=rid)


# ── duplicate terminalization ─────────────────────────────────────────────────


def test_duplicate_terminalization_is_refused_exactly_one_terminal(con) -> None:
    """A clean all-obligation run terminalizes exactly once; a second attempt is refused."""
    rid = "r-clean"
    record_analyze_invocation(con, run_id=rid, backbones=[_obligation("effnet")])
    _seed_baseline_evidence(con, rid, "effnet")

    terminalize_analyze_completed(con, run_id=rid)  # first: clean completed
    assert invocation_state(con, run_id=rid)["terminal_completed"] is True
    assert rid in run_mod._completed_analyze_run_ids(con)

    with pytest.raises(AnalyzeInvocationError):
        terminalize_analyze_completed(con, run_id=rid)  # duplicate refused

    assert _count_analyze_rows(con, rid) == 1  # terminal rode the SAME row; no extra lifecycle rows
    assert run_mod._completed_analyze_run_ids(con) == [rid]  # still exactly one completed entry


# ── complete-plus-failed rows veto the run ────────────────────────────────────


def test_complete_plus_failed_rows_veto_run_and_refuse_report(con) -> None:
    """A completed terminal PLUS a later failed analyze row is contradictory -> never a completed scope."""
    rid = "r-contra"
    record_analyze_invocation(con, run_id=rid, backbones=[_obligation("effnet")])
    _seed_baseline_evidence(con, rid, "effnet")
    terminalize_analyze_completed(con, run_id=rid)
    assert rid in run_mod._completed_analyze_run_ids(con)
    _seed_failed_analyze_row(con, rid)  # later failed re-run/attempt of the same run

    assert rid not in run_mod._completed_analyze_run_ids(con)  # failed row vetoes the whole run
    assert run_mod._resolve_report_run_id(con, {"report_run_id": None}) is None

    # run-scoped geometry evidence exists but no completed scope -> the report phase fails closed.
    assert _count_geometry_evidence(con, rid) > 0
    with pytest.raises(run_mod._MissingArtifactError):
        run_mod._run_report(con, {"report_run_id": None}, "")


# ── no failed run is reportable / clean run still resolves amid failed siblings ──


def test_only_clean_obligation_run_resolves_amid_failed_sibling(con) -> None:
    """A newer failed run never shadows an older clean obligation-gated run for auto report selection."""
    clean = "r-auto-clean"
    bad = "r-auto-bad"
    # Older CLEAN run (obligations + baseline + terminal completed).
    record_analyze_invocation(con, run_id=clean, backbones=[_obligation("effnet")])
    _seed_baseline_evidence(con, clean, "effnet")
    terminalize_analyze_completed(con, run_id=clean)
    # Newer FAILED run (obligations recorded, failed before completing).
    record_analyze_invocation(con, run_id=bad, backbones=[_obligation("musicnn")])
    _seed_failed_analyze_row(con, bad)

    assert run_mod._completed_analyze_run_ids(con) == [clean]  # bad vetoed, never reportable
    assert run_mod._resolve_report_run_id(con, {"report_run_id": None}) == clean
    # An explicit request for the failed run is refused (not a completed analyze scope).
    assert run_mod._resolve_report_run_id(con, {"report_run_id": bad}) is None
