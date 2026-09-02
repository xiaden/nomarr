"""Plan C Phase 2: authoritative segmentation membership + observed medoid tests.

These tests prove the pure, vector-free segmentation map that Phase 3 fans out
into ``seg_meta`` / ``seg_membership``:

* Exact membership (incl. absorbed outliers) matches PTC running-centroid semantics
  (strict ``>``, ``OUTLIER_WINDOW=3``) — the per-segment *in-range* membership equals
  ``helpers.binning.temporal_segment``'s ``indices``, and absorbed-outlier rows equal
  its ``outlier_count``, while additionally recording WHICH indices are absorbed.
* Membership is never reconstructed from the inclusive ``start_idx``/``end_idx``
  ranges (those are structural report metadata only).
* Medoids are OBSERVED source patch indices with smallest-index tie-breaking, chosen
  from in-range members; never a copied/synthetic vector, never an absorbed outlier.
* Invariant relationships hold: membership row count == member_count; absorbed-outlier
  rows == absorbed_outlier_count; patch-count weight == member_count incl. absorbed
  outliers; ``segment_signature`` is deterministic over membership + medoid; membership
  partitions the stream exactly once.
* The external ``global_pool:{backbone}:medoid`` identity is preserved via delegation to
  ``pooling.select_global_medoid_index`` (observed index only), and ``medoid`` never
  re-enters as a scoring/aggregation method.
"""

from __future__ import annotations

from dataclasses import fields

import numpy as np
import pytest

from scripts.embedding_research.helpers.binning import global_dist, perdim_dist, temporal_segment
from scripts.embedding_research.helpers.segmentation import (
    MembershipSegment,
    authoritative_segmentation,
    global_flat_medoid_source_index,
    segment_signature,
    select_medoid_source_index,
    validate_full_partition,
    validate_segment_invariants,
)
from scripts.embedding_research.pooling import select_global_medoid_index
from scripts.embedding_research.strategy_binned import _constants


def _unit_rows(rng: np.random.Generator, n: int, d: int, spread: float = 1.5) -> np.ndarray:
    """Deterministic L2-unit rows that reliably exercise boundary/return behaviour."""
    m = rng.standard_normal((n, d)) * spread
    if n:
        m[0] += 3.0  # keep the seed row comfortably nonzero
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (m / norms).astype(np.float32)


def _in_range(seg):
    return [i for i, flag in zip(seg.member_indices, seg.is_absorbed_outlier, strict=False) if not flag]


def _assert_matches_temporal(norm, threshold, dist_fn, outlier_window=3):
    segs = authoritative_segmentation(norm, threshold, dist_fn, outlier_window=outlier_window)
    ts = temporal_segment(norm, threshold, dist_fn, outlier_window=outlier_window)
    assert len(segs) == len(ts), "segment count must match temporal_segment"
    for seg, t in zip(segs, ts, strict=False):
        # In-range membership is exactly temporal_segment's pooling indices.
        assert _in_range(seg) == list(t["indices"])
        # Absorbed-outlier rows equal temporal_segment's outlier count.
        assert seg.absorbed_outlier_count == t["outlier_count"]
        validate_segment_invariants(seg)
    validate_full_partition(segs, len(norm))
    return segs


def test_empty_matrix_returns_no_segments():
    norm = np.zeros((0, 4), dtype=np.float32)
    assert authoritative_segmentation(norm, 0.5, global_dist) == ()


def test_single_patch_is_one_member_segment():
    norm = np.array([[1.0, 0.0]], dtype=np.float32)
    segs = _assert_matches_temporal(norm, 0.5, global_dist)
    (seg,) = segs
    assert seg.member_indices == (0,)
    assert seg.is_absorbed_outlier == (False,)
    assert seg.medoid_source_patch_idx == 0
    assert seg.weight == seg.member_count == 1


def test_absorbed_interior_outlier_records_index_and_flag():
    # p0 == p2, p1 orthogonal and far from the centroid -> p1 is absorbed between
    # two in-range members (historical single-outlier absorption).
    norm = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]], dtype=np.float32)
    segs = _assert_matches_temporal(norm, 1.0, global_dist)
    (seg,) = segs
    assert seg.member_indices == (0, 1, 2)
    assert seg.is_absorbed_outlier == (False, True, False)
    assert seg.absorbed_outlier_count == 1
    assert seg.weight == seg.member_count == 3
    assert seg.start_idx == 0 and seg.end_idx == 2
    # The medoid is chosen from observed IN-RANGE members (never the outlier).
    assert seg.medoid_source_patch_idx in (0, 2)


