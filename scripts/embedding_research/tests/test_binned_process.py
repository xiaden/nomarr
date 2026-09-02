"""Tests for binned-process pure computation helpers.

Covers the Part B weighted directional semantics of ``compute_agg_mats``:
every ordered ``(i, j)`` pair (including ``i > j`` and the diagonal) is
evaluated with per-song bin weights on both sides, distinct ``rep_a``/``rep_b``
representations are never assumed symmetric, the bidirectional reduction is
symmetric by construction, and the diagonal is validated from the same formula
rather than unconditionally overwritten to ``1.0``.
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from scripts.embedding_research.strategy_binned._constants import (
    _ALLOWED_AGG_METHODS,
    _ALLOWED_REP_TYPES,
    validate_optimizer_representation,
)
from scripts.embedding_research.strategy_binned._optimize import _eval_threshold, optimize_std_threshold
from scripts.embedding_research.strategy_binned._pool import _pool_segment
from scripts.embedding_research.strategy_binned._process import compute_agg_mats, compute_retrieval_rows
from scripts.embedding_research.strategy_binned._weighted import target_weighted
from scripts.embedding_research.vector_types import RawTensor, UnitTensor


def _unit_tensor(rows: list[list[float]]) -> UnitTensor:
    return UnitTensor(np.asarray(rows, dtype=np.float32))


def _uniform_weights(n_bins: int) -> np.ndarray:
    return np.ones(n_bins, dtype=np.float32)


def test_compute_agg_mats_returns_symmetric_matrices_for_identical_songs() -> None:
    """Identical single-bin songs yield all-ones symmetric float32 matrices per agg method.

    This is the proven self-comparison contract: with a single bin and identical
    ``rep_a == rep_b`` the cosine self-similarity is exactly 1.0, so the diagonal
    from the formula is 1.0 — not a forced overwrite.
    """
    tensors = [
        _unit_tensor([[1.0, 0.0]]),
        _unit_tensor([[1.0, 0.0]]),
        _unit_tensor([[1.0, 0.0]]),
    ]
    weights = [_uniform_weights(1)] * 3

    agg_mats = compute_agg_mats(tensors, tensors, weights, weights, metric="cosine")

    assert set(agg_mats) == {
        "target_weighted",
        "bidirectional_weighted",
        "normalized_mean_pair_weighted",
    }
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
    weights = [_uniform_weights(1)] * 3
    agg_mats = compute_agg_mats(tensors, tensors, weights, weights, metric="cosine")

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
    assert len(rows) == len(agg_mats)
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


# ── P2-S3: ordered-direction / symmetry behaviour ─────────────────────────────


def _directional_fixture():
    """Two 2-bin songs with distinct rep_a / rep_b representations and different weights."""
    # Song 0: rep_a bins, rep_b bins, per-bin weights
    norm_a0 = _unit_tensor([[1.0, 0.0], [0.8, 0.6]])
    norm_b0 = _unit_tensor([[1.0, 0.0], [0.6, 0.8]])
    w0 = np.array([1.0, 3.0], dtype=np.float32)
    # Song 1
    norm_a1 = _unit_tensor([[0.0, 1.0], [0.6, 0.8]])
    norm_b1 = _unit_tensor([[0.8, 0.6], [0.0, 1.0]])
    w1 = np.array([2.0, 1.0], dtype=np.float32)

    norm_a = [norm_a0, norm_a1]
    norm_b = [norm_b0, norm_b1]
    weights_a = [w0, w1]
    weights_b = [w0, w1]
    return norm_a, norm_b, weights_a, weights_b


def test_bidirectional_matrix_is_symmetric_ordered_pairs() -> None:
    """bidirectional_weighted is symmetric: it averages both supplied directions."""
    norm_a, norm_b, wa, wb = _directional_fixture()
    agg_mats = compute_agg_mats(norm_a, norm_b, wa, wb, metric="cosine")
    np.testing.assert_allclose(agg_mats["bidirectional_weighted"], agg_mats["bidirectional_weighted"].T)


def test_directional_reductions_are_asymmetric() -> None:
    """target_weighted / normalized_mean_pair_weighted stay directional when weights differ."""
    norm_a, norm_b, wa, wb = _directional_fixture()
    agg_mats = compute_agg_mats(norm_a, norm_b, wa, wb, metric="cosine")

    # Ordered (0,1) and (1,0) pairs are evaluated independently and differ.
    assert agg_mats["target_weighted"][0, 1] != agg_mats["target_weighted"][1, 0]
    assert agg_mats["normalized_mean_pair_weighted"][0, 1] != agg_mats["normalized_mean_pair_weighted"][1, 0]


def test_diagonal_validated_from_same_formula() -> None:
    """Diagonal is not unconditionally overwritten to 1.0; it follows the formula."""
    norm_a, norm_b, wa, wb = _directional_fixture()
    agg_mats = compute_agg_mats(norm_a, norm_b, wa, wb, metric="cosine")

    s_00 = norm_a[0].data @ norm_b[0].data.T
    expected = target_weighted(s_00, wb[0])
    # Multi-bin self-comparison under the formula is < 1.0 (not forced).
    assert expected != 1.0
    np.testing.assert_allclose(agg_mats["target_weighted"][0, 0], expected, rtol=1e-6, atol=1e-6)


# ── P2-S4: config validation boundary rejects legacy/medoid aggregation ───────


def test_allowed_agg_methods_are_weighted_reductions_only() -> None:
    """Validation boundary accepts only the Part B weighted reductions."""
    for name in ("target_weighted", "bidirectional_weighted", "normalized_mean_pair_weighted"):
        assert name in _ALLOWED_AGG_METHODS
    for legacy in ("mean", "median", "max", "min", "medoid"):
        assert legacy not in _ALLOWED_AGG_METHODS


# ── QA R1: per-song distinct weights_a / weights_b thread through compute_agg_mats ──────


def _distinct_weights_fixture():
    """Source/target song sides (one real song per side, plus a filler) with distinct per-bin weights.

    ``norm_a[0]`` source bins = ``[[1,0],[0.6,0.8]]`` (weights_a[0] = [1, 3]);
    ``norm_a[1]`` is a filler song.  ``norm_b[0]`` is a filler song;
    ``norm_b[1]`` target bins = ``[[0,1],[0.8,0.6]]`` (weights_b varied).
    The ordered pair ``(0, 1)`` therefore uses ``norm_a[0]`` x ``norm_b[1]`` with
    forward similarity ``S = norm_a[0] @ norm_b[1].T = [[0, 0.8], [0.8, 0.96]]``.
    """
    norm_a = [_unit_tensor([[1.0, 0.0], [0.6, 0.8]]), _unit_tensor([[1.0, 0.0], [0.0, 1.0]])]
    norm_b = [_unit_tensor([[1.0, 0.0], [0.0, 1.0]]), _unit_tensor([[0.0, 1.0], [0.8, 0.6]])]
    weights_a = [np.array([1.0, 3.0], dtype=np.float32), _uniform_weights(2)]
    weights_b_distinct = [np.array([4.0, 1.0], dtype=np.float32), np.array([4.0, 1.0], dtype=np.float32)]
    weights_b_same = [np.array([1.0, 3.0], dtype=np.float32), np.array([1.0, 3.0], dtype=np.float32)]
    return norm_a, norm_b, weights_a, weights_b_distinct, weights_b_same


def test_compute_agg_mats_uses_distinct_weights_a_vs_weights_b() -> None:
    """Distinct per-song weights_a != weights_b thread through compute_agg_mats.

    Verifies the side-swap / weights-b-ignored bug is absent: changing only the
    target (song B) weights changes the scores, and the weighted reductions match
    hand-computed values (which would be impossible if weights_b were ignored).
    """
    norm_a, norm_b, weights_a, weights_b_distinct, weights_b_same = _distinct_weights_fixture()

    distinct = compute_agg_mats(norm_a, norm_b, weights_a, weights_b_distinct, metric="cosine")
    same = compute_agg_mats(norm_a, norm_b, weights_a, weights_b_same, metric="cosine")

    # Forward similarity for ordered pair (0,1) = norm_a[0] @ norm_b[1].T = [[0, 0.8], [0.8, 0.96]].
    # Hand-computed target_weighted with weights_b = [4,1]:
    #   row0: (4*0 + 1*0.8)/5 = 0.16 ; row1: (4*0.8 + 1*0.96)/5 = 0.832 ; mean = 0.496
    np.testing.assert_allclose(distinct["target_weighted"][0, 1], 0.496, rtol=1e-6, atol=1e-6)
    # Same-weights target_weighted with weights_b = [1,3]:
    #   row0: (1*0 + 3*0.8)/4 = 0.6 ; row1: (1*0.8 + 3*0.96)/4 = 0.92 ; mean = 0.76
    np.testing.assert_allclose(same["target_weighted"][0, 1], 0.76, rtol=1e-6, atol=1e-6)
    # Changing only song-B weights must change the score (weights_b is not ignored).
    assert distinct["target_weighted"][0, 1] != same["target_weighted"][0, 1]

    # Hand-computed normalized_mean_pair_weighted with weights_b = [4,1], w_A=[1,3]:
    #   sum_ab = 1*4*0 + 1*1*0.8 + 3*4*0.8 + 3*1*0.96 = 13.28 ; denom 20 => 0.664
    np.testing.assert_allclose(distinct["normalized_mean_pair_weighted"][0, 1], 0.664, rtol=1e-6, atol=1e-6)
    # Same-weights normalized with weights_b = [1,3]:
    #   sum_ab = 1*1*0 + 1*3*0.8 + 3*1*0.8 + 3*3*0.96 = 13.44 ; denom 16 => 0.84
    np.testing.assert_allclose(same["normalized_mean_pair_weighted"][0, 1], 0.84, rtol=1e-6, atol=1e-6)
    assert distinct["normalized_mean_pair_weighted"][0, 1] != same["normalized_mean_pair_weighted"][0, 1]


# ── QA R1: cosine-only guard ─────────────────────────────────────────────────


def test_compute_agg_mats_rejects_non_cosine_metric() -> None:
    """compute_agg_mats raises ValueError for any metric other than 'cosine'."""
    tensors = [_unit_tensor([[1.0, 0.0]])]
    weights = [_uniform_weights(1)]
    with pytest.raises(ValueError):
        compute_agg_mats(tensors, tensors, weights, weights, metric="l2")


# ── QA R1: retrieval-row agg_method values are exactly the three weighted names ──


def test_retrieval_rows_agg_methods_are_exactly_weighted_reductions() -> None:
    """Retrieval rows carry only the three Part B aggregate names — no legacy leak."""
    tensors = [_unit_tensor([[1.0, 0.0]])]
    weights = [_uniform_weights(1)]
    agg_mats = compute_agg_mats(tensors, tensors, weights, weights, metric="cosine")

    rows, _ = compute_retrieval_rows(
        agg_mats,
        artists=["artist-a"],
        backbone="bb",
        bin_mode="temporal_global",
        std_thresh=0.3,
        rep_a="mean",
        rep_b="mean",
        metric="cosine",
        k=1,
        n_songs=1,
    )

    assert {r.agg_method for r in rows} == set(_ALLOWED_AGG_METHODS)
    for legacy in ("mean", "median", "max", "min", "medoid"):
        assert all(r.agg_method != legacy for r in rows)


# ── QA R2: optimizer & constants validation boundary coverage ──────────────


def test_optimize_std_threshold_default_agg_method_is_valid() -> None:
    """The default agg_method for optimize_std_threshold is 'target_weighted' and enabled.

    Regression for QA R1: the default was previously the legacy 'median', which
    is absent from _ALLOWED_AGG_METHODS and raised ValueError at runtime.
    """
    default = inspect.signature(optimize_std_threshold).parameters["agg_method"].default
    assert default == "target_weighted"
    assert default in _ALLOWED_AGG_METHODS


def test_eval_threshold_rejects_legacy_agg_method_at_entry() -> None:
    """_eval_threshold raises ValueError up front for a legacy aggregate name.

    The validation runs before the row-filter so a stale agg_method cannot
    silently match no row and return 0.0.
    """
    with pytest.raises(ValueError, match="median"):
        _eval_threshold(
            dist_thresh=1.0,
            backbone="bb",
            bin_mode="temporal_global",
            song_data=[],
            objective="disc_artist",
            k=10,
            rep_type="median",
            agg_method="median",
            metric="cosine",
        )


def test_optimize_std_threshold_rejects_agg_method_medoid() -> None:
    """optimize_std_threshold rejects agg_method='medoid' at the validation boundary.

    medoid is a valid representation, never an aggregation method.
    """
    with pytest.raises(ValueError, match="medoid"):
        optimize_std_threshold(
            con=None,
            backbone="bb",
            bin_mode="temporal_global",
            agg_method="medoid",
        )


def test_allowed_rep_types_include_medoid() -> None:
    """medoid is a valid representation type even though it is not an aggregation.

    This is the ledger-item-3 'allowed half': rep_type=medoid is permitted, only
    agg_method=medoid is rejected.
    """
    assert "medoid" in _ALLOWED_REP_TYPES


def test_optimizer_rep_validator_accepts_observed_medoid() -> None:
    """The optimizer representation default is the observed source medoid."""
    assert validate_optimizer_representation("medoid") == "medoid"


def test_optimizer_rep_validator_rejects_stale_synthetic_median() -> None:
    """Config/behavior gate: the stale coordinate-wise synthetic 'median' optimizer rep is rejected.

    Selecting the synthetic median as the optimizer representation would write a
    never-observed bin vector into the sim matrix. The vocabulary boundary rejects
    it loudly so a stale config cannot silently evaluate a synthetic centroid.
    """
    with pytest.raises(ValueError, match="medoid"):
        validate_optimizer_representation("median")


def test_optimizer_rep_validator_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="rep_type"):
        validate_optimizer_representation("bogus")


def test_shipped_default_pool_emits_observed_medoid_not_synthetic_median() -> None:
    """Under the shipped default rep_types, _pool_segment emits an OBSERVED medoid.

    Regression guard for R14: no synthetic coordinate-wise median vector is
    written. With the default ``pooling.rep_types = ["medoid"]`` the per-bin pool
    surface contains only the observed medoid (an actual source patch, identified
    by selected_global_idx) — the synthetic "median" rep is absent.
    """
    raw_rows = [[2.0, 0.0], [0.0, 2.0], [1.0, 1.0]]  # deliberately non-symmetric
    raw = np.asarray(raw_rows, dtype=np.float32)
    rt = RawTensor(raw)
    ut = rt.normalize()
    payloads = _pool_segment(rt, ut, indices=[0, 1, 2])

    # Synthetic coordinate-wise median must not appear in the default pool surface.
    assert "median" not in payloads
    assert "medoid" in payloads

    med = payloads["medoid"]
    # The medoid representation is an OBSERVED source patch, never synthetic.
    sel = med["selected_global_idx"]
    assert sel in (0, 1, 2)
    np.testing.assert_array_equal(np.asarray(med["vec_raw"].data), raw[sel])
