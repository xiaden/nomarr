"""Smoke tests for binned-process pure computation helpers."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research.strategy_binned._constants import AGG_METHODS
from scripts.embedding_research.strategy_binned._process import compute_agg_mats, compute_retrieval_rows
from scripts.embedding_research.vector_types import UnitTensor


def _unit_tensor(rows: list[list[float]]) -> UnitTensor:
    return UnitTensor(np.asarray(rows, dtype=np.float32))


def test_compute_agg_mats_returns_symmetric_matrices() -> None:
    """compute_agg_mats() returns square symmetric float32 matrices per agg method."""
    tensors = [
        _unit_tensor([[1.0, 0.0]]),
        _unit_tensor([[1.0, 0.0]]),
        _unit_tensor([[1.0, 0.0]]),
    ]
    bin_counts = np.array([1.0, 1.0, 1.0], dtype=np.float32)

    agg_mats = compute_agg_mats(tensors, tensors, bin_counts, metric="cosine")

    assert set(agg_mats) == set(AGG_METHODS)
    for mat in agg_mats.values():
        assert mat.shape == (3, 3)
        assert mat.dtype == np.float32
        np.testing.assert_allclose(mat, mat.T)
        np.testing.assert_allclose(np.diag(mat), np.ones(3, dtype=np.float32))


def test_compute_retrieval_rows_returns_expected_tuple() -> None:
    """compute_retrieval_rows() returns retrieval rows plus optional per-head rows."""
    tensors = [
        _unit_tensor([[1.0, 0.0]]),
        _unit_tensor([[1.0, 0.0]]),
        _unit_tensor([[0.0, 1.0]]),
    ]
    bin_counts = np.array([1.0, 1.0, 1.0], dtype=np.float32)
    agg_mats = compute_agg_mats(tensors, tensors, bin_counts, metric="cosine")

    rows, per_head_rows = compute_retrieval_rows(
        agg_mats,
        artists=["artist-a", "artist-a", "artist-b"],
        backbone="bb",
        bin_mode="temporal_global",
        std_thresh=0.3,
        rep_a="mean",
        rep_b="mean",
        metric="cosine",
        k=1,
        n_songs=3,
    )

    assert isinstance(rows, list)
    assert isinstance(per_head_rows, list)
    assert len(rows) == len(AGG_METHODS)
    assert per_head_rows == []
    for row in rows:
        assert row.backbone == "bb"
        assert row.bin_mode == "temporal_global"
        assert row.std_thresh == 0.3
        assert row.rep_a == "mean"
        assert row.rep_b == "mean"
        assert row.sim_metric == "cosine"
        assert row.k == 1
        assert row.n_songs == 3


def test_compute_agg_mats_l2_metric_returns_symmetric_matrices() -> None:
    """compute_agg_mats() with metric='l2' returns valid symmetric float32 matrices."""
    tensors = [
        _unit_tensor([[1.0, 0.0]]),
        _unit_tensor([[1.0, 0.0]]),
        _unit_tensor([[0.0, 1.0]]),
    ]
    bin_counts = np.array([1.0, 1.0, 1.0], dtype=np.float32)

    agg_mats = compute_agg_mats(tensors, tensors, bin_counts, metric="l2")

    assert set(agg_mats) == set(AGG_METHODS)
    for mat in agg_mats.values():
        assert mat.shape == (3, 3)
        assert mat.dtype == np.float32
        np.testing.assert_allclose(mat, mat.T, atol=1e-5)
        np.testing.assert_allclose(np.diag(mat), np.ones(3, dtype=np.float32), atol=1e-5)

    for mat in agg_mats.values():
        assert mat[0, 1] == pytest.approx(1.0, abs=1e-5)

    for mat in agg_mats.values():
        assert 0.0 < mat[0, 2] < 1.0
