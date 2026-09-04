"""Spec-first tests for the bounded exact scorer (Plan D Phase 2 — P2-S1..P2-S4).

``bounded_scoring.score_bounded_exact`` reproduces, chunk-by-chunk, the exact
``max_per_candidate_segment`` semantics whose small full-matrix fixture oracle is
``scoring_harness.score_max_per_candidate_segment``.  These tests pin:

* chunk invariance (identical score/winner/collision outcomes across different
  query/candidate chunk sizes, within documented float tolerance);
* oracle equivalence on the deterministic collision and equal-tie fixtures when both
  consume identical float inputs (documented rtol/atol — P2-level smoke; the full
  golden matrix is Phase 4);
* deterministic first-index tie outcomes;
* ``retain_all_candidate_segments`` collision behaviour;
* the ``equal_tie_split + unique_source_max`` alternative (score/retention identical
  to the oracle, fractional winner credits);
* ``expensive_trace`` is labelled, honours bounded chunks, and is off by default;
* no normal-path source-x-candidate (NxN) product retention (tracemalloc peak stays
  far below the full-product size);
* finite-only reductions and explicit rejection of non-finite vectors/weights;
* ``working_memory`` chunk-derivation arithmetic surfaced on the result.
"""

from __future__ import annotations

import math
import tracemalloc

import numpy as np
import pytest

from scripts.embedding_research.bounded_scoring import (
    ScoringCandidateView,
    derive_chunk_sizes,
    score_bounded_exact,
)
from scripts.embedding_research.scoring_harness import (
    SegmentScoreInput,
    score_max_per_candidate_segment,
    variant_name,
)

#: Documented float tolerance for chunk-invariance / oracle-equivalence smoke tests.
#: Elementwise dot products are deterministic across chunk boundaries, so the only
#: drift source is float matmul ordering; 1e-12 is far tighter than the DD's
#: tolerance-bounded (not bit-identical) requirement.
_ATOL = 1e-9
_RTOL = 1e-9

_PRIMARY = ("first_index", "retain_all_candidate_segments")
_ALTERNATIVE = ("equal_tie_split", "unique_source_max")


def _unit(rng, n: int, d: int, spread: float = 1.5) -> np.ndarray:
    """Deterministic float32 L2-unit rows (a normalized frozen-stream stand-in)."""
    m = rng.standard_normal((n, d)) * spread
    m[0] += 3.0
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (m / norms).astype(np.float32)


def _view(vectors: np.ndarray, weights=None, rows=()):
    return ScoringCandidateView(
        vectors=vectors,
        row_addresses=rows,
        candidate_weights=None if weights is None else np.asarray(weights, dtype=np.float64),
    )


# --------------------------------------------------------------------------- #
# Shared deterministic fixtures (float32 stored, like a real gathered view)     #
# --------------------------------------------------------------------------- #

# Source vectors e1/e2; candidate vectors c0=e1, c1=(0.8,0.6), c2=e2.
_SV = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
_CV = np.array([[1.0, 0.0], [0.8, 0.6], [0.0, 1.0]], dtype=np.float32)
_SW = np.array([2.0, 1.0], dtype=np.float64)
_CW = np.array([3.0, 2.0, 4.0], dtype=np.float64)


def _collision_input() -> SegmentScoreInput:
    # Both oracle and bounded consume the SAME float32-stored arrays so the comparison
    # is exact rather than contaminated by a float32-vs-float64 conversion difference.
    return SegmentScoreInput(_SV, _CV, _SW, _CW)


def _oracle(tp: str, cp: str):
    return score_max_per_candidate_segment(_collision_input(), tie_policy=tp, collision_policy=cp)


def _bounded(tp: str, cp: str, *, qcs=None, ccs=None, wm=4096, **kw):
    return score_bounded_exact(
        _SV,
        _SW,
        _view(_CV, _CW),
        query_chunk_size=qcs,
        candidate_chunk_size=ccs,
        working_memory=wm,
        tie_policy=tp,
        collision_policy=cp,
        **kw,
    )


