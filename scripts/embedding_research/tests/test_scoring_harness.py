"""Spec-first numerical contract tests for the scoring harness.

These tests pin the exact collision and tie fixtures of
``scripts/embedding_research/scoring_harness.py`` (the max-per-candidate-segment
deduplicated score) *before* any formula is treated as authoritative.  They cover:

- the deterministic collision fixture with exact expected values and complete traces;
- a separate equal-cosine tie fixture proving deterministic first-index ties and the
  explicit ``equal_tie_split`` split-tie variant;
- rejection of malformed dimensions/weights and non-finite values;
- proof that no Cartesian duplicate contribution is emitted (one contribution per
  candidate segment);
- proof that collision metadata (groups, winner indices, weights, cosine maxima,
  retention, numeric contributions) is complete;
- proof that every ambiguity variant is deterministic across repeated runs;
- the ``run_scoring_harness`` driver over the max-per-candidate score.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from scripts.embedding_research.scoring_harness import (
    ScoringFixture,
    SegmentScoreInput,
    run_scoring_harness,
    score_max_per_candidate_segment,
    variant_name,
)

_TOL = 1e-9

# ────────────────────────────────────────────────────────────────────────────────
# Deterministic collision fixture (P1-S4)
# ────────────────────────────────────────────────────────────────────────────────

_COLLISION_INPUT = SegmentScoreInput(
    source_vectors=np.array([[1.0, 0.0], [0.0, 1.0]]),  # e1, e2
    candidate_vectors=np.array([[1.0, 0.0], [0.8, 0.6], [0.0, 1.0]]),
    source_weights=np.array([2.0, 1.0]),
    candidate_weights=np.array([3.0, 2.0, 4.0]),
)

_COLLISION_MAXIMA = (1.0, 0.8, 1.0)
_COLLISION_COLLISIONS = ((0, 1),)  # candidates 0 and 1 collide on source winner 0.
_COLLISION_RETAIN_ALL_SCORE = 8.6 / 9.0
_COLLISION_UNIQUE_MAX_SCORE = 7.0 / 7.0  # retain c0 and c2, drop c1.

# ────────────────────────────────────────────────────────────────────────────────
# Equal-cosine tie fixture (P1-S4)
# ────────────────────────────────────────────────────────────────────────────────

_TIE_INPUT = SegmentScoreInput(
    source_vectors=np.array([[1.0, 0.0], [0.0, 1.0]]),  # e1, e2
    candidate_vectors=np.array([[math.sqrt(0.5), math.sqrt(0.5)]]),  # 45° — ties both sources
    source_weights=np.array([2.0, 3.0]),
    candidate_weights=np.array([4.0]),
)

_TIE_COS = math.sqrt(0.5)


# ────────────────────────────────────────────────────────────────────────────────
# P1-S4: exact collision fixture values and complete traces
# ────────────────────────────────────────────────────────────────────────────────


def test_collision_fixture_primary_exact_maxima_and_score() -> None:
    trace = score_max_per_candidate_segment(_COLLISION_INPUT)
    assert trace.variant == variant_name("first_index", "retain_all_candidate_segments")
    assert trace.tie_policy == "first_index"
    assert trace.collision_policy == "retain_all_candidate_segments"
    np.testing.assert_allclose([c.cosine for c in trace.contributions], _COLLISION_MAXIMA, rtol=_TOL, atol=_TOL)
    np.testing.assert_allclose(trace.numerator, 8.6, rtol=_TOL, atol=_TOL)
    np.testing.assert_allclose(trace.denominator, 9.0, rtol=_TOL, atol=_TOL)
    np.testing.assert_allclose(trace.score, _COLLISION_RETAIN_ALL_SCORE, rtol=_TOL, atol=_TOL)


def test_collision_fixture_winner_and_collision_groups() -> None:
    trace = score_max_per_candidate_segment(_COLLISION_INPUT)
    # Candidate 2 wins on source 1.
    c2 = trace.contributions[2]
    assert c2.winner_source_index == 1
    assert c2.winner_source_indices == (1,)
    np.testing.assert_allclose(c2.cosine, 1.0, rtol=_TOL, atol=_TOL)
    # Candidates 0 and 1 collide on source winner 0.
    c0 = trace.contributions[0]
    c1 = trace.contributions[1]
    assert c0.winner_source_index == 0
    assert c1.winner_source_index == 0
    assert set(c0.collision_group) == {0, 1}
    assert trace.collisions == ((0, 1),)
    # winner_counts: source 0 has two retained candidates, source 1 has one.
    assert dict(trace.winner_counts) == {0: 2.0, 1: 1.0}


def test_collision_fixture_all_retained_contributions_once() -> None:
    trace = score_max_per_candidate_segment(_COLLISION_INPUT)
    assert len(trace.contributions) == 3
    assert all(c.retained for c in trace.contributions)
    # Each candidate contributes exactly once (no Cartesian duplicate emission).
    indices = [c.candidate_index for c in trace.contributions]
    assert sorted(indices) == [0, 1, 2]
    assert len(set(indices)) == len(indices)


def test_collision_fixture_contributions_match_weights_and_cosines() -> None:
    trace = score_max_per_candidate_segment(_COLLISION_INPUT)
    weights = [3.0, 2.0, 4.0]
    for c, w, cosine in zip(trace.contributions, weights, _COLLISION_MAXIMA, strict=False):
        np.testing.assert_allclose(c.candidate_weight, w, rtol=_TOL, atol=_TOL)
        np.testing.assert_allclose(c.contribution, w * cosine, rtol=_TOL, atol=_TOL)


def test_collision_fixture_unique_source_max_drops_collider() -> None:
    trace = score_max_per_candidate_segment(
        _COLLISION_INPUT, tie_policy="equal_tie_split", collision_policy="unique_source_max"
    )
    assert trace.collision_policy == "unique_source_max"
    retained = [c.candidate_index for c in trace.contributions if c.retained]
    dropped = [c.candidate_index for c in trace.contributions if not c.retained]
    # c0 and c2 are retained (one per source); c1 is dropped but remains in the trace.
    assert sorted(retained) == [0, 2]
    assert sorted(dropped) == [1]
    np.testing.assert_allclose(trace.numerator, 7.0, rtol=_TOL, atol=_TOL)
    np.testing.assert_allclose(trace.denominator, 7.0, rtol=_TOL, atol=_TOL)
    np.testing.assert_allclose(trace.score, _COLLISION_UNIQUE_MAX_SCORE, rtol=_TOL, atol=_TOL)
    # Dropped contribution recorded but not counted.
    dropped_c1 = next(c for c in trace.contributions if c.candidate_index == 1)
    assert dropped_c1.retained is False
    np.testing.assert_allclose(dropped_c1.contribution, 2.0 * 0.8, rtol=_TOL, atol=_TOL)
    # winner_counts over retained candidates only.
    assert dict(trace.winner_counts) == {0: 1.0, 1: 1.0}


# ────────────────────────────────────────────────────────────────────────────────
# P1-S4: equal-cosine tie fixture — first_index and equal_tie_split
# ────────────────────────────────────────────────────────────────────────────────


def test_equal_cosine_tie_first_index_resolves_to_source_zero() -> None:
    trace = score_max_per_candidate_segment(_TIE_INPUT)  # defaults: first_index + retain_all
    c = trace.contributions[0]
    assert c.winner_source_index == 0
    assert c.winner_source_indices == (0, 1)  # both sources tie on the maximum.
    np.testing.assert_allclose(c.cosine, _TIE_COS, rtol=_TOL, atol=_TOL)
    assert dict(trace.winner_counts) == {0: 1.0}  # first_index credits only source 0.
    np.testing.assert_allclose(trace.numerator, 4.0 * _TIE_COS, rtol=_TOL, atol=_TOL)
    np.testing.assert_allclose(trace.denominator, 4.0, rtol=_TOL, atol=_TOL)


def test_equal_cosine_tie_split_variant_splits_winner_credit() -> None:
    trace = score_max_per_candidate_segment(_TIE_INPUT, tie_policy="equal_tie_split")
    c = trace.contributions[0]
    assert c.winner_source_indices == (0, 1)
    # Split tie: winner credit is split 0.5 / 0.5 across the two tied sources.
    assert dict(trace.winner_counts) == {0: 0.5, 1: 0.5}
    # The contribution is still retained once with its full weight.
    assert c.retained is True
    np.testing.assert_allclose(c.contribution, 4.0 * _TIE_COS, rtol=_TOL, atol=_TOL)
    np.testing.assert_allclose(trace.numerator, 4.0 * _TIE_COS, rtol=_TOL, atol=_TOL)
    np.testing.assert_allclose(trace.score, _TIE_COS, rtol=_TOL, atol=_TOL)


def test_first_index_vs_equal_tie_split_differ_in_winner_counts() -> None:
    first = score_max_per_candidate_segment(_TIE_INPUT)
    split = score_max_per_candidate_segment(_TIE_INPUT, tie_policy="equal_tie_split")
    assert dict(first.winner_counts) != dict(split.winner_counts)
    assert dict(first.winner_counts) == {0: 1.0}
    assert dict(split.winner_counts) == {0: 0.5, 1: 0.5}


# ────────────────────────────────────────────────────────────────────────────────
# P1-S5: malformed inputs are rejected
# ────────────────────────────────────────────────────────────────────────────────


def test_rejects_1d_vectors() -> None:
    with pytest.raises(ValueError):
        SegmentScoreInput(
            source_vectors=np.array([1.0, 0.0]),
            candidate_vectors=np.array([[1.0, 0.0]]),
            source_weights=np.array([2.0]),
            candidate_weights=np.array([3.0]),
        )


def test_rejects_dimension_mismatch() -> None:
    with pytest.raises(ValueError):
        SegmentScoreInput(
            source_vectors=np.array([[1.0, 0.0]]),
            candidate_vectors=np.array([[1.0, 0.0, 0.0]]),
            source_weights=np.array([2.0]),
            candidate_weights=np.array([3.0]),
        )


def test_rejects_non_unit_norm_rows() -> None:
    with pytest.raises(ValueError):
        SegmentScoreInput(
            source_vectors=np.array([[2.0, 0.0]]),
            candidate_vectors=np.array([[1.0, 0.0]]),
            source_weights=np.array([2.0]),
            candidate_weights=np.array([3.0]),
        )


def test_rejects_non_finite_vectors() -> None:
    with pytest.raises(ValueError):
        SegmentScoreInput(
            source_vectors=np.array([[1.0, np.nan]]),
            candidate_vectors=np.array([[1.0, 0.0]]),
            source_weights=np.array([2.0]),
            candidate_weights=np.array([3.0]),
        )


def test_rejects_non_positive_weights() -> None:
    with pytest.raises(ValueError):
        SegmentScoreInput(
            source_vectors=np.array([[1.0, 0.0]]),
            candidate_vectors=np.array([[1.0, 0.0]]),
            source_weights=np.array([0.0]),  # not strictly positive.
            candidate_weights=np.array([3.0]),
        )


def test_rejects_weight_length_mismatch() -> None:
    with pytest.raises(ValueError):
        SegmentScoreInput(
            source_vectors=np.array([[1.0, 0.0], [0.0, 1.0]]),
            candidate_vectors=np.array([[1.0, 0.0]]),
            source_weights=np.array([2.0]),  # length 1 != 2 source rows.
            candidate_weights=np.array([3.0]),
        )


def test_rejects_id_length_mismatch() -> None:
    with pytest.raises(ValueError):
        SegmentScoreInput(
            source_vectors=np.array([[1.0, 0.0], [0.0, 1.0]]),
            candidate_vectors=np.array([[1.0, 0.0]]),
            source_weights=np.array([2.0, 1.0]),
            candidate_weights=np.array([3.0]),
            candidate_ids=("a", "b"),  # length 2 != 1 candidate row.
        )


def test_rejects_unknown_policies() -> None:
    with pytest.raises(ValueError):
        score_max_per_candidate_segment(_COLLISION_INPUT, tie_policy="median")
    with pytest.raises(ValueError):
        score_max_per_candidate_segment(_COLLISION_INPUT, collision_policy="mean")


# ────────────────────────────────────────────────────────────────────────────────
# P1-S1: input construction is read-only — the caller's arrays stay writable
# ────────────────────────────────────────────────────────────────────────────────


def test_input_construction_does_not_make_caller_arrays_readonly() -> None:
    """SegmentScoreInput stores read-only float64 copies but leaves the caller's
    arrays writable.

    ``np.asarray(x, dtype=float64)`` returns the caller's own array when it is
    already float64, so freezing that view with ``setflags(write=False)`` would
    make the caller's array read-only — an observable side effect.  The harness
    claims to be pure (reads only its arguments), so this must never happen.
    """
    source_vectors = np.array([[1.0, 0.0], [0.0, 1.0]])
    candidate_vectors = np.array([[1.0, 0.0], [0.8, 0.6], [0.0, 1.0]])
    source_weights = np.array([2.0, 1.0])
    candidate_weights = np.array([3.0, 2.0, 4.0])

    SegmentScoreInput(
        source_vectors=source_vectors,
        candidate_vectors=candidate_vectors,
        source_weights=source_weights,
        candidate_weights=candidate_weights,
    )

    # The caller's arrays remain writable after construction.
    source_vectors[0, 0] = 9.0
    source_weights[0] = 9.0
    candidate_vectors[1, 0] = 9.0
    candidate_weights[1] = 9.0


def test_input_stores_readonly_float64_copies() -> None:
    """The stored arrays are read-only (immutability), float64, and copies."""
    src = np.array([[1.0, 0.0], [0.0, 1.0]])
    s_in = SegmentScoreInput(
        source_vectors=src,
        candidate_vectors=np.array([[1.0, 0.0]]),
        source_weights=np.array([2.0, 1.0]),
        candidate_weights=np.array([3.0]),
    )
    assert s_in.source_vectors.dtype == np.float64
    assert s_in.source_vectors.flags.writeable is False
    assert s_in.candidate_vectors.flags.writeable is False
    assert s_in.source_weights.flags.writeable is False
    assert s_in.candidate_weights.flags.writeable is False
    # Stored arrays are owned copies: mutating the caller's array does not
    # propagate into the stored (already-frozen) copy.
    src[0, 0] = 9.0
    assert s_in.source_vectors[0, 0] == 1.0


# ────────────────────────────────────────────────────────────────────────────────
# P1-S5: no Cartesian duplicate contribution; complete collision metadata
# ────────────────────────────────────────────────────────────────────────────────


def test_no_cartesian_duplicate_contribution_for_any_variant() -> None:
    for tie_policy, collision_policy in (
        ("first_index", "retain_all_candidate_segments"),
        ("equal_tie_split", "retain_all_candidate_segments"),
        ("first_index", "unique_source_max"),
        ("equal_tie_split", "unique_source_max"),
    ):
        trace = score_max_per_candidate_segment(
            _COLLISION_INPUT, tie_policy=tie_policy, collision_policy=collision_policy
        )
        indices = [c.candidate_index for c in trace.contributions]
        assert sorted(indices) == [0, 1, 2]  # one contribution per candidate segment.
        assert len(set(indices)) == len(indices)  # no duplicates.


def test_collision_metadata_complete_in_trace() -> None:
    trace = score_max_per_candidate_segment(_COLLISION_INPUT)
    # collision groups present and correct.
    assert trace.collisions == ((0, 1),)
    # winner_counts present.
    assert dict(trace.winner_counts) == {0: 2.0, 1: 1.0}
    # every contribution exposes winner indices, weight, cosine, contribution,
    # collision group, retention, and ambiguity variant.
    for c in trace.contributions:
        assert isinstance(c.winner_source_index, int)
        assert isinstance(c.winner_source_indices, tuple)
        assert c.candidate_weight > 0
        assert math.isfinite(c.cosine)
        assert math.isfinite(c.contribution)
        assert isinstance(c.collision_group, tuple)
        assert isinstance(c.retained, bool)
        assert c.ambiguity_variant == trace.variant


def test_trace_is_json_safe_and_finite() -> None:
    for tie_policy, collision_policy in (
        ("first_index", "retain_all_candidate_segments"),
        ("equal_tie_split", "unique_source_max"),
    ):
        trace = score_max_per_candidate_segment(
            _COLLISION_INPUT, tie_policy=tie_policy, collision_policy=collision_policy
        )
        assert trace.finite is True
        payload = json.loads(trace.to_json())  # json.dumps must round-trip.
        assert payload["variant"] == variant_name(tie_policy, collision_policy)
        assert math.isfinite(payload["score"])
        assert all(math.isfinite(v) for v in (payload["numerator"], payload["denominator"]))
        for contrib in payload["contributions"]:
            assert math.isfinite(contrib["cosine"])
            assert math.isfinite(contrib["contribution"])
            assert isinstance(contrib["candidate_index"], int)


# ────────────────────────────────────────────────────────────────────────────────
# P1-S5: determinism across repeated runs
# ────────────────────────────────────────────────────────────────────────────────


def test_variants_are_deterministic_across_repeated_runs() -> None:
    for tie_policy, collision_policy in (
        ("first_index", "retain_all_candidate_segments"),
        ("equal_tie_split", "retain_all_candidate_segments"),
        ("first_index", "unique_source_max"),
        ("equal_tie_split", "unique_source_max"),
    ):
        canonical = score_max_per_candidate_segment(
            _COLLISION_INPUT, tie_policy=tie_policy, collision_policy=collision_policy
        ).to_json()
        for _ in range(5):
            rerun = score_max_per_candidate_segment(
                _COLLISION_INPUT, tie_policy=tie_policy, collision_policy=collision_policy
            )
            assert rerun.to_json() == canonical


# ────────────────────────────────────────────────────────────────────────────────
# P1-S5: run_scoring_harness driver
# ────────────────────────────────────────────────────────────────────────────────

_COLLISION_FIXTURE = ScoringFixture(
    name="collision",
    input=_COLLISION_INPUT,
    expected_maxima=_COLLISION_MAXIMA,
    expected_collisions=_COLLISION_COLLISIONS,
    expected_retain_all_score=_COLLISION_RETAIN_ALL_SCORE,
    expected_unique_max_score=_COLLISION_UNIQUE_MAX_SCORE,
)

_TIE_FIXTURE = ScoringFixture(
    name="equal_tie",
    input=_TIE_INPUT,
    expected_maxima=(_TIE_COS,),
    expected_collisions=(),  # single candidate — no collision group.
    expected_retain_all_score=_TIE_COS,
)


def test_run_scoring_harness_report_shape_and_variants() -> None:
    variants = [
        ("first_index", "retain_all_candidate_segments"),
        ("equal_tie_split", "unique_source_max"),
    ]
    report = run_scoring_harness([_COLLISION_FIXTURE, _TIE_FIXTURE], variants)
    assert report.fixtures == ("collision", "equal_tie")
    assert report.variants == tuple(variant_name(tp, cp) for tp, cp in variants)
    assert report.finite is True
    assert report.deterministic is True
    assert len(report.traces) == 2
    assert "collision" in report.traces[report.variants[0]]
    assert "equal_tie" in report.traces[report.variants[0]]


def test_run_scoring_harness_matches_expected_values() -> None:
    variants = [
        ("first_index", "retain_all_candidate_segments"),
        ("equal_tie_split", "unique_source_max"),
    ]
    report = run_scoring_harness([_COLLISION_FIXTURE, _TIE_FIXTURE], variants)
    primary = variant_name("first_index", "retain_all_candidate_segments")
    coll_trace = report.traces[primary]["collision"]
    np.testing.assert_allclose(coll_trace.score, _COLLISION_RETAIN_ALL_SCORE, rtol=_TOL, atol=_TOL)
    np.testing.assert_allclose([c.cosine for c in coll_trace.contributions], _COLLISION_MAXIMA, rtol=_TOL, atol=_TOL)
    alt = variant_name("equal_tie_split", "unique_source_max")
    np.testing.assert_allclose(report.traces[alt]["collision"].score, _COLLISION_UNIQUE_MAX_SCORE, rtol=_TOL, atol=_TOL)
    tie_trace = report.traces[primary]["equal_tie"]
    np.testing.assert_allclose(tie_trace.score, _TIE_COS, rtol=_TOL, atol=_TOL)


def test_run_scoring_harness_report_is_json_safe() -> None:
    variants = [
        ("first_index", "retain_all_candidate_segments"),
        ("equal_tie_split", "unique_source_max"),
    ]
    report = run_scoring_harness([_COLLISION_FIXTURE, _TIE_FIXTURE], variants)
    payload = json.loads(report.to_json())
    assert payload["deterministic"] is True
    assert payload["finite"] is True
    assert set(payload["variants"]) == {variant_name(tp, cp) for tp, cp in variants}


def test_run_scoring_harness_comparisons_expose_denominators_and_retention() -> None:
    variants = [
        ("first_index", "retain_all_candidate_segments"),
        ("equal_tie_split", "unique_source_max"),
    ]
    report = run_scoring_harness([_COLLISION_FIXTURE], variants)
    primary = variant_name("first_index", "retain_all_candidate_segments")
    alt = variant_name("equal_tie_split", "unique_source_max")
    # Primary retains all three candidate segments; denominator 9.
    assert report.comparisons[primary]["collision"]["retained"] == [0, 1, 2]
    assert report.comparisons[primary]["collision"]["dropped"] == []
    np.testing.assert_allclose(report.comparisons[primary]["collision"]["denominator"], 9.0, rtol=_TOL, atol=_TOL)
    # Alternative drops the collider; denominator 7.
    assert report.comparisons[alt]["collision"]["retained"] == [0, 2]
    assert report.comparisons[alt]["collision"]["dropped"] == [1]
    np.testing.assert_allclose(report.comparisons[alt]["collision"]["denominator"], 7.0, rtol=_TOL, atol=_TOL)
