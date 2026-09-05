"""Catalog-first bounded retrieval analysis (Plan D, Phase 3 — P3-S1..P3-S4).

The PRIMARY retrieval-analysis path for the frozen-stream segmentation catalog.  It consumes
**catalog memberships** (``seg_meta`` medoid source indices, never copied threshold vectors) and a
**disposable gathered search view** (:mod:`scripts.embedding_research.search_views`), and scores
each query song against every candidate song's gathered medoid rows with the bounded exact scorer
(:func:`scripts.embedding_research.bounded_scoring.score_bounded_exact`).

This is the medoid-to-medoid primary path the design (DD R10/R11/R12) mandates.  It does NOT read
the legacy copied ``flat_vecs`` / ``binned_ptc`` / ``binned_ptc_heads`` / CTP caches — those remain
explicitly-labelled read-only **archival** compatibility paths for golden comparisons (see the
``cache.*`` module docstrings and P3-S3) and are never silently fallen back to here (no
"if catalog empty -> read archival" logic exists).

One analysis invocation ===
  * per-run view materialization (views ALWAYS regenerated; existence never authorizes reuse — Phase
    1 ``materialize_search_view`` gathers + rewrites every time),
   * a per-query-song scoring loop: for each candidate song, bounded-score the query song's medoid
     rows against that candidate song's medoid rows, with ``seg_meta.searchable_weight`` candidate
     weights attached (the compact normalized searchable weight
     ``searchable_count_g / total_searchable_song`` per the corrective M_g model — absorbed-outlier
     and mask-silent patches are EXCLUDED; this is the candidate-weight factor the scoring harness
     requires so all-ones is NOT equivalent on a weighted corpus),
  * independent retrieval-metric lenses (MAP@k / MRR / NDCG@k / Recall@k / artist discrimination)
    computed over the SAME per-query winner/score results,
  * a finite-only, run-scoped write of aggregate + per-song rows carrying corpus/config/score-variant
    identity (``view_content_hash``, config ids, score-variant name + ``SCORING_SEMANTICS_VERSION``).
    Non-finite values are rejected (``NonFiniteResultError``), never persisted.

Primary scoring semantics are preserved verbatim by the bounded scorer: ``max_per_candidate_segment``
+ ``first_index`` + ``retain_all_candidate_segments`` (P2).  Determinism and no cross-backbone
mixing are inherited from Phase 1 views (single-backbone corpus) and the deterministic scorer.

Run-scoping (P3-S4)
-------------------
``analyze_metrics`` carries a physical ``run_id`` column (added by the backup-first migration;
legacy rows carry ``run_id='legacy'``).  This module's results are written by
:func:`db.analyze_scope.write_catalog_analyze_rows`, the run-scoped writer which:
  * keys rows by a corpus/config/score-variant ``strategy_key`` and stamps each aggregate row with the
    run's physical ``run_id``.  Since the migration the table carries no PRIMARY KEY, so uniqueness is
    asserted at the application layer: writing a strategy scope REPLACES only that run's own
    ``(run_id, strategy scope)`` rows (delete-then-insert in the caller's transaction), never unrelated
    retained-run rows or legacy baseline/corpus rows,
  * records the run's output-row scope in ``run_provenance.output_artifact_hashes`` so cleanup/reset
    can identify exactly this run's rows,
  * never globally deletes ``analyze_metrics``.

The metric-lens mapping QA must validate
----------------------------------------
The legacy retrieval metrics operated on a full N x N similarity matrix.  The bounded primary path
produces per-query, per-candidate-*segment* winner/score results (R12).  This module computes, for a
query song, one ``max_per_candidate_segment`` value against each candidate song (query rows x that
candidate song's medoid rows); the per-query candidate-song ranking is sorted by those values and the
lenses are computed over that ranking with the same ranked-list arithmetic ``similarity`` uses.
This segment->song mapping and the per-candidate-song scoring loop are documented implementation
decisions for QA to validate against the DD and the Phase 4 oracle goldens.

Search-representation collapse scheduling (P1-S4 amendment)
-------------------------------------------------------------
Each analysis run recomputes, from the catalog's CURRENT rows, the transient
:class:`~scripts.embedding_research.catalog_identity.SearchRepresentationClass` equivalence classes
over the run's participating configs (single source of truth = ``collapse_search_representations``).
Only the canonical (lowest ``config_id``) rows of each class enter the query/candidate union: alias
rows are projected OUT of the materialized all-config view, so an alias NEVER triggers a second
materialization or scorer invocation and never duplicates candidate rows, weights, winners, retained
counts, or deltas.  Distinct classes keep the ordinary bounded query/candidate loop (the per-query
scorer call count is the number of logical query/candidate inputs, NOT per-config).

``CatalogAnalysisResult.config_ids`` is the sorted tuple of EVERY participating config (canonical +
aliases) while the transient ``representation_classes`` field reports each class's canonical id +
sorted aliases — no durable alias state.  ``n_candidate_rows`` and every ``PerQueryResult.candidate_keys``
count/reference canonical searchable medoid rows only (deterministically sorted); aliases inherit the
canonical class's identical score/winner/delta identity through the transient mapping.

Lazy catalog attach + typed refusal
-----------------------------------
``catalog`` may be a compact ``CatalogHandle``, its snapshot ``con``, OR a snapshot path.  A path is
opened read-only at run time and the handle closed when the analysis finishes; a connection is
validated to be a real compact catalog (typed :class:`CatalogRefusalError` on a missing/corrupt/
non-compact catalog or an absent backbone config surface).  There is NO stale fallback: analysis
fails closed rather than silently guessing on an unattachable catalog.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from scripts.embedding_research import bounded_scoring
from scripts.embedding_research import search_views as sv
from scripts.embedding_research.catalog import (
    compact_configs_by_backbone,
    compact_segments_by_config_song,
)
from scripts.embedding_research.catalog_identity import (
    SearchRepresentationClass,
    collapse_search_representations,
)
from scripts.embedding_research.search_views import SCORING_SEMANTICS_VERSION, SearchViewRecord

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "CatalogAnalysisConfig",
    "CatalogAnalysisResult",
    "CatalogRefusalError",
    "NonFiniteResultError",
    "PerQueryResult",
    "analyze_catalog_corpus",
    "candidate_weights_from_catalog",
    "materialize_corpus_view",
    "run_catalog_analysis",
]

_PRIMARY_SCORE_VARIANT = "max_per_candidate_segment"
_STRATEGY_TYPE = "catalog"


class NonFiniteResultError(ValueError):
    """A computed retrieval result was non-finite and was rejected (never persisted)."""


class CatalogRefusalError(ValueError):
    """Analysis refuses an unattachable/invalid catalog (missing, non-compact, or corrupt).

    Raised by the lazy-attach path when a snapshot path cannot be opened or a supplied
    connection is not a valid compact catalog for the run's backbone.  Analysis FAILS CLOSED
    with this typed refusal — there is never a silent/stale fallback to an older catalog or
    to a non-compact research connection.
    """


@dataclass(frozen=True)
class PerQueryResult:
    """The bounded winner/score result for ONE query song against the candidate corpus.

    ``score`` is the query's overall finite value (max over candidate songs of the bounded
    ``max_per_candidate_segment``).  ``candidate_scores`` maps each candidate song id -> that song's
    bounded ``max_per_candidate_segment`` value (finite).  ``candidate_keys`` is the union of scored
    candidate row-address provenance; ``winner_counts`` credits winning query-source rows.
    """

    query_song_id: str
    score: float
    winner_counts: dict[int, float]
    candidate_scores: Mapping[str, float]
    candidate_keys: tuple[tuple[int, str, int, int], ...]
    retained_count: int
    dropped_count: int
    variant: str

    def all_finite(self) -> bool:
        return np.isfinite(self.score) and all(np.isfinite(v) for v in self.candidate_scores.values())


@dataclass
class CatalogAnalysisConfig:
    """Configuration for one catalog-first analysis run.

    * ``run_id`` — the analysis run anchoring views/provenance/output rows.
    * ``backbone`` — single-backbone corpus (views are single-backbone; no cross-backbone mixing).
    * ``song_ids`` — the sorted candidate corpus.  Each song is scored as a query against every other
      (leave-one-out corpus retrieval).
    * ``artists`` — per-song ground-truth artist labels (song_id -> label).  These are inputs to the
      *lens layer* (relevance); they are independent of how medoid vectors are gathered.
    * ``config_ids`` — config surface (empty = every canonical config of the backbone).
    * ``k`` — retrieval cut-off for the lenses.
    * ``working_memory`` — bounded-memory byte budget (view build + each bounded score).
    * ``score_variant``/``tie_policy``/``collision_policy`` — primary scoring semantics (defaults
      reproduce the primary ``max_per_candidate_segment`` path exactly).
    """

    run_id: str
    backbone: str
    song_ids: tuple[str, ...]
    artists: Mapping[str, str]
    config_ids: tuple[int, ...] = ()
    k: int = 10
    working_memory: int = 32 * 1024 * 1024
    score_variant: str = _PRIMARY_SCORE_VARIANT
    tie_policy: str = "first_index"
    collision_policy: str = "retain_all_candidate_segments"


@dataclass
class CatalogAnalysisResult:
    """The finite, run-scoped output of :func:`run_catalog_analysis`.

    ``metrics`` is the aggregate lens dict (finite-only); ``per_song`` maps each scored query song id
    -> its per-song finite lens values; ``per_query`` is the underlying bounded per-query result set
    (the SAME inputs every lens was computed over).  ``strategy_key`` / ``view_content_hash`` /
    ``config_ids`` / ``score_variant`` / ``scoring_semantics_version`` carry the output-row identity.

    ``config_ids`` is the sorted tuple of EVERY participating config (canonical + aliases) and
    ``representation_classes`` the transient (non-persisted) per-run collapse: each class reports its
    canonical (lowest) ``config_id`` plus sorted aliases.  ``n_candidate_rows`` counts the unique
    CANONICAL searchable medoid rows that enter the query/candidate union (alias rows are excluded).
    ``finite`` is always True (any non-finite value raises :class:`NonFiniteResultError` first).
    """

    run_id: str
    backbone: str
    config_ids: tuple[int, ...]
    representation_classes: tuple[SearchRepresentationClass, ...]
    k: int
    view_content_hash: str
    score_variant: str
    scoring_semantics_version: int
    strategy_key: str
    finite: bool
    metrics: dict[str, float]
    per_song: dict[str, dict[str, float]]
    per_query: tuple[PerQueryResult, ...]
    n_queries: int
    n_candidate_rows: int


# --------------------------------------------------------------------------- #
# Candidate weights from the catalog                                           #
# --------------------------------------------------------------------------- #


def candidate_weights_from_catalog(catalog, rows: Sequence[tuple[int, str, int, int]]) -> np.ndarray:
    """Per-row candidate weights aligned to *rows* (compact ``seg_meta.searchable_weight``).

    ``rows`` are view ``row_addresses`` ``(config_id, song_id, seg_id, medoid_source_patch_idx)``.
    Each row's candidate weight is that segment's compact ``seg_meta.searchable_weight``
    (``searchable_count_g / total_searchable_song`` per the corrective M_g model) — the exact
    candidate-weight factor the analysis handoff requires.  Reads the COMPACT ``seg_meta`` rows
    (P1-S6(a) ``compact_segments_by_config_song``); ``catalog`` is the compact snapshot
    connection/CatalogHandle.  Raises if a row's compact seg_meta is absent (corrupt/partial).
    """
    con = getattr(catalog, "con", catalog)
    weights = np.empty(len(rows), dtype=np.float32)
    for i, (config_id, song, seg_id, _medoid) in enumerate(rows):
        metas = compact_segments_by_config_song(con, int(config_id), song)
        matched = [m for m in metas if int(m.seg_id) == int(seg_id)]
        if not matched:
            raise ValueError(
                f"no compact seg_meta for candidate row ({config_id!r},{song!r},{seg_id!r}) — cannot attach weight"
            )
        weights[i] = float(matched[0].searchable_weight)
    return weights


def _load_vectors(store, record: SearchViewRecord) -> np.ndarray:
    """Load the on-disk float32 gathered vectors for a materialized view (row i == row_addresses[i])."""
    path = store.output_root / record.view_ref / "vectors.npy"
    return np.load(path, allow_pickle=False)


def materialize_corpus_view(store, catalog, cfg: CatalogAnalysisConfig, *, research_con=None) -> SearchViewRecord:
    """Materialize the (always-regenerated) disposable corpus view for *cfg*.

    One view per analysis run over the full single-backbone corpus.  Phase 1 enforces regeneration; a
    prior view file never short-circuits gathering.  Returns the recorded :class:`SearchViewRecord`.
    ``catalog`` is the COMPACT snapshot connection/CatalogHandle (catalog reads only) and ``store`` the
    ``StreamStore`` bound to the frozen streams; ``sv.materialize_search_view`` gathers + writes the
    disposable payload.  When ``research_con`` (the research connection whose ``run_provenance``
    receives the view-ref line) is given, the view is recorded there via :func:`sv.record_search_view`
    (materialization itself never records provenance).
    """
    record = sv.materialize_search_view(
        catalog,
        store,
        song_ids=cfg.song_ids,
        backbone=cfg.backbone,
        run_id=cfg.run_id,
        working_memory=cfg.working_memory,
    )
    if research_con is not None:
        sv.record_search_view(research_con, record, run_id=cfg.run_id)
    return record


def _song_rows(addrs, vectors) -> dict[str, tuple[list[int], np.ndarray]]:
    """song_id -> (row positions, their medoid vectors) for every song present in *addrs*."""
    pos = _positions_by_song(addrs)
    return {song: (idx, vectors[idx]) for song, idx in pos.items()}


def _score_query_vs_song(
    cfg: CatalogAnalysisConfig,
    query_vectors: np.ndarray,
    query_weights: np.ndarray,
    candidate_song_vectors: np.ndarray,
    candidate_weights: np.ndarray,
    candidate_keys: tuple[tuple[int, str, int, int], ...],
) -> tuple[float, dict[int, float], int, int]:
    """Boundedly score one query song against ONE candidate song's gathered medoid rows."""
    result = bounded_scoring.score_bounded_exact(
        query_vectors=query_vectors,
        query_weights=query_weights,
        candidate_view=bounded_scoring.ScoringCandidateView(
            vectors=candidate_song_vectors,
            row_addresses=candidate_keys,
            candidate_weights=candidate_weights,
        ),
        working_memory=cfg.working_memory,
        tie_policy=cfg.tie_policy,
        collision_policy=cfg.collision_policy,
    )
    if not result.finite or not np.isfinite(result.score):
        raise NonFiniteResultError("query vs candidate produced a non-finite bounded score; refusing to persist")
    return (
        float(result.score),
        {int(k): float(v) for k, v in result.winner_counts.items()},
        result.retained_count,
        result.dropped_count,
    )