# --------------------------------------------------------------------------- #
# P2-S3: primary semantics preserved + alternative; oracle equivalence          #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "tp,cp",
    [
        _PRIMARY,
        _ALTERNATIVE,
        ("first_index", "unique_source_max"),
        ("equal_tie_split", "retain_all_candidate_segments"),
    ],
)
def test_score_denominator_and_retention_match_oracle(tp, cp) -> None:
    o = _oracle(tp, cp)
    r = _bounded(tp, cp)
    np.testing.assert_allclose(r.score, o.score, rtol=_RTOL, atol=_ATOL)
    np.testing.assert_allclose(r.denominator, o.denominator, rtol=_RTOL, atol=_ATOL)
    assert r.retained_count == sum(1 for c in o.contributions if c.retained)
    assert r.dropped_count == sum(1 for c in o.contributions if not c.retained)
    # winner_counts match the oracle exactly (integer for first_index).
    assert dict(o.winner_counts) == dict(r.winner_counts)
    # Result carries the variant identity + scoring semantics version.
    assert r.variant == variant_name(tp, cp)
    assert r.tie_policy == tp
    assert r.collision_policy == cp


def test_primary_collision_retains_all_candidates() -> None:
    r = _bounded(*_PRIMARY)
    assert r.retained_count == 3
    assert r.dropped_count == 0
    # Deterministic collision group on source winner 0 (candidates 0 and 1).
    assert r.collisions == ((0, 1),)
    # Numerator/denominator match the oracle (both computed on the same float32 input).
    o = _oracle(*_PRIMARY)
    np.testing.assert_allclose(r.numerator, o.numerator, rtol=_RTOL, atol=_ATOL)
    np.testing.assert_allclose(r.denominator, o.denominator, rtol=_RTOL, atol=_ATOL)


def test_alternative_drops_the_collider() -> None:
    r = _bounded(*_ALTERNATIVE)
    assert r.retained_count == 2
    assert r.dropped_count == 1
    np.testing.assert_allclose(r.numerator, 7.0, rtol=_RTOL, atol=_ATOL)
    np.testing.assert_allclose(r.denominator, 7.0, rtol=_RTOL, atol=_ATOL)
    np.testing.assert_allclose(r.score, 1.0, rtol=_RTOL, atol=_ATOL)
    assert r.winner_counts == {0: 1.0, 1: 1.0}


def test_first_index_resolves_ties_to_lowest_source() -> None:
    tie_cv = np.array([[math.sqrt(0.5), math.sqrt(0.5)]], dtype=np.float32)
    tie_cw = np.array([4.0], dtype=np.float64)
    inp = SegmentScoreInput(_SV, tie_cv, np.array([2.0, 3.0]), tie_cw)
    o = score_max_per_candidate_segment(inp)  # first_index + retain_all
    r = score_bounded_exact(_SV, np.array([2.0, 3.0]), _view(tie_cv, tie_cw), working_memory=64)
    assert dict(o.winner_counts) == {0: 1.0}
    assert r.winner_counts == {0: 1.0}
    np.testing.assert_allclose(r.score, o.score, rtol=_RTOL, atol=_ATOL)
    # equal_tie_split fractional credits match the oracle.
    o2 = score_max_per_candidate_segment(inp, tie_policy="equal_tie_split")
    r2 = score_bounded_exact(
        _SV, np.array([2.0, 3.0]), _view(tie_cv, tie_cw), working_memory=64, tie_policy="equal_tie_split"
    )
    assert dict(o2.winner_counts) == dict(r2.winner_counts)


def test_tie_policy_does_not_change_the_score() -> None:
    # The oracle's score is independent of tie policy (only winner credits differ).
    for cp in ("retain_all_candidate_segments", "unique_source_max"):
        s1 = _bounded("first_index", cp).score
        s2 = _bounded("equal_tie_split", cp).score
        np.testing.assert_allclose(s1, s2, rtol=_RTOL, atol=_ATOL)


