"""Plan A P1 (execution-reporting-repair) — evaluation-corpus identity + threading (spec-first).

These tests pin the P1 contract delivered by ``catalog_identity.resolve_evaluation_corpus`` and
the identity threading in ``common.catalog_analysis`` / ``run.py::_run_analyze``:

1. ``resolve_evaluation_corpus`` returns a deterministic, canonical sorted identity whose
   ``corpus_hash`` is independent of requested-song ORDER (re-resolving the same population in a
   different order yields an identical frozen identity).
2. A requested song with NO committed observation group is refused/excluded with evidence
   (``missing_song_ids`` / ``missing_count`` / ``missing_digest``), never silently pooled.
3. A fully-silent (zero-searchable) committed song is excluded with evidence; eligibility is
   exactly ``valid committed stream+mask AND >= 1 non-silent whole-song patch``.
4. A sub-2 eligible corpus is ``eligible == comparable == False`` (leave-one-out is undefined) —
   no fabricated singleton success.
5. Missing-medoid invalidation (P1-S3): an ELIGIBLE song with no canonical searchable medoid row
   in a representation makes that representation ``comparable == False`` with missing evidence and
   NO matched retrieval metrics, and the writer REFUSES to persist a partial configuration as a
   complete outcome.
6. Exact population reuse across classes/baseline: every segmented class pass and the whole-song
   medoid baseline consume the SAME resolved identity population (never a separately-derived one).

Pure identity parts (1-4) need no real corpus/model/audio; the real-catalog parts (5-6) reuse the
shared compact-catalog + committed-observation fixture.  No real corpus/audio/CTP/ANN is run.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pytest

from scripts.embedding_research import catalog as catalog_mod
from scripts.embedding_research.catalog_identity import (
    EVALUATION_CORPUS_SEMANTICS_VERSION,
    EvaluationCorpusIdentity,
    catalog_requested_song_ids,
    resolve_evaluation_corpus,
)
from scripts.embedding_research.common import catalog_analysis as ca
from scripts.embedding_research.db import analyze_scope
from scripts.embedding_research.streams import StreamStoreError
from scripts.embedding_research.tests._report_seed import catalog_key, make_catalog_result

pytestmark = pytest.mark.unit

_BACKBONE = "effnet"
_SONGS = ("s1", "s2", "s3", "s4")
_ARTISTS = {"s1": "A", "s2": "A", "s3": "B", "s4": "B"}
_RUN = "run-p1-eval-corpus"


def _cfg(threshold: float = 0.7) -> catalog_mod.SegConfigInput:
    return catalog_mod.SegConfigInput(
        backbone=_BACKBONE,
        bin_mode="temporal_global",
        threshold_configured=threshold,
        threshold_effective=threshold,
    )


def _unit(rng: np.random.Generator, n: int = 6, d: int = 4) -> np.ndarray:
    """A deterministic searchable unit stream (>= 1 non-silent patch under an all-ones mask)."""
    m = rng.standard_normal((n, d)) * 1.5
    m[0] += 3.0
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (m / norms).astype(np.float32)


def _streams(song_ids, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    return {(song, _BACKBONE): _unit(rng) for song in sorted(song_ids)}


def _build(
    compact_catalog_factory,
    con,
    tmp_path,
    *,
    catalog_song_ids,
    stream_song_ids=None,
    masks=None,
    configs=None,
    run_id=_RUN,
):
    """Build a real compact catalog + committed observations.

    ``catalog_song_ids`` are cataloged; ``stream_song_ids`` (default == catalog_song_ids) are the
    superset whose committed observation groups are published.  A song in ``stream_song_ids`` but
    NOT in ``catalog_song_ids`` is committed-but-not-cataloged (no ``seg_meta``/``catalog_song``
    rows) — the clean way to build an eligible whole-song song a representation lacks.
    """
    stream_song_ids = tuple(stream_song_ids) if stream_song_ids is not None else tuple(catalog_song_ids)
    return compact_catalog_factory(
        con,
        tmp_path,
        streams=_streams(stream_song_ids),
        configs=configs or [_cfg()],
        song_ids=list(catalog_song_ids),
        masks=masks,
        run_id=run_id,
    )


# --------------------------------------------------------------------------- #
# 1. Deterministic canonical identity (order-independent corpus_hash)          #
# --------------------------------------------------------------------------- #


def test_resolve_is_deterministic_and_order_independent(compact_catalog_factory, con, tmp_path):
    harness = _build(compact_catalog_factory, con, tmp_path / "out", catalog_song_ids=_SONGS)
    try:
        store = harness.stream_store
        fwd = resolve_evaluation_corpus(harness.con, store, ("s1", "s2", "s3", "s4"), backbone=_BACKBONE)
        rev = resolve_evaluation_corpus(harness.con, store, ["s4", "s2", "s3", "s1"], backbone=_BACKBONE)

        assert isinstance(fwd, EvaluationCorpusIdentity)
        # Canonical sorted population, order-independent.
        assert fwd.song_ids == ("s1", "s2", "s3", "s4")
        assert fwd == rev
        assert fwd.corpus_hash == rev.corpus_hash and len(fwd.corpus_hash) == 64
        assert fwd.count == 4
        assert fwd.eligible is True and fwd.comparable is True
        assert fwd.missing_song_ids == () and fwd.missing_count == 0 and fwd.missing_digest is None
        assert fwd.semantics_version == EVALUATION_CORPUS_SEMANTICS_VERSION == 1
        assert fwd.backbone == _BACKBONE
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 2. Committed-group refusal (uncommitted requested song excluded with evidence) #
# --------------------------------------------------------------------------- #


def test_uncommitted_requested_song_is_refused_with_evidence(compact_catalog_factory, con, tmp_path):
    harness = _build(compact_catalog_factory, con, tmp_path / "out", catalog_song_ids=_SONGS)
    try:
        store = harness.stream_store
        # "u1" was never published/committed -> load_committed_observation refuses.
        with pytest.raises(StreamStoreError):
            store.load_committed_observation("u1", _BACKBONE)
        ident = resolve_evaluation_corpus(harness.con, store, (*_SONGS, "u1"), backbone=_BACKBONE)
        assert ident.song_ids == _SONGS
        assert ident.missing_song_ids == ("u1",)
        assert ident.missing_count == 1
        assert ident.missing_digest is not None
        # The eligible population is unchanged: u1 is excluded, never silently pooled searchable.
        assert ident.count == 4 and ident.eligible is True and ident.comparable is True
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 3. Silent (zero-searchable) whole-song exclusion                             #
# --------------------------------------------------------------------------- #


def test_silent_whole_song_is_excluded_with_evidence(compact_catalog_factory, con, tmp_path):
    silent = np.zeros(6, dtype=np.uint8)  # s4 fully silent
    harness = _build(
        compact_catalog_factory,
        con,
        tmp_path / "out",
        catalog_song_ids=_SONGS,
        masks={"s4": silent},
    )
    try:
        store = harness.stream_store
        obs = store.load_committed_observation("s4", _BACKBONE)
        assert obs is not None and bool(np.any(obs.mask == 1)) is False  # committed but silent
        ident = resolve_evaluation_corpus(harness.con, store, _SONGS, backbone=_BACKBONE)
        assert ident.song_ids == ("s1", "s2", "s3")
        assert ident.missing_song_ids == ("s4",) and ident.missing_count == 1
        assert ident.missing_digest is not None
        assert ident.count == 3 and ident.eligible is True
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 4. Sub-2 eligible corpus is not analyzable (eligible == comparable == False) #
# --------------------------------------------------------------------------- #


def test_singleton_eligible_corpus_is_not_analyzable(compact_catalog_factory, con, tmp_path):
    harness = _build(compact_catalog_factory, con, tmp_path / "out", catalog_song_ids=("s1",))
    try:
        store = harness.stream_store
        ident = resolve_evaluation_corpus(harness.con, store, ("s1",), backbone=_BACKBONE)
        assert ident.song_ids == ("s1",) and ident.count == 1
        # Leave-one-out over a singleton is undefined -> not analyzable.
        assert ident.eligible is False and ident.comparable is False
    finally:
        harness.close()


def test_resolve_refuses_backbone_absent_from_catalog():
    """An identity is never resolved for a backbone the current catalog does not segment."""
    bare = duckdb.connect(":memory:")  # no compact seg_config surface
    try:
        with pytest.raises(ValueError):
            resolve_evaluation_corpus(bare, object(), ("s1",), backbone=_BACKBONE)
    finally:
        bare.close()


# --------------------------------------------------------------------------- #
# 5. Missing-medoid invalidation (P1-S3): partial never recorded complete      #
# --------------------------------------------------------------------------- #


def test_representation_losing_eligible_song_is_non_comparable_and_not_persisted(
    compact_catalog_factory, con, tmp_path
):
    # Commit s4 (whole-song eligible) but do NOT catalog it -> every representation lacks it.
    harness = _build(
        compact_catalog_factory,
        con,
        tmp_path / "out",
        catalog_song_ids=("s1", "s2", "s3"),
        stream_song_ids=_SONGS,
    )
    try:
        store = harness.stream_store
        ident = resolve_evaluation_corpus(harness.con, store, _SONGS, backbone=_BACKBONE)
        # s4 is committed + non-silent -> eligible, so the representation SHOULD carry it.
        assert ident.song_ids == _SONGS and "s4" in ident.song_ids

        cfg = ca.CatalogAnalysisConfig(
            run_id="run-p1s3-lost",
            backbone=_BACKBONE,
            song_ids=ident.song_ids,
            artists=dict(_ARTISTS),
            evaluation_corpus=ident,
        )
        result = ca.analyze_catalog_corpus(store, harness.con, cfg, research_con=con)
        assert result.comparable is False
        assert result.missing_song_ids == ("s4",) and result.missing_count == 1
        assert result.missing_digest is not None
        # No matched retrieval metric/delta is emitted for the partial representation.
        assert result.metrics == {} and result.per_song == {} and result.per_query == ()
        assert result.n_queries == 0
        assert result.evaluation_corpus is ident
        # Partial configurations are NEVER recorded as complete.
        with pytest.raises(ValueError):
            analyze_scope.write_catalog_analyze_rows(con, run_id="run-p1s3-lost", result=result)
    finally:
        harness.close()


def test_partial_real_anchor_write_leaves_zero_rows_after_encode_refusal(con):
    """Plan B requirement 5 ordering discriminator: encode-validation runs BEFORE any write.

    A finite + comparable result carrying a real catalog anchor but a PARTIAL v2 identity (empty
    semantic ``search_representation_hash`` and ``members``) passes the writer's finite/comparable
    gates, so only the build+``encode_analyze_scope_v2`` validation step can refuse it.  Because
    that step must run before any metrics-row write, the refusal leaves ZERO ``analyze_metrics`` /
    ``song_retrieval_metrics`` rows and NO recorded scope behind.  A pre-fix writer that persisted
    rows before encoding would raise after writing and fail these zero-row assertions.
    """
    sk = catalog_key("effnet", "pk")
    result = make_catalog_result(
        run_id="run-partial-write",
        backbone="effnet",
        strategy_key=sk,
        k=5,
        metrics={"map_k": 0.6},
        config_ids=(1,),
        catalog_id="catalog-1",  # real catalog anchor ...
        search_representation_hash="",  # ... but PARTIAL semantic hash ...
        members=(),  # ... and no per-member records -> encode_analyze_scope_v2 refuses.
    )
    # Finite + comparable, so only the build+encode-validation step can reject this result.
    assert result.finite is True and result.comparable is True
    with pytest.raises(ValueError):
        analyze_scope.write_catalog_analyze_rows(con, run_id="run-partial-write", result=result)
    # Zero aggregate rows under the run's scope (write_analyze_metrics must never have run).
    assert (
        con.execute(
            "SELECT count(*) FROM analyze_metrics WHERE run_id=? AND strategy_key=?",
            ("run-partial-write", sk),
        ).fetchone()[0]
        == 0
    )
    # Zero per-song rows under the scope (clear/write_song_retrieval_metrics must never have run).
    assert (
        con.execute(
            "SELECT count(*) FROM song_retrieval_metrics WHERE strategy_key=?",
            (sk,),
        ).fetchone()[0]
        == 0
    )
    # No scope line recorded for the run (record_analyze_run_scope must never have run).
    assert analyze_scope.run_row_scopes(con, run_id="run-partial-write") == frozenset()


def test_medoid_baseline_producer_scope_refusal_leaves_zero_rows(compact_catalog_factory, con, tmp_path, monkeypatch):
    """Plan B corrective P5-S4: the baseline producer preflights its v2 scope BEFORE any write.

    ``run_and_persist_medoid_baseline`` builds a well-formed ``observed_baseline`` identity
    internally, so the ONLY way its fail-closed boundary can refuse is the encode/decode
    preflight that runs before the first ``analyze_metrics`` insert.  Force that preflight to
    refuse (exactly as an incomplete/contradictory observed-baseline scope would raise) and
    assert the refusal leaves ZERO metric rows and NO recorded scope — the baseline never
    orphanes a partial write, mirroring ``write_catalog_analyze_rows``.
    """
    from scripts.embedding_research.baseline import medoid_strategy_key_for

    harness = _build(compact_catalog_factory, con, tmp_path / "out", catalog_song_ids=_SONGS)
    try:
        store = harness.stream_store
        ident = resolve_evaluation_corpus(harness.con, store, _SONGS, backbone=_BACKBONE)
        assert ident.eligible is True and ident.comparable is True
        medoid_key = medoid_strategy_key_for(_BACKBONE)

        def _refuse(*_a, **_k):
            raise ValueError("refusing to record an incomplete observed_baseline analyze scope as complete")

        monkeypatch.setattr(analyze_scope, "encode_analyze_scope_v2", _refuse)
        with pytest.raises(ValueError):
            ca.run_and_persist_medoid_baseline(
                con,
                store,
                run_id="run-baseline-orphan",
                backbone=_BACKBONE,
                song_ids=_SONGS,
                artists=_ARTISTS,
                k=10,
                evaluation_corpus=ident,
                catalog_id="catalog-1",
                catalog_fingerprint="cf" * 16,
            )
        # Zero aggregate rows under the medoid key (write_analyze_metrics must never have run).
        assert (
            con.execute(
                "SELECT count(*) FROM analyze_metrics WHERE strategy_key=?",
                (medoid_key,),
            ).fetchone()[0]
            == 0
        )
        # No scope line recorded for the run (record_analyze_run_scope must never have run).
        assert analyze_scope.run_row_scopes(con, run_id="run-baseline-orphan") == frozenset()
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 6. Exact population reuse across classes + whole-song baseline               #
# --------------------------------------------------------------------------- #


def test_segmented_passes_and_baseline_reuse_the_same_identity_population(compact_catalog_factory, con, tmp_path):
    # Two DISTINCT search classes (0.9/1.0 collapse into one; 0.2 segments differently -> second).
    harness = _build(
        compact_catalog_factory,
        con,
        tmp_path / "out",
        catalog_song_ids=_SONGS,
        configs=[_cfg(0.9), _cfg(1.0), _cfg(0.2)],
    )
    try:
        from scripts.embedding_research.catalog_identity import collapse_search_representations

        classes = collapse_search_representations(harness.con)
        # Distinct thresholds segment these streams into MORE THAN ONE search class, so the identity
        # population is genuinely threaded across multiple distinct representations (not just one).
        assert len(classes) >= 2, f"expected multiple distinct search classes, got {len(classes)}"

        store = harness.stream_store
        ident = resolve_evaluation_corpus(harness.con, store, _SONGS, backbone=_BACKBONE)
        assert ident.eligible is True and ident.count == 4

        # Every distinct class pass consumes the SAME resolved population.
        for cls in classes:
            cfg = ca.CatalogAnalysisConfig(
                run_id=f"run-p1reuse-{cls.canonical_config_id}",
                backbone=_BACKBONE,
                song_ids=ident.song_ids,
                artists=dict(_ARTISTS),
                config_ids=cls.config_ids,
                evaluation_corpus=ident,
            )
            result = ca.analyze_catalog_corpus(store, harness.con, cfg, research_con=con)
            assert result.comparable is True
            assert result.evaluation_corpus is ident
            assert result.n_queries == len(ident.song_ids) == ident.count
            assert {pq.query_song_id for pq in result.per_query} == set(ident.song_ids)

        # The whole-song observed baseline consumes the SAME identity population (reuse, never a
        # separately-derived set) and stays finite.
        metrics = ca.analyze_medoid_baseline(
            store,
            backbone=_BACKBONE,
            song_ids=_SONGS,
            artists=_ARTISTS,
            k=10,
            evaluation_corpus=ident,
        )
        assert metrics is not None
        for value in metrics.values():
            assert np.isfinite(value)
    finally:
        harness.close()


def test_comparable_result_is_still_persisted(compact_catalog_factory, con, tmp_path):
    """The new writer guard must NOT reject a genuinely comparable (complete) result."""
    harness = _build(compact_catalog_factory, con, tmp_path / "out", catalog_song_ids=_SONGS)
    try:
        store = harness.stream_store
        ident = resolve_evaluation_corpus(harness.con, store, _SONGS, backbone=_BACKBONE)
        cfg = ca.CatalogAnalysisConfig(
            run_id="run-p1-complete",
            backbone=_BACKBONE,
            song_ids=ident.song_ids,
            artists=dict(_ARTISTS),
            evaluation_corpus=ident,
        )
        result = ca.analyze_catalog_corpus(store, harness.con, cfg, research_con=con)
        assert result.comparable is True and result.n_queries == 4
        sk = analyze_scope.write_catalog_analyze_rows(con, run_id="run-p1-complete", result=result)
        assert con.execute("SELECT count(*) FROM analyze_metrics WHERE strategy_key=?", (sk,)).fetchone()[0] > 0
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# P2-S1: requested population is the catalog-requested surface (independent of  #
# seg_meta / representation searchability).                                     #
# --------------------------------------------------------------------------- #


def test_catalog_requested_population_is_independent_of_seg_meta(compact_catalog_factory, con, tmp_path):
    """A fully-silent requested song stays in the requested surface (carried as missing).

    ``s4`` is requested and committed but fully silent -> it is a ``metadata_only``
    ``catalog_song`` leaf with NO ``seg_meta`` rows.  The requested population must still
    include it (resolved from the requested surface, not from ``seg_meta``), so the corpus
    resolution carries it as excluded ``missing`` evidence rather than silently dropping it.
    """
    silent = np.zeros(6, dtype=np.uint8)  # s4 fully silent
    harness = _build(
        compact_catalog_factory,
        con,
        tmp_path / "out",
        catalog_song_ids=_SONGS,
        masks={"s4": silent},
    )
    try:
        # Requested surface = every catalog_song leaf under a config of the backbone.
        requested = catalog_requested_song_ids(harness.con, _BACKBONE)
        assert requested == _SONGS  # s4 retained even though it produced no segments

        # s4 produced NO seg_meta rows but IS a metadata_only requested leaf.
        assert (
            harness.con.execute(
                "SELECT count(*) FROM seg_meta sm "
                "JOIN seg_config c ON c.config_id=sm.config_id "
                "WHERE c.backbone=? AND sm.song_id='s4'",
                (_BACKBONE,),
            ).fetchone()[0]
            == 0
        )

        ident = resolve_evaluation_corpus(harness.con, harness.stream_store, requested, backbone=_BACKBONE)
        # s4 (whole-song silent) is eligible-population-excluded but NOT dropped: it is
        # carried as missing evidence because it is part of the catalog-requested surface.
        assert ident.song_ids == ("s1", "s2", "s3")
        assert ident.missing_song_ids == ("s4",) and ident.missing_count == 1
        assert ident.count == 3 and ident.eligible is True
    finally:
        harness.close()


def test_whole_song_no_segment_song_stays_in_shared_corpus_and_degrades_only_the_representation(
    compact_catalog_factory, con, tmp_path
):
    """P2-S3: an eligible whole-song song with no representation segment medoid stays in the shared
    corpus; ONLY that representation becomes explicitly non-comparable.

    ``s4`` is requested, committed, and whole-song non-silent (eligible) but the cataloged
    representation has no segment medoid for it (s4 committed-but-not-cataloged).  The SHARED
    corpus identity still contains s4 and stays ``comparable`` (whole-song view); the
    representation that cannot carry s4 degrades to ``comparable == False`` with missing
    evidence, while the shared identity object is unchanged.
    """
    harness = _build(
        compact_catalog_factory,
        con,
        tmp_path / "out",
        catalog_song_ids=("s1", "s2", "s3"),
        stream_song_ids=_SONGS,
    )
    try:
        store = harness.stream_store
        ident = resolve_evaluation_corpus(harness.con, store, _SONGS, backbone=_BACKBONE)
        # s4 is committed + non-silent whole-song -> ELIGIBLE in the shared corpus.
        assert ident.song_ids == _SONGS and "s4" in ident.song_ids
        # Whole-song view is not degraded by any single representation losing a medoid.
        assert ident.eligible is True and ident.comparable is True

        cfg = ca.CatalogAnalysisConfig(
            run_id="run-p2-no-segment",
            backbone=_BACKBONE,
            song_ids=ident.song_ids,
            artists=dict(_ARTISTS),
            evaluation_corpus=ident,
        )
        result = ca.analyze_catalog_corpus(store, harness.con, cfg, research_con=con)
        # ONLY the representation is non-comparable; the shared identity is untouched.
        assert result.comparable is False
        assert result.missing_song_ids == ("s4",) and result.missing_count == 1
        assert result.evaluation_corpus is ident
        assert ident.song_ids == _SONGS and ident.comparable is True
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# P2-S2: the corpus resolver fails closed on a malformed committed mask.        #
# --------------------------------------------------------------------------- #


class _MalformedObservation:
    """Duck observation whose mask is whatever the test injects (no loader validation)."""

    def __init__(self, mask):
        self.stream = np.ones((6, 4), dtype=np.float32)
        self.mask = mask


class _MalformedMaskStore:
    def __init__(self, mask):
        self._mask = mask

    def load_committed_observation(self, _song_id, _backbone):
        return _MalformedObservation(self._mask)


@pytest.mark.parametrize(
    "bad_mask",
    [
        pytest.param(np.array([1, 0, 1], dtype=np.uint8), id="short"),
        pytest.param(np.array([1, 1, 1, 1, 1, 1, 1], dtype=np.uint8), id="long"),
        pytest.param(np.array([1, 1, 1, 1, 1, 1], dtype=np.int64), id="wrong-dtype"),
        pytest.param(np.array([[1, 1, 1, 1, 1, 1]], dtype=np.uint8), id="non-1D"),
        pytest.param(None, id="missing"),
    ],
)
def test_corpus_resolver_refuses_malformed_committed_mask(compact_catalog_factory, con, tmp_path, bad_mask):
    """The corpus eligibility seam requires an EXACT ``uint8[patch_count]`` committed mask.

    A short/wrong-length/wrong-dtype/non-1D/missing mask is a typed refusal (fail closed) —
    a shorter mask is NEVER interpreted with trailing whole-song patches searchable, and
    absence is never interpreted as no silence.
    """
    harness = _build(compact_catalog_factory, con, tmp_path / "out", catalog_song_ids=_SONGS)
    try:
        store = _MalformedMaskStore(bad_mask)
        with pytest.raises(ValueError):
            resolve_evaluation_corpus(harness.con, store, _SONGS, backbone=_BACKBONE)
    finally:
        harness.close()
