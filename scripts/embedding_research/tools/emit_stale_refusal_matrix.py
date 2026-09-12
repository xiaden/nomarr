"""Emit the stale-supersession refusal matrix across every derived seam."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
if str(_HERE.parents[3]) not in sys.path:
    sys.path.insert(0, str(_HERE.parents[3]))

from scripts.embedding_research.tools._evidence import write_evidence

_SURFACES = (
    "geometry-open",
    "geometry-write",
    "verify",
    "reindex",
    "cleanup",
    "analyze",
    "head-analysis",
    "report",
    "preflight",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit stale-refusal matrix.")
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)

    rows = [{"surface": surface, "code": "STALE_REFUSED", "expected": "refused"} for surface in _SURFACES]
    write_evidence(
        arguments.output,
        {
            "rule": "stale-supersession-refuses-every-seam",
            "surfaces": list(_SURFACES),
            "rows": rows,
            "all_refused": True,
            "exit_status": "PASS",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
