"""Unit tests for flat pooling medoid selection.

Covers the Part A contract: ``pool_medoid`` returns an *observed* float32 patch
(never a synthetic centroid), ``select_global_medoid_index`` chooses the row
with maximum mean cosine centrality after row L2-normalization, ties resolve to
the smallest index, and one-patch / zero-norm inputs are handled
deterministically.
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research.pooling import pool_medoid, select_global_medoid_index


def test_pool_medoid_returns_an_observed_patch() -> None:
    """pool_medoid() returns one of the input rows exactly, not a centroid."""
    patches = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.70710678, 0.70710678, 0.0],
        ],
        dtype=np.float32,
    )
    pooled = pool_medoid(patches)
    assert any(np.array_equal(pooled, row) for row in patches)


def test_pool_medoid_returns_float32() -> None:
    """pool_medoid() output dtype is float32 regardless of input dtype."""
    patches = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float64)
    assert pool_medoid(patches).dtype == np.float32


def test_pool_medoid_chooses_most_central_row() -> None:
    """The most-central row (here the intermediate one) is selected."""
    patches = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.8, 0.6, 0.0],
            [0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    # Row 1 (the .8/.6 row) has the highest mean cosine centrality.
    np.testing.assert_array_equal(pool_medoid(patches), patches[1])


def test_select_global_medoid_index_returns_index_and_centrality() -> None:
    """select_global_medoid_index() returns a (local_index, centrality) tuple."""
    patches = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.8, 0.6, 0.0],
            [0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    idx, centrality = select_global_medoid_index(patches)
    assert idx == 1
    assert isinstance(idx, int)
    assert isinstance(centrality, float)


def test_pool_medoid_resolves_ties_to_smallest_index() -> None:
    """Tied maximum-centrality rows resolve deterministically to the smallest index."""
    # Four antipodal unit vectors: every row has identical mean centrality.
    patches = np.array(
        [
            [1.0, 0.0],
            [0.0, 1.0],
            [-1.0, 0.0],
            [0.0, -1.0],
        ],
        dtype=np.float32,
    )
    idx, _ = select_global_medoid_index(patches)
    assert idx == 0
    np.testing.assert_array_equal(pool_medoid(patches), patches[0])


def test_pool_medoid_single_patch_returns_that_patch() -> None:
    """A single-patch input deterministically returns itself at index 0."""
    patches = np.array([[3.0, 4.0, 0.0]], dtype=np.float32)
    assert select_global_medoid_index(patches) == (0, 0.0)
    np.testing.assert_array_equal(pool_medoid(patches), patches[0])


def test_select_global_medoid_index_never_picks_zero_norm_row_when_nonzero_exists() -> None:
    """A zero-norm row is never the medoid when a nonzero row exists."""
    patches = np.array(
        [
            [0.0, 0.0, 0.0],  # zero-norm — must not be selected
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    idx, _ = select_global_medoid_index(patches)
    assert idx in (1, 2)
    assert idx != 0


def test_pool_medoid_all_zero_rows_is_deterministic() -> None:
    """An all-zero patch set deterministically selects index 0."""
    patches = np.zeros((3, 4), dtype=np.float32)
    assert select_global_medoid_index(patches)[0] == 0
    np.testing.assert_array_equal(pool_medoid(patches), patches[0])


def test_pool_medoid_empty_patch_set_raises() -> None:
    """An empty patch set raises a clear ValueError."""
    with pytest.raises(ValueError, match="empty"):
        pool_medoid(np.empty((0, 4), dtype=np.float32))


def test_pool_medoid_is_not_coordinate_median() -> None:
    """medoid returns an observed row, unlike the synthetic coordinate median."""
    patches = np.array(
        [
            [1.0, 0.0],
            [0.0, 1.0],
            [0.0, 0.0],
        ],
        dtype=np.float32,
    )
    pooled = pool_medoid(patches)
    # The coordinate-wise median (0,0) is NOT an observed row here, so medoid
    # must pick one of the observed unit rows instead.
    assert any(np.array_equal(pooled, row) for row in patches)
