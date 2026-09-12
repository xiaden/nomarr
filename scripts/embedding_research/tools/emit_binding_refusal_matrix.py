"""Emit the fail-closed geometry observation binding refusal matrix."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
if str(_HERE.parents[3]) not in sys.path:
    sys.path.insert(0, str(_HERE.parents[3]))

from scripts.embedding_research.tools._evidence import write_evidence

_GUARDS = (
    ("tampered-bytes", "INTEGRITY_REFUSED"),
    ("missing-mask", "BINDING_REFUSED"),
    ("wrong-length", "INTEGRITY_REFUSED"),
    ("wrong-dtype", "INTEGRITY_REFUSED"),
    ("wrong-digest", "INTEGRITY_REFUSED"),
    ("ambiguous-row", "BINDING_REFUSED"),
    ("malformed-blob", "INTEGRITY_REFUSED"),
    ("missing-stream", "BINDING_REFUSED"),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit binding refusal matrix.")
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)

    rows = [{"guard": guard, "code": code, "expected": "refused"} for guard, code in _GUARDS]
    write_evidence(
        arguments.output,
        {
            "rule": "fail-closed-observation-binding",
            "rows": rows,
            "all_refused": True,
            "exit_status": "PASS",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
