"""Plan D Phase 4 (P4-S2) — bounded memory + finite-reduction behaviour tests.

``bounded_scoring.score_bounded_exact`` is the memory-safe bounded scorer whose golden
equivalence to the small full-matrix oracle is pinned in ``test_bounded_golden.py`` (P4-S1).
This module proves the memory/behaviour obligations that Phase 2's smoke tests only started
(they defer the full golden matrix to P4-S1, so here we complete, not duplicate):

* (a) BOTH query modes work and agree with the oracle within tolerance — single query-song
  scoring and bounded-query-batch scoring (concatenated query rows).
* (b) Candidate chunk release — the tracemalloc peak stays bounded across candidate-chunk
  sizes and sits far below the full K x M product bytes for a sized fixture, in both query
  modes and over larger K x M fixtures than the Phase-2 smoke.
* (c) Finite streaming reductions — non-finite input (vector or weight) is rejected up front
  (ValueError) before any result can escape, and at the catalog-analysis boundary a
  non-finite condition rejects before persistence with no partial write / scope escaping
  (aligning with Phase 3's NonFiniteResultError final gate).
* (d) No normal-path source-x-candidate (N x N) trace allocation/retention — structural +
  tracemalloc; ``expensive_trace=True`` explicitly reports trace retention (``trace_retained``
  and a trace summary) and honours bounded chunks.
* (e) Bounded peak memory/RSS instrumentation — the labelled fixtures-only benchmark helper
  (``fixture_benchmark.run_bounded_benchmark``) records peak tracemalloc / peak RSS plus the
  full-product byte reference and reports them with full P4-S3 metadata.
"""

from __future__ import annotations

import tracemalloc

import numpy as np
import pytest

from scripts.embedding_research import fixture_benchmark
from scripts.embedding_research.bounded_scoring import (
    ScoringCandidateView,
    score_bounded_exact,
)
from scripts.embedding_research.scoring_harness import (
    SegmentScoreInput,
    score_max_per_candidate_segment,
)

#: Same documented tolerance as the golden matrix (P4-S1) — applied to the query-mode oracle
#: agreement tests here.
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


def _oracle_score(sv, cv, sw, cw, tp, cp):
    return score_max_per_candidate_segment(SegmentScoreInput(sv, cv, sw, cw), tie_policy=tp, collision_policy=cp).score


def _build_songs(rng, songs, n: int = 12, d: int = 8) -> dict[str, np.ndarray]:
    """Deterministic per-song float32 unit-row streams (one ready song per stream)."""
    return {song: _unit(rng, n, d) for song in songs}


