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
    rows against that candidate song's medoid rows, with ``seg_meta.weight`` candidate weights
    attached (weight == member_count incl. absorbed outliers, per Plan C — the Phase 2 handoff
    requires them to reproduce the oracle's candidate-weight factor; all-ones is NOT equivalent on a
    weighted corpus),
  * independent retrieval-metric lenses (MAP@k / MRR / NDCG@k / Recall@k / artist discrimination)
    computed over the SAME per-query winner/score results,
  * a finite-only, run-scoped write of aggregate + per-song rows carrying corpus/config/score-variant
    identity (``search_view_hash``, config ids, score-variant name + ``SCORING_SEMANTICS_VERSION``).
    Non-finite values are rejected (``NonFiniteResultError``), never persisted.

Primary scoring semantics are preserved verbatim by the bounded scorer: ``max_per_candidate_segment``
+ ``first_index`` + ``retain_all_candidate_segments`` (P2).  Determinism and no cross-backbone
mixing are inherited from Phase 1 views (single-backbone corpus) and the deterministic scorer.

Run-scoping (P3-S4)
-------------------
``analyze_metrics`` gains its ``run_id`` column in a LATER backup-first migration (Plan E).  Until
then this module's results are written by :func:`db.analyze_scope.write_catalog_analyze_rows`, the
pre-migration run-scoped writer which:
  * keys rows by a corpus/config/score-variant ``strategy_key`` embedding the view keyset hash, so an
    analysis run only touches the rows it owns (INSERT OR REPLACE replaces its own corpus/config rows;
    unrelated retained-run rows and baseline/corpus rows are never deleted),
  * records the run's output-row scope in ``run_provenance.output_artifact_hashes`` so the later
    reset migration can identify exactly this run's rows,
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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from scripts.embedding_research import bounded_scoring
from scripts.embedding_research import search_views as sv
from scripts.embedding_research.cache_identity import SCORING_SEMANTICS_VERSION
from scripts.embedding_research.catalog import configs_by_backbone, segments_by_config_song
from scripts.embedding_research.search_views import (
    AnalysisCorpus,
    QueryKeyset,
    SearchViewRecord,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "CatalogAnalysisConfig",
    "CatalogAnalysisResult",
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
    query_keyset: QueryKeyset = field(default_factory=QueryKeyset)

    def corpus(self) -> AnalysisCorpus:
        return AnalysisCorpus(backbone=self.backbone, song_ids=self.song_ids, config_ids=self.config_ids)


@dataclass
class CatalogAnalysisResult:
    """The finite, run-scoped output of :func:`run_catalog_analysis`.

    ``metrics`` is the aggregate lens dict (finite-only); ``per_song`` maps each scored query song id
    -> its per-song finite lens values; ``per_query`` is the underlying bounded per-query result set
    (the SAME inputs every lens was computed over).  ``strategy_key`` / ``search_view_hash`` /
    ``config_ids`` / ``score_variant`` / ``scoring_semantics_version`` carry the output-row identity.
    ``finite`` is always True (any non-finite value raises :class:`NonFiniteResultError` first).
    """

    run_id: str
    backbone: str
    config_ids: tuple[int, ...]
    k: int
    search_view_hash: str
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
    """Per-row candidate weights aligned to *rows* (``seg_meta.weight``, member-count semantics).

    ``rows`` are view ``row_addresses`` ``(config_id, song_id, seg_id, medoid_source_patch_idx)``.
    Each row's candidate weight is that segment's ``seg_meta.weight`` (== member_count incl. absorbed
    outliers, per Plan C) — the exact candidate-weight factor the Phase 2 oracle-equivalence handoff
    requires.  Raises if a row's seg_meta is absent (corrupt/partial catalog).
    """
    weights = np.empty(len(rows), dtype=np.float32)
    for i, (config_id, song, seg_id, _medoid) in enumerate(rows):
        metas = segments_by_config_song(catalog, int(config_id), song)
        matched = [m for m in metas if int(m.seg_id) == int(seg_id)]
        if not matched:
            raise ValueError(
                f"no seg_meta for candidate row ({config_id!r},{song!r},{seg_id!r}) — cannot attach weight"
            )
        weights[i] = float(matched[0].weight)
    return weights


def _load_vectors(store, record: SearchViewRecord) -> np.ndarray:
    """Load the on-disk float32 gathered vectors for a materialized view (row i == row_addresses[i])."""
    path = store.output_root / record.view_ref / "vectors.npy"
    return np.load(path, allow_pickle=False)


def materialize_corpus_view(store, catalog, cfg: CatalogAnalysisConfig) -> SearchViewRecord:
    """Materialize the (always-regenerated) disposable corpus view for *cfg*.

    One view per analysis run over the full single-backbone corpus.  Phase 1 enforces regeneration; a
    prior view file never short-circuits gathering.  Returns the recorded :class:`SearchViewRecord`.
    """
    return sv.materialize_search_view(
        store,
        catalog,
        cfg.corpus(),
        cfg.run_id,
        query_keyset=cfg.query_keyset,
        working_memory=cfg.working_memory,
    )


def _song_rows(record: SearchViewRecord, vectors: np.ndarray) -> dict[str, tuple[list[int], np.ndarray]]:
    """song_id -> (row positions, their medoid vectors) for every song present in the view."""
    out: dict[str, tuple[list[int], np.ndarray]] = {}
    pos: dict[str, list[int]] = {}
    for i, row in enumerate(record.row_addresses):
        pos.setdefault(row[1], []).append(i)
    for song, idx in pos.items():
        out[song] = (idx, vectors[idx])
    return out


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
# Top-level driver                                                             #
# --------------------------------------------------------------------------- #


def run_catalog_analysis(store, catalog, cfg: CatalogAnalysisConfig) -> CatalogAnalysisResult:
    """Run the catalog-first bounded analysis for *cfg* and return a finite run-scoped result.

    Orchestrates: materialize the corpus view -> for each query song, bounded-score it against each
    candidate song's medoid rows with ``seg_meta.weight`` candidate weights -> compute the independent
    retrieval lenses over the identical per-query results -> return the finite aggregate + per-song
    result (persisted by :func:`db.analyze_scope.write_catalog_analyze_rows`).
    """
    record = materialize_corpus_view(store, catalog, cfg)
    vectors = _load_vectors(store, record)
    song_rows = _song_rows(record, vectors)

    missing = [s for s in cfg.song_ids if s not in song_rows]
    if missing:
        raise NonFiniteResultError(f"songs have no medoid rows in the corpus view: {sorted(missing)}")

    all_weights = candidate_weights_from_catalog(catalog, record.row_addresses)
    # Group all candidate row positions per song.
    cand_pos_by_song: dict[str, list[int]] = {}
    for i, row in enumerate(record.row_addresses):
        if row[1] in cfg.song_ids:
            cand_pos_by_song.setdefault(row[1], []).append(i)

    per_query: list[PerQueryResult] = []
    for query_song in sorted(set(cfg.song_ids)):
        q_rows, q_vecs = song_rows[query_song]
        q_w = all_weights[q_rows]
        cand_scores: dict[str, float] = {}
        all_cand_keys: list[tuple[int, str, int, int]] = []
        total_retained = total_dropped = 0
        merged_winners: dict[int, float] = {}
        for cand_song in sorted(cfg.song_ids):
            if cand_song == query_song:
                continue
            c_rows = cand_pos_by_song[cand_song]
            keys = tuple(record.row_addresses[i] for i in c_rows)
            all_cand_keys.extend(keys)
            score, winners, retained, dropped = _score_query_vs_song(
                cfg,
                q_vecs,
                q_w,
                vectors[c_rows],
                all_weights[c_rows],
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
                candidate_keys=tuple(all_cand_keys),
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
        config_ids=tuple(sorted(cfg.config_ids or _resolved_config_ids(catalog, cfg.backbone))),
        k=cfg.k,
        search_view_hash=record.key.search_view_hash,
        score_variant=cfg.score_variant,
        scoring_semantics_version=SCORING_SEMANTICS_VERSION,
        strategy_key=_strategy_key(cfg, record),
        finite=True,
        metrics=metrics,
        per_song=per_song,
        per_query=tuple(per_query),
        n_queries=len(per_query),
        n_candidate_rows=len(cfg.song_ids),
    )


def analyze_catalog_corpus(store, catalog, cfg: CatalogAnalysisConfig) -> CatalogAnalysisResult:
    """Facade returning the finite run-scoped catalog-first analysis result (see run_catalog_analysis)."""
    return run_catalog_analysis(store, catalog, cfg)


def _strategy_key(cfg: CatalogAnalysisConfig, record: SearchViewRecord) -> str:
    """Corpus/config/score-variant row identity embedding the view keyset hash."""
    return f"catalog:{cfg.backbone}:{cfg.score_variant}:v{SCORING_SEMANTICS_VERSION}:{record.key.keyset_hash[:16]}"


def _resolved_config_ids(catalog, backbone: str) -> tuple[int, ...]:
    return tuple(r.config_id for r in configs_by_backbone(catalog, backbone) if r.alias_of_config_id is None)


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