# --------------------------------------------------------------------------- #
# P2-S1: pure CPU, candidate-weights default, result fields                     #
# --------------------------------------------------------------------------- #


def test_candidate_weights_default_to_ones_when_absent() -> None:
    r = score_bounded_exact(_SV, _SW, _view(_CV, None), working_memory=64)
    # With unit candidate weights the denominator equals the candidate count.
    assert r.denominator == 3.0
    assert math.isfinite(r.score)
    assert r.finite is True


def test_result_exposes_provenance_and_configuration() -> None:
    rows = ((1, "s1", 0, 3), (1, "s1", 1, 4), (1, "s2", 0, 7))
    r = _bounded(*_PRIMARY, qcs=2, ccs=2, wm=123456)
    # explicit chunk sizes override the working_memory-derived default.
    assert r.query_chunk_size == 2
    assert r.candidate_chunk_size == 2
    assert r.working_memory == 123456
    assert r.n_source_rows == 2
    assert r.n_candidate_rows == 3
    assert r.candidate_key_provenance is not None
    assert r.scoring_semantics_version >= 1
    # Query/candidate key provenance from a supplied row_addresses.
    r2 = score_bounded_exact(_SV, _SW, _view(_CV, _CW, rows=rows), working_memory=64)
    assert r2.candidate_key_provenance == rows


# --------------------------------------------------------------------------- #
# P2-S2: chunk invariance + no normal-path NxN retention                       #
# --------------------------------------------------------------------------- #


def _random_fixture(seed: int = 3, k: int = 13, m: int = 40, d: int = 6):
    rng = np.random.default_rng(seed)
    query = _unit(rng, k, d)
    cand = _unit(rng, m, d)
    qw = np.abs(rng.standard_normal(k)) + 0.5
    cw = np.abs(rng.standard_normal(m)) + 0.5
    return query, qw, cand, cw


@pytest.mark.parametrize(
    "qcs,ccs",
    [
        (1, 1),  # row-by-row / column-by-column (tightest memory)
        (1, 7),
        (5, 3),
        (13, 40),  # single chunk = the oracle full matrix shape
        (100, 100),  # chunk larger than the data -> no effective chunking
    ],
)
def test_chunk_invariance(qcs, ccs) -> None:
    query, qw, cand, cw = _random_fixture()
    score_bounded_exact(query, qw, _view(cand, cw), query_chunk_size=qcs, candidate_chunk_size=ccs)
    for tp, cp in (_PRIMARY, _ALTERNATIVE):
        full = score_bounded_exact(
            query,
            qw,
            _view(cand, cw),
            query_chunk_size=1000,
            candidate_chunk_size=1000,
            tie_policy=tp,
            collision_policy=cp,
        )
        r = score_bounded_exact(
            query,
            qw,
            _view(cand, cw),
            query_chunk_size=qcs,
            candidate_chunk_size=ccs,
            tie_policy=tp,
            collision_policy=cp,
        )
        np.testing.assert_allclose(r.score, full.score, rtol=_RTOL, atol=_ATOL)
        np.testing.assert_allclose(r.numerator, full.numerator, rtol=_RTOL, atol=_ATOL)
        np.testing.assert_allclose(r.denominator, full.denominator, rtol=_RTOL, atol=_ATOL)
        assert dict(r.winner_counts) == dict(full.winner_counts)
        assert r.retained_count == full.retained_count


def test_random_fixture_matches_full_matrix_oracle() -> None:
    query, qw, cand, cw = _random_fixture()
    inp = SegmentScoreInput(query, cand, qw, cw)
    for tp, cp in (_PRIMARY, _ALTERNATIVE):
        o = score_max_per_candidate_segment(inp, tie_policy=tp, collision_policy=cp)
        r = score_bounded_exact(query, qw, _view(cand, cw), working_memory=1024, tie_policy=tp, collision_policy=cp)
        np.testing.assert_allclose(r.score, o.score, rtol=_RTOL, atol=_ATOL)
        np.testing.assert_allclose(r.denominator, o.denominator, rtol=_RTOL, atol=_ATOL)
        assert r.retained_count == sum(1 for c in o.contributions if c.retained)
        assert dict(o.winner_counts) == dict(r.winner_counts)