def test_membership_is_not_derivable_from_start_end_range():
    # Same geometry as above: idx 1 lies strictly between start_idx and end_idx yet
    # is an absorbed outlier.  A range-contiguous reconstruction would flag every
    # interior patch as an in-range member, which is wrong.
    norm = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]], dtype=np.float32)
    (seg,) = authoritative_segmentation(norm, 1.0, global_dist)
    assert seg.start_idx == 0 and seg.end_idx == 2
    assert seg.is_absorbed_outlier == (False, True, False)
    # Naive "range => all members" reconstruction contradicts the authoritative flags.
    naive_members = tuple(False for _ in range(seg.start_idx, seg.end_idx + 1))
    assert naive_members != seg.is_absorbed_outlier
    # idx 1 is an interior index whose outlier status cannot be recovered from the range.
    assert seg.is_absorbed_outlier[1] is True


def test_hard_split_partitions_stream_once():
    # p0 in range; p1..p4 all far and mutually identical => the outlier window (3) is
    # exceeded without a return, forcing a hard split into a second segment.
    norm = np.array([[1.0, 0.0], [0.0, 1.0], [0.0, 1.0], [0.0, 1.0], [0.0, 1.0]], dtype=np.float32)
    segs = _assert_matches_temporal(norm, 0.5, global_dist)
    assert len(segs) == 2
    assert segs[0].member_indices == (0,)
    assert segs[0].is_absorbed_outlier == (False,)
    assert segs[1].member_indices == (1, 2, 3, 4)
    assert segs[1].is_absorbed_outlier == (False, False, False, False)
    # Every source index 0..4 appears exactly once across segments.
    validate_full_partition(segs, 5)


@pytest.mark.parametrize("dist_fn", [global_dist, perdim_dist])
@pytest.mark.parametrize("outlier_window", [1, 2, 3, 4])
def test_random_membership_matches_temporal_semantics(dist_fn, outlier_window):
    rng = np.random.default_rng(20260830)
    for _ in range(8):
        n = int(rng.integers(1, 40))
        d = int(rng.integers(2, 24))
        threshold = float(rng.uniform(0.1, 1.6))
        norm = _unit_rows(rng, n, d)
        _assert_matches_temporal(norm, threshold, dist_fn, outlier_window=outlier_window)


def test_medoid_tie_break_selects_smallest_index():
    # Two identical best candidates -> equal centrality -> np.argmax first-max picks
    # the smallest source index (observed rows [0] and [2] identical here).
    norm = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]], dtype=np.float32)
    (seg,) = authoritative_segmentation(norm, 1.0, global_dist)
    assert seg.medoid_source_patch_idx == 0
    # Direct check on the selector: index 5 is identical to index 0 and both dominate.
    rows = np.array(
        [[1.0, 0.0], [0.2, 0.98], [0.0, 1.0], [0.3, 0.95], [0.1, 0.99], [1.0, 0.0]],
        dtype=np.float32,
    )
    assert select_medoid_source_index(rows, [0, 5]) == 0  # tie -> smallest


def test_medoid_is_observed_in_range_member_never_outlier():
    rng = np.random.default_rng(7)
    for _ in range(12):
        norm = _unit_rows(rng, int(rng.integers(1, 50)), 16)
        threshold = float(rng.uniform(0.1, 1.6))
        for dist_fn in (global_dist, perdim_dist):
            for seg in authoritative_segmentation(norm, threshold, dist_fn):
                validate_segment_invariants(seg)
                assert seg.medoid_source_patch_idx in seg.member_indices
                flag_by_idx = dict(zip(seg.member_indices, seg.is_absorbed_outlier, strict=False))
                assert flag_by_idx[seg.medoid_source_patch_idx] is False


def test_membership_segment_persists_index_metadata_only_no_vectors():
    # The pure map must never carry pool_medoid_raw / pool_medoid_norm / synthetic
    # median / threshold-specific vector artifacts — only indices + counts + signature.
    names = {f.name for f in fields(MembershipSegment)}
    assert names == {
        "seg_id",
        "member_indices",
        "is_absorbed_outlier",
        "start_idx",
        "end_idx",
        "medoid_source_patch_idx",
        "segment_signature",
        "membership_version",
    }
    norm = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]], dtype=np.float32)
    (seg,) = authoritative_segmentation(norm, 1.0, global_dist)
    assert isinstance(seg.medoid_source_patch_idx, int)
    assert all(isinstance(i, int) for i in seg.member_indices)
    assert all(isinstance(f, bool) for f in seg.is_absorbed_outlier)


