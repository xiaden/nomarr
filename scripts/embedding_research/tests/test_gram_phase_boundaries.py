"""R9 — exact seven-phase CLI, derived allowlist, fixture sentinels and seven timings."""

from __future__ import annotations

import ast
from pathlib import Path

import duckdb

from scripts.embedding_research import run as run_mod
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.tests import _report_seed
from scripts.embedding_research.tests._gram_evidence import emit_evidence

_EXPECTED_PHASES = ("ingest", "embed", "infer-heads", "geometry", "analyze", "head-analysis", "report")
_RUN_SOURCE = Path(run_mod.__file__).read_text(encoding="utf-8")
_RUN_TREE = ast.parse(_RUN_SOURCE)
_IMPORT_PREFIX = "scripts.embedding_research."


def _relative_imports(body: ast.AST) -> list[str]:
    paths = [
        binding.name[len(_IMPORT_PREFIX) :]
        for node in ast.walk(body)
        if isinstance(node, ast.Import)
        for binding in node.names
        if binding.name.startswith(_IMPORT_PREFIX)
    ]
    paths += [
        (node.module or "")[len(_IMPORT_PREFIX) :]
        for node in ast.walk(body)
        if isinstance(node, ast.ImportFrom)
        if (node.module or "").startswith(_IMPORT_PREFIX)
    ]
    return paths


def _function(name: str) -> ast.FunctionDef:
    for node in _RUN_TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"run.py has no {name}")


def test_exact_cli_phase_tuple_and_runner_map() -> None:
    assert run_mod.CLI_PHASES == _EXPECTED_PHASES
    assert frozenset(_EXPECTED_PHASES[:3]) == run_mod.AUDIO_PHASES
    assert frozenset(_EXPECTED_PHASES[3:]) == run_mod.DERIVED_PHASES
    assert frozenset(_EXPECTED_PHASES[3:]) == run_mod._DERIVED_CONSUMER_PHASES
    assert set(run_mod.CLI_PHASE_RUNNERS) == set(_EXPECTED_PHASES)
    for phase, runner in run_mod.CLI_PHASE_RUNNERS.items():
        assert runner.__name__ == "_run_" + phase.replace("-", "_")
    assert frozenset({"verify", "reindex", "cleanup", "reset"}) == run_mod.MAINTENANCE_COMMANDS
    emit_evidence(
        "r9-phase-tuple.json",
        {"phases": list(_EXPECTED_PHASES), "audio_count": 3, "derived_count": 4, "runner_count": len(_EXPECTED_PHASES)},
    )


def test_preflight_and_allowlist_contract() -> None:
    assert frozenset({"common", "config", "report", "streams", "db"}) == run_mod.DERIVED_ALLOWED_IMPORT_ROOTS
    assert frozenset({"discover_audio", "onnxruntime", "torch", "cuda"}) == run_mod.DERIVED_FORBIDDEN_TOKENS
    for phase in _EXPECTED_PHASES[3:]:
        body = _function("_run_" + phase.replace("-", "_"))
        for rel in _relative_imports(body):
            assert any(rel == root or rel.startswith(root + ".") for root in run_mod.DERIVED_ALLOWED_IMPORT_ROOTS), (
                f"{phase} imports non-CPU root {rel}"
            )
        source = ast.get_source_segment(_RUN_SOURCE, body) or ""
        for token in run_mod.DERIVED_FORBIDDEN_TOKENS:
            assert token not in source, f"{phase} contains forbidden token {token}"
    # A non-derived phase performs no derived preflight work.
    assert run_mod._preflight_derived_phase(None, "ingest", None) == []


def test_fixture_sentinels_and_timings() -> None:
    assert _report_seed.PHASE_NAMES == _EXPECTED_PHASES
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    try:
        _report_seed.seed_phase_timings(con)
        rows = con.execute("SELECT phase FROM phase_timings WHERE run_ts = ?", [_report_seed.RUN_TS]).fetchall()
        phases = [row[0] for row in rows]
        assert len(phases) == 7
        assert set(phases) == set(_EXPECTED_PHASES)
    finally:
        con.close()
    emit_evidence(
        "r9-seven-phase-timings.json",
        {"phase_count": 7, "phases": list(_EXPECTED_PHASES), "run_ts": _report_seed.RUN_TS},
    )
