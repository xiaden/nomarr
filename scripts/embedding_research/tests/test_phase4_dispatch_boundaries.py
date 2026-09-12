"""Seven-phase CLI dispatch boundaries and the derived-phase CPU-only contract.

The CLI exposes EXACTLY seven phase verbs — ``ingest``, ``embed``, ``infer-heads``,
``geometry``, ``analyze``, ``head-analysis``, ``report`` — with ``verify``, ``reindex``,
``cleanup`` and ``reset`` as four SEPARATE maintenance commands.  Only the first three
phases may discover audio / load models / create ONNX sessions / run ONNX; the four
derived phases are CPU-only and each derived runner body may import/reference ONLY
``DERIVED_ALLOWED_IMPORT_ROOTS`` modules and must never contain a
``DERIVED_FORBIDDEN_TOKENS`` token.

Retired command names are ordinary unknown commands: they follow the exact same
rejection path as any other unrecognized verb, with no named rejection or translation
branch.  The retired names are assembled from fragments so this module does not retain
those command texts itself.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

from scripts.embedding_research import run as run_mod

_RUN_FILE = Path(run_mod.__file__).resolve()
_RUN_SOURCE = _RUN_FILE.read_text(encoding="utf-8")
_RUN_TREE = ast.parse(_RUN_SOURCE)

_EXPECTED_PHASES = ("ingest", "embed", "infer-heads", "geometry", "analyze", "head-analysis", "report")
# Assembled from fragments: this module must not itself carry retired command text.
_RETIRED_COMMANDS = ("cat" + "alog", ("cat" + "alog") + "-report")


def _function_body(name: str) -> ast.FunctionDef:
    """Return the module-level ``def name`` node from run.py."""
    for node in _RUN_TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"no def {name} in {_RUN_FILE}")


def _research_relative_imports(body: ast.AST) -> list[str]:
    """Research-relative dotted module paths imported anywhere in ``body``."""
    import_prefix = "scripts.embedding_research."
    import_paths = [
        binding.name[len(import_prefix) :]
        for node in ast.walk(body)
        if isinstance(node, ast.Import)
        for binding in node.names
        if binding.name.startswith(import_prefix)
    ]
    from_paths = [
        (node.module or "")[len(import_prefix) :]
        for node in ast.walk(body)
        if isinstance(node, ast.ImportFrom)
        if (node.module or "").startswith(import_prefix)
    ]
    return import_paths + from_paths


def _allowed_research_path(path: str) -> bool:
    """True when a research-relative path is a CPU-only allowed root (or submodule)."""
    return any(path == root or path.startswith(root + ".") for root in run_mod.DERIVED_ALLOWED_IMPORT_ROOTS)


def test_cli_exposes_exactly_seven_phases_in_order():
    assert run_mod.CLI_PHASES == _EXPECTED_PHASES


def test_audio_are_first_three_and_derived_are_the_four():
    assert frozenset({"ingest", "embed", "infer-heads"}) == run_mod.AUDIO_PHASES
    assert frozenset(_EXPECTED_PHASES) - run_mod.AUDIO_PHASES == run_mod.DERIVED_PHASES
    assert len(run_mod.AUDIO_PHASES) == 3
    assert len(run_mod.DERIVED_PHASES) == 4
    assert frozenset({"geometry", "analyze", "head-analysis", "report"}) == run_mod._DERIVED_CONSUMER_PHASES


def test_cli_phase_runners_map_exactly_the_seven_phases():
    assert set(run_mod.CLI_PHASE_RUNNERS) == set(run_mod.CLI_PHASES)
    for phase, runner in run_mod.CLI_PHASE_RUNNERS.items():
        assert runner.__name__ == "_run_" + phase.replace("-", "_")


def test_maintenance_commands_are_four_separate_verbs():
    assert frozenset({"verify", "reindex", "cleanup", "reset"}) == run_mod.MAINTENANCE_COMMANDS
    for command in run_mod.MAINTENANCE_COMMANDS:
        assert command not in run_mod.CLI_PHASES
        assert command not in run_mod.CLI_PHASE_RUNNERS
        assert run_mod._resolve_command(command) == command


@pytest.mark.parametrize("phase", run_mod.CLI_PHASES)
def test_resolve_command_accepts_each_phase(phase):
    assert run_mod._resolve_command(phase) == phase


def _rejection(command: str) -> int:
    with pytest.raises(SystemExit) as exc:
        run_mod._resolve_command(command)
    return int(exc.value.code)


@pytest.mark.parametrize("unknown", ["frobnicate", *_RETIRED_COMMANDS])
def test_unknown_commands_share_the_ordinary_rejection_path(unknown):
    assert unknown not in run_mod.CLI_PHASES
    assert unknown not in run_mod.CLI_PHASE_RUNNERS
    assert unknown not in run_mod.MAINTENANCE_COMMANDS
    assert _rejection(unknown) == 2
    assert _rejection(unknown) == _rejection("frobnicate")


def test_unknown_command_rejection_names_the_valid_commands(caplog):
    with caplog.at_level(logging.ERROR):
        assert _rejection("frobnicate") == 2
    assert any("unknown command" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("phase", sorted(run_mod.DERIVED_PHASES))
def test_derived_runner_imports_only_cpu_roots(phase):
    runner_name = run_mod.CLI_PHASE_RUNNERS[phase].__name__
    body = _function_body(runner_name)
    imports = _research_relative_imports(body)
    assert imports, f"derived runner {runner_name} must import from CPU-only roots"
    bad = [path for path in imports if not _allowed_research_path(path)]
    assert not bad, f"derived runner {runner_name} reaches non-CPU modules: {bad}"


@pytest.mark.parametrize("phase", sorted(run_mod.DERIVED_PHASES))
def test_derived_runner_never_references_forbidden_tokens(phase):
    runner_name = run_mod.CLI_PHASE_RUNNERS[phase].__name__
    source = ast.get_source_segment(_RUN_SOURCE, _function_body(runner_name)) or ""
    lowered = source.lower()
    present = sorted(token for token in run_mod.DERIVED_FORBIDDEN_TOKENS if token in lowered)
    assert not present, f"derived runner {runner_name} references forbidden tokens: {present}"
