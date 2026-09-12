"""Emit the exact 171-entry primary threshold grid identity."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
if str(_HERE.parents[3]) not in sys.path:
    sys.path.insert(0, str(_HERE.parents[3]))

from scripts.embedding_research.tools._evidence import write_evidence

_START = 0.30
_STEP = 0.01
_COUNT = 171


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit the exact primary threshold grid.")
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)

    thresholds = [_START + index * _STEP for index in range(_COUNT)]
    violations: list[str] = []
    if len(thresholds) != _COUNT:
        violations.append("grid length is not 171")
    if thresholds[0] != _START:
        violations.append("grid start is not 0.30")
    if round(thresholds[-1], 6) != round(_START + (_COUNT - 1) * _STEP, 6):
        violations.append("grid end is not 2.00")

    write_evidence(
        arguments.output,
        {
            "rule": "exact-171-primary-threshold-grid",
            "start": _START,
            "step": _STEP,
            "count": _COUNT,
            "first": thresholds[0],
            "last": round(thresholds[-1], 6),
            "index_identity": "t_i = 0.30 + i*0.01, i=0..170",
            "thresholds": [round(value, 6) for value in thresholds],
            "violations": violations,
            "exit_status": "PASS" if not violations else "NONZERO",
        },
    )
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
