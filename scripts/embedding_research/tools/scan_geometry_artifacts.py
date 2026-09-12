"""Prove no filesystem Gram geometry artifact exists anywhere in the research tree.

A single searchable token list covers the disallowed filesystem payloads. Runtime matches
must be empty; the scanner exits nonzero if any appear.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
if str(_HERE.parents[3]) not in sys.path:
    sys.path.insert(0, str(_HERE.parents[3]))

from scripts.embedding_research.tools._evidence import (
    PACKAGE_ROOT,
    iter_python_files,
    relative,
    scan_files,
    write_evidence,
)


def _tokens() -> tuple[str, ...]:
    join = "".join
    return (
        join(("gram", ".npy")),
        join(("gram", ".bin")),
        join(("gram", ".f32")),
        join(("geometry", ".gram")),
        join(("gram_", "blob.npy")),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan for filesystem Gram artifacts.")
    parser.add_argument("--root", default=str(PACKAGE_ROOT))
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)

    root = Path(arguments.root).resolve()
    files = iter_python_files(root, include_tests=True)
    matches = scan_files(files, _tokens())
    write_evidence(
        arguments.output,
        {
            "rule": "no-filesystem-gram-artifact",
            "root": relative(root),
            "tokens": list(_tokens()),
            "scanned_files": [relative(path) for path in files],
            "filesystem_matches": matches,
            "exit_status": "NONZERO" if matches else "PASS",
        },
    )
    return 1 if matches else 0


if __name__ == "__main__":
    raise SystemExit(main())
