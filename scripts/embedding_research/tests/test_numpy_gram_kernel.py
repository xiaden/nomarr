"""Focused corrective tests for the NumPy Gram kernel and edge semantics."""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from scripts.embedding_research import fixture_benchmark
from scripts.embedding_research.db.geometry_profile import GRAM_BLOB_LAYOUT, NUMPY_KERNEL_VERSION, GeometryProfile
from scripts.embedding_research.helpers import gram_segmentation
from scripts.embedding_research.helpers.gram_segmentation import (
    GramRefusalError,
    derive_all_temporal_global,
    gram_from_stream,
)
from scripts.embedding_research.tests._scalar_oracle import run_spherical_segmentation_global


def test_numpy_kernel_has_canonical_bytes_and_zero_rows() -> None:
    stream = np.asarray([[3.0, 4.0], [0.0, 0.0], [-3.0, -4.0]], dtype=np.float32)
    gram, blob = gram_from_stream(stream)
    assert gram.dtype == np.dtype("<f4")
    assert gram.flags.c_contiguous
    assert not gram.flags.writeable
    assert blob == gram.tobytes(order="C")
    assert np.array_equal(np.frombuffer(blob, dtype="<f4").reshape(3, 3), gram)
    assert gram[0, 2] == np.float32(-1.0)
    assert gram[1, 1] == np.float32(0.0)
    assert len(blob) == 4 * stream.shape[0] * stream.shape[0]
    assert blob == np.asarray(gram, dtype="<f4", order="C").tobytes(order="C")


def test_numpy_kernel_matches_scalar_oracle_for_all_primary_thresholds() -> None:
    stream = np.asarray([[1, 0], [1, 0], [0, 1], [0, 1], [1, 0], [0, 1]], dtype=np.float32)
    gram, _ = gram_from_stream(stream)
    for index in range(171):
        threshold = float(np.float32(np.float32(0.30) + np.float32(index) * np.float32(0.01)))
        actual = derive_all_temporal_global(gram, (index,))[0]
        expected = run_spherical_segmentation_global(stream, threshold)
        assert tuple((s.start_idx, s.end_idx, s.absorbed_indices) for s in actual.segments) == tuple(
            (s.start_idx, s.end_idx, s.absorbed_indices) for s in expected
        )


def test_boundary_ulp_and_absorption_edges() -> None:
    equal = np.asarray([[1.0, 0.875], [0.875, 1.0]], dtype=np.float32)
    assert len(derive_all_temporal_global(equal, (20,))[0].segments) == 1
    one_ulp = np.nextafter(np.float32(0.875), np.float32(0.0))
    split = np.asarray([[1.0, one_ulp], [one_ulp, 1.0]], dtype=np.float32)
    assert len(derive_all_temporal_global(split, (20,))[0].segments) == 2
    three, _ = gram_from_stream(np.asarray([[1, 0], [-1, 0], [-1, 0], [-1, 0], [1, 0]], dtype=np.float32))
    assert derive_all_temporal_global(three, (0,))[0].segments[0].absorbed_indices == (1, 2, 3)
    four, _ = gram_from_stream(np.asarray([[1, 0], [-1, 0], [-1, 0], [-1, 0], [-1, 0], [1, 0]], dtype=np.float32))
    assert derive_all_temporal_global(four, (0,))[0].diagnostics["hard_split_count"] >= 1


def test_profile_and_fixture_benchmark_identify_numpy_kernel() -> None:
    profile = GeometryProfile.current().to_manifest()
    assert profile["numerical_kernel_version"] == NUMPY_KERNEL_VERSION
    assert profile["gram_blob_layout"] == GRAM_BLOB_LAYOUT
    record = fixture_benchmark.run_bounded_benchmark(seed=0)
    assert record.numerical_kernel_version == NUMPY_KERNEL_VERSION
    assert record.validate() == []


def test_production_centroid_owner_is_vectorized_and_scalar_oracle_is_test_only() -> None:
    source = inspect.getsource(gram_segmentation._row_distance)
    assert "np.sum" in source
    assert "for left" not in source
    assert "for right" not in source
    assert "np.matmul" in inspect.getsource(gram_segmentation.gram_from_stream)
    assert "_scalar_oracle" not in inspect.getsource(gram_segmentation)


def test_opposite_and_near_zero_cancellation_are_finite_and_deterministic() -> None:
    opposite, _ = gram_from_stream(np.asarray([[1, 0], [-1, 0], [1, 0]], dtype=np.float32))
    first = derive_all_temporal_global(opposite, (0,))[0]
    second = derive_all_temporal_global(opposite, (0,))[0]
    assert first == second
    assert np.isfinite(opposite).all()
    cancellation, _ = gram_from_stream(
        np.asarray([[1.0, 0.0], [-1.0, np.finfo(np.float32).eps], [0.0, 1.0]], dtype=np.float32)
    )
    assert np.isfinite(cancellation).all()


def test_nonfinite_and_near_zero_inputs_refuse_or_remain_finite() -> None:
    with pytest.raises(GramRefusalError):
        gram_from_stream(np.asarray([[np.nan, 0.0]], dtype=np.float32))
    near_zero, _ = gram_from_stream(np.asarray([[np.finfo(np.float32).tiny, 0.0]], dtype=np.float32))
    assert np.isfinite(near_zero).all()
