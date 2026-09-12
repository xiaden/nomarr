"""Emit the synthetic-only declaration manifest for the hard-cut bundle."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
if str(_HERE.parents[3]) not in sys.path:
    sys.path.insert(0, str(_HERE.parents[3]))

from scripts.embedding_research.tools._evidence import PACKAGE_ROOT, relative, write_evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit the synthetic-only declaration.")
    parser.add_argument("--root", default=str(PACKAGE_ROOT))
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)

    root = Path(arguments.root).resolve()
    write_evidence(
        arguments.output,
        {
            "declaration": "synthetic-fixture-only",
            "real_corpus": False,
            "audio_reads": 0,
            "onnx_sessions": 0,
            "cuda_devices": 0,
            "root": relative(root),
            "warning": "SYNTHETIC FIXTURE — no empirical retrieval claim.",
            "exit_status": "PASS",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
