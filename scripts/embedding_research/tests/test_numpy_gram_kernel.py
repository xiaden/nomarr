"""Focused corrective tests for the NumPy Gram kernel and edge semantics."""

from __future__ import annotations

import numpy as np
import pytest

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


def test_nonfinite_and_near_zero_inputs_refuse_or_remain_finite() -> None:
    with pytest.raises(GramRefusalError):
        gram_from_stream(np.asarray([[np.nan, 0.0]], dtype=np.float32))
    near_zero, _ = gram_from_stream(np.asarray([[np.finfo(np.float32).tiny, 0.0]], dtype=np.float32))
    assert np.isfinite(near_zero).all()
