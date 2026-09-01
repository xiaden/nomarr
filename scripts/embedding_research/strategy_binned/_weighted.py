"""Pure weighted directional scoring reductions for the Part B repair.

These functions implement the exact retrieval-semantics reductions locked by
``tests/test_weighted_scoring.py`` (spec-first, Phase 1).  They are pure: they
read only their ``np.ndarray`` arguments, perform no I/O, and return a Python
``float`` scalar.  All accumulation is done in float64 to avoid float32
catastrophic cancellation; the caller is responsible for casting matrix
outputs to float32.

Ordered-pair convention
-----------------------
``S[a, b]`` is the similarity from **source bin** ``a`` of song A to
**target bin** ``b`` of song B (rows = source bins, columns = target bins).
For a directional pair ``(A, B)`` the matrix has shape ``(n_A, n_B)`` where
``n_A`` is the number of bins of A and ``n_B`` the number of bins of B.

``w_A`` and ``w_B`` are **positive temporal patch-count weights** (the number
of raw patches pooled into each bin by ``helpers/binning.temporal_segment``).

Validation contract
-------------------
* ``pair_similarity`` must be 2-D (source x target); a wrong ndim raises
  ``ValueError``.
* Every supplied weight vector must be 1-D and its length must equal the
  dimension it weights (target weights ``== n_cols``; source weights
  ``== n_rows``); a mismatch raises ``ValueError``.
* Zero-total-weight inputs (all weights zero on either side) raise
  ``ValueError`` because the denominator is undefined.
"""

from __future__ import annotations

import numpy as np

__all__ = ["bidirectional_weighted", "normalized_mean_pair_weighted", "target_weighted"]


def _as_float64_2d(pair_similarity: np.ndarray, name: str) -> np.ndarray:
    arr = np.asarray(pair_similarity)
    if arr.ndim != 2:
        raise ValueError(f"{name} must be a 2-D source-x-target similarity matrix, got ndim={arr.ndim}")
    return arr.astype(np.float64)


def _as_weights(weights: np.ndarray, length: int, name: str) -> np.ndarray:
    w = np.asarray(weights)
    if w.ndim != 1:
        raise ValueError(f"{name} must be 1-D, got ndim={w.ndim}")
    if w.shape[0] != length:
        raise ValueError(f"{name} length {w.shape[0]} != expected dimension {length}")
    w64 = w.astype(np.float64)
    total = float(w64.sum())
    if total == 0.0:
        raise ValueError(f"{name} sums to zero; the weighted denominator is undefined")
    return w64


def target_weighted(pair_similarity: np.ndarray, target_weights: np.ndarray) -> float:
    """Weighted directional score of one ordered pair.

    ``target_weighted(S, w_target) = (1/n_A) * sum_a( sum_b(w_target[b] * S[a,b]) / sum_b(w_target[b]) )``

    the mean over source bins ``a`` of the target-bin-weighted row means, where
    ``n_A`` is the number of source bins (rows) of ``S``.

    Returns a Python ``float`` computed in float64.
    """
    s = _as_float64_2d(pair_similarity, "pair_similarity")
    n_source = s.shape[0]
    if n_source == 0:
        raise ValueError("pair_similarity has zero source bins; score is undefined")
    w_target = _as_weights(target_weights, s.shape[1], "target_weights")
    total_w = float(w_target.sum())
    # Row means weighted by the target-bin patch counts, then mean over source bins.
    row_means = (s * w_target[None, :]).sum(axis=1) / total_w
    return float(row_means.sum() / n_source)


def normalized_mean_pair_weighted(
    pair_similarity: np.ndarray,
    source_weights: np.ndarray,
    target_weights: np.ndarray,
) -> float:
    """Weighted global bilinear mean of one ordered pair.

    ``normalized_mean_pair_weighted(S, w_A, w_B)
        = sum_ab(w_A[a] * w_B[b] * S[a,b]) / (sum_a(w_A[a]) * sum_b(w_B[b]))``

    ``w_A`` weights the source bins (rows), ``w_B`` the target bins (columns).

    Returns a Python ``float`` computed in float64.
    """
    s = _as_float64_2d(pair_similarity, "pair_similarity")
    w_a = _as_weights(source_weights, s.shape[0], "source_weights")
    w_b = _as_weights(target_weights, s.shape[1], "target_weights")
    numerator = float((w_a[:, None] * w_b[None, :] * s).sum())
    denominator = float(w_a.sum() * w_b.sum())
    return float(numerator / denominator)


def bidirectional_weighted(
    forward_similarity: np.ndarray,
    reverse_similarity: np.ndarray,
    forward_target_weights: np.ndarray,
    reverse_target_weights: np.ndarray,
) -> float:
    """Arithmetic mean of the two separately-supplied directional scores.

    ``bidirectional_weighted(fwd, rev, w_fwd_tgt, w_rev_tgt)
        = (target_weighted(fwd, w_fwd_tgt) + target_weighted(rev, w_rev_tgt)) / 2``

    The reverse matrix is a *separately supplied* input — it is never derived
    by transposing or copying the forward matrix.  The forward score weights
    the target bins of the forward matrix; the reverse score weights the
    target bins of the reverse matrix.

    Returns a Python ``float`` computed in float64.
    """
    fwd = target_weighted(forward_similarity, forward_target_weights)
    rev = target_weighted(reverse_similarity, reverse_target_weights)
    return float((fwd + rev) / 2.0)