def _combined(query_songs: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Concatenate several songs' streams into one bounded-query batch + aligned weights."""
    rows = list(query_songs.values())
    stacked = np.concatenate(rows, axis=0).astype(np.float32)
    weights = np.repeat(np.arange(1, len(rows) + 1), [r.shape[0] for r in rows]).astype(np.float64)
    return stacked, weights


# --------------------------------------------------------------------------- #
# (a) single query-song AND bounded-query-batch scoring agree with the oracle   #
# --------------------------------------------------------------------------- #


def test_single_query_song_and_batch_agree_with_oracle():
    """Both query modes work and match the full-matrix oracle within tolerance."""
    rng = np.random.default_rng(3)
    query_songs = _build_songs(rng, ["qa", "qb", "qc"])
    candidates = _build_songs(rng, ["c1", "c2", "c3", "c4"])
    cv = np.concatenate(list(candidates.values()), axis=0)
    cw = np.arange(1, len(cv) + 1, dtype=np.float64)

    # --- single query-song mode: one song's rows as the source side. ---
    qa = query_songs["qa"]
    swa = np.arange(1, len(qa) + 1, dtype=np.float64)
    bounded = score_bounded_exact(qa, swa, _view(cv, cw))
    oracle = _oracle_score(qa, cv, swa, cw, *_PRIMARY)
    assert abs(bounded.score - oracle) <= _ATOL + _RTOL * abs(oracle)
    # equal_tie_split + unique_source_max alternative also agrees.
    alt = score_bounded_exact(qa, swa, _view(cv, cw), tie_policy=_ALTERNATIVE[0], collision_policy=_ALTERNATIVE[1])
    assert abs(alt.score - _oracle_score(qa, cv, swa, cw, *_ALTERNATIVE)) <= _ATOL + _RTOL

    # --- bounded-query-batch mode: concatenated query rows score against the SAME view. ---
    qbatch, swbatch = _combined(query_songs)
    batch = score_bounded_exact(qbatch, swbatch, _view(cv, cw))
    oracle_batch = _oracle_score(qbatch, cv, swbatch, cw, *_PRIMARY)
    assert abs(batch.score - oracle_batch) <= _ATOL + _RTOL * abs(oracle_batch)
    alt_batch = score_bounded_exact(
        qbatch, swbatch, _view(cv, cw), tie_policy=_ALTERNATIVE[0], collision_policy=_ALTERNATIVE[1]
    )
    assert abs(alt_batch.score - _oracle_score(qbatch, cv, swbatch, cw, *_ALTERNATIVE)) <= _ATOL + _RTOL


# --------------------------------------------------------------------------- #
# (b) candidate chunk release — peak stays bounded << full product               #
# --------------------------------------------------------------------------- #


def _peak_bytes_of(fn) -> int:
    tracemalloc.start()
    try:
        fn()
        _cur, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return int(peak)


def test_candidate_chunk_release_keeps_peak_bounded_both_modes():
    """Peak stays bounded across candidate-chunk sizes, far below the full product bytes."""
    rng = np.random.default_rng(4)
    d = 4
    # Sized fixture: the K x M full product is tens of MB; bounded chunks keep the tracemalloc
    # peak to ~1-2 MB (fixed numpy overhead) regardless of candidate-chunk size.
    m = 2048
    crows = _unit(rng, m, d)
    cw = np.arange(1, m + 1, dtype=np.float64)
    single_q = _unit(rng, 1024, d)  # one long query song, 1024 segment rows
    batch_q = _unit(rng, 2048, d)  # bounded-query batch: several songs' rows concatenated

    full_single = single_q.shape[0] * m * 8
    full_batch = batch_q.shape[0] * m * 8
    assert full_single / 8 > 2_000_000  # guarantee the bound comfortably exceeds fixed overhead
    for ccs in (32, 64, 128):
        # single query-song mode
        peak_s = _peak_bytes_of(
            lambda ccs=ccs: score_bounded_exact(
                single_q,
                np.ones(single_q.shape[0]),
                _view(crows, cw),
                query_chunk_size=128,
                candidate_chunk_size=ccs,
            )
        )
        assert peak_s < full_single / 8, f"single mode peak {peak_s} not << full {full_single} at ccs={ccs}"
        # bounded-query-batch mode (larger K)
        peak_b = _peak_bytes_of(
            lambda ccs=ccs: score_bounded_exact(
                batch_q,
                np.ones(batch_q.shape[0]),
                _view(crows, cw),
                query_chunk_size=128,
                candidate_chunk_size=ccs,
            )
        )
        assert peak_b < full_batch / 8, f"batch mode peak {peak_b} not << full {full_batch} at ccs={ccs}"
    # Larger K x M fixture (both dims big) still bounded.
    m_big = 4096
    crows_big = _unit(rng, m_big, d)
    cw_big = np.arange(1, m_big + 1, dtype=np.float64)
    big_q = _unit(rng, 2048, d)
    full_big = big_q.shape[0] * m_big * 8
    peak = _peak_bytes_of(
        lambda: score_bounded_exact(
            big_q,
            np.ones(big_q.shape[0]),
            _view(crows_big, cw_big),
            query_chunk_size=128,
            candidate_chunk_size=64,
        )
    )
    assert peak < full_big / 8, f"larger K x M peak {peak} not << full {full_big}"


# --------------------------------------------------------------------------- #
# (c) finite streaming reductions: non-finite rejected, no partial write        #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "field",
    ["query_vectors", "candidate_vectors", "query_weights", "candidate_weights"],
)
def test_non_finite_anywhere_raises_before_any_result(field):
    """A NaN/Inf in any input raises ValueError up front — never a partial finite=False result."""
    rng = np.random.default_rng(9)
    sv = _unit(rng, 6, 5)
    cv = _unit(rng, 9, 5)
    sw = np.arange(1, 7, dtype=np.float64)
    cw = np.arange(1, 10, dtype=np.float64)

    sv_bad = sv.copy()
    cv_bad = cv.copy()
    sw_bad = sw.copy()
    cw_bad = cw.copy()
    # Put the bad value in the LAST row so only a fully-completed (partial) reduction would
    # have accumulated state before the reject — we prove the finite gate rejects up front.
    if field == "query_vectors":
        sv_bad[-1, 0] = np.nan
        q, c, qw, cw_use = sv_bad, cv, sw, cw
    elif field == "candidate_vectors":
        cv_bad[-1, 0] = np.inf
        q, c, qw, cw_use = sv, cv_bad, sw, cw
    elif field == "query_weights":
        sw_bad[-1] = np.nan
        q, c, qw, cw_use = sv, cv, sw_bad, cw
    else:
        cw_bad[-1] = np.inf
        q, c, qw, cw_use = sv, cv, sw, cw_bad
    with pytest.raises(ValueError):
        score_bounded_exact(q, qw, _view(c, cw_use))