def test_signature_contract_is_deterministic_and_sensitive():
    base = segment_signature((0, 1, 2), (False, True, False), medoid_source_patch_idx=0)
    # Same membership + medoid -> identical signature.
    assert base == segment_signature((0, 1, 2), (False, True, False), medoid_source_patch_idx=0)
    # Membership order does not matter (canonical sort) -> identical signature.
    assert base == segment_signature((2, 1, 0), (False, True, False), medoid_source_patch_idx=0)
    # Any membership/medoid change changes the signature.
    assert base != segment_signature((0, 1, 2), (False, True, False), medoid_source_patch_idx=2)
    assert base != segment_signature((0, 1, 2), (False, False, False), medoid_source_patch_idx=0)
    assert base != segment_signature((0, 1), (False, True), medoid_source_patch_idx=0)


def test_segmentation_is_deterministic_across_runs():
    rng = np.random.default_rng(99)
    norm = _unit_rows(rng, 64, 16)
    a = authoritative_segmentation(norm, 0.7, global_dist)
    b = authoritative_segmentation(norm, 0.7, global_dist)
    assert len(a) == len(b)
    for sa, sb in zip(a, b, strict=False):
        assert sa.member_indices == sb.member_indices
        assert sa.is_absorbed_outlier == sb.is_absorbed_outlier
        assert sa.medoid_source_patch_idx == sb.medoid_source_patch_idx
        assert sa.segment_signature == sb.segment_signature


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_global_flat_baseline_identity_preserved(seed):
    rng = np.random.default_rng(seed)
    norm = _unit_rows(rng, int(rng.integers(2, 40)), 16)
    expected, _ = select_global_medoid_index(norm)
    idx = global_flat_medoid_source_index(norm)
    assert idx == int(expected), "global_pool:{backbone}:medoid identity must be preserved"
    assert isinstance(idx, int) and 0 <= idx < len(norm)
    # Independent per backbone: each call only ever returns an observed index of its
    # own matrix, and is fully deterministic (two calls agree).
    assert global_flat_medoid_source_index(norm) == idx


def test_global_flat_baseline_is_per_backbone_independent_and_index_only():
    rng = np.random.default_rng(5)
    backbone_a = _unit_rows(rng, 30, 8)
    backbone_b = _unit_rows(rng, 17, 8)
    idx_a = global_flat_medoid_source_index(backbone_a)
    idx_b = global_flat_medoid_source_index(backbone_b)
    assert 0 <= idx_a < 30
    assert 0 <= idx_b < 17
    # Index-only result: never a synthetic/median vector.
    assert not isinstance(idx_a, np.ndarray) and not isinstance(idx_b, np.ndarray)
    assert global_flat_medoid_source_index(backbone_a) == idx_a


def test_medoid_never_reenters_primary_scoring_via_agg_method():
    # agg_method=medoid is forbidden at the score-variant boundary (module import
    # itself raises if it ever leaked into AGG_METHODS).
    assert "medoid" not in _constants.AGG_METHODS
    with pytest.raises(ValueError):
        _constants.validate_score_variant("medoid")


def test_legacy_segment_medoid_selection_is_preserved():
    # Golden equivalence: our observed segment-medoid selector reproduces the legacy
    # PTC medoid selection (mean-incl-self cosine centrality, smallest-index ties).
    from scripts.embedding_research.strategy_binned._pool import select_medoid_index

    rng = np.random.default_rng(21)
    for _ in range(8):
        norm = _unit_rows(rng, int(rng.integers(2, 40)), 16)
        threshold = float(rng.uniform(0.1, 1.6))
        for seg in authoritative_segmentation(norm, threshold, global_dist):
            in_range = _in_range(seg)
            if len(in_range) < 1:
                continue
            unit_seg = norm[np.asarray(in_range, dtype=int)]
            legacy_local, _ = select_medoid_index(unit_seg)
            legacy_global = in_range[int(legacy_local)]
            assert seg.medoid_source_patch_idx == legacy_global
