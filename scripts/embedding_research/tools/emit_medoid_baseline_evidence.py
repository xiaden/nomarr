"""Emit Gram centrality/medoid evidence with smallest-index tie and zero-row exclusion."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve()
if str(_HERE.parents[3]) not in sys.path:
    sys.path.insert(0, str(_HERE.parents[3]))

from scripts.embedding_research.tools._evidence import write_evidence


def _centralities(gram: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return gram.sum(axis=1)


def _medoid(centralities: np.ndarray, eligible: list[int]) -> int:
    best = eligible[0]
    for index in eligible[1:]:
        if centralities[index] > centralities[best]:
            best = index
    return best


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit Gram medoid/baseline evidence.")
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args(argv)

    rows = np.asarray([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], dtype=np.float32)
    gram = (rows @ rows.T).astype(np.float32)
    centralities = _centralities(gram)
    eligible = [index for index in range(gram.shape[0]) if not np.all(gram[index] == 0.0)]
    medoid = _medoid(centralities, eligible)
    tie = sorted(int(index) for index in eligible if centralities[index] == centralities[medoid])

    zero_gram = np.zeros((2, 2), dtype=np.float32)
    zero_eligible = [index for index in range(zero_gram.shape[0]) if not np.all(zero_gram[index] == 0.0)]

    violations: list[str] = []
    if medoid != min(tie):
        violations.append("tie did not resolve to the smallest source index")
    if zero_eligible:
        violations.append("zero rows were not excluded from the population")

    write_evidence(
        arguments.output,
        {
            "rule": "gram-centrality-smallest-index-zero-row-exclusion",
            "gram": gram.tolist(),
            "centralities": centralities.tolist(),
            "eligible_indices": eligible,
            "medoid_index": medoid,
            "tie_group": tie,
            "zero_row_eligible_indices": zero_eligible,
            "violations": violations,
            "exit_status": "PASS" if not violations else "NONZERO",
        },
    )
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())
