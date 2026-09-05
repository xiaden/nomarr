"""Tests for the retained retrieval-metrics computation.

``classify.py`` and ``common/analyze.py`` (with their ``db.flat``/cache writers)
were deleted in the corrective-pass hard cut, so this module now covers only the
``similarity.compute_retrieval_metrics`` helpers that survive.
"""

from __future__ import annotations

import numpy as np

from scripts.embedding_research.similarity import compute_retrieval_metrics


def _sim_matrix() -> np.ndarray:
    """4x4 similarity matrix with two clearly separated artist/genre groups."""
    return np.array(
        [
            [1.0, 0.95, 0.10, 0.10],
            [0.95, 1.0, 0.10, 0.10],
            [0.10, 0.10, 1.0, 0.92],
            [0.10, 0.10, 0.92, 1.0],
        ],
        dtype=np.float32,
    )


def test_compute_retrieval_metrics_populates_per_head_corr():
    """per_head_corr is populated when head_names are supplied."""
    sim_matrix = _sim_matrix()
    labels = ["A", "A", "B", "B"]
    genres = ["Rock", "Rock", "Jazz", "Jazz"]
    head_scores = [[0.1, 0.2, 0.8, 0.9], [0.2, 0.1, 0.9, 0.8]]
    head_names = ["mood", "energy"]

    metrics = compute_retrieval_metrics(
        sim_matrix,
        labels,
        k=2,
        genres=genres,
        head_scores=head_scores,
        head_names=head_names,
    )

    assert set(metrics["per_head_corr"]) == set(head_names)
    assert all(np.isfinite(value) for value in metrics["per_head_corr"].values())


def test_compute_retrieval_metrics_zero_optional_components_without_inputs():
    """Missing optional inputs degrade to zero discrimination cleanly."""
    metrics = compute_retrieval_metrics(_sim_matrix(), ["A", "A", "B", "B"], k=2, genres=None, head_scores=None)

    np.testing.assert_allclose(metrics["disc_genre"], 0.0, rtol=1e-5)
    np.testing.assert_allclose(metrics["disc_head"], 0.0, rtol=1e-5)


def test_compute_retrieval_metrics_disc_general_positive_when_all_components_present():
    """disc_general is positive when artist, genre, and head components are all positive."""
    metrics = compute_retrieval_metrics(
        _sim_matrix(),
        ["A", "A", "B", "B"],
        k=2,
        genres=["Rock", "Rock", "Jazz", "Jazz"],
        head_scores=[[0.1, 0.1, 0.9, 0.9]],
        head_names=["genre_head"],
    )

    assert metrics["disc_artist"] > 0.0
    assert metrics["disc_genre"] > 0.0
    assert metrics["disc_head"] > 0.0
    assert metrics["disc_general"] > 0.0
    np.testing.assert_allclose(
        metrics["disc_general"],
        np.mean([metrics["disc_artist"], metrics["disc_genre"], metrics["disc_head"]]),
        rtol=1e-5,
    )
