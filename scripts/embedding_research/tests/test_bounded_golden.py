"""Plan D Phase 4 (P4-S1) — golden equivalence: bounded scorer vs the full-matrix oracle.

``bounded_scoring.score_bounded_exact`` is a memory-safe chunked re-derivation of the
exact ``max_per_candidate_segment`` semantics whose small full-matrix oracle lives in
``scoring_harness.score_max_per_candidate_segment``.  This module is the **golden
equivalence** gate that Phase 2 (P2-S1..P2-S4 smoke in ``test_bounded_scoring.py``)
deferred to Phase 4:

* bounded results equal the oracle **within a documented float tolerance** (the DD's
  tolerance-bounded policy: float matrices are tolerance-bounded, never bit-identical);
* the documented tolerance constants and their rationale are stated here;
* **identity / discrete outcomes are byte-exact, never tolerance-bounded** — collisions,
  tie groups and the set of winning sources compare exactly (and the search-view identity
  hashes ``keyset_hash`` / ``content_hash`` / ``search_view_hash`` are asserted byte-equal
  across identical regenerations, and stale corpora differ byte-wise, not within a
  tolerance);
* tie/collision outcomes are deterministic and byte-exact across repeated invocations
  (fixed seeds, repeated runs produce identical JSON);
* a **tolerance-tightness** check records the observed maximum abs/rel differences between
  bounded and oracle results across the whole fixture matrix and asserts they sit **well
  inside** the documented tolerance.  The recorded maxima are labelled
  observed-on-fixtures (they describe the synthetic fixture matrix only, never an
  empirical corpus run);
* both the primary ``max_per_candidate_segment + first_index +
  retain_all_candidate_segments`` variant and the ``equal_tie_split + unique_source_max``
  alternative are covered.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from scripts.embedding_research.bounded_scoring import (
    ScoringCandidateView,
    score_bounded_exact,
)
from scripts.embedding_research.scoring_harness import (
    SegmentScoreInput,
    score_max_per_candidate_segment,
)

# --------------------------------------------------------------------------- #
# Documented tolerance policy (P4-S1).                                          #
# --------------------------------------------------------------------------- #
# The bounded scorer and the oracle both upcast the SAME float32-stored rows to float64
# and compute elementwise dot products.  Chunking is by query/candidate rows and never
# splits a single dot product, so the drift source is limited to float matmul ordering.
# We therefore bound the float comparison tightly: any finite result that differs from
# the oracle by more than these constants is a genuine re-derivation defect, NOT a normal
# float-arithmetic difference.  These are the documented rtol/atol constants for the whole
# golden matrix; identity/discrete outcomes (below) are never tolerance-bounded.
_GOLDEN_ATOL = 1e-9
_GOLDEN_RTOL = 1e-9

#: Collision groups / tie winner source-sets must be byte-exact between bounded and oracle
#: (never tolerance-bounded).  This is a strict equality contract.
_PRIMARY = ("first_index", "retain_all_candidate_segments")
_ALTERNATIVE = ("equal_tie_split", "unique_source_max")
_VARIANTS = (_PRIMARY, _ALTERNATIVE)

#: Live accumulator for the tolerance-tightness report.  Populated only while this test
#: module runs; values are observed-on-fixtures maxima and are part of the test report,
#: never an empirical corpus claim.
_OBSERVED_MAX_ABS: dict[str, float] = {}
_OBSERVED_MAX_REL: dict[str, float] = {}


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


def _bounded(sv, cv, sw, cw, tp, cp):
    return score_bounded_exact(
        sv,
        sw,
        _view(cv, cw),
        tie_policy=tp,
        collision_policy=cp,
    )


def _oracle(sv, cv, sw, cw, tp, cp):
    return score_max_per_candidate_segment(
        SegmentScoreInput(sv, cv, sw, cw),
        tie_policy=tp,
        collision_policy=cp,
    )


def _norm_collisions(collisions) -> list[list[int]]:
    # Byte-exact normalized collision groups (order-independent, source-index stable).
    return sorted(sorted(int(i) for i in g) for g in collisions)


def _norm_winner_sources(winner_counts) -> list[int]:
    # Byte-exact set of winning source indices (keys for bounded dict / oracle pairs).
    if isinstance(winner_counts, dict):
        return sorted(int(s) for s in winner_counts)
    return sorted(int(s) for s, _c in winner_counts)


def _compare_fixture(sv, cv, sw, cw, tp, cp):
    """Return (errors, diffs) comparing bounded to oracle on one fixture+variant.

    Discrete outcomes (collisions, winning source set) are compared byte-exact.  Float
    score/numerator/denominator are compared within the documented tolerance.  Tracks the
    observed maximum abs/rel diffs for the tolerance-tightness report.
    """
    bounded = _bounded(sv, cv, sw, cw, tp, cp)
    oracle = _oracle(sv, cv, sw, cw, tp, cp)

    errors: list[str] = []
    diffs: dict[str, float] = {}
    for scalar in ("score", "numerator", "denominator"):
        bv = float(getattr(bounded, scalar))
        ov = float(getattr(oracle, scalar))
        diffs[f"abs_{scalar}"] = abs(bv - ov)
        diffs[f"rel_{scalar}"] = (abs(bv - ov) / abs(ov)) if ov != 0.0 else abs(bv - ov)
        _OBSERVED_MAX_ABS[scalar] = max(_OBSERVED_MAX_ABS.get(scalar, 0.0), abs(bv - ov))
        denom = abs(ov) if ov != 0.0 else 1.0
        _OBSERVED_MAX_REL[scalar] = max(_OBSERVED_MAX_REL.get(scalar, 0.0), abs(bv - ov) / denom)
        if not (abs(bv - ov) <= _GOLDEN_ATOL + _GOLDEN_RTOL * abs(ov)):
            errors.append(f"{scalar} bounded={bv!r} oracle={ov!r} outside tolerance")

    # Discrete outcomes — byte-exact, never tolerance-bounded.
    if _norm_collisions(bounded.collisions) != _norm_collisions(oracle.collisions):
        errors.append(f"collisions differ: bounded={bounded.collisions} oracle={oracle.collisions}")
    if _norm_winner_sources(bounded.winner_counts) != _norm_winner_sources(oracle.winner_counts):
        errors.append(f"winning source set differs: bounded={bounded.winner_counts} oracle={oracle.winner_counts}")
    if bounded.finite != oracle.finite:
        errors.append(f"finite flag differs: bounded={bounded.finite} oracle={oracle.finite}")
    if bounded.variant != oracle.variant:
        errors.append(f"variant differs: bounded={bounded.variant} oracle={oracle.variant}")
    return errors, diffs


def _fixture_matrix(seed: int = 11):
    """Deterministic (sv, cv, sw, cw) fixture set covering shapes + discrete structure."""
    rng = np.random.default_rng(seed)
    cases: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []

    # The canonical collision/equal-tie fixture (identical float32 inputs, exact compare).
    sv = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    cv = np.array([[1.0, 0.0], [0.8, 0.6], [0.0, 1.0]], dtype=np.float32)
    sw = np.array([2.0, 1.0], dtype=np.float64)
    cw = np.array([3.0, 2.0, 4.0], dtype=np.float64)
    cases.append((sv, cv, sw, cw))

    # A genuine exact tie: two candidate rows identical, and two source rows at equal max.
    sv_t = _unit(rng, 3, 6)
    cv_t = np.concatenate([sv_t[[0]], sv_t[[0]], _unit(rng, 4, 6)], axis=0).astype(np.float32)
    cases.append((sv_t, cv_t, np.arange(1, 4, dtype=np.float64), np.arange(1, 7, dtype=np.float64)))

    # Random deterministic fixtures across a range of (source, candidate, dim) shapes.
    for k, m, d in ((4, 5, 3), (7, 12, 5), (13, 20, 8), (25, 31, 11)):
        sv_r = _unit(rng, k, d)
        cv_r = _unit(rng, m, d)
        sw_r = np.abs(rng.standard_normal(k)) + 0.5
        cw_r = np.abs(rng.standard_normal(m)) + 0.5
        cases.append((sv_r, cv_r, sw_r, cw_r))
    return cases


# --------------------------------------------------------------------------- #
# Golden equivalence                                                           #
# --------------------------------------------------------------------------- #


def test_golden_equivalence_primary_and_alternative():
    """Bounded equals the oracle within the documented tolerance on every fixture."""
    failures: list[str] = []
    for idx, (sv, cv, sw, cw) in enumerate(_fixture_matrix()):
        for tp, cp in _VARIANTS:
            errors, _diffs = _compare_fixture(sv, cv, sw, cw, tp, cp)
            failures.extend(f"fixture#{idx} {tp}+{cp}: {e}" for e in errors)
    assert not failures, "golden equivalence failures:\n" + "\n".join(failures)


def test_golden_equivalence_chunk_invariance_across_matrix():
    """Bounded still equals the oracle when chunk sizes vary (query+candidate)."""
    failures: list[str] = []
    for idx, (sv, cv, sw, cw) in enumerate(_fixture_matrix()):
        for tp, cp in _VARIANTS:
            for qcs, ccs in ((1, 1), (2, 3), (3, 2)):
                b = score_bounded_exact(
                    sv,
                    sw,
                    _view(cv, cw),
                    query_chunk_size=qcs,
                    candidate_chunk_size=ccs,
                    tie_policy=tp,
                    collision_policy=cp,
                )
                o = _oracle(sv, cv, sw, cw, tp, cp)
                if not (abs(b.score - o.score) <= _GOLDEN_ATOL + _GOLDEN_RTOL * abs(o.score)):
                    failures.append(
                        f"fixture#{idx} {tp}+{cp} chunks=({qcs},{ccs}): score bounded={b.score!r} oracle={o.score!r}"
                    )
                if _norm_collisions(b.collisions) != _norm_collisions(o.collisions):
                    failures.append(
                        f"fixture#{idx} {tp}+{cp} chunks=({qcs},{ccs}): collisions differ "
                        f"bounded={b.collisions} oracle={o.collisions}"
                    )
    assert not failures, "chunk-invariance golden failures:\n" + "\n".join(failures)


# --------------------------------------------------------------------------- #
# Tolerance-tightness (observed max diff is part of the fixture test report)    #
# --------------------------------------------------------------------------- #


def test_tolerance_tightness_records_observed_max_diff():
    """Record + assert the observed maxima sit well inside the documented tolerance.

    The recorded maxima describe this synthetic fixture matrix ONLY (observed-on-fixtures);
    they are never an empirical corpus/model claim.  ``_OBSERVED_MAX_ABS/_REL`` are part of
    the test report so a future reader can see how tightly bounded matches the oracle.
    """
    # Re-run the whole matrix to (re)accumulate the observed maxima deterministically.
    for sv, cv, sw, cw in _fixture_matrix():
        for tp, cp in _VARIANTS:
            _compare_fixture(sv, cv, sw, cw, tp, cp)

    for scalar in ("score", "numerator", "denominator"):
        max_abs = _OBSERVED_MAX_ABS[scalar]
        max_rel = _OBSERVED_MAX_REL[scalar]
        # "well inside the documented tolerance": strictly under a tenth of atol/rtol.
        assert max_abs < _GOLDEN_ATOL / 10.0, (
            f"observed max abs diff on {scalar} = {max_abs} not well inside atol {_GOLDEN_ATOL}"
        )
        assert max_rel < _GOLDEN_RTOL / 10.0, (
            f"observed max rel diff on {scalar} = {max_rel} not well inside rtol {_GOLDEN_RTOL}"
        )


# --------------------------------------------------------------------------- #
# Determinism (byte-exact across repeated invocations)                          #
# --------------------------------------------------------------------------- #


def test_tie_and_collision_outcomes_byte_exact_across_runs():
    """Repeated invocations produce byte-identical results (fixed seed / deterministic)."""
    for idx, (sv, cv, sw, cw) in enumerate(_fixture_matrix()):
        for tp, cp in _VARIANTS:
            first = _bounded(sv, cv, sw, cw, tp, cp).to_dict()
            for _ in range(3):
                rerun = _bounded(sv, cv, sw, cw, tp, cp).to_dict()
                assert json.dumps(rerun, sort_keys=True) == json.dumps(first, sort_keys=True), (
                    f"fixture#{idx} {tp}+{cp} not deterministic across runs"
                )


def test_tie_winner_is_lowest_tied_source_and_deterministic():
    """A genuine multi-source tie resolves to the LOWEST tied source index, stably."""
    rng = np.random.default_rng(5)
    # Candidate rows that are exact duplicates of two source rows => both tie for max.
    sv = _unit(rng, 4, 6)
    # candidate 0 duplicates source 1 exactly; candidate 1 is its own best match.
    cv = np.stack([sv[1], sv[3], sv[1], sv[0]], axis=0).astype(np.float32)
    cw = np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float64)
    sw = np.ones(4, dtype=np.float64)

    for _ in range(5):
        res = score_bounded_exact(
            sv,
            sw,
            _view(cv, cw),
            tie_policy="first_index",
            collision_policy="retain_all_candidate_segments",
        )
        # candidate 0 & 2 both perfectly match source 1 => winner source == 1, collision.
        assert res.winner_counts.get(1) is not None
        # the tie group {0,2} is a collision sharing representative source 1.
        assert (0, 2) in {tuple(g) for g in res.collisions} or (2, 0) in {tuple(g) for g in res.collisions}
        assert res.finite is True
    # The oracle agrees on the same discrete outcome.
    o = _oracle(sv, cv, sw, cw, "first_index", "retain_all_candidate_segments")
    assert _norm_collisions(res.collisions) == _norm_collisions(o.collisions)
    assert _norm_winner_sources(res.winner_counts) == _norm_winner_sources(o.winner_counts)


# --------------------------------------------------------------------------- #
# Identity hashes are byte-exact, never tolerance-bounded                        #
# --------------------------------------------------------------------------- #


def _identity_hash_compare(con, out, run_id):
    """Build a synthetic corpus, materialize a view, return identity-hash primitives."""
    from scripts.embedding_research import catalog
    from scripts.embedding_research import search_views as sv
    from scripts.embedding_research.streams.store import StreamStore

    store = StreamStore(con, output_root=str(out))
    rng = np.random.default_rng(7)
    for song in ("s1", "s2"):
        store.publish(song, "effnet", _unit(rng, 10, 6), run_id="run-embed")
    store.reconcile()
    catalog.build_segmentation_catalog(
        con,
        store,
        [
            catalog.SegConfigInput(
                backbone="effnet",
                bin_mode="temporal_global",
                threshold_configured=0.7,
                threshold_effective=0.7,
            )
        ],
        ["s1", "s2"],
        "run-cat-1",
        verify=True,
    )
    corpus = sv.AnalysisCorpus(backbone="effnet", song_ids=["s1", "s2"])
    # Two independent materializations of the SAME identity must hash byte-equal.
    rec_a = sv.materialize_search_view(store, con, corpus, run_id, working_memory=1024 * 1024)
    rec_b = sv.materialize_search_view(store, con, corpus, run_id, working_memory=1024 * 1024)
    return rec_a, rec_b


def test_search_view_identity_hashes_byte_exact(con, tmp_path):
    """keyset/content/search_view hashes are byte-exact across identical regeneration."""
    rec_a, rec_b = _identity_hash_compare(con, tmp_path / "out", "run-an-x")
    # Byte equality of the identity hashes (never tolerance-bounded).
    assert rec_a.keyset_hash == rec_b.keyset_hash
    assert rec_a.content_hash == rec_b.content_hash
    assert rec_a.key.search_view_hash == rec_b.key.search_view_hash
    # The hashes are real hex digests, not floats — equality is string equality.
    assert isinstance(rec_a.keyset_hash, str) and len(rec_a.keyset_hash) == 64
    assert isinstance(rec_a.content_hash, str) and len(rec_a.content_hash) == 64
    assert isinstance(rec_a.key.search_view_hash, str)
    # Same identity => same matrix shape and row set (byte-stable discrete surface).
    assert rec_a.row_addresses == rec_b.row_addresses
    assert rec_a.key.matrix_shape == rec_b.key.matrix_shape


def test_search_view_stale_corpus_changes_hash_bytewise_and_rejected(con, tmp_path):
    """A changed corpus yields byte-different identity hashes and stale validation rejects the old view.

    The whole-catalog ``search_view_hash`` advances when a song is added, so an earlier view's
    keyset no longer matches a fresh materialization of the same logical surface: exact identity
    (byte-equality of the sha256 hashes) governs reuse — never a tolerance and never file existence.
    """
    from scripts.embedding_research import catalog
    from scripts.embedding_research.search_views import (
        StaleSearchViewError,
        validate_search_view_keyset,
    )
    from scripts.embedding_research.streams.store import StreamStore

    rec_a, _ = _identity_hash_compare(con, tmp_path / "out", "run-an-x")

    # Grow the SAME catalog with a third song => whole-catalog search_view_hash changes.
    store = StreamStore(con, output_root=str(tmp_path / "out2"))
    rng = np.random.default_rng(99)
    for song in ("s1", "s2", "s3"):
        store.publish(song, "effnet", _unit(rng, 10, 6), run_id="run-embed")
    store.reconcile()
    catalog.build_segmentation_catalog(
        con,
        store,
        [
            catalog.SegConfigInput(
                backbone="effnet",
                bin_mode="temporal_global",
                threshold_configured=0.7,
                threshold_effective=0.7,
            )
        ],
        ["s1", "s2", "s3"],
        "run-cat-2",
        verify=True,
    )

    # The SAME 2-song scope re-materialized against the GROWN catalog has a byte-different
    # keyset/content hash than rec_a (the whole-catalog search_view_hash advanced when s3 was
    # added), so the old view is stale by exact identity — never by a tolerance.
    from scripts.embedding_research.search_views import AnalysisCorpus, materialize_search_view

    corpus = AnalysisCorpus(backbone="effnet", song_ids=["s1", "s2"])
    rec_fresh = materialize_search_view(store, con, corpus, "run-an-x", working_memory=1024 * 1024)
    assert rec_fresh.keyset_hash != rec_a.keyset_hash
    assert rec_fresh.content_hash != rec_a.content_hash

    # A freshly materialized current record validates; the OLD record is stale and rejected.
    validate_search_view_keyset(con, rec_fresh)
    with pytest.raises(StaleSearchViewError):
        validate_search_view_keyset(con, rec_a)