# --------------------------------------------------------------------------- #
# Lazy catalog attach + transient collapse                                     #
# --------------------------------------------------------------------------- #


def _attach_catalog(catalog):
    """Resolve *catalog* to its compact snapshot connection, opening a path if given.

    ``catalog`` may be a compact ``CatalogHandle``, its snapshot ``con`` (duck-typed via
    ``getattr(catalog, "con", catalog)``), or a snapshot path (``str`` / ``os.PathLike``).  A path is
    opened READ-ONLY at run time (lazy attach); the returned owned handle must be closed by the
    caller when the analysis finishes.  Returns ``(con, owned_handle_or_None)``.  A path that cannot
    be opened raises :class:`CatalogRefusalError` (typed refusal — never a stale fallback).
    """
    if isinstance(catalog, (str, os.PathLike)):
        from scripts.embedding_research.catalog_storage import open_snapshot_file

        try:
            handle = open_snapshot_file(catalog, read_only=True)
        except Exception as exc:  # missing / corrupt / unreadable snapshot
            raise CatalogRefusalError(f"cannot open compact catalog snapshot {catalog!r}: {exc}") from exc
        return handle.con, handle
    con = getattr(catalog, "con", catalog)
    return con, None


def _validate_catalog(con, backbone: str) -> None:
    """Fail closed with a typed :class:`CatalogRefusalError` when *con* is not an attachable compact catalog.

    Checks the compact ``seg_config`` table is present and the run's backbone has a config surface.
    A non-compact connection, a corrupt/unqueryable catalog, or an absent backbone surface refuses
    rather than silently proceeding with empty/stale data.
    """
    from scripts.embedding_research.catalog_storage import SEG_CONFIG_TABLE

    try:
        tables = {str(r[0]) for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    except Exception as exc:
        raise CatalogRefusalError(
            f"compact catalog unavailable ({exc}); analysis refuses rather than guessing"
        ) from exc
    if SEG_CONFIG_TABLE not in tables:
        raise CatalogRefusalError(
            f"catalog is not an attachable compact catalog (missing {SEG_CONFIG_TABLE} table); no stale fallback"
        )
    if not compact_configs_by_backbone(con, backbone):
        raise CatalogRefusalError(f"compact catalog has no seg_config rows for backbone {backbone!r}")


def _participating_config_ids(con, cfg: CatalogAnalysisConfig) -> tuple[int, ...]:
    """Every config participating in *cfg* (the pinned ``config_ids`` or the backbone surface), sorted."""
    resolved = cfg.config_ids or _resolved_config_ids(con, cfg.backbone)
    return tuple(sorted(int(c) for c in resolved))


def _analysis_representation_classes(con, cfg: CatalogAnalysisConfig) -> tuple[SearchRepresentationClass, ...]:
    """The run's transient collapse of *cfg*'s participating configs into current equivalence classes.

    Single source of truth is :func:`catalog_identity.collapse_search_representations` recomputed
    from the catalog's CURRENT rows; members are restricted to the participating configs, each class
    keeps its canonical (lowest) ``config_id`` and sorted aliases, and classes are ordered by
    canonical ``config_id``.  Nothing is persisted here — the mapping is purely transient.
    """
    participating = set(_participating_config_ids(con, cfg))
    classes: list[SearchRepresentationClass] = []
    for cls in collapse_search_representations(con):
        members = tuple(sorted(c for c in cls.config_ids if c in participating))
        if members:
            classes.append(SearchRepresentationClass(cls.search_representation_hash, members[0], members))
    classes.sort(key=lambda c: c.canonical_config_id)
    return tuple(classes)


def _canonical_row_mask(record: SearchViewRecord, canonical_ids) -> np.ndarray:
    """Boolean keep-mask over *record* rows selecting ONLY the canonical configs' rows.

    Alias rows (canonical-id NOT in *canonical_ids*) are projected out so they never enter the
    query/candidate union, weights, winners, retained counts, or deltas.
    """
    return np.asarray([row[0] in canonical_ids for row in record.row_addresses], dtype=bool)


def _positions_by_song(addrs) -> dict[str, list[int]]:
    """song_id -> ascending row positions in the (projected) address list."""
    out: dict[str, list[int]] = {}
    for i, row in enumerate(addrs):
        out.setdefault(row[1], []).append(i)
    return out


# --------------------------------------------------------------------------- #
# Top-level driver                                                             #
# --------------------------------------------------------------------------- #


def run_catalog_analysis(store, catalog, cfg: CatalogAnalysisConfig, *, research_con=None) -> CatalogAnalysisResult:
    """Run the catalog-first bounded analysis for *cfg* and return a finite run-scoped result.

    Orchestrates: lazily attach + validate the catalog -> materialize the disposable all-config corpus
    view ONCE -> project to the canonical rows of each transient :class:`SearchRepresentationClass`
    (aliases never duplicate rows or trigger extra materialization/scoring) -> for each query song,
    bounded-score it against each canonical other-song candidate (once per logical input) with compact
    ``seg_meta.searchable_weight`` weights -> compute the lenses over the identical per-query results
    -> return the finite aggregate + per-song result.  ``catalog`` is a compact CatalogHandle / its
    snapshot ``con``, OR a snapshot path (opened read-only at run time and closed here).
    ``research_con`` (the research connection for the view's ``run_provenance.view_refs``) is
    forwarded to the materializer.
    """
    con, owned = _attach_catalog(catalog)
    try:
        return _run_attached_analysis(store, con, cfg, research_con=research_con)
    finally:
        if owned is not None:
            owned.close()


def _run_attached_analysis(store, con, cfg: CatalogAnalysisConfig, *, research_con=None) -> CatalogAnalysisResult:
    """Run the analysis against an attached (validated) compact catalog connection ``con``."""
    _validate_catalog(con, cfg.backbone)
    record = materialize_corpus_view(store, con, cfg, research_con=research_con)
    vectors = _load_vectors(store, record)

    # Per-run transient collapse (canonical = lowest config_id; alias rows projected out).
    classes = _analysis_representation_classes(con, cfg)
    participating = _participating_config_ids(con, cfg)
    canonical_ids = frozenset(c.canonical_config_id for c in classes)
    keep = _canonical_row_mask(record, canonical_ids)
    p_addrs = tuple(addr for addr, k in zip(record.row_addresses, keep, strict=True) if k)
    p_vecs = vectors[keep]

    if not p_addrs:
        raise CatalogRefusalError(
            f"no canonical searchable medoid rows for backbone {cfg.backbone!r} after collapse "
            f"(participating configs={participating}); analysis refuses"
        )
    # Candidate weights are the raw compact ``seg_meta.searchable_weight`` per CANONICAL row
    # (single source: candidate_weights_from_catalog), NOT the view's normalized set — this keeps
    # the weight seam consistent with the pre-collapse scheduler and the poisoned-weight rejection
    # path (a poisoned canonical weight is caught before persistence).
    p_weights = candidate_weights_from_catalog(con, p_addrs)
    song_rows = _song_rows(p_addrs, p_vecs)
    # Searchable songs only: a zero-searchable (metadata-only) song has no canonical medoid rows and
    # is excluded from both the query set and the candidate set (never an error).
    searchable = [s for s in cfg.song_ids if s in song_rows]
    if not searchable:
        raise NonFiniteResultError(
            "no searchable (medoid-bearing) songs among cfg.song_ids under the canonical configs; "
            "a metadata-only (zero-searchable) corpus has no candidates to score"
        )

    cand_pos_by_song = {s: song_rows[s][0] for s in searchable}
    per_query: list[PerQueryResult] = []
    for query_song in sorted(searchable):
        q_pos, q_vecs = song_rows[query_song]
        q_w = p_weights[q_pos]
        cand_scores: dict[str, float] = {}
        all_cand_keys: list[tuple[int, str, int, int]] = []
        total_retained = total_dropped = 0
        merged_winners: dict[int, float] = {}
        for cand_song in sorted(searchable):
            if cand_song == query_song:
                continue
            c_pos = cand_pos_by_song[cand_song]
            keys = tuple(p_addrs[i] for i in c_pos)
            all_cand_keys.extend(keys)
            score, winners, retained, dropped = _score_query_vs_song(
                cfg,
                q_vecs,
                q_w,
                p_vecs[c_pos],
                p_weights[c_pos],
                keys,
            )
            cand_scores[cand_song] = score
            for src, cnt in winners.items():
                merged_winners[src] = merged_winners.get(src, 0.0) + cnt
            total_retained += retained
            total_dropped += dropped
        if not cand_scores:
            continue
        top = max(cand_scores.values())
        if not np.isfinite(top):
            raise NonFiniteResultError(f"query {query_song!r} non-finite top candidate score")
        per_query.append(
            PerQueryResult(
                query_song_id=query_song,
                score=top,
                winner_counts=merged_winners,
                candidate_scores=cand_scores,
                candidate_keys=tuple(sorted(all_cand_keys)),
                retained_count=total_retained,
                dropped_count=total_dropped,
                variant=cfg.score_variant,
            )
        )

    lenses = _Lenses(cfg)
    metrics, per_song = lenses.evaluate(per_query)
    return CatalogAnalysisResult(
        run_id=cfg.run_id,
        backbone=cfg.backbone,
        config_ids=participating,
        representation_classes=classes,
        k=cfg.k,
        view_content_hash=record.content_hash,
        score_variant=cfg.score_variant,
        scoring_semantics_version=SCORING_SEMANTICS_VERSION,
        strategy_key=_strategy_key(cfg, record),
        finite=True,
        metrics=metrics,
        per_song=per_song,
        per_query=tuple(per_query),
        n_queries=len(per_query),
        n_candidate_rows=len(p_addrs),
    )


def analyze_catalog_corpus(store, catalog, cfg: CatalogAnalysisConfig, *, research_con=None) -> CatalogAnalysisResult:
    """Facade returning the finite run-scoped catalog-first analysis result (see run_catalog_analysis)."""
    return run_catalog_analysis(store, catalog, cfg, research_con=research_con)


def _strategy_key(cfg: CatalogAnalysisConfig, record: SearchViewRecord) -> str:
    """Corpus/config/score-variant row identity embedding the view keyset hash."""
    return f"catalog:{cfg.backbone}:{cfg.score_variant}:v{SCORING_SEMANTICS_VERSION}:{record.keyset_hash[:16]}"


def _resolved_config_ids(catalog, backbone: str) -> tuple[int, ...]:
    """Every canonical COMPACT ``seg_config`` id for *backbone* (sorted by config_id)."""
    con = getattr(catalog, "con", catalog)
    return tuple(r.config_id for r in compact_configs_by_backbone(con, backbone))


# --------------------------------------------------------------------------- #
# Independent retrieval-metric lenses                                         #
# --------------------------------------------------------------------------- #


class _Lenses:
    """Independent evaluation lenses over the SAME per-query winner/score results.

    Each lens is finite-only.  AP/MRR/NDCG/Recall mirror ``similarity``'s ranked-list arithmetic
    (deliberately NOT rewritten) over a per-query candidate-song ranking; discrimination is
    mean-within minus mean-cross of the per-song values.  Per-song lenses are computed first;
    aggregates are their means.  Any non-finite value raises :class:`NonFiniteResultError`.

    Mirror guarantees mirror ``similarity.compute_retrieval_metrics`` exactly: NDCG discounts a
    1-based top-ranked hit by log2(rank + 1) (== similarity's ``log2(r + 2)`` over 0-based ``r``,
    so a single top-ranked relevant song yields NDCG 1.0), and MRR scans the FULL ranking -- a first
    same-artist hit beyond ``k`` still contributes 1/rank, matching similarity's full-matrix MRR
    (never k-truncated).  AP@k and Recall@k stay k-bounded as in similarity.
    """

    def __init__(self, cfg: CatalogAnalysisConfig) -> None:
        self._cfg = cfg
        self._artist = dict(cfg.artists)

    def evaluate(self, per_query: Sequence[PerQueryResult]) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
        totals = {"map_k": 0.0, "mrr": 0.0, "ndcg_k": 0.0, "recall_k": 0.0}
        within_all: list[float] = []
        cross_all: list[float] = []
        per_song: dict[str, dict[str, float]] = {}
        n = 0
        for pq in per_query:
            sm = self._per_song_metrics(pq)
            if sm is None:
                continue
            per_song[pq.query_song_id] = sm
            n += 1
            for key in totals:
                totals[key] += float(sm[key])
            within_all.append(float(sm["within"]))
            cross_all.append(float(sm["cross"]))

        if n == 0:
            raise NonFiniteResultError("no query produced finite, relevance-bearing results")

        metrics: dict[str, float] = {}
        for key, total in totals.items():
            metrics[key] = total / n
            _require_finite(metrics[key], f"aggregate {key}")
        disc = float(np.mean(within_all)) - float(np.mean(cross_all))
        _require_finite(disc, "disc_artist")
        metrics["disc_artist"] = disc
        metrics["disc_score"] = disc  # back-compat alias == disc_artist (per similarity contract)
        return metrics, per_song

    def _per_song_metrics(self, pq: PerQueryResult) -> dict[str, float] | None:
        k = self._cfg.k
        qartist = self._artist.get(pq.query_song_id)
        if qartist is None:
            raise NonFiniteResultError(f"no artist label for query {pq.query_song_id!r}; cannot lens")
        # Rank candidate songs by bounded max_per_candidate_segment (desc), tie-break by song id.
        ranked = sorted(pq.candidate_scores.items(), key=lambda kv: (-float(kv[1]), kv[0]))
        rel = [s for s, _v in ranked if s != pq.query_song_id and self._artist.get(s) == qartist]
        if not rel:
            return None  # no same-artist candidate -> relevance lens undefined for this query
        # AP@k
        hits = 0
        ap = 0.0
        for rank, (song, _v) in enumerate(ranked[:k], start=1):
            if song != pq.query_song_id and self._artist.get(song) == qartist:
                hits += 1
                ap += hits / rank
        ap /= min(k, len(rel))
        # MRR — over the FULL ranking (not k-truncated), mirroring ``similarity``'s
        # compute_retrieval_metrics reciprocal-rank: a first same-artist hit beyond k
        # still counts (1/rank), exactly as the legacy full-matrix MRR does.
        mrr = 0.0
        for rank, (song, _v) in enumerate(ranked, start=1):
            if song != pq.query_song_id and self._artist.get(song) == qartist:
                mrr = 1.0 / rank
                break
        # NDCG@k / Recall@k
        ndcg = _ndcg_at_k(ranked, k, qartist, self._artist, pq.query_song_id)
        rec_hits = sum(1 for song, _v in ranked[:k] if song != pq.query_song_id and self._artist.get(song) == qartist)
        rec = rec_hits / min(k, len(rel))
        within = [
            v
            for song, v in pq.candidate_scores.items()
            if song != pq.query_song_id and self._artist.get(song) == qartist
        ]
        cross = [
            v
            for song, v in pq.candidate_scores.items()
            if song != pq.query_song_id and self._artist.get(song) != qartist
        ]
        values = {
            "map_k": float(ap),
            "mrr": float(mrr),
            "ndcg_k": float(ndcg),
            "recall_k": float(rec),
            "within": float(np.mean(within)) if within else 0.0,
            "cross": float(np.mean(cross)) if cross else 0.0,
        }
        for key, value in values.items():
            _require_finite(value, f"{pq.query_song_id}.{key}")
        return values


def _ndcg_at_k(ranked, k: int, qartist: str, artists: Mapping[str, str], query_song_id: str) -> float:
    """NDCG@k over same-artist relevance (mirrors ``similarity``'s discounted-gain arithmetic).

    Discount is 1/log2(rank + 1) for 1-based ``rank`` -- equivalent to ``similarity``'s
    ``h / log2(r + 2)`` for 0-based ``r``, so a single top-ranked relevant song is NDCG 1.0.
    """
    dcg = 0.0
    for rank, (song, _v) in enumerate(ranked[:k], start=1):
        if song != query_song_id and artists.get(song) == qartist:
            dcg += 1.0 / np.log2(rank + 1)
    rel_total = sum(1 for s, a in artists.items() if s != query_song_id and a == qartist)
    n_rel = min(k, rel_total)
    idcg = sum(1.0 / np.log2(r + 1) for r in range(1, n_rel + 1))
    return float(dcg / idcg) if idcg > 0 else 0.0


def _require_finite(value: float, name: str) -> None:
    if not np.isfinite(value):
        raise NonFiniteResultError(f"non-finite {name}={value!r}; refusing to persist")
