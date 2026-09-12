"""Independent retired-runtime scanner for the six named hard-cut rules.

Each rule is executable on its own and fails nonzero only on a runtime edge (a match in
non-test executable or configuration source, or in the generated fixture report). Test
references to the retired scalar oracle are recorded separately and are allowed: they
cannot satisfy a runtime edge.
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
    rule_for,
    scan_files,
    write_evidence,
)

_CONFIG_SUFFIXES = (".toml", ".cfg", ".ini")
_REPORT_NAMES = ("report.json", "report.html")


def _config_files(root: Path) -> list[Path]:
    return [path for suffix in _CONFIG_SUFFIXES for path in sorted(root.rglob(f"*{suffix}"))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed retired-runtime edge scan.")
    parser.add_argument("--root", default=str(PACKAGE_ROOT))
    parser.add_argument("--include-tests", action="store_true")
    parser.add_argument("--include-config", action="store_true")
    parser.add_argument("--include-generated", action="store_true")
    parser.add_argument("--rule", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)

    root = Path(arguments.root).resolve()
    tokens = rule_for(arguments.rule)
    runtime_files = iter_python_files(root, include_tests=False)
    scanned = list(runtime_files)
    if arguments.include_config:
        scanned.extend(_config_files(root))
    runtime_matches = scan_files(scanned, tokens)

    test_references: list[dict] = []
    if arguments.include_tests:
        test_files = [path for path in iter_python_files(root, include_tests=True) if "tests" in path.parts]
        test_references = scan_files(test_files, tokens)

    generated_matches: list[dict] = []
    if arguments.include_generated:
        report_dir = (
            root.parents[1] / "artifacts/evidence/threshold-independent-per-song-gram-geometry-migration/report"
        )
        for name in _REPORT_NAMES:
            candidate = report_dir / name
            if candidate.is_file():
                generated_matches.extend(scan_files([candidate], tokens))

    write_evidence(
        arguments.output,
        {
            "rule": arguments.rule,
            "root": relative(root),
            "tokens": list(tokens),
            "scanned_runtime_files": [relative(path) for path in scanned],
            "runtime_matches": runtime_matches,
            "test_references": test_references,
            "generated_matches": generated_matches,
            "exit_status": "NONZERO" if (runtime_matches or generated_matches) else "PASS",
        },
    )
    return 1 if (runtime_matches or generated_matches) else 0


if __name__ == "__main__":
    raise SystemExit(main())
