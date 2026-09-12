"""R4 — observed medoid selection from the Gram matrix (ties, zero rows, non-finite)."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research.helpers.gram_segmentation import (
    GramRefusalError,
    gram_from_stream,
    observed_global_medoid_from_gram,
    select_observed_medoid_from_gram,
)
from scripts.embedding_research.tests._gram_evidence import emit_evidence


def test_segment_medoid_from_gram() -> None:
    gram = np.asarray(
        [[1.0, 1.0, 0.0, 0.0], [1.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 1.0], [0.0, 0.0, 1.0, 1.0]],
        dtype=np.float32,
    )
    medoid, centrality = select_observed_medoid_from_gram(gram, (3, 2, 1, 0))
    assert medoid == 0, "exact centrality ties resolve to the smallest source index"
    assert centrality == pytest.approx(0.5)
    emit_evidence(
        "r4-medoid-tie.json",
        {"medoid": medoid, "centrality": centrality, "tie_break": "smallest-source-index"},
    )


def test_global_baseline_tie_and_zero_rows() -> None:
    gram = np.asarray([[1.0, 0.5, 0.0], [0.5, 1.0, 0.0], [0.0, 0.0, 0.0]], dtype=np.float32)
    mask = np.asarray([1, 1, 1], dtype=np.uint8)
    medoid, centrality = observed_global_medoid_from_gram(gram, mask)
    assert medoid == 0
    assert centrality == pytest.approx(0.75)
    assert observed_global_medoid_from_gram(gram, np.zeros(3, dtype=np.uint8)) == (None, None)
    assert select_observed_medoid_from_gram(gram, (2,)) == (None, None), "zero-diagonal rows are excluded"


def test_nonfinite_medoid_refusal() -> None:
    with pytest.raises(GramRefusalError):
        select_observed_medoid_from_gram(np.asarray([[np.nan]], dtype=np.float32), (0,))
    with pytest.raises(GramRefusalError):
        select_observed_medoid_from_gram(np.eye(2, dtype=np.float32), (0, 0))
    with pytest.raises(GramRefusalError):
        select_observed_medoid_from_gram(np.eye(2, dtype=np.float32), (2,))
    gram, _ = gram_from_stream(np.asarray([[1, 0], [0, 1]], dtype=np.float32))
    assert select_observed_medoid_from_gram(gram, ()) == (None, None)
    emit_evidence(
        "r4-medoid-refusals.json",
        {"nonfinite": True, "duplicate": True, "out_of_range": True, "empty_is_none": True},
    )
