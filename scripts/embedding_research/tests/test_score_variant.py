"""Phase 2 tests: primary ``max_per_candidate_segment`` score-variant semantics.

The former strategy_binned ``_process``/``_constants`` and cache_identity
score-variant surfaces were deleted in the corrective-pass hard cut; the active
max-per-candidate-segment oracle is exercised by ``test_scoring_harness.py`` and
``test_bounded_*.py``.  This file retains only the surviving-surfaces checks that
were originally co-located here:

* ``disc_general`` excludes zero-valued components (``similarity``);
* no ``disc_album`` key anywhere in the retained touched surfaces (audit).
"""

from __future__ import annotations

import ast
import pathlib

import numpy as np
import pytest

from scripts.embedding_research.similarity import compute_retrieval_metrics


def test_disc_general_excludes_zero_valued_components() -> None:
    """disc_general is the mean of the non-zero disc components, excluding zeros."""
    # Artist-only inputs: disc_artist > 0, disc_genre/disc_head are zero, so
    # disc_general must equal disc_artist (the zero-valued components excluded).
    sim_mat = np.array(
        [
            [1.0, 0.9, 0.1, 0.0],
            [0.9, 1.0, 0.1, 0.0],
            [0.1, 0.1, 1.0, 0.9],
            [0.0, 0.0, 0.9, 1.0],
        ],
        dtype=np.float32,
    )
    metrics = compute_retrieval_metrics(sim_mat, ["A", "A", "B", "B"], k=2, genres=None, head_scores=None)
    assert metrics["disc_artist"] > 0.0
    assert metrics["disc_genre"] == 0.0
    assert metrics["disc_head"] == 0.0
    assert metrics["disc_general"] == pytest.approx(metrics["disc_artist"])
    assert metrics["disc_general"] > 0.0


def test_no_disc_album_in_touched_surfaces() -> None:
    root = pathlib.Path(__file__).resolve().parents[1]
    touched = [
        "report/_base.py",
        "db/_schema.py",
        "scoring_harness.py",
        "similarity.py",
    ]
    for rel in touched:
        source = (root / rel).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id != "disc_album", f"disc_album Name in {rel}"
            if isinstance(node, ast.Attribute):
                assert node.attr != "disc_album", f"disc_album Attribute in {rel}"
