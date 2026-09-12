"""Scan runtime imports for excluded optimization/ANN/production dependencies."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
if str(_HERE.parents[3]) not in sys.path:
    sys.path.insert(0, str(_HERE.parents[3]))

from scripts.embedding_research.tools._evidence import (
    PACKAGE_ROOT,
    imported_names,
    iter_python_files,
    relative,
    write_evidence,
)

_EXCLUDED_ROOTS = (
    "torch",
    "onnxruntime",
    "faiss",
    "annoy",
    "hnswlib",
    "nomarr",
    "frontend",
    "ctp",
    "spectral",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan runtime imports for excluded scope.")
    parser.add_argument("--root", default=str(PACKAGE_ROOT))
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)

    root = Path(arguments.root).resolve()
    files = iter_python_files(root, include_tests=False)
    violations: list[dict] = []
    for path in files:
        imported = imported_names(path.read_text(encoding="utf-8"))
        excluded = sorted(imported.intersection(_EXCLUDED_ROOTS))
        if excluded:
            violations.append({"path": relative(path), "imports": excluded})

    write_evidence(
        arguments.output,
        {
            "rule": "excluded-scope-imports",
            "excluded_roots": list(_EXCLUDED_ROOTS),
            "scanned_files": [relative(path) for path in files],
            "violations": violations,
            "exit_status": "PASS" if not violations else "NONZERO",
        },
    )
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
