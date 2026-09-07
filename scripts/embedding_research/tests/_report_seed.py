"""Shared seeding helpers for the catalog-only report tests (research-only).

Builds active catalog ``analyze_metrics`` rows through the real analyze-scope catalog writer
(``db.analyze_scope.write_catalog_analyze_rows``) so the report tests exercise the true
persistence + provenance-scope path.
"""

from __future__ import annotations

import hashlib

from scripts.embedding_research.baseline import MEDOID_STRATEGY_TYPE, medoid_strategy_key_for
from scripts.embedding_research.catalog_identity import (
    EVALUATION_CORPUS_SEMANTICS_VERSION,
    EvaluationCorpusIdentity,
)
from scripts.embedding_research.common import catalog_analysis as _ca
from scripts.embedding_research.common.catalog_analysis import CatalogAnalysisResult
from scripts.embedding_research.db import write_analyze_metrics
from scripts.embedding_research.db.analyze_scope import (
    SCOPE_KIND_OBSERVED_BASELINE,
    AnalyzeScopeIdentity,
    ScopeMemberIdentity,
    record_analyze_run_scope,
    write_catalog_analyze_rows,
)

#: Fixture catalog anchor used by default so seeded catalog rows persist a full v2 identity
#: (the analyze-scope incomplete gate refuses to write a real class scope that lacks a catalog
#: anchor / semantic hash / ordered per-member thresholds).  Pass ``catalog_id=""`` to build a
#: genuinely identity-less structural fixture instead.
_FIXTURE_CATALOG_ID = "catalog-fixture-0000"
_FIXTURE_CATALOG_FINGERPRINT = "feedfacecafebeef00000000"
_FIXTURE_BIN_MODE = "temporal_global"
_FIXTURE_THRESHOLD = 0.5

#: A deterministic per-backbone evaluation-corpus identity shared by DEFAULT by both seed_catalog
#: and seed_medoid_baseline, so seeded segmented classes and their observed-medoid baselines carry
#: an EQUAL, comparable corpus identity and can form matched deltas under the matching-only gate
#: (the corrective hard cut removed the legacy identity-less structural-match fallback).  A caller
#: passes ``evaluation_corpus`` explicitly to override (e.g. unequal / non-comparable populations
#: to pin the incomplete surface); a genuinely identity-less structural class (``catalog_id=""``)
#: never receives the default corpus.
_FIXTURE_CORPUS_SONGS = ("song-0", "song-1", "song-2", "song-3")


def _fixture_corpus(backbone: str) -> EvaluationCorpusIdentity:
    return EvaluationCorpusIdentity(
        backbone=backbone,
        song_ids=_FIXTURE_CORPUS_SONGS,
        corpus_hash=hashlib.sha256(f"fixture-eval-corpus:{backbone}".encode()).hexdigest()[:16],
        count=len(_FIXTURE_CORPUS_SONGS),
        eligible=True,
        comparable=True,
        missing_song_ids=(),
        missing_count=0,
        missing_digest=None,
        semantics_version=EVALUATION_CORPUS_SEMANTICS_VERSION,
    )


def _fixture_semantic(config_ids: tuple[int, ...]) -> str:
    """Deterministic DURABLE SEMANTIC search-representation hash for a config membership.

    Stable per sorted config set (equal representations share one semantic) and never equal to any
    disposable keyset.  Fixture-only; real semantics come from ``catalog_identity``.
    """
    key = "fixture-configs:" + ",".join(str(c) for c in sorted(config_ids))
    return hashlib.sha256(key.encode()).hexdigest()


def _fixture_members(config_ids: tuple[int, ...]) -> tuple[ScopeMemberIdentity, ...]:
    """One ordered member record per config (configured==effective finite threshold, bin mode,
    exact segmentation hash)."""
    return tuple(
        ScopeMemberIdentity(
            config_id=int(c),
            threshold_configured=_FIXTURE_THRESHOLD,
            threshold_effective=_FIXTURE_THRESHOLD,
            bin_mode=_FIXTURE_BIN_MODE,
            exact_segmentation_hash=hashlib.sha256(f"fixture-member:{c}".encode()).hexdigest()[:16],
        )
        for c in sorted(config_ids)
    )


def _default_corpus(backbone: str, evaluation_corpus, *, structural: bool) -> EvaluationCorpusIdentity | None:
    """The evaluation-corpus identity to persist for a seeded row.

    An explicit ``evaluation_corpus`` wins; otherwise a non-structural row carries the shared
    per-backbone fixture corpus (so classes + their medoid baselines match); a genuinely
    identity-less structural row (``catalog_id=""``) carries none.
    """
    if evaluation_corpus is not None:
        return evaluation_corpus
    return None if structural else _fixture_corpus(backbone)


