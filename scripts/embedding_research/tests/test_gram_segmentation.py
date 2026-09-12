"""Synthetic contract tests for the NumPy Gram temporal-global engine."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research.helpers.gram_segmentation import (
    GramRefusalError,
    derive_all_temporal_global,
    derive_temporal_global_from_gram,
    gram_from_stream,
)


def _segment_shape(result):
    return [
        {"indices": list(segment.indices), "outlier_count": segment.outlier_count} for segment in result.segments
    ], result.diagnostics


def test_scalar_gram_bytes_are_full_little_endian_c_order() -> None:
    stream = np.asarray([[3.0, 4.0], [0.0, 0.0], [4.0, 3.0]], dtype=np.float32)
    gram, blob = gram_from_stream(stream)
    assert gram.dtype == np.dtype("<f4")
    assert gram.flags.c_contiguous
    assert len(blob) == 4 * 9
    assert np.array_equal(np.frombuffer(blob, dtype="<f4").reshape(3, 3), gram)
    assert gram[1, 1] == np.float32(0.0)


def test_gram_engine_matches_structural_shape_and_keeps_single_range() -> None:
    stream = np.asarray(
        [[1, 0, 0], [0, 1, 0], [0.9, 0.2, 0], [-1, 0, 0], [0, -1, 0], [0.8, 0.3, 0]],
        dtype=np.float32,
    )
    gram, _ = gram_from_stream(stream)
    result = derive_temporal_global_from_gram(gram, 20)
    shape, diagnostics = _segment_shape(result)
    assert shape == [{"indices": [0, 2, 5], "outlier_count": 3}]
    assert diagnostics["return_from_outlier_count"] == 2
    assert result.ranges == ((0, 6),)


def test_hard_split_after_four_consecutive_outliers() -> None:
    # Row 5 returns within the window, but rows 6-9 are four consecutive outliers
    # that exceed OUTLIER_WINDOW=3, forcing a hard split at the run start.
    stream = np.asarray(
        [[1, 0], [0, 1], [0.9, 0.2], [-1, 0], [0, -1], [0.8, 0.3], [-1, 0], [-0.9, -0.2], [-1, 0], [-0.9, -0.2]],
        dtype=np.float32,
    )
    gram, _ = gram_from_stream(stream)
    hard = derive_temporal_global_from_gram(gram, 0)
    assert hard.diagnostics["hard_split_count"] == 1
    assert hard.segments[0].end_idx == 6
    assert hard.segments[1].start_idx == 6


def test_all_thresholds_reuse_one_matrix_and_preserve_order() -> None:
    gram, _ = gram_from_stream(np.asarray([[1, 0], [0, 1]], dtype=np.float32))
    results = derive_all_temporal_global(gram, (2, 0, 2))
    assert tuple(result.threshold_index for result in results) == (2, 0, 2)
    assert all(result.segments for result in results)


def test_nonfinite_and_malformed_inputs_refuse_before_branching() -> None:
    with pytest.raises(GramRefusalError):
        gram_from_stream(np.asarray([[np.nan, 0]], dtype=np.float32))
    with pytest.raises(GramRefusalError):
        derive_temporal_global_from_gram(np.asarray([[1, np.inf]], dtype=np.float32), 0)
    with pytest.raises(GramRefusalError):
        derive_temporal_global_from_gram(np.eye(2, dtype=np.float64), 0)


@pytest.mark.unit
def test_gram_observed_medoid_excludes_zero_diagonal_and_ties_by_source():
    gram = np.asarray(
        [[1.0, 0.5, 0.0, 0.0], [0.5, 1.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0]],
        dtype=np.float32,
    )
    from scripts.embedding_research.helpers.gram_segmentation import select_observed_medoid_from_gram

    assert select_observed_medoid_from_gram(gram, (3, 2, 1, 0)) == (0, 0.5)


@pytest.mark.unit
def test_gram_global_mask_and_projection_partition_positive_mass():
    from scripts.embedding_research.helpers.gram_segmentation import (
        GramSearchResult,
        GramSearchSegment,
        observed_global_medoid_from_gram,
        search_projection_from_gram,
    )

    gram = np.eye(6, dtype=np.float32)
    structural = derive_temporal_global_from_gram(gram, 0)
    mask = np.asarray([1, 0, 1, 1, 0, 1], dtype=np.uint8)
    assert observed_global_medoid_from_gram(gram, mask) == (0, 0.25)
    projection = search_projection_from_gram(structural, gram, mask)
    assert isinstance(projection, GramSearchResult)
    assert sum(segment.searchable_count for segment in projection.segments) == projection.total_searchable
    assert sum(segment.searchable_weight for segment in projection.segments) == pytest.approx(1.0)
    assert all(isinstance(segment, GramSearchSegment) for segment in projection.segments)


@pytest.mark.unit
def test_gram_mask_is_exact_binary_and_zero_total_has_no_medoid():
    from scripts.embedding_research.helpers.gram_segmentation import (
        GramRefusalError,
        observed_global_medoid_from_gram,
        require_exact_binary_mask,
    )

    gram = np.eye(2, dtype=np.float32)
    with pytest.raises(GramRefusalError):
        require_exact_binary_mask(np.asarray([1, 2], dtype=np.uint8), 2)
    with pytest.raises(GramRefusalError):
        require_exact_binary_mask(np.asarray([1], dtype=np.uint8), 2)
    assert observed_global_medoid_from_gram(gram, np.zeros(2, dtype=np.uint8)) == (None, None)


# ── R3 matrix node IDs: independent scalar oracle + strict/ULP + outlier/hard split ──


def test_all_171_thresholds_branch_equivalent() -> None:
    """Every one of the 171 indexed thresholds is branch-equivalent to the scalar oracle."""
    from scripts.embedding_research.tests._gram_evidence import emit_evidence
    from scripts.embedding_research.tests._scalar_oracle import run_spherical_segmentation_global

    stream = np.asarray([[1, 0], [1, 0], [0, 1], [0, 1], [1, 0], [0, 1]], dtype=np.float32)
    gram, _ = gram_from_stream(stream)
    divergent: list[int] = []
    for index in range(171):
        threshold = float(np.float32(np.float32(0.30) + np.float32(index) * np.float32(0.01)))
        gram_result = derive_temporal_global_from_gram(gram, index)
        gram_shape = tuple((s.start_idx, s.end_idx, tuple(s.absorbed_indices)) for s in gram_result.segments)
        oracle_shape = tuple(
            (s.start_idx, s.end_idx, tuple(s.absorbed_indices))
            for s in run_spherical_segmentation_global(stream, threshold)
        )
        if gram_shape != oracle_shape:
            divergent.append(index)
    assert divergent == [], f"scalar oracle divergence at threshold indices {divergent}"
    emit_evidence(
        "r3-all-171-oracle-equivalence.json",
        {"threshold_count": 171, "divergent_indices": divergent, "stream_shape": list(stream.shape)},
    )


def test_strict_boundary_and_ulp() -> None:
    """A distance exactly at the threshold stays in-segment; one float32 ULP above splits."""
    equal_gram = np.asarray([[1.0, 0.875], [0.875, 1.0]], dtype=np.float32)
    equal = derive_temporal_global_from_gram(equal_gram, 20)
    assert len(equal.segments) == 1, "exact equality must not split (strict >)"

    below = np.float32(np.nextafter(np.float32(0.875), np.float32(0.0)))
    split_gram = np.asarray([[1.0, below], [below, 1.0]], dtype=np.float32)
    split = derive_temporal_global_from_gram(split_gram, 20)
    assert len(split.segments) == 2, "one float32 ULP above the threshold must split"


def test_outlier_window_and_hard_split() -> None:
    """Three consecutive outliers absorb; four exceed the window and hard-split."""
    three = np.asarray([[1, 0], [-1, 0], [-1, 0], [-1, 0], [1, 0]], dtype=np.float32)
    gram_three, _ = gram_from_stream(three)
    absorbed = derive_temporal_global_from_gram(gram_three, 0)
    assert absorbed.diagnostics["absorbed_outlier_count"] == 3
    assert absorbed.segments[0].absorbed_indices == (1, 2, 3)

    four = np.asarray([[1, 0], [-1, 0], [-1, 0], [-1, 0], [-1, 0], [1, 0]], dtype=np.float32)
    gram_four, _ = gram_from_stream(four)
    hard = derive_temporal_global_from_gram(gram_four, 0)
    assert hard.diagnostics["hard_split_count"] >= 1
    assert hard.segments[0].end_idx == 1


def test_zero_norm_and_source_order() -> None:
    """Zero-norm rows stay all-zero and source order is always ascending; input refuses."""
    from scripts.embedding_research.helpers.gram_segmentation import normalize_float32

    stream = np.asarray([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    gram, _ = gram_from_stream(stream)
    assert gram[0, 0] == np.float32(0.0)
    assert np.array_equal(gram[0], np.zeros(3, dtype=np.float32))
    result = derive_temporal_global_from_gram(gram, 0)
    for segment in result.segments:
        assert list(segment.indices) == sorted(segment.indices)

    with pytest.raises(GramRefusalError):
        normalize_float32(np.zeros((0, 2), dtype=np.float32))
    with pytest.raises(GramRefusalError):
        normalize_float32(np.asarray([1.0, 0.0], dtype=np.float32))
    with pytest.raises(GramRefusalError):
        normalize_float32(np.asarray([[1.0, 0.0]], dtype=np.float64))
    with pytest.raises(GramRefusalError):
        derive_temporal_global_from_gram(np.zeros((0, 0), dtype=np.float32), 0)
    with pytest.raises(GramRefusalError):
        derive_temporal_global_from_gram(np.asarray([[1, 0]], dtype=np.float32), 0)
    with pytest.raises(GramRefusalError):
        derive_temporal_global_from_gram(np.eye(2, dtype=np.float64), 0)
    with pytest.raises(GramRefusalError):
        derive_temporal_global_from_gram(np.eye(2, dtype=np.float32), True)
    with pytest.raises(GramRefusalError):
        derive_temporal_global_from_gram(np.eye(2, dtype=np.float32), -1)