def test_no_normal_path_retains_full_product() -> None:
    """Peak memory stays far below the full source-x-candidate (KxM) product size.

    Uses small dimension D so the in-memory KxD/MxD vector payloads are tiny while the
    hypothetical full product KxMx8 bytes is huge.  Chunking must keep peak RSS far
    below the full-product size (chunked matmul, chunks released after reduction).
    """
    rng = np.random.default_rng(11)
    k = m = 4000
    d = 4
    query = _unit(rng, k, d)
    cand = _unit(rng, m, d)
    qw = np.abs(rng.standard_normal(k)) + 0.5
    cw = np.abs(rng.standard_normal(m)) + 0.5

    tracemalloc.start()
    try:
        r = score_bounded_exact(
            query, qw, _view(cand, cw), query_chunk_size=64, candidate_chunk_size=64, working_memory=32 * 1024
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    full_product_bytes = k * m * 8  # float64 elements of the full KxM similarity matrix.
    assert math.isfinite(r.score)
    # The normal path holds no attribute carrying the full product (design-level
    # guarantee) and peak allocation is far below what the product would require.
    assert peak < full_product_bytes / 8
    assert r.trace is None
    assert r.trace_retained is False


# --------------------------------------------------------------------------- #
# P2-S2: expensive_trace — explicit, labelled, honours chunks, off by default    #
# --------------------------------------------------------------------------- #


def test_expensive_trace_off_by_default() -> None:
    r = _bounded(*_PRIMARY)
    assert r.trace_retained is False
    assert r.trace is None


def test_expensive_trace_is_labelled_and_segment_level() -> None:
    o = _oracle(*_PRIMARY)
    r = _bounded(*_PRIMARY, qcs=2, ccs=2, expensive_trace=True)
    assert r.trace_retained is True
    assert r.trace is not None
    assert len(r.trace.contributions) == 3  # one per candidate segment, never per-pair.
    # Segment-level contribution fields match the oracle trace.
    for cs, oc in zip(r.trace.contributions, o.contributions, strict=False):
        assert cs.candidate_index == oc.candidate_index
        np.testing.assert_allclose(cs.cosine, oc.cosine, rtol=_RTOL, atol=_ATOL)
        np.testing.assert_allclose(cs.contribution, oc.contribution, rtol=_RTOL, atol=_ATOL)
        assert cs.retained == oc.retained
        assert cs.winner_source_index == oc.winner_source_index
        assert cs.winner_source_indices == oc.winner_source_indices
    assert sorted(c.candidate_index for c in r.trace.contributions) == [0, 1, 2]


def test_expensive_trace_honours_bounded_chunks() -> None:
    # Even with a full trace requested, peak memory must not blow up to the full
    # product; chunk limits are still honoured.
    rng = np.random.default_rng(12)
    k, m, d = 1500, 1500, 4
    query = _unit(rng, k, d)
    cand = _unit(rng, m, d)
    qw = np.abs(rng.standard_normal(k)) + 0.5
    cw = np.abs(rng.standard_normal(m)) + 0.5
    tracemalloc.start()
    try:
        r = score_bounded_exact(
            query,
            qw,
            _view(cand, cw),
            query_chunk_size=100,
            candidate_chunk_size=100,
            working_memory=64 * 1024,
            expensive_trace=True,
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert r.trace_retained is True
    assert len(r.trace.contributions) == m
    assert peak < (k * m * 8) / 8  # still far below the full-product size.


# --------------------------------------------------------------------------- #
# Finite reductions + validation                                                #
# --------------------------------------------------------------------------- #


def test_rejects_non_finite_vectors() -> None:
    bad = _SV.copy()
    bad[0, 0] = np.nan
    with pytest.raises(ValueError):
        score_bounded_exact(bad, _SW, _view(_CV, _CW), working_memory=64)


def test_rejects_non_finite_weights() -> None:
    with pytest.raises(ValueError):
        score_bounded_exact(_SV, np.array([2.0, np.inf]), _view(_CV, _CW), working_memory=64)
    with pytest.raises(ValueError):
        score_bounded_exact(_SV, _SW, _view(_CV, np.array([3.0, np.nan, 4.0])), working_memory=64)


def test_rejects_non_unit_norm_rows() -> None:
    bad = np.array([[2.0, 0.0]], dtype=np.float32)
    with pytest.raises(ValueError):
        score_bounded_exact(bad, np.array([1.0]), _view(_CV, _CW), working_memory=64)


def test_rejects_weight_length_mismatch_and_nonpositive() -> None:
    with pytest.raises(ValueError):
        score_bounded_exact(_SV, np.array([1.0]), _view(_CV, _CW), working_memory=64)
    with pytest.raises(ValueError):
        score_bounded_exact(_SV, np.array([2.0, 0.0]), _view(_CV, _CW), working_memory=64)


def test_rejects_unknown_policies() -> None:
    with pytest.raises(ValueError):
        _bounded("median", "retain_all_candidate_segments")
    with pytest.raises(ValueError):
        _bounded("first_index", "mean")


def test_rejects_nonpositive_working_memory_and_chunks() -> None:
    with pytest.raises(ValueError):
        score_bounded_exact(_SV, _SW, _view(_CV, _CW), working_memory=0)
    with pytest.raises(ValueError):
        score_bounded_exact(_SV, _SW, _view(_CV, _CW), query_chunk_size=-1, candidate_chunk_size=2)
    with pytest.raises(ValueError):
        score_bounded_exact(_SV, _SW, _view(_CV, _CW), query_chunk_size=2, candidate_chunk_size=0)


# --------------------------------------------------------------------------- #
# P2-S4: working-memory chunk-derivation arithmetic                            #
# --------------------------------------------------------------------------- #


def test_derive_chunk_sizes_from_working_memory() -> None:
    # chunk = max(1, int(sqrt(wm / 8))) for float64 cosine blocks.
    assert derive_chunk_sizes(8) == (1, 1)
    assert derive_chunk_sizes(128) == (4, 4)  # sqrt(16) = 4
    qcs, ccs = derive_chunk_sizes(32 * 1024 * 1024)  # 32 MiB
    assert qcs == ccs
    assert qcs == int(math.sqrt((32 * 1024 * 1024) / 8))


def test_explicit_chunk_sizes_override_derived_defaults() -> None:
    r_default = _bounded(*_PRIMARY, wm=32768)
    assert r_default.query_chunk_size == derive_chunk_sizes(32768)[0]
    assert r_default.candidate_chunk_size == derive_chunk_sizes(32768)[1]
    r_explicit = _bounded(*_PRIMARY, qcs=3, ccs=9, wm=32768)
    assert r_explicit.query_chunk_size == 3
    assert r_explicit.candidate_chunk_size == 9
    # Config is surfaced on the result for a benchmark to record.
    assert r_explicit.working_memory == 32768


def test_segment_summary_is_bounded_and_finite() -> None:
    for tp, cp in (_PRIMARY, _ALTERNATIVE):
        r = _bounded(tp, cp)
        s = r.segment_summary()
        assert math.isfinite(s["score"])
        assert s["finite"] == 1.0
        assert s["retained_count"] == float(r.retained_count)
        assert s["dropped_count"] == float(r.dropped_count)


def test_result_is_json_safe() -> None:
    import json

    r = _bounded(*_ALTERNATIVE, expensive_trace=True)
    payload = json.loads(json.dumps(r.to_dict()))
    assert payload["variant"] == variant_name(*_ALTERNATIVE)
    assert payload["finite"] is True
    assert len(payload["trace"]["contributions"]) == 3
