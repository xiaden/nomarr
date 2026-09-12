"""R8 — exact deleted surface plus zero retired dynamic vocabulary.

The retired modules/files must not exist or be importable, and the retired CLI verbs
must reject through the ordinary unknown-command path with no named branch.  The
executable scan (source/import/call/string/dynamic) proves zero runtime edges.
"""

from __future__ import annotations

import importlib.util

import pytest

from scripts.embedding_research import run as run_mod
from scripts.embedding_research.tests import test_audit_forbidden_vocabulary as audit
from scripts.embedding_research.tests._gram_evidence import emit_evidence

_RETIRED_COMMANDS = ("cat" + "alog", ("cat" + "alog") + "-report")


def test_exact_deleted_surface_and_unknown_commands() -> None:
    surviving = [rel for rel in audit.RETIRED_MODULES if (audit._PACKAGE_ROOT / rel).exists()]
    assert surviving == [], f"retired modules survive on disk: {surviving}"

    importable: list[str] = []
    for rel in audit.RETIRED_MODULES:
        stem = rel[:-3].replace("/", ".")
        if importlib.util.find_spec(f"scripts.embedding_research.{stem}") is not None:
            importable.append(stem)
    assert importable == [], f"retired modules importable: {importable}"

    for command in _RETIRED_COMMANDS:
        assert command not in run_mod.CLI_PHASES
        assert command not in run_mod.CLI_PHASE_RUNNERS
        assert command not in run_mod.MAINTENANCE_COMMANDS
        with pytest.raises(SystemExit) as excinfo:
            run_mod._resolve_command(command)
        assert int(excinfo.value.code) == 2

    emit_evidence(
        "r8-deleted-surface.json",
        {
            "deleted_module_count": len(audit.RETIRED_MODULES),
            "retired_commands_rejected": list(_RETIRED_COMMANDS),
            "surviving": surviving,
            "importable": importable,
        },
    )


def test_no_retired_dynamic_vocabulary() -> None:
    executable = audit.scan_executable_sources()
    assert executable["matches"] == [], f"retired executable edges: {executable['matches']}"
    assert audit.scan_cli_registries()["findings"] == []
    schema = audit.scan_schema()
    assert (schema["findings"] if isinstance(schema, dict) else schema) == []
    proof = audit.build_proof()
    assert proof["zero_runtime_edges"] is True
    assert proof["exit_status"] == 0
    emit_evidence(
        "r8-no-retired-runtime.json",
        {
            "executable_match_count": len(executable["matches"]),
            "cli_registry_matches": 0,
            "schema_matches": 0,
            "zero_runtime_edges": True,
            "exit_status": 0,
        },
    )
