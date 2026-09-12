"""Emit the exact seven-phase boundary tuple and dynamic registry keys."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve()
if str(_HERE.parents[3]) not in sys.path:
    sys.path.insert(0, str(_HERE.parents[3]))

from scripts.embedding_research.tools._evidence import PACKAGE_ROOT, relative, write_evidence


def _extract(root: Path) -> dict[str, Any]:
    """Read the phase registry from the CLI module explicitly (no AST approximation)."""
    sys.path.insert(0, str(root.parents[1]))
    from scripts.embedding_research import run as run_module

    return {
        "cli_phases": list(run_module.CLI_PHASES),
        "audio_phases": sorted(run_module.AUDIO_PHASES),
        "derived_phases": sorted(run_module.DERIVED_PHASES),
        "runner_keys": list(run_module.CLI_PHASE_RUNNERS),
        "derived_allowed_import_roots": sorted(run_module.DERIVED_ALLOWED_IMPORT_ROOTS),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit phase boundary evidence.")
    parser.add_argument("--root", default=str(PACKAGE_ROOT))
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)

    root = Path(arguments.root).resolve()
    extracted = _extract(root)
    cli_phases = extracted["cli_phases"]
    audio_phases = extracted["audio_phases"]
    derived = extracted["derived_phases"]
    allowed_roots = extracted["derived_allowed_import_roots"]
    runner_keys = extracted["runner_keys"]

    violations: list[str] = []
    if len(cli_phases) != 7:
        violations.append(f"CLI phase tuple must hold seven phases, saw {len(cli_phases)}")
    if set(runner_keys) != set(cli_phases):
        violations.append("runner map keys differ from the CLI phase tuple")
    if set(derived) != {"geometry", "analyze", "head-analysis", "report"}:
        violations.append(f"unexpected derived phase set: {derived}")

    write_evidence(
        arguments.output,
        {
            "rule": "exact-seven-phase-boundary",
            "source": relative(root / "run.py"),
            "cli_phases": cli_phases,
            "audio_phases": audio_phases,
            "derived_phases": derived,
            "runner_keys": runner_keys,
            "derived_allowed_import_roots": allowed_roots,
            "violations": violations,
            "exit_status": "PASS" if not violations else "NONZERO",
        },
    )
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
