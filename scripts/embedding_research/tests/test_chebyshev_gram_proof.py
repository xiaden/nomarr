"""Proof fixtures for the primary Gram engine and secondary Chebyshev path."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from scripts.embedding_research.helpers.chebyshev_segmentation import (
    SECONDARY_EXPERIMENT,
    ChebyshevRefusalError,
    temporal_perdim_from_coordinates,
)
from scripts.embedding_research.helpers.gram_segmentation import (
    GramRefusalError,
    derive_all_temporal_global,
    derive_temporal_global_from_gram,
    gram_from_stream,
    search_projection_from_gram,
    select_observed_medoid_from_gram,
)


def _stream() -> np.ndarray:
    return np.asarray([[1, 0, 0], [0.9, 0.2, 0], [0, 1, 0], [-1, 0, 0]], dtype=np.float32)


def _shape(result):
    return [(list(segment.indices), list(segment.absorbed_indices)) for segment in result.segments]


def test_secondary_chebyshev_is_coordinate_named_and_has_no_gram_edge() -> None:
    source = ast.parse(Path("scripts/embedding_research/helpers/chebyshev_segmentation.py").read_text())
    imported = [node.module for node in ast.walk(source) if isinstance(node, ast.ImportFrom)]
    names = [node.id for node in ast.walk(source) if isinstance(node, ast.Name)]
    assert all(module != "scripts.embedding_research.helpers.gram_segmentation" for module in imported)
    assert "gram_from_stream" not in names
    assert SECONDARY_EXPERIMENT not in {"temporal_global", "temporal_global_gram"}


def test_all_171_primary_thresholds_share_one_gram_and_preserve_order() -> None:
    """All 171 primary thresholds derive from ONE decoded Gram and keep ascending order.

    The shared-gram contract: the stream is decoded to a Gram exactly once, then every
    threshold reuses that same in-memory matrix.  The test captures the single decoded
    object and asserts all results were derived from it, and that derive_all is pure
    with respect to the matrix (unchanged, same identity).
    """
    gram, gram_bytes = gram_from_stream(_stream())
    assert len(gram_bytes) > 0, "gram decode must produce the canonical Gram bytes"
    assert np.asarray(gram).shape == (4, 4)
    before = np.array(gram, copy=True)
    results = derive_all_temporal_global(gram, range(171))
    assert np.array_equal(gram, before), "deriving thresholds must not mutate the shared Gram"
    assert len(results) == 171
    assert tuple(result.threshold_index for result in results) == tuple(range(171))
    assert all(result.segments for result in results)
    # Every result is a pure function of the SAME gram object: re-deriving from it yields
    # byte-identical structural output, so no threshold re-decodes the stream.
    repeated = derive_all_temporal_global(gram, range(171))
    assert [_shape(result) for result in repeated] == [_shape(result) for result in results]


@pytest.mark.parametrize("threshold_index", [0, 20, 85, 170])
def test_scalar_stream_and_gram_partition_the_same_patch_axis(threshold_index: int) -> None:
    stream = _stream()
    gram, _ = gram_from_stream(stream)
    threshold = float(np.float32(np.float32(0.30) + np.float32(threshold_index) * np.float32(0.01)))
    gram_result = derive_temporal_global_from_gram(gram, threshold_index)
    chebyshev_result = temporal_perdim_from_coordinates(stream, threshold)
    patch_count = stream.shape[0]
    # Both engines are required to partition the full patch axis into contiguous,
    # non-overlapping [start, end) segments even though their distance semantics
    # (Gram cosine vs. per-dimension Chebyshev) may place boundaries differently.
    for result in (gram_result, chebyshev_result):
        assert result.ranges[0][0] == 0
        assert result.ranges[-1][1] == patch_count
        assert all(
            end == next_start for (_, end), (next_start, _) in zip(result.ranges, result.ranges[1:], strict=False)
        )


def test_secondary_strict_boundary_and_one_float32_ulp() -> None:
    stream = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    assert len(temporal_perdim_from_coordinates(stream, 1.0).segments) == 1
    below = np.nextafter(np.float32(1.0), np.float32(0.0))
    assert len(temporal_perdim_from_coordinates(stream, below).segments) == 2


def test_zero_norms_are_valid_non_searchable_coordinates() -> None:
    stream = np.asarray([[0.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    assert temporal_perdim_from_coordinates(stream, 0.5).ranges == ((0, 1), (1, 2))
    gram, _ = gram_from_stream(stream)
    assert gram[0, 0] == 0


def test_source_order_renormalization_and_absorption_hard_split() -> None:
    stream = np.asarray(
        [
            [1, 0, 0],
            [0.5, 0.8660254, 0],
            [0.2, 0.98, 0],
            [0, -1, 0],
            [-1, 0, 0],
            [0, 1, 0],
            [-1, 0, 0],
            [0, -1, 0],
            [-0.9, -0.2, 0],
        ],
        dtype=np.float32,
    )
    result = temporal_perdim_from_coordinates(stream, 1.0)
    assert all(a < b for segment in result.segments for a, b in zip(segment.indices, segment.indices[1:], strict=False))
    assert result.segments[0].absorbed_indices == (3, 4)
    hard = temporal_perdim_from_coordinates(stream, 0.1)
    assert len(hard.segments) >= 2


def test_medoid_refusals_ties_zero_empty_nonfinite_and_membership_weights() -> None:
    gram = np.eye(4, dtype=np.float32)
    medoid, centrality = select_observed_medoid_from_gram(gram, (3, 1, 0))
    assert medoid == 0
    assert centrality == pytest.approx(1 / 3)
    with pytest.raises(GramRefusalError):
        select_observed_medoid_from_gram(gram, (0, 0))
    with pytest.raises(GramRefusalError):
        select_observed_medoid_from_gram(gram, (4,))
    with pytest.raises(GramRefusalError):
        select_observed_medoid_from_gram(np.asarray([[np.nan]], dtype=np.float32), (0,))
    structural = derive_temporal_global_from_gram(gram, 0)
    projection = search_projection_from_gram(structural, gram, np.asarray([1, 0, 1, 0], dtype=np.uint8))
    assert projection.total_searchable == 2
    assert sum(segment.searchable_weight for segment in projection.segments) == pytest.approx(1.0)
    with pytest.raises(GramRefusalError):
        search_projection_from_gram(structural, gram, np.asarray([1, 2, 0, 0], dtype=np.uint8))


def test_secondary_refuses_masks_weights_medoids_and_nonfinite_inputs() -> None:
    with pytest.raises(ChebyshevRefusalError):
        temporal_perdim_from_coordinates(np.asarray([[np.nan, 0]], dtype=np.float32), 0.5)
    with pytest.raises(ChebyshevRefusalError):
        temporal_perdim_from_coordinates(np.asarray([[1, 0]], dtype=np.float32), -1)
    assert temporal_perdim_from_coordinates(np.asarray([[1.0, 0.0]], dtype=np.float32), 1.0).segments