def make_catalog_result(
    *,
    run_id: str,
    backbone: str,
    strategy_key: str,
    k: int,
    metrics: dict[str, float],
    view_content_hash: str = "viewhash0",
    config_ids: tuple[int, ...] = (1,),
    score_variant: str = "max_per_candidate_segment",
    version: int = 1,
    evaluation_corpus=None,
    catalog_id: str = _FIXTURE_CATALOG_ID,
    catalog_fingerprint: str = _FIXTURE_CATALOG_FINGERPRINT,
    search_representation_hash: str | None = None,
    members: tuple | None = None,
    view_keyset_hash: str = "",
) -> CatalogAnalysisResult:
    """A minimal finite CatalogAnalysisResult with empty per-song / per-query lenses.

    Carries a FULL v2 identity by default: a fixture catalog anchor, a deterministic DURABLE
    SEMANTIC ``search_representation_hash`` (distinct from any disposable keyset) and ordered
    per-member records (configured/effective threshold + bin mode + exact segmentation hash) for
    every ``config_id``.  Pass ``catalog_id=""`` to build a genuinely identity-less structural
    fixture (no semantic / members / catalog anchor), e.g. to test that such a row renders
    visibly incomplete and its disposable keyset never becomes semantic.

    ``evaluation_corpus`` (an :class:`~scripts.embedding_research.catalog_identity.
    EvaluationCorpusIdentity`) is optional: when supplied the catalog writer persists it on the
    class's ``analyze_scope_v2`` provenance line, so the real loaders carry the identity to the
    delta builder.  ``None`` (the default) keeps the class's evaluation-corpus identity empty.
    """
    structural = not catalog_id
    effective_members = () if structural else (tuple(members) if members is not None else _fixture_members(config_ids))
    effective_semantic = (
        ""
        if structural
        else (search_representation_hash if search_representation_hash is not None else _fixture_semantic(config_ids))
    )
    effective_fingerprint = "" if structural else catalog_fingerprint
    return CatalogAnalysisResult(
        run_id=run_id,
        backbone=backbone,
        config_ids=config_ids,
        representation_classes=(),
        k=k,
        view_content_hash=view_content_hash,
        score_variant=score_variant,
        scoring_semantics_version=version,
        strategy_key=strategy_key,
        finite=True,
        metrics=metrics,
        per_song={},
        per_query=(),
        n_queries=0,
        n_candidate_rows=0,
        evaluation_corpus=evaluation_corpus,
        catalog_id=catalog_id,
        catalog_fingerprint=effective_fingerprint,
        search_representation_hash=effective_semantic,
        view_keyset_hash=view_keyset_hash,
        members=effective_members,
    )


def seed_catalog(
    con,
    *,
    run_id: str,
    backbone: str,
    strategy_key: str,
    k: int,
    metrics: dict[str, float],
    view_content_hash: str = "viewhash0",
    config_ids: tuple[int, ...] = (1,),
    score_variant: str = "max_per_candidate_segment",
    version: int = 1,
    evaluation_corpus=None,
    catalog_id: str = _FIXTURE_CATALOG_ID,
    catalog_fingerprint: str = _FIXTURE_CATALOG_FINGERPRINT,
    search_representation_hash: str | None = None,
    members: tuple | None = None,
    view_keyset_hash: str = "",
) -> str:
    """Persist one active catalog class through the real analyze-scope catalog writer.

    Defaults to a full v2 identity (see :func:`make_catalog_result`); pass ``catalog_id=""`` for
    a genuinely identity-less structural fixture.

    When ``evaluation_corpus`` is omitted the class carries the shared per-backbone fixture
    corpus (equal to the one :func:`seed_medoid_baseline` records), so a seeded class + its medoid
    baseline match under the matching-only delta gate.  ``evaluation_corpus`` may be passed to pin
    an unequal / non-comparable population instead.  A structural class (``catalog_id=""``)
    carries no evaluation-corpus identity.
    """
    result = make_catalog_result(
        run_id=run_id,
        backbone=backbone,
        strategy_key=strategy_key,
        k=k,
        metrics=metrics,
        view_content_hash=view_content_hash,
        config_ids=config_ids,
        score_variant=score_variant,
        version=version,
        evaluation_corpus=_default_corpus(backbone, evaluation_corpus, structural=not catalog_id),
        catalog_id=catalog_id,
        catalog_fingerprint=catalog_fingerprint,
        search_representation_hash=search_representation_hash,
        members=members,
        view_keyset_hash=view_keyset_hash,
    )
    return write_catalog_analyze_rows(con, run_id=run_id, result=result)


