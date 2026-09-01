"""Numerical contract tests for the Part B weighted directional scoring reductions.

This module pins the exact numerical and directional contract that
``scripts/embedding_research/strategy_binned/_weighted.py`` satisfies.  The
implementation exists and these tests are green (spec-first Phase 1 contract
fully realized in Phase 2); keep this contract in sync with any formula change.

Ordered-pair convention
-----------------------
``S[a, b]`` is the similarity from **source bin** ``a`` of song A to
**target bin** ``b`` of song B (rows = source bins, columns = target bins).
For a directional pair ``(A, B)`` the matrix has shape ``(n_A, n_B)`` where
``n_A`` is the number of bins of A and ``n_B`` the number of bins of B.

``w_A`` and ``w_B`` are **positive temporal patch-count weights**, one per bin
for the respective song (the number of raw patches pooled into each bin from
``helpers/binning.temporal_segment``).  They are strictly positive and never
sum to zero for a valid input.

Ordered song pairs are evaluated independently.  The reverse direction
``S_BA`` (B -> A) is a *separately supplied* matrix and must never be derived
by transposing or copying the forward matrix ``S_AB`` (A -> B).

Implemented signatures (in ``scripts/embedding_research/strategy_binned/_weighted.py``)
---------------------------------------------------------------------------------------
The functions live in ``scripts/embedding_research/strategy_binned/_weighted.py``::

    target_weighted(pair_similarity: np.ndarray, target_weights: np.ndarray) -> float
    normalized_mean_pair_weighted(pair_similarity: np.ndarray, source_weights: np.ndarray, target_weights: np.ndarray) -> float
    bidirectional_weighted(
        forward_similarity: np.ndarray,
        reverse_similarity: np.ndarray,
        forward_target_weights: np.ndarray,
        reverse_target_weights: np.ndarray,
    ) -> float

Exact formulas
--------------
* ``target_weighted(S, w_target) = (1/n_A) * sum_a( sum_b(w_target[b] * S[a,b]) / sum_b(w_target[b]) )``
  — the mean over source bins ``a`` of the target-bin-weighted row means.
* ``normalized_mean_pair_weighted(S, w_A, w_B) = sum_ab(w_A[a] * w_B[b] * S[a,b]) / (sum_a(w_A[a]) * sum_b(w_B[b]))``.
* ``bidirectional_weighted(fwd, rev, w_fwd_tgt, w_rev_tgt) = (target_weighted(fwd, w_fwd_tgt) + target_weighted(rev, w_rev_tgt)) / 2``.

Validation contract
-------------------
* ``pair_similarity`` must be a 2-D array (source x target).  A wrong ndim
  raises ``ValueError``.
* ``target_weights`` length must equal the target dimension (the number of
  columns).  A length mismatch raises ``ValueError``.
* For ``normalized_mean_pair_weighted`` / ``bidirectional_weighted`` every
  supplied weight vector must match its matrix dimension; a mismatch raises
  ``ValueError``.
* Zero-total-weight inputs (all weights zero on either side) raise
  ``ValueError`` (the denominator is undefined).
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research.strategy_binned._weighted import (
    bidirectional_weighted,
    normalized_mean_pair_weighted,
    target_weighted,
)

# Exact numerical fixture from the Part B ledger.
_S = np.array([[1.0, 0.2], [0.4, 0.8]])
_W_A = np.array([1.0, 3.0])
_W_B = np.array([2.0, 1.0])

# Documented arithmetic tolerance for the exact fixture.
_TOL = 1e-9


# ── P1-S2: formula / signature smoke tests (valid inputs) ──────────────────────


def test_target_weighted_matches_documented_formula() -> None:
    """target_weighted is the mean over source bins of target-weighted row means."""
    expected = (
        ((_W_B[0] * _S[0, 0] + _W_B[1] * _S[0, 1]) / _W_B.sum())
        + ((_W_B[0] * _S[1, 0] + _W_B[1] * _S[1, 1]) / _W_B.sum())
    ) / 2.0
    np.testing.assert_allclose(target_weighted(_S, _W_B), expected, rtol=_TOL, atol=_TOL)


def test_normalized_mean_pair_weighted_matches_documented_formula() -> None:
    """normalized_mean_pair_weighted is the globally weighted bilinear mean."""
    expected = (_W_A[:, None] * _W_B[None, :] * _S).sum() / (_W_A.sum() * _W_B.sum())
    np.testing.assert_allclose(
        normalized_mean_pair_weighted(_S, _W_A, _W_B),
        float(expected),
        rtol=_TOL,
        atol=_TOL,
    )


def test_bidirectional_weighted_matches_documented_formula() -> None:
    """bidirectional_weighted is the arithmetic mean of the two supplied directions."""
    fwd = target_weighted(_S, _W_B)
    rev = target_weighted(_S.T, _W_A)
    np.testing.assert_allclose(
        bidirectional_weighted(_S, _S.T, _W_B, _W_A),
        (fwd + rev) / 2.0,
        rtol=_TOL,
        atol=_TOL,
    )


def test_target_weighted_returns_float() -> None:
    """target_weighted returns a scalar float, not an array."""
    result = target_weighted(_S, _W_B)
    assert isinstance(result, float)


# ── P1-S3: exact numerical fixture ─────────────────────────────────────────────


def test_exact_fixture_target_a_to_b() -> None:
    """S=[[1,.2],[.4,.8]], w_B=[2,1] -> target A->B = 0.6333333333."""
    np.testing.assert_allclose(target_weighted(_S, _W_B), 0.6333333333333333, rtol=_TOL, atol=_TOL)


def test_exact_fixture_target_b_to_a() -> None:
    """S.T, w_A=[1,3] -> target B->A = 0.6000000000."""
    np.testing.assert_allclose(target_weighted(_S.T, _W_A), 0.6000000000, rtol=_TOL, atol=_TOL)


def test_exact_fixture_bidirectional() -> None:
    """bidirectional = 0.6166666667."""
    np.testing.assert_allclose(bidirectional_weighted(_S, _S.T, _W_B, _W_A), 0.6166666667, rtol=_TOL, atol=_TOL)


def test_exact_fixture_normalized_mean_pair() -> None:
    """normalized mean-pair = 0.5833333333."""
    np.testing.assert_allclose(normalized_mean_pair_weighted(_S, _W_A, _W_B), 0.5833333333, rtol=_TOL, atol=_TOL)


# ── P1-S2: invalid shapes / zero weights fail clearly ──────────────────────────


def test_target_weighted_wrong_ndim_raises() -> None:
    """A 1-D similarity input (not source x target) raises ValueError."""
    with pytest.raises(ValueError):
        target_weighted(np.array([1.0, 0.2]), _W_B)


def test_target_weighted_weight_length_mismatch_raises() -> None:
    """Weights length != target (column) dimension raises ValueError."""
    with pytest.raises(ValueError):
        target_weighted(_S, np.array([1.0, 2.0, 3.0]))


def test_target_weighted_zero_total_weight_raises() -> None:
    """Zero total target weight (undefined denominator) raises ValueError."""
    with pytest.raises(ValueError):
        target_weighted(_S, np.array([0.0, 0.0]))


def test_normalized_mean_pair_weighted_zero_source_weight_raises() -> None:
    """Zero total source weight raises ValueError."""
    with pytest.raises(ValueError):
        normalized_mean_pair_weighted(_S, np.array([0.0, 0.0]), _W_B)


def test_normalized_mean_pair_weighted_zero_target_weight_raises() -> None:
    """Zero total target weight raises ValueError."""
    with pytest.raises(ValueError):
        normalized_mean_pair_weighted(_S, _W_A, np.array([0.0, 0.0]))


def test_normalized_mean_pair_weighted_shape_mismatch_raises() -> None:
    """Source weights not matching the row dimension raises ValueError."""
    with pytest.raises(ValueError):
        normalized_mean_pair_weighted(_S, np.array([1.0, 2.0, 3.0]), _W_B)


def test_bidirectional_weighted_reverse_zero_weight_raises() -> None:
    """A zero-total reverse-target weight raises ValueError."""
    with pytest.raises(ValueError):
        bidirectional_weighted(_S, _S.T, _W_B, np.array([0.0, 0.0]))


# ── P1-S4: asymmetric directionality (no mirroring) ────────────────────────────


def test_target_weighted_can_differ_by_direction() -> None:
    """target_weighted is directional: forward A->B and reverse B->A differ."""
    fwd = target_weighted(_S, _W_B)  # 0.6333...
    rev = target_weighted(_S.T, _W_A)  # 0.6
    assert fwd != rev
    np.testing.assert_allclose(fwd, 0.6333333333333333, rtol=_TOL, atol=_TOL)
    np.testing.assert_allclose(rev, 0.6000000000, rtol=_TOL, atol=_TOL)


# A reverse matrix that is NOT the forward transpose.
_S_REVERSE = np.array([[0.9, 0.1], [0.3, 0.7]])


def test_bidirectional_uses_supplied_reverse_not_mirrored() -> None:
    """bidirectional_weighted uses the supplied reverse matrix; ignoring it
    (mirroring the forward transpose instead) yields a different, wrong score."""
    fwd = target_weighted(_S, _W_B)  # 0.6333...
    supplied_rev = target_weighted(_S_REVERSE, _W_A)  # 0.45
    mirrored_rev = target_weighted(_S.T, _W_A)  # 0.6 (forward transposed)

    result = bidirectional_weighted(_S, _S_REVERSE, _W_B, _W_A)
    expected = (fwd + supplied_rev) / 2.0  # 0.541666...
    np.testing.assert_allclose(result, expected, rtol=_TOL, atol=_TOL)

    # This assertion FAILS if the implementation derived the reverse from the
    # forward matrix by mirroring (which would yield (fwd + mirrored_rev)/2).
    assert result != (fwd + mirrored_rev) / 2.0


def test_bidirectional_with_distinct_reverse_gives_different_score() -> None:
    """Swapping the supplied reverse changes the bidirectional score, proving
    the reverse direction is not assumed to be the forward transpose."""
    with_mirrored = bidirectional_weighted(_S, _S.T, _W_B, _W_A)  # 0.616666...
    with_distinct = bidirectional_weighted(_S, _S_REVERSE, _W_B, _W_A)  # 0.541666...
    assert with_mirrored != with_distinct
    np.testing.assert_allclose(with_distinct, 0.5416666666666666, rtol=_TOL, atol=_TOL)


# ── P2-S3: symmetry exists only under tested conditions ───────────────────────


def test_bidirectional_weighted_symmetric_when_reverse_consistent() -> None:
    """bidirectional_weighted is symmetric exactly when the two supplied directions
    are swapped consistently (forward<->reverse with target weights swapped)."""
    fwd_first = bidirectional_weighted(_S, _S_REVERSE, _W_B, _W_A)
    rev_first = bidirectional_weighted(_S_REVERSE, _S, _W_A, _W_B)
    np.testing.assert_allclose(fwd_first, rev_first, rtol=_TOL, atol=_TOL)


def test_normalized_pair_weighted_symmetric_only_when_transpose_swapped() -> None:
    """normalized_mean_pair_weighted is symmetric only when the reverse similarity
    is the transpose and the source/target weights are swapped."""
    swapped = normalized_mean_pair_weighted(_S.T, _W_B, _W_A)
    forward = normalized_mean_pair_weighted(_S, _W_A, _W_B)
    np.testing.assert_allclose(swapped, forward, rtol=_TOL, atol=_TOL)
    # With weights NOT swapped, the same matrix transposed gives a different score
    # (directional), proving the symmetry requires the weight swap too.
    unswapped = normalized_mean_pair_weighted(_S.T, _W_A, _W_B)
    assert unswapped != forward


def test_target_weighted_remains_directional() -> None:
    """target_weighted stays directional: differing target weights/representations
    yield different forward vs reverse scores."""
    fwd = target_weighted(_S, _W_B)
    rev = target_weighted(_S.T, _W_A)
    assert fwd != rev


# ── P3-S1: property-style numerical tests (deterministic, no hypothesis) ─────
#
# These lock the mathematical *properties* of the reductions — weight scaling
# invariance, one-bin reduction, all-unit-weight behaviour, finite-output
# guarantees, and the forward/reverse/bidirectional relationship — independent
# of any single numeric fixture.  All inputs are fixed, small, and deterministic
# (no property-fuzz dependency).

_PROP_S = np.array([[0.9, 0.2, 0.1], [0.3, 0.7, 0.5], [0.4, 0.6, 0.8]], dtype=float)
_PROP_WA = np.array([2.0, 5.0, 3.0])
_PROP_WB = np.array([4.0, 1.0, 2.0])


# (a) weight-scaling invariance — scaling any weight vector by a positive
#     constant must not change any of the three scores.


def test_target_weighted_invariant_to_target_weight_scaling() -> None:
    base = target_weighted(_PROP_S, _PROP_WB)
    for c in (0.5, 2.0, 10.0, 1e-3):
        np.testing.assert_allclose(target_weighted(_PROP_S, c * _PROP_WB), base, rtol=_TOL, atol=_TOL)


def test_normalized_mean_pair_weighted_invariant_to_weight_scaling() -> None:
    base = normalized_mean_pair_weighted(_PROP_S, _PROP_WA, _PROP_WB)
    for c in (0.1, 3.0, 100.0):
        np.testing.assert_allclose(
            normalized_mean_pair_weighted(_PROP_S, c * _PROP_WA, _PROP_WB), base, rtol=_TOL, atol=_TOL
        )
        np.testing.assert_allclose(
            normalized_mean_pair_weighted(_PROP_S, _PROP_WA, c * _PROP_WB), base, rtol=_TOL, atol=_TOL
        )
        # Scaling one side up and the other down also leaves the ratio unchanged.
        np.testing.assert_allclose(
            normalized_mean_pair_weighted(_PROP_S, c * _PROP_WA, (1.0 / c) * _PROP_WB), base, rtol=_TOL, atol=_TOL
        )


def test_bidirectional_weighted_invariant_to_weight_scaling() -> None:
    base = bidirectional_weighted(_PROP_S, _PROP_S.T, _PROP_WB, _PROP_WA)
    for c in (0.25, 4.0):
        np.testing.assert_allclose(
            bidirectional_weighted(_PROP_S, _PROP_S.T, c * _PROP_WB, _PROP_WA), base, rtol=_TOL, atol=_TOL
        )
        np.testing.assert_allclose(
            bidirectional_weighted(_PROP_S, _PROP_S.T, _PROP_WB, c * _PROP_WA), base, rtol=_TOL, atol=_TOL
        )


# (b) one-bin reduction — a 1x1 matrix collapses each reduction to S[0,0].


def test_one_bin_target_weighted_reduces_to_scalar() -> None:
    s = np.array([[0.75]])
    for w in (np.array([1.0]), np.array([5.0]), np.array([0.25])):
        np.testing.assert_allclose(target_weighted(s, w), 0.75, rtol=_TOL, atol=_TOL)


def test_one_bin_normalized_mean_pair_reduces_to_scalar() -> None:
    s = np.array([[0.75]])
    for wa, wb in ((np.array([1.0]), np.array([1.0])), (np.array([2.0]), np.array([7.0]))):
        np.testing.assert_allclose(normalized_mean_pair_weighted(s, wa, wb), 0.75, rtol=_TOL, atol=_TOL)


def test_one_bin_bidirectional_is_mean_of_two_directions() -> None:
    fwd = np.array([[0.75]])
    rev = np.array([[0.25]])
    for wf, wr in ((np.array([1.0]), np.array([1.0])), (np.array([3.0]), np.array([2.0]))):
        np.testing.assert_allclose(bidirectional_weighted(fwd, rev, wf, wr), 0.5, rtol=_TOL, atol=_TOL)


# (c) all-unit weights — the reductions collapse to unweighted means.


def test_all_unit_target_weighted_is_row_mean_of_row_means() -> None:
    ones = np.ones(_PROP_S.shape[1])
    expected = float(_PROP_S.mean(axis=1).mean())
    np.testing.assert_allclose(target_weighted(_PROP_S, ones), expected, rtol=_TOL, atol=_TOL)


def test_all_unit_normalized_pair_weighted_is_global_mean() -> None:
    wa = np.ones(_PROP_S.shape[0])
    wb = np.ones(_PROP_S.shape[1])
    np.testing.assert_allclose(
        normalized_mean_pair_weighted(_PROP_S, wa, wb), float(_PROP_S.mean()), rtol=_TOL, atol=_TOL
    )


# (d) finite outputs for finite inputs — including weights summing to 1 and
#     arbitrary positive weights.


def test_finite_outputs_for_finite_inputs() -> None:
    s = np.array([[0.2, 0.7], [0.9, 0.4]])
    wa = np.array([0.6, 0.4])  # sums to 1
    wb = np.array([0.3, 0.7])  # sums to 1
    assert np.isfinite(target_weighted(s, wb))
    assert np.isfinite(normalized_mean_pair_weighted(s, wa, wb))
    assert np.isfinite(bidirectional_weighted(s, s.T, wb, wa))
    # Arbitrary (un-normalised) positive weights — very small and very large.
    assert np.isfinite(target_weighted(s, np.array([1e-8, 1e8])))
    assert np.isfinite(normalized_mean_pair_weighted(s, np.array([0.001, 0.002]), np.array([5.0, 3.0])))
    assert np.isfinite(bidirectional_weighted(s, s.T, np.array([1e-8, 1e8]), wa))


# (e) forward/reverse/bidirectional relationship.


def test_bidirectional_is_mean_of_two_target_weighted_directions() -> None:
    rev = _PROP_S.T
    expected = (target_weighted(_PROP_S, _PROP_WB) + target_weighted(rev, _PROP_WA)) / 2.0
    np.testing.assert_allclose(bidirectional_weighted(_PROP_S, rev, _PROP_WB, _PROP_WA), expected, rtol=_TOL, atol=_TOL)


def test_bidirectional_symmetric_consistent_equals_both_directions() -> None:
    """When forward == reverse with equal weights, bidirectional equals both."""
    s = np.array([[1.0, 0.2, 0.3], [0.2, 0.8, 0.5], [0.3, 0.5, 0.9]])
    w = np.array([2.0, 1.0, 3.0])
    both = target_weighted(s, w)
    np.testing.assert_allclose(bidirectional_weighted(s, s, w, w), both, rtol=_TOL, atol=_TOL)
