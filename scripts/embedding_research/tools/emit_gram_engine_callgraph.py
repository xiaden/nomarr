"""Emit the canonical Gram-engine call graph proof.

Only one function owns threshold segmentation (``analyze_all_thresholds``). The emitted
graph records every intra-package call edge in the geometry analysis modules so the
validator can prove the single-engine invariant without executing inference.
"""

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
    definition_names,
    relative,
    write_evidence,
)

_ENGINE_MODULES = ("common/threshold_analysis.py", "common/geometry_analysis.py", "common/embed.py")
_ENGINE_OWNER = "analyze_all_thresholds"


def _edges(path: Path) -> list[dict[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    edges: list[dict[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        edges.extend(
            {"caller": node.name, "callee": child.func.id}
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        )
    return edges


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit the single Gram-engine call graph.")
    parser.add_argument("--root", default=str(PACKAGE_ROOT))
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)

    root = Path(arguments.root).resolve()
    modules = [root / name for name in _ENGINE_MODULES]
    graph: dict[str, list[dict[str, str]]] = {}
    owners: list[dict[str, str]] = []
    for module in modules:
        if not module.is_file():
            continue
        rel = relative(module)
        graph[rel] = _edges(module)
        if _ENGINE_OWNER in definition_names(module.read_text(encoding="utf-8")):
            owners.append({"module": rel, "symbol": _ENGINE_OWNER})

    engine_callers = sorted(
        {edge["caller"] for edges in graph.values() for edge in edges if edge["callee"] == _ENGINE_OWNER}
    )
    write_evidence(
        arguments.output,
        {
            "rule": "single-canonical-gram-engine",
            "engine_owner": _ENGINE_OWNER,
            "engine_definition_sites": owners,
            "engine_callers": engine_callers,
            "call_graph": graph,
            "exit_status": "PASS" if len(owners) == 1 else "NONZERO",
        },
    )
    return 0 if len(owners) == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
