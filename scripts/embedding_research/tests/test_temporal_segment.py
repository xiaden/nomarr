"""Regression tests locking the temporal segmentation contract (NO semantic change).

These tests document the exact, frozen behaviour of ``temporal_segment`` in
``helpers/binning.py`` so that future edits cannot silently drift from it:

* input rows are L2-normalised unit vectors; the running centroid is the
  *renormalized* spherical mean (``vec / ||vec||``) of the in-range patches;
* a split happens only when ``dist_fn(patch, centroid) > threshold`` (strict ``>``);
* ``temporal_global`` uses ``global_dist`` (L2) and ``temporal_perdim`` uses
  ``perdim_dist`` (Chebyshev);
* at most ``OUTLIER_WINDOW`` (3) consecutive boundary patches are absorbed as
  outliers when a later patch returns in range; absorbed patches are excluded
  from the segment's ``indices`` (and therefore from pooling); otherwise a hard
  split is forced;
* ``temporal_segment_with_diagnostics`` stays in lockstep with ``temporal_segment``
  and reports the boundary-reason counters.

This phase only adds coverage — it does not change the segmentation semantics.
"""

from __future__ import annotations

import numpy as np

from scripts.embedding_research.helpers.binning import (
    DIST_FNS,
    OUTLIER_WINDOW,
    global_dist,
    perdim_dist,
    temporal_segment,
    temporal_segment_with_diagnostics,
)

_SQRT2 = float(np.sqrt(2.0))


# ── Distance functions ─────────────────────────────────────────────────────────


def test_outlier_window_is_three() -> None:
    """The absorption window is fixed at 3 consecutive boundary patches."""
    assert OUTLIER_WINDOW == 3


def test_dist_fns_map_modes_correctly() -> None:
    """temporal_global -> global_dist (L2); temporal_perdim -> perdim_dist (Chebyshev)."""
    assert DIST_FNS["temporal_global"] is global_dist
    assert DIST_FNS["temporal_perdim"] is perdim_dist


def test_global_dist_is_euclidean_l2() -> None:
    """global_dist is the L2 norm of the difference vector."""
    a = np.array([1.0, 0.0, 0.0])
    b = np.array([0.0, 1.0, 0.0])
    assert abs(global_dist(a, b) - _SQRT2) < 1e-9


def test_perdim_dist_is_chebyshev() -> None:
    """perdim_dist is the max absolute component difference."""
    a = np.array([1.0, 0.0])
    b = np.array([0.0, 1.0])
    assert perdim_dist(a, b) == 1.0


# ── Strict `>` thresholding ────────────────────────────────────────────────────


def test_split_requires_strictly_greater_than_threshold() -> None:
    """A patch exactly AT the threshold does NOT split (strict >)."""
    thresh = 1.0
    p0 = np.array([1.0, 0.0])
    p1 = np.array([0.5, float(np.sqrt(3.0)) / 2.0])  # L2 distance from p0 == 1.0
    assert abs(global_dist(p0, p1) - 1.0) < 1e-9

    segments = temporal_segment(np.array([p0, p1]), thresh, global_dist)
    assert segments == [{"indices": [0, 1], "outlier_count": 0}]


def test_patch_just_over_threshold_splits() -> None:
    """A patch just over the threshold triggers a boundary / new bin."""
    thresh = 1.0
    p0 = np.array([1.0, 0.0])
    p1 = np.array([0.0, 1.0])  # distance sqrt(2) > 1.0
    segments = temporal_segment(np.array([p0, p1]), thresh, global_dist)
    assert segments == [
        {"indices": [0], "outlier_count": 0},
        {"indices": [1], "outlier_count": 0},
    ]


# ── Renormalized running spherical centroid ────────────────────────────────────


def test_running_spherical_centroid_is_renormalized() -> None:
    """Boundary checks use the renormalized running mean, not the original patch.

    p1 is in range, pulling the centroid toward it; p2 is far from the ORIGINAL
    first patch but near the drifted centroid, so it stays in-range. This only
    holds if the centroid is the renormalized spherical mean of all in-range
    patches rather than a fixed reference.
    """
    thresh = 1.2
    p0 = np.array([1.0, 0.0, 0.0])
    p1 = np.array([0.5, float(np.sqrt(3.0)) / 2.0, 0.0])  # dist 1.0 < 1.2 -> joins
    # dist from the drifted centroid (~[0.866, 0.5, 0]) is ~0.82 < 1.2,
    # but dist from p0 is ~1.26 > 1.2.
    p2 = np.array([0.2, 0.98, 0.0])
    assert global_dist(p2, p0) > thresh  # would split against the original
    assert global_dist(p2, np.array([0.8660254, 0.5, 0.0])) < thresh

    segments = temporal_segment(np.array([p0, p1, p2]), thresh, global_dist)
    assert segments == [{"indices": [0, 1, 2], "outlier_count": 0}]


# ── Outlier absorption / exclusion / hard split ────────────────────────────────


