"""Count geometry decode and segmentation calls to prove batching and collapse."""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
if str(_HERE.parents[3]) not in sys.path:
    sys.path.insert(0, str(_HERE.parents[3]))

from scripts.embedding_research.tools._evidence import (
    PACKAGE_ROOT,
    relative,
    write_evidence,
)

_DECODE = "_verified_geometry_decode"
_COLLAPSE = "collapse_search_representations"
_SCORER = "score_unique_geometry_representations"
_SEGMENT = "analyze_all_thresholds"


def _function_calls(tree: ast.Module) -> dict[str, list[str]]:
    calls: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        found = [
            child.func.id
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        ]
        calls[node.name] = found
    return calls


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit geometry decode/segmentation call counters.")
    parser.add_argument("--root", default=str(PACKAGE_ROOT))
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)

    root = Path(arguments.root).resolve()
    modules = [root / "common/threshold_analysis.py", root / "common/geometry_analysis.py"]
    counters: dict[str, dict[str, int]] = {}
    violations: list[str] = []
    for module in modules:
        if not module.is_file():
            continue
        rel = relative(module)
        calls = _function_calls(ast.parse(module.read_text(encoding="utf-8")))
        decode_calls = sum(1 for found in calls.values() for name in found if name == _DECODE)
        collapse_calls = sum(1 for found in calls.values() for name in found if name == _COLLAPSE)
        counters[rel] = {"decode_calls": decode_calls, "collapse_calls": collapse_calls}
        scorer_calls = calls.get(_SCORER, [])
        if _SEGMENT in scorer_calls:
            violations.append(f"{rel}:{_SCORER} calls {_SEGMENT}")

    write_evidence(
        arguments.output,
        {
            "rule": "one-decode-per-geometry-and-no-scorer-segmentation",
            "counters": counters,
            "scorer_segmentation_violations": violations,
            "exit_status": "PASS" if not violations else "NONZERO",
        },
    )
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
