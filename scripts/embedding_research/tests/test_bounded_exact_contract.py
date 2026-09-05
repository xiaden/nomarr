"""Plan D P1-S5 — bounded exact scorer / small oracle contract (spec-first).

These tests pin the CONTRACTS §D ``score_bounded_exact`` / ``score_exact_oracle`` surface and
semantics delivered in ``bounded_scoring.py`` and ``scoring_harness.py``:

1. exact, finite CPU results: bounded output equals exact arithmetic on the fixture (finite-only;
   non-finite input fails closed);
2. max-per-candidate-segment winner semantics with the declared tie/collision policy;
3. first-index ties resolve to the lowest source index deterministically;
4. ``retain_all_candidate_segments`` keeps every tied candidate segment in the bounded trace;
5. a small ``working_memory`` forces chunked processing (no single full matrix) and the normal
   path retains NO full N x N trace; the expensive/debug trace mode is explicitly labelled + opt-in;
6. an empty (zero-searchable-rows) candidate view yields a finite EMPTY result — never NaN/Inf and
   never a crash (the analyze scheduler excludes zero-searchable candidates upstream);
7. oracle equivalence: ``score_bounded_exact`` matches ``score_exact_oracle`` within the declared
   tolerance; winner/retention/collision metadata is identical;
8. scorer chunk-size parameters stay aligned with ``working_memory`` and the emitted
   ``scoring_semantics_version`` stays pinned to the search-view semantics constant.

Every fixture is synthetic numpy (no corpus, no DB); small ``working_memory`` values are used to
force chunk boundaries.  Keep every other P1-S5-adjacent bounded test green — this file adds the
P1-S5 contract assertions without removing any existing scorer surface.
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research import bounded_scoring
from scripts.embedding_research.bounded_scoring import ScoringCandidateView, score_bounded_exact
from scripts.embedding_research.scoring_harness import score_exact_oracle

pytestmark = pytest.mark.unit

# Declared scorer/oracle equivalence tolerance.  The scorer and the oracle both compute every
# cosine element as the SAME float64 dot product of the same two rows, so chunk boundaries never
# change an element (maxima/ties/retention/winner metadata are identical).  The score numerator
# and denominator can still differ by ~1 ulp because the bounded scorer accumulates retained
# contributions with ``np.sum`` (pairwise summation) while the small oracle accumulates
# sequentially in Python — a genuine reduction-order difference, NOT a chunking effect.  We
# therefore declare a tolerance far above a few ulps (rtol = atol = 1e-12) for the numeric score,
# and assert winner/retention/collision metadata equality exactly.
_RTOL = 1e-12
_ATOL = 1e-12


def _addrs(n: int) -> tuple[tuple[int, str, int, int], ...]:
    return tuple((1, "s", 1, i) for i in range(n))


def _view(vectors: np.ndarray, weights: np.ndarray | None = None) -> ScoringCandidateView:
    return ScoringCandidateView(
        vectors=np.asarray(vectors, dtype=np.float64), row_addresses=_addrs(len(vectors)), candidate_weights=weights
    )


def _norm(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v)


def _random_unit(n: int, d: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(n, d)).astype(np.float64)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


# Query rows on the standard basis; a candidate set with an intra-query tie (c2) and a
# representative-winner collision (c0 vs c1) so tie/collision semantics are exercised.
_Q = np.array([[1.0, 0.0], [0.0, 1.0]])
_QW = np.array([2.0, 1.0])
_C = np.array(
    [
        [1.0, 0.0],  # c0 -> max cos 1.0 from q0
        [1.0, 0.0],  # c1 duplicate -> collision group with c0 (winner q0)
        *_norm([1.0, 1.0]).reshape(1, 2),  # c2 -> ties q0/q1 at ~0.707; first_index winner q0
        [0.0, 1.0],  # c3 -> max cos 1.0 from q1
    ]
)
_CW = np.array([3.0, 2.0, 4.0, 5.0])

# Small working memory that forces chunk size 1 (derive_chunk_sizes(8) == (1, 1)).
_WM_TINY = 8
# Working memory that forces chunk size 2 (derive_chunk_sizes(32) == (2, 2)).
_WM_CHUNK2 = 32


def _assert_numeric_eq(r, o) -> None:
    """Score/numerator/denominator match within the declared tolerance; metadata exactly."""
    np.testing.assert_allclose(r.score, o.score, rtol=_RTOL, atol=_ATOL)
    np.testing.assert_allclose(r.numerator, o.numerator, rtol=_RTOL, atol=_ATOL)
    np.testing.assert_allclose(r.denominator, o.denominator, rtol=_RTOL, atol=_ATOL)
    assert r.finite == o.finite
    assert r.winner_counts == o.winner_counts
    assert r.retained_count == o.retained_count and r.dropped_count == o.dropped_count
    assert r.collisions == o.collisions


# --------------------------------------------------------------------------- #
# 1. Exact finite CPU results + non-finite input fails closed                  #
# --------------------------------------------------------------------------- #


def test_bounded_equals_exact_arithmetic_and_is_finite() -> None:
    """Bounded output equals exact full-matrix arithmetic on the fixture; all values finite."""
    cos = _Q @ _C.T
    maxcos = cos.max(axis=0)
    num = float((_CW * maxcos).sum())  # retain_all_candidate_segments keeps every candidate
    den = float(_CW.sum())
    expected = num / den

    r = score_bounded_exact(_Q, _QW, _view(_C, _CW), working_memory=_WM_TINY)
    o = score_exact_oracle(_Q, _QW, _C, _CW)

    assert r.finite is True
    assert np.isfinite(r.score) and np.isfinite(r.numerator) and np.isfinite(r.denominator)
    assert all(np.isfinite(v) for v in r.winner_counts.values())
    np.testing.assert_allclose(r.score, expected, rtol=_RTOL, atol=_ATOL)
    _assert_numeric_eq(r, o)


def test_non_finite_input_fails_closed() -> None:
    """NaN/Inf in query vectors, candidate vectors, or weights raise ValueError — never NaN output."""
    nan_q = _Q.copy()
    nan_q[0, 0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        score_bounded_exact(nan_q, _QW, _view(_C, _CW), working_memory=_WM_TINY)

    nan_c = _C.copy()
    nan_c[1, 0] = np.inf
    with pytest.raises(ValueError, match="finite"):
        score_bounded_exact(_Q, _QW, _view(nan_c, _CW), working_memory=_WM_TINY)

    bad_w = _CW.copy()
    bad_w[0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        score_bounded_exact(_Q, _QW, _view(_C, bad_w), working_memory=_WM_TINY)


# --------------------------------------------------------------------------- #
# 2/3. Max-per-candidate-segment + first-index ties                             #
# --------------------------------------------------------------------------- #


def test_first_index_tie_resolves_to_lowest_source_deterministically() -> None:
    """A candidate whose max cosine ties across query rows is credited to the LOWEST source index."""
    single_tie = _norm([1.0, 1.0]).reshape(1, 2)
    view = _view(single_tie, np.array([4.0]))

    r_first = score_bounded_exact(_Q, _QW, view, working_memory=_WM_TINY, tie_policy="first_index")
    r_split = score_bounded_exact(_Q, _QW, view, working_memory=_WM_TINY, tie_policy="equal_tie_split")

    # first_index -> single credit to source 0.
    assert r_first.winner_counts == {0: 1.0}
    # equal_tie_split -> credit split equally across the tied sources 0 and 1.
    assert set(r_split.winner_counts) == {0, 1}
    assert r_split.winner_counts[0] == pytest.approx(0.5)
    assert r_split.winner_counts[1] == pytest.approx(0.5)
    # Deterministic across repeated runs at different chunkings.
    again = score_bounded_exact(_Q, _QW, view, working_memory=_WM_CHUNK2, tie_policy="first_index")
    assert again.winner_counts == r_first.winner_counts and again.score == r_first.score


def test_max_per_candidate_segment_matches_oracle_under_both_variants() -> None:
    """Bounded and oracle agree (within tolerance) for the primary and alternative variants."""
    for tie_policy, collision_policy in (
        ("first_index", "retain_all_candidate_segments"),
        ("equal_tie_split", "unique_source_max"),
    ):
        r = score_bounded_exact(
            _Q, _QW, _view(_C, _CW), working_memory=_WM_TINY, tie_policy=tie_policy, collision_policy=collision_policy
        )
        o = score_exact_oracle(_Q, _QW, _C, _CW, tie_policy=tie_policy, collision_policy=collision_policy)
        assert r.variant == o.variant
        assert r.finite is True and o.finite is True
        _assert_numeric_eq(r, o)


# --------------------------------------------------------------------------- #
# 4. Retain-all collision trace keeps all tied candidate segments              #
# --------------------------------------------------------------------------- #


def test_retain_all_keeps_all_tied_candidate_segments_in_bounded_trace() -> None:
    """collision_policy=retain_all_candidate_segments keeps every tied candidate in the trace."""
    r = score_bounded_exact(
        _Q,
        _QW,
        _view(_C, _CW),
        working_memory=_WM_TINY,
        collision_policy="retain_all_candidate_segments",
        expensive_trace=True,
    )
    # Collision group c0/c1 (and c2) share representative winner source 0 -> a real collision.
    assert any(len(g) >= 2 for g in r.collisions)
    assert r.trace is not None and r.trace_retained is True
    assert len(r.trace.contributions) == 4
    assert all(c.retained for c in r.trace.contributions)  # retain_all keeps every segment
    assert r.retained_count == 4 and r.dropped_count == 0

    # The alternative drops colliders; the trace still labels them retained=False.
    alt = score_bounded_exact(
        _Q,
        _QW,
        _view(_C, _CW),
        working_memory=_WM_TINY,
        collision_policy="unique_source_max",
        expensive_trace=True,
    )
    assert alt.dropped_count == 2 and alt.retained_count == 2
    assert alt.trace is not None
    assert sum(1 for c in alt.trace.contributions if not c.retained) == 2


# --------------------------------------------------------------------------- #
# 5. Chunked processing + no normal N x N trace                                  #
# --------------------------------------------------------------------------- #


def test_small_working_memory_forces_chunking_and_normal_path_keeps_no_full_trace(monkeypatch) -> None:
    """Chunk size aligns with working_memory; processing is chunked; normal path keeps no N x N trace."""
    q = _random_unit(3, 4, seed=1)
    c = _random_unit(6, 4, seed=7)
    cw = np.ones(6)
    qw = np.ones(3)

    real_block = bounded_scoring._block_max_and_winner
    calls = {"n": 0}

    def _spy(*a, **k):
        calls["n"] += 1
        return real_block(*a, **k)

    monkeypatch.setattr(bounded_scoring, "_block_max_and_winner", _spy)

    r = score_bounded_exact(q, qw, _view(c, cw), working_memory=_WM_CHUNK2)
    assert r.candidate_chunk_size == 2 and r.query_chunk_size == 2  # aligned with working_memory
    # One _block_max_and_winner call per candidate chunk (6 rows / 2 = 3), proving chunked
    # processing rather than one big full-matrix block.
    assert calls["n"] == 3
    assert calls["n"] > 1
    # Normal path retains NO full matrix/trace.
    assert r.trace is None and r.trace_retained is False
    assert r.finite is True


def test_expensive_trace_is_explicit_labelled_and_opt_in(monkeypatch) -> None:
    """expensive_trace=True is a labelled, opt-in mode; it never fires by default."""
    q = _random_unit(3, 4, seed=2)
    c = _random_unit(6, 4, seed=9)
    cw = np.ones(6)
    qw = np.ones(3)

    real_block = bounded_scoring._block_max_and_winner
    calls = {"n": 0}

    def _spy(*a, **k):
        calls["n"] += 1
        return real_block(*a, **k)

    monkeypatch.setattr(bounded_scoring, "_block_max_and_winner", _spy)

    # Default off.
    normal = score_bounded_exact(q, qw, _view(c, cw), working_memory=_WM_CHUNK2)
    assert normal.trace is None and normal.trace_retained is False

    calls["n"] = 0
    lab = score_bounded_exact(q, qw, _view(c, cw), working_memory=_WM_CHUNK2, expensive_trace=True)
    assert lab.trace is not None and lab.trace_retained is True  # explicitly labelled
    assert len(lab.trace.contributions) == 6  # segment-level only, never the 3x6 pair product
    # Expensive mode still honours the same chunk limits (3 candidate blocks, not one full matrix).
    assert calls["n"] == 3


# --------------------------------------------------------------------------- #
# 6. Zero-searchable (empty) candidate view                                    #
# --------------------------------------------------------------------------- #


def test_empty_candidate_view_yields_finite_empty_result() -> None:
    """A zero-searchable-rows candidate view is a finite EMPTY result — never NaN/Inf or a crash."""
    empty = ScoringCandidateView(vectors=np.empty((0, 2), dtype=np.float32), row_addresses=())
    r = score_bounded_exact(_Q, _QW, empty, working_memory=_WM_TINY)
    assert r.finite is True
    assert r.score == 0.0 and r.numerator == 0.0 and r.denominator == 0.0
    assert r.n_candidate_rows == 0 and r.n_source_rows == 2
    assert r.retained_count == 0 and r.dropped_count == 0
    assert r.winner_counts == {} and r.collisions == ()
    assert r.trace is None and r.trace_retained is False

    # Empty with the explicit trace mode requested: empty labelled trace, still finite.
    lt = score_bounded_exact(_Q, _QW, empty, working_memory=_WM_TINY, expensive_trace=True)
    assert lt.trace_retained is True and lt.trace is not None
    assert lt.trace.contributions == () and lt.finite is True


# --------------------------------------------------------------------------- #
# 7. Oracle equivalence across fixtures / chunks / variants (+ float32)        #
# --------------------------------------------------------------------------- #


def test_oracle_equivalence_across_fixtures_chunks_and_variants() -> None:
    """score_bounded_exact matches score_exact_oracle across fixtures, chunkings, and variants."""
    fixtures = [
        (_Q, _QW, _C, _CW),
        (_Q, _QW, _norm([1.0, 1.0]).reshape(1, 2), np.array([4.0])),
        (_random_unit(2, 5, seed=3), np.array([1.0, 2.0]), _random_unit(3, 5, seed=4), np.array([3.0, 1.0, 2.0])),
        (
            _random_unit(5, 8, seed=5),
            np.full(5, 1.0),
            _random_unit(7, 8, seed=6),
            np.array([1.0, 2.0, 3.0, 1.0, 2.0, 1.0, 1.0]),
        ),
    ]
    working_memories = [8, 16, 32, 128]
    variants = [("first_index", "retain_all_candidate_segments"), ("equal_tie_split", "unique_source_max")]

    for q, qw, c, cw in fixtures:
        for wm in working_memories:
            for tie_policy, collision_policy in variants:
                r = score_bounded_exact(
                    q, qw, _view(c, cw), working_memory=wm, tie_policy=tie_policy, collision_policy=collision_policy
                )
                o = score_exact_oracle(q, qw, c, cw, tie_policy=tie_policy, collision_policy=collision_policy)
                _assert_numeric_eq(r, o)


def test_bounded_chunk_invariance_is_exact() -> None:
    """Chunk boundaries never change a bounded result: score is bit-identical across chunk sizes."""
    q, qw, c, cw = (_random_unit(5, 8, seed=5), np.full(5, 1.0), _random_unit(7, 8, seed=6), np.full(7, 1.0))
    reference = score_bounded_exact(q, qw, _view(c, cw), working_memory=_WM_CHUNK2).score
    for wm in (8, 16, 64, 1024):
        r = score_bounded_exact(q, qw, _view(c, cw), working_memory=wm)
        assert r.score == reference  # exact: chunking does not change any element/sum


def test_oracle_equivalence_on_production_float32_payloads() -> None:
    """Feeding the SAME float32 payload (production view dtype) to scorer and oracle matches."""
    q = np.asarray(_Q, dtype=np.float32)
    c = np.asarray(_C, dtype=np.float32)
    view = ScoringCandidateView(vectors=c, row_addresses=_addrs(len(c)), candidate_weights=_CW)
    for wm in (8, 32):
        r = score_bounded_exact(q, _QW, view, working_memory=wm)
        o = score_exact_oracle(q, _QW, c, _CW)  # SegmentScoreInput widens the same float32 rows
        _assert_numeric_eq(r, o)


# --------------------------------------------------------------------------- #
# 8. Semantics-version pinning                                                 #
# --------------------------------------------------------------------------- #


def test_scoring_semantics_version_stays_pinned_to_search_view_constant() -> None:
    """The scorer's emitted semantics version equals the search-view/semantics constant (== 1)."""
    from scripts.embedding_research import search_views

    r = score_bounded_exact(_Q, _QW, _view(_C, _CW), working_memory=_WM_TINY)
    assert r.scoring_semantics_version == bounded_scoring.SCORING_SEMANTICS_VERSION
    assert r.scoring_semantics_version == search_views.SCORING_SEMANTICS_VERSION
    assert r.scoring_semantics_version == 1
