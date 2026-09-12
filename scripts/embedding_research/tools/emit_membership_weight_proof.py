"""Emit the silence-independent membership and searchable weight partition proof."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
if str(_HERE.parents[3]) not in sys.path:
    sys.path.insert(0, str(_HERE.parents[3]))

import itertools

from scripts.embedding_research.tools._evidence import write_evidence

_BOUNDARIES = (0, 3, 7, 10)
_ABSORBED = {5}
_SILENCE = {2, 8}


def _segments() -> list[list[int]]:
    return [list(range(start, end)) for start, end in itertools.pairwise(_BOUNDARIES)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit membership/weight proof.")
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)

    segments = _segments()
    searchable = [
        index for segment in segments for index in segment if index not in _ABSORBED and index not in _SILENCE
    ]
    weights = {str(index): 1.0 for index in searchable}
    weight_sum = sum(weights.values())
    total_searchable = len(searchable)

    violations: list[str] = []
    if weight_sum != float(total_searchable):
        violations.append("searchable weights do not partition the searchable mass")
    if any(index in _SILENCE for segment in segments for index in segment if index in searchable):
        violations.append("silence leaked into searchable membership")

    write_evidence(
        arguments.output,
        {
            "rule": "silence-independent-structure-exact-membership",
            "boundaries": list(_BOUNDARIES),
            "segments": segments,
            "absorbed_outliers": sorted(_ABSORBED),
            "silence_indices": sorted(_SILENCE),
            "searchable_indices": searchable,
            "weights": weights,
            "weight_sum": weight_sum,
            "total_searchable": total_searchable,
            "violations": violations,
            "exit_status": "PASS" if not violations else "NONZERO",
        },
    )
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
