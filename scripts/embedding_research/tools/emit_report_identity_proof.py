"""Emit report identity proof: the ten identity axes, no retired vocabulary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve()
if str(_HERE.parents[3]) not in sys.path:
    sys.path.insert(0, str(_HERE.parents[3]))

from scripts.embedding_research.tools._evidence import (
    EVIDENCE_ROOT,
    write_evidence,
)
from scripts.embedding_research.validate_fixture_report import EXPECTED_IDENTITY_COLUMNS


def _tables(node: Any):
    if isinstance(node, dict):
        if isinstance(node.get("tables"), list):
            yield from node["tables"]
        for key in ("panels", "subsections"):
            for child in node.get(key, []) or []:
                yield from _tables(child)


def _identity_columns(report: dict[str, Any]) -> list[str]:
    for section in report.get("sections", []):
        if section.get("id") in ("analysis", "head-analysis"):
            for table in _tables(section):
                columns = table.get("columns", [])
                if "geometry_id" in columns:
                    return columns
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit report identity proof.")
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)

    report_path = EVIDENCE_ROOT / "report/report.json"
    violations: list[str] = []
    columns: list[str] = []
    if not report_path.is_file():
        violations.append(f"report missing at {report_path}")
    else:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        columns = _identity_columns(report)
        missing = [column for column in EXPECTED_IDENTITY_COLUMNS if column not in columns]
        violations.extend(f"report identity table missing {column}" for column in missing)

    write_evidence(
        arguments.output,
        {
            "rule": "ten-axis-geometry-report-identity",
            "report": report_path.as_posix(),
            "expected_identity_columns": list(EXPECTED_IDENTITY_COLUMNS),
            "observed_identity_columns": columns,
            "violations": violations,
            "exit_status": "PASS" if not violations else "NONZERO",
        },
    )
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