def test_boundary_patch_absorbed_as_outlier_when_later_returns() -> None:
    """A boundary patch followed by an in-range patch is absorbed and excluded."""
    thresh = 1.0
    p0 = np.array([1.0, 0.0, 0.0])
    p1 = np.array([0.0, 1.0, 0.0])  # boundary (dist sqrt2 > 1.0)
    p2 = np.array([0.9, 0.1, 0.0])  # returns in range
    segments = temporal_segment(np.array([p0, p1, p2]), thresh, global_dist)
    assert segments == [{"indices": [0, 2], "outlier_count": 1}]
    assert 1 not in segments[0]["indices"]  # absorbed patch excluded from pooling


def test_three_consecutive_boundary_patches_absorbed_on_return() -> None:
    """Up to OUTLIER_WINDOW consecutive boundary patches absorb when a later one returns."""
    thresh = 0.5
    p0 = np.array([1.0, 0.0, 0.0])
    p1 = np.array([0.0, 1.0, 0.0])
    p2 = np.array([-1.0, 0.0, 0.0])
    p3 = np.array([0.0, -1.0, 0.0])
    p4 = np.array([0.9, 0.2, 0.0])  # in range -> absorbs p1,p2,p3
    segments = temporal_segment(np.array([p0, p1, p2, p3, p4]), thresh, global_dist)
    assert segments == [{"indices": [0, 4], "outlier_count": 3}]


def test_hard_split_after_more_than_three_consecutive_boundary() -> None:
    """Four+ consecutive boundary patches force a hard split, not absorption."""
    thresh = 0.5
    p0 = np.array([1.0, 0.0, 0.0])
    p1 = np.array([0.0, 1.0, 0.0])
    p2 = np.array([-1.0, 0.0, 0.0])
    p3 = np.array([0.0, -1.0, 0.0])
    p4 = np.array([0.6, 0.6, 0.0])  # also boundary -> run length 4 > window 3
    segments = temporal_segment(np.array([p0, p1, p2, p3, p4]), thresh, global_dist)
    assert segments == [
        {"indices": [0], "outlier_count": 0},
        {"indices": [1, 2, 3, 4], "outlier_count": 0},
    ]


# ── Per-dimension (Chebyshev) mode ─────────────────────────────────────────────


def test_perdim_mode_uses_chebyshev_strict_threshold() -> None:
    """temporal_perdim splits only when the Chebyshev distance exceeds the threshold."""
    p0 = np.array([1.0, 0.0])
    p1 = np.array([0.0, 1.0])  # perdim_dist == 1.0
    assert perdim_dist(p0, p1) == 1.0

    # threshold == 1.0: not strictly greater -> no split.
    segments = temporal_segment(np.array([p0, p1]), 1.0, perdim_dist)
    assert segments == [{"indices": [0, 1], "outlier_count": 0}]

    # threshold == 0.5: 1.0 > 0.5 -> split.
    segments2 = temporal_segment(np.array([p0, p1]), 0.5, perdim_dist)
    assert segments2 == [
        {"indices": [0], "outlier_count": 0},
        {"indices": [1], "outlier_count": 0},
    ]


# ── Diagnostics in lockstep ────────────────────────────────────────────────────


def test_diagnostics_lockstep_with_temporal_segment() -> None:
    """temporal_segment_with_diagnostics returns the same bins plus reason counters."""
    thresh = 0.5
    patches = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],  # boundary, then p2 returns -> absorbed
            [0.9, 0.2, 0.0],
            [1.0, 0.0, 0.0],  # in range
            [0.0, 1.0, 0.0],  # boundary, then p5 returns -> absorbed
            [0.9, 0.1, 0.0],
        ],
        dtype=np.float32,
    )

    segments, diagnostics = temporal_segment_with_diagnostics(patches, thresh, global_dist)
    assert segments == temporal_segment(patches, thresh, global_dist)
    assert set(diagnostics) == {
        "distance_boundary_count",
        "absorbed_outlier_count",
        "hard_split_count",
        "return_from_outlier_count",
    }
    assert diagnostics == {
        "distance_boundary_count": 2,
        "absorbed_outlier_count": 2,
        "hard_split_count": 0,
        "return_from_outlier_count": 2,
    }
    assert segments == [{"indices": [0, 2, 3, 5], "outlier_count": 2}]


def test_diagnostics_hard_split_count_increments() -> None:
    """A hard split is counted in diagnostics alongside the bin boundary."""
    thresh = 0.5
    patches = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [-1.0, 0.0, 0.0],
            [0.0, -1.0, 0.0],
            [0.6, 0.6, 0.0],
        ],
        dtype=np.float32,
    )
    segments, diagnostics = temporal_segment_with_diagnostics(patches, thresh, global_dist)
    assert segments == temporal_segment(patches, thresh, global_dist)
    assert diagnostics["hard_split_count"] == 1
    assert len(segments) == 2


def test_empty_input_returns_empty_with_zero_diagnostics() -> None:
    """Empty patch input yields no bins and all-zero diagnostic counters."""
    segments, diagnostics = temporal_segment_with_diagnostics(np.empty((0, 4), dtype=np.float32), 0.5, global_dist)
    assert segments == []
    assert all(value == 0 for value in diagnostics.values())