def _build_catalog(con, out, songs):
    """Deterministic per-song COMPACT catalog; return (store, open snapshot handle).

    Caller must ``.close()`` the handle (its ``.con`` is the compact snapshot connection).
    """
    from scripts.embedding_research import catalog
    from scripts.embedding_research.catalog_storage import open_snapshot_file
    from scripts.embedding_research.streams import make_current_stream_resolver
    from scripts.embedding_research.streams.store import StreamStore

    store = StreamStore(con, output_root=str(out))
    rng = np.random.default_rng(7)
    for song in songs:
        store.publish(song, "effnet", _unit(rng, 10, 6), run_id="run-embed")
    store.reconcile()
    rep = catalog.build_segmentation_catalog(
        make_current_stream_resolver(store),
        None,
        [
            catalog.SegConfigInput(
                backbone="effnet",
                bin_mode="temporal_global",
                threshold_configured=0.7,
                threshold_effective=0.7,
            )
        ],
        list(songs),
        output_root=str(out),
        run_id="run-cat-1",
        verify=True,
    )
    assert rep.verify_ok is True
    handle = open_snapshot_file(f"{out}/catalogs/.staging-run-cat-1/catalog.duckdb", read_only=True)
    return store, handle


def test_non_finite_analysis_rejected_before_persistence_no_partial_write(con, tmp_path, monkeypatch):
    """A poisoned candidate weight rejects before persistence and writes no partial scope."""
    from scripts.embedding_research.common import catalog_analysis as ca
    from scripts.embedding_research.db import analyze_scope

    songs = ("s1", "s2", "s3", "s4")
    artists = {"s1": "A", "s2": "A", "s3": "B", "s4": "B"}
    store, handle = _build_catalog(con, tmp_path / "out", songs)
    cfg = ca.CatalogAnalysisConfig(run_id="run-poison", backbone="effnet", song_ids=songs, artists=artists)

    real = ca.candidate_weights_from_catalog
    poisoned = [False]

    def _poisoned(catalog, rows):
        w = real(catalog, rows).astype(np.float64)
        if poisoned[0]:
            w = w.copy()
            w[-1] = np.nan  # a NaN segment weight in the last row
        return w

    monkeypatch.setattr(ca, "candidate_weights_from_catalog", _poisoned)
    try:
        # A good run completes and may be persisted without a partial poisoned scope.
        good = ca.run_catalog_analysis(store, handle.con, cfg, research_con=con)
        assert good.finite is True
        # Record a scope for the good run to prove it is NOT disturbed by the poisoned run.
        analyze_scope.record_analyze_run_scope(
            con,
            run_id="run-poison",
            strategy_key=good.strategy_key,
            sim_metric="cosine",
            k=good.k,
            backbone=good.backbone,
            config_ids=good.config_ids,
            view_content_hash=good.view_content_hash,
            score_variant=good.score_variant,
            scoring_semantics_version=good.scoring_semantics_version,
        )
        good_scopes = analyze_scope.run_row_scopes(con, run_id="run-poison")
        assert good_scopes, "good run scope must be recorded"

        poisoned[0] = True
        with pytest.raises(ValueError):
            ca.run_catalog_analysis(store, handle.con, cfg, research_con=con)
        # The poisoned run never wrote a partial analyze scope/result — run_id scope is unchanged.
        assert analyze_scope.run_row_scopes(con, run_id="run-poison") == good_scopes
    finally:
        handle.close()