def seed_medoid_baseline(
    con,
    *,
    run_id: str,
    backbone: str,
    k: int,
    metrics: dict[str, float],
    evaluation_corpus=None,
    catalog_id: str = _FIXTURE_CATALOG_ID,
    catalog_fingerprint: str = _FIXTURE_CATALOG_FINGERPRINT,
) -> str:
    """Persist one observed global-medoid baseline row (run-scoped).

    The medoid baseline is persisted through the same real ``analyze_metrics`` writer the
    analyze producer uses (``db.write_analyze_metrics`` under ``strategy_type ==
    MEDOID_STRATEGY_TYPE`` == ``"global_pool"``, key ``global_pool:{backbone}:medoid``,
    ``sim_metric="cosine"``).  It is deliberately NOT a catalog class: no config identity.  It
    mirrors the analyze producer's baseline provenance (``run_and_persist_medoid_baseline``) by
    recording an ``analyze_scope_v2`` line TAGGED ``observed_baseline`` (scope_kind) carrying the
    fixture catalog anchor and its evaluation-corpus identity.  It is never an identity-less
    exemption.  When ``evaluation_corpus`` is omitted it records the shared per-backbone fixture
    corpus (equal to the one :func:`seed_catalog` records for a class of the same backbone), so a
    seeded baseline + class match under the matching-only delta gate.
    """
    key = medoid_strategy_key_for(backbone)
    efc = _default_corpus(backbone, evaluation_corpus, structural=False)
    write_analyze_metrics(
        con,
        key,
        MEDOID_STRATEGY_TYPE,
        "cosine",
        int(k),
        dict(metrics),
        run_id=run_id,
    )
    record_analyze_run_scope(
        con,
        run_id=run_id,
        identity=AnalyzeScopeIdentity(
            strategy_key=key,
            sim_metric="cosine",
            k=int(k),
            backbone=backbone,
            # Non-class observed baseline: explicitly TAGGED observed_baseline (scope_kind), never
            # an identity-less exemption (mirrors run_and_persist_medoid_baseline).  config_ids/
            # members/search_representation_hash stay empty BY THE TAG; the catalog anchor + score
            # semantics + optional evaluation-corpus identity are carried.
            scope_kind=SCOPE_KIND_OBSERVED_BASELINE,
            score_variant=_ca._PRIMARY_SCORE_VARIANT,
            scoring_semantics_version=_ca.SCORING_SEMANTICS_VERSION,
            catalog_id=catalog_id,
            catalog_fingerprint=catalog_fingerprint,
            evaluation_corpus_hash=efc.corpus_hash if efc is not None else None,
            evaluation_corpus_count=int(efc.count) if efc is not None else None,
            evaluation_corpus_comparable=bool(efc.comparable) if efc is not None else False,
            evaluation_corpus_missing_count=int(efc.missing_count) if efc is not None else 0,
            evaluation_corpus_missing_digest=(efc.missing_digest or "") if efc is not None else "",
            evaluation_corpus_semantics_version=(int(efc.semantics_version) if efc is not None else None),
            evaluation_corpus_eligible=bool(efc.eligible) if efc is not None else False,
            evaluation_corpus_eligible_digest=((efc.eligible_digest or "") if efc is not None else ""),
            evaluation_corpus_requested_count=(int(efc.requested_count) if efc is not None else None),
            evaluation_corpus_requested_digest=((efc.requested_digest or "") if efc is not None else ""),
            evaluation_corpus_observation_digest=((efc.observation_digest or "") if efc is not None else ""),
            evaluation_corpus_complete=bool(efc.completeness) if efc is not None else False,
            evaluation_corpus_integrity=((efc.integrity or "") if efc is not None else ""),
        ),
    )
    return key


def seed_phase_timing(con, *, run_ts: str = "run-1", phase: str = "analyze", elapsed_s: float = 1.5) -> None:
    from scripts.embedding_research.db._schema import upsert_phase_timing

    upsert_phase_timing(con, run_ts, phase, elapsed_s)


def catalog_key(backbone: str, keyset: str = "abc") -> str:
    """Build a well-formed active catalog strategy key for *backbone*."""
    return f"catalog:{backbone}:max_per_candidate_segment:v1:{keyset}"


#: Forbidden legacy vocabulary that must NEVER appear in an emitted report section/table id,
#: key, title, description, warning, or value (the hard-cut report contract).  ``global_pool`` is
#: NOT on this list: the observed ``global_pool:{backbone}:medoid`` baseline strategy key is a
#: legitimate emitted winner-section value under the medoid-baseline contract (the remaining
#: tokens — ptc/ctp/binned/truncation/optimizer/weighted/rep_a/rep_b/calibration — stay enforced;
#: see test_audit_forbidden_vocabulary.py for the source-audit gate, which is unchanged).
FORBIDDEN_REPORT_VOCABULARY: tuple[str, ...] = (
    "ptc",
    "ctp",
    "binned",
    "truncation",
    "optimizer",
    "weighted",
    "rep_a",
    "rep_b",
    "calibration",
    # Plan C P3-S2: removed analyze opt-in / pre-cut-migration surface + transitional back-compat /
    # deprecated phrasings + the removed disc_score alias must never appear in an emitted payload.
    "disc_score",
    "emit_medoid_baseline",
    "legacy_run_id",
    "migrate_analyze_metrics_provenance",
    "analyze_metrics_backup",
    "back-compat",
    "back_compat",
    "deprecated",
)


EXACT_SECTION_IDS: tuple[str, ...] = (
    "summary",
    "corpus",
    "analysis",
    "winners",
    "head-analysis",
    "provenance",
    "efficiency",
)


def assert_no_forbidden_vocabulary(payload: dict) -> None:
    """Assert no forbidden legacy token appears in any emitted text/key of the payload."""
    import json as _json

    text = _json.dumps(payload, default=str).lower()
    hits = [tok for tok in FORBIDDEN_REPORT_VOCABULARY if tok.lower() in text]
    assert not hits, f"forbidden report vocabulary emitted: {hits}"
