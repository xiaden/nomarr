"""R5 — silence-independent structure, exact membership subtraction, weight partition."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research.helpers.gram_segmentation import (
    GramRefusalError,
    derive_temporal_global_from_gram,
    gram_from_stream,
    require_exact_binary_mask,
    search_projection_from_gram,
)
from scripts.embedding_research.tests._gram_evidence import emit_evidence


def _absorbed_stream() -> np.ndarray:
    return np.asarray([[1, 0], [-1, 0], [-1, 0], [-1, 0], [1, 0]], dtype=np.float32)


def _split_stream() -> np.ndarray:
    return np.asarray([[1, 0], [-1, 0], [-1, 0], [-1, 0], [-1, 0], [1, 0]], dtype=np.float32)


def test_silence_independent_structure() -> None:
    stream = _absorbed_stream()
    gram, _ = gram_from_stream(stream)
    structural = derive_temporal_global_from_gram(gram, 0)
    first = search_projection_from_gram(structural, gram, np.ones(5, dtype=np.uint8))
    second = search_projection_from_gram(structural, gram, np.asarray([1, 0, 0, 0, 1], dtype=np.uint8))
    assert first.segments[0].structural == second.segments[0].structural
    assert first.segments[0].searchable_indices == (0, 4)
    assert second.segments[0].searchable_indices == (0, 4)
    emit_evidence(
        "r5-silence-independent-structure.json",
        {"ranges": structural.ranges, "absorbed": structural.absorbed_indices},
    )


def test_membership_subtraction_and_mask_validation() -> None:
    stream = _absorbed_stream()
    gram, _ = gram_from_stream(stream)
    structural = derive_temporal_global_from_gram(gram, 0)
    projection = search_projection_from_gram(structural, gram, np.asarray([1, 1, 1, 0, 1], dtype=np.uint8))
    # in-range [0,5) minus absorbed {1,2,3} minus silent {3} == {0,4}
    assert projection.segments[0].searchable_indices == (0, 4)
    assert projection.total_searchable == 2

    with pytest.raises(GramRefusalError):
        require_exact_binary_mask(None, 5)
    with pytest.raises(GramRefusalError):
        require_exact_binary_mask(np.asarray([1, 0], dtype=np.uint8), 5)
    with pytest.raises(GramRefusalError):
        require_exact_binary_mask(np.asarray([1.0, 0.0, 1.0, 0.0, 1.0], dtype=np.float32), 5)
    with pytest.raises(GramRefusalError):
        require_exact_binary_mask(np.asarray([1, 2, 1, 0, 1], dtype=np.uint8), 5)


def test_searchable_weight_partition() -> None:
    stream = _split_stream()
    gram, _ = gram_from_stream(stream)
    structural = derive_temporal_global_from_gram(gram, 0)
    projection = search_projection_from_gram(structural, gram, np.ones(6, dtype=np.uint8))
    assert projection.total_searchable > 0
    weights = [segment.searchable_weight for segment in projection.segments]
    assert all(weight >= 0.0 for weight in weights)
    assert sum(weights) == pytest.approx(1.0)
    zero = search_projection_from_gram(structural, gram, np.zeros(6, dtype=np.uint8))
    assert zero.total_searchable == 0
    assert all(segment.searchable_weight == 0.0 for segment in zero.segments)
    emit_evidence(
        "r5-weight-partition.json",
        {"segment_count": len(projection.segments), "weight_sum": sum(weights), "zero_total": zero.total_searchable},
    )