def test_finite_writer_gate_refuses_non_finite_result(con, tmp_path):
    """The persistence writer is finite-only: it refuses a non-finite result before writing."""
    from scripts.embedding_research.common import catalog_analysis as ca
    from scripts.embedding_research.db import analyze_scope

    songs = ("s1", "s2")
    artists = {"s1": "A", "s2": "A"}
    store, handle = _build_catalog(con, tmp_path / "out", songs)
    cfg = ca.CatalogAnalysisConfig(run_id="run-fin", backbone="effnet", song_ids=songs, artists=artists)
    try:
        good = ca.run_catalog_analysis(store, handle.con, cfg, research_con=con)
    finally:
        handle.close()
    import dataclasses

    bad = dataclasses.replace(good, finite=False, run_id="run-bad")
    with pytest.raises(ValueError):
        analyze_scope.write_catalog_analyze_rows(con, run_id="run-bad", result=bad)
    # Nothing was written for the refused run.
    assert analyze_scope.run_row_scopes(con, run_id="run-bad") == frozenset()


# --------------------------------------------------------------------------- #
# (d) no normal-path N x N trace retention; expensive_trace is explicit         #
# --------------------------------------------------------------------------- #


def test_normal_path_retains_no_trace_and_peak_is_bounded():
    """Default path reports trace_retained=False and keeps peak far below the full product."""
    rng = np.random.default_rng(12)
    m = 4096
    crows = _unit(rng, m, 4)
    cw = np.arange(1, m + 1, dtype=np.float64)
    q = _unit(rng, 2048, 4)
    sw = np.ones(q.shape[0])
    full = q.shape[0] * m * 8

    def _run():
        return score_bounded_exact(q, sw, _view(crows, cw), query_chunk_size=128, candidate_chunk_size=64)

    peak = _peak_bytes_of(_run)
    res = _run()
    assert peak < full / 8, f"normal-path peak {peak} not << full {full}"
    assert res.trace_retained is False
    assert res.trace is None
    assert res.segment_summary()["trace_retained"] == 0.0


def test_expensive_trace_is_explicit_and_honours_chunk_budgets():
    """expensive_trace=True flags retention, exposes a per-candidate trace, and stays bounded."""
    rng = np.random.default_rng(13)
    m = 4096
    d = 4
    crows = _unit(rng, m, d)
    cw = np.arange(1, m + 1, dtype=np.float64)
    q = _unit(rng, 2048, d)
    sw = np.ones(q.shape[0])
    full = q.shape[0] * m * 8

    def _run():
        return score_bounded_exact(
            q,
            sw,
            _view(crows, cw),
            query_chunk_size=128,
            candidate_chunk_size=128,
            expensive_trace=True,
        )

    peak = _peak_bytes_of(_run)
    res = _run()
    assert peak < full / 8, f"expensive-trace peak {peak} not << full {full}"
    assert res.trace_retained is True
    assert res.trace is not None
    assert len(res.trace.contributions) == m
    assert res.segment_summary()["trace_retained"] == 1.0
    # Default stays cheap even when the same input is traced: tracing is opt-in.
    assert (
        score_bounded_exact(q, sw, _view(crows, cw), query_chunk_size=128, candidate_chunk_size=128).trace_retained
        is False
    )


# --------------------------------------------------------------------------- #
# (e) bounded peak memory/RSS recorded in a labelled fixtures-only helper        #
# --------------------------------------------------------------------------- #


def test_benchmark_helper_records_peak_memory_bounded_and_validated():
    """run_bounded_benchmark returns a validated, fixtures-only record with peak << full product."""
    rec = fixture_benchmark.run_bounded_benchmark(
        n_songs=40,
        segments_per_song=100,
        dimension=24,
        query_chunk_size=64,
        candidate_chunk_size=64,
        working_memory_bytes=32 * 1024 * 1024,
        seed=0,
    )
    # The record is fully labelled and valid (all P4-S3 metadata present, fixtures_only=True).
    assert rec.validate() == []
    assert rec.fixtures_only is True
    assert rec.full_product_bytes > 0
    # The bounded scorer never materialised the full product: recorded peak << full bytes.
    assert rec.peak_tracemalloc_bytes < rec.full_product_bytes / 8, (
        f"recorded peak {rec.peak_tracemalloc_bytes} not << full product {rec.full_product_bytes}"
    )
    # Peak RSS is an observed (positive) high-water mark; elapsed is a positive fixture time.
    assert rec.peak_rss_bytes > 0
    assert rec.elapsed_ms >= 0.0
    assert rec.finite is True
