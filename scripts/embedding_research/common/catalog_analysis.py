"""Catalog-first bounded retrieval analysis (Plan D, Phase 3 — P3-S1..P3-S4).

The PRIMARY retrieval-analysis path for the frozen-stream segmentation catalog.  It consumes
**catalog memberships** (``seg_meta`` medoid source indices, never copied threshold vectors) and a
**disposable gathered search view** (:mod:`scripts.embedding_research.search_views`), and scores
each query song against every candidate song's gathered medoid rows with the bounded exact scorer
(:func:`scripts.embedding_research.bounded_scoring.score_bounded_exact`).

This is the medoid-to-medoid primary path the design (DD R10/R11/R12) mandates.  It reads only the
current catalog memberships (``seg_meta`` medoid source indices) and the disposable gathered search
view — the former copied ``flat_vecs`` / ``binned_ptc`` / ``binned_ptc_heads`` / CTP cache readers
were DELETED in the hard cut (execution-reporting-repair Plan C, Wave 2b), so no read-only archival
compatibility path and no "if catalog empty -> read archival" fallback exists anywhere in the tree.

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

Run-scoping (one current run-scoped schema)
-------------------------------------------
``analyze_metrics`` carries a physical ``run_id`` column with one current meaning (the run that
produced the row); there is no pre-cut / legacy partition.  This module's results are written by
:func:`db.analyze_scope.write_catalog_analyze_rows`, the run-scoped writer which:
  * keys rows by a corpus/config/score-variant ``strategy_key`` and stamps each aggregate row with the
    run's physical ``run_id`` (REQUIRED — supplied by the caller; no default).  The table carries no
    PRIMARY KEY, so uniqueness is asserted at the application layer: writing a strategy scope
    REPLACES only that run's own ``(run_id, strategy scope)`` rows (delete-then-insert in the
    caller's transaction), never unrelated / retained-run rows,
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

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from scripts.embedding_research import bounded_scoring
from scripts.embedding_research import search_views as sv
from scripts.embedding_research.catalog import (
    compact_configs_by_backbone,
    compact_segments_by_config_song,
)
from scripts.embedding_research.catalog_identity import (
    EvaluationCorpusIdentity,
    SearchRepresentationClass,
    collapse_search_representations,
    exact_segmentation_hash,
    song_ids_digest,
)
from scripts.embedding_research.catalog_identity import (
    catalog_fingerprint as _catalog_fingerprint,
)
from scripts.embedding_research.search_views import SCORING_SEMANTICS_VERSION, SearchViewRecord

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "AnalyzeRefusalError",
    "CatalogAnalysisConfig",
    "CatalogAnalysisResult",
    "CatalogRefusalError",
    "HeadSongLabel",
    "NonFiniteResultError",
    "PerQueryResult",
    "RulerLabelSource",
    "RulerResult",
    "analyze_catalog_corpus",
    "analyze_medoid_baseline",
    "analyze_medoid_baseline_rulers",
    "candidate_weights_from_catalog",
    "materialize_corpus_view",
    "resolve_head_ruler_labels",
    "run_and_persist_medoid_baseline",
    "run_catalog_analysis",
]

# --------------------------------------------------------------------------- #
# Independent-ruler label-source identity (Plan A P3-S1)                         #
# --------------------------------------------------------------------------- #

#: Label-source vocabulary (amended P3-S1: artist + genre read persisted
#: ``songs.artist`` / ``songs.genre``; head reads the frozen committed semantic-head
#: suite selected by the filesystem ``heads/current`` marker).  ``None``/blank values are
#: a MISSING label (a per-ruler exclusion), never substituted with a guessed label.
_ARTIST_SOURCE = "songs.artist"
_GENRE_SOURCE = "songs.genre"
#: Version of the artist/genre label-source contract (persisted DB columns).
_SONGS_LABEL_SOURCE_VERSION = "songs-table-v1"
#: Head label-source identity is the filesystem marker schema + EffNet committed suite.
_HEAD_SOURCE = "head:effnet:heads/current"
_HEAD_SOURCE_VERSION = "head-current-v1"


@dataclass(frozen=True)
class HeadSongLabel:
    """The frozen semantic-head label for ONE song (amended P3-S1 full-tuple ruler).

    ``full_tuple`` is the ordered ``((head_id, label_index), ...)`` tuple over EVERY
    canonical head in canonical sorted head-suite order; two songs are head-relevant
    exactly when their complete ordered tuples are identical.  ``labels`` exposes the
    canonical ``HEAD_LABELS[head][label_index]`` text aligned to ``full_tuple`` and
    ``pooled`` the finite pooled class-1 means aligned to ``full_tuple``.  The remaining
    fields retain the label-resolution EVIDENCE: marker/stream identity, mask identity,
    searchable-row count and head-set/version.

    A song carries a head label ONLY when every required head is present, binary
    (``dim == 2``), aligned, and its pooled value is finite.  Missing marker/suite/stream/
    mask/row evidence means the song has NO head label (excluded from the head ruler); a
    present non-finite activation raises ``NonFiniteResultError`` at resolution time.
    """

    song_id: str
    backbone: str
    full_tuple: tuple[tuple[str, int], ...]
    labels: tuple[str, ...]
    pooled: tuple[float, ...]
    searchable_rows: int
    head_set_fingerprint: str
    head_ids: str
    dim_by_head: str
    alignment_version: str
    stream_ref: str
    stream_digest: str
    mask_ref: str
    mask_digest: str
    commit_sha256: str


@dataclass(frozen=True)
class RulerLabelSource:
    """Deterministic label-source / evidence identity for ONE ruler (result-level).

    Carries the label source + contract version, the count of songs that resolve a label
    for the ruler (the ruler's population), the count of songs that did NOT (missing-label
    per-ruler exclusion), and a deterministic digest of the label map.  ``note`` carries
    ruler-specific evidence (e.g. the head-set/version / active head-suite identity).
    """

    source: str
    version: str
    song_count: int
    missing_count: int
    digest: str
    note: str = ""


@dataclass(frozen=True)
class RulerResult:
    """Aggregate retrieval-lens outcome for ONE independent ruler (result-level).

    ``active`` is False when the ruler had no evaluable query (its ``n_queries`` is 0 and
    the retrieval aggregates are undefined -> 0.0).  ``disc`` is the mean-within minus
    mean-cross discrimination value; for the head ruler it is the FINITE guarded ``0.0``
    (with the guard reason in ``disc_guard``) when the labeled population has fewer than
    two distinct full-tuple groups or either pair set is empty.  ``n_queries`` counts only
    ruler-evaluable queries after that ruler's missing-label and no-relevant-candidate
    exclusions.
    """

    ruler: str
    active: bool
    n_queries: int
    map_k: float
    mrr: float
    ndcg_k: float
    recall_k: float
    disc: float
    disc_guard: str = ""


_PRIMARY_SCORE_VARIANT = "max_per_candidate_segment"
_STRATEGY_TYPE = "catalog"
#: Sentinel row-address fields for a whole-song medoid representation (it has no catalog
#: config / structural segment of its own).  These keys never reach the persisted report.
_MEDOID_ROW_CONFIG_ID = -1
_MEDOID_SEG_ID = -1


class NonFiniteResultError(ValueError):
    """A computed retrieval result was non-finite and was rejected (never persisted)."""


class CatalogRefusalError(ValueError):
    """Analysis refuses an unattachable/invalid catalog (missing, non-compact, or corrupt).

    Raised by the lazy-attach path when a snapshot path cannot be opened or a supplied
    connection is not a valid compact catalog for the run's backbone.  Analysis FAILS CLOSED
    with this typed refusal — there is never a silent/stale fallback to an older catalog or
    to a non-compact research connection.
    """


class AnalyzeRefusalError(ValueError):
    """The analyze scope for a backbone refuses to run / cannot complete (fail-closed).

    Raised when a requested backbone cannot produce the MANDATORY observed
    ``global_pool:{backbone}:medoid`` baseline (its evaluation corpus is not analyzable, or
    fewer than two searchable medoid songs make the observed baseline undefined) so the
    analyze phase FAILS rather than presenting a successful baseline-less scope or a
    fabricated baseline vector.  The analyze runner surfaces this as a ``failed`` phase
    outcome (never a silent success).
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
    * ``evaluation_corpus`` — the backbone's resolved :class:`EvaluationCorpusIdentity` (optional).
      When set, ``song_ids`` MUST be this identity's eligible population and the pass compares each
      eligible song against this representation: an eligible song with no canonical searchable medoid
      row in THIS representation makes it non-comparable (missing-medoid invalidation), so no matched
      retrieval metric is emitted/persisted as complete.
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
    evaluation_corpus: EvaluationCorpusIdentity | None = None
    k: int = 10
    working_memory: int = 32 * 1024 * 1024
    score_variant: str = _PRIMARY_SCORE_VARIANT
    tie_policy: str = "first_index"
    collision_policy: str = "retain_all_candidate_segments"
    #: Independent-ruler label sources (amended P3-S1).  ``genres`` mirrors ``artists``
    #: from the persisted ``songs.genre`` column; ``head_labels`` maps song_id -> its
    #: frozen semantic-head :class:`HeadSongLabel`.  For every ruler a ``None``/blank value
    #: (or the ABSENCE of a ``head_labels`` entry) is a MISSING label -> that song is
    #: excluded from the ruler's query/candidate membership (never substituted).
    genres: Mapping[str, str] = field(default_factory=dict)
    head_labels: Mapping[str, HeadSongLabel] = field(default_factory=dict)


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

    When the run pinned an ``evaluation_corpus`` (``evaluation_corpus`` is set), ``comparable`` is
    True only when every eligible corpus song carries a canonical searchable medoid row in THIS
    representation; a representation that lost an eligible song (PTC absorption) is ``comparable ==
    False`` with the loss surfaced in ``missing_song_ids`` / ``missing_count`` / ``missing_digest``
    and NO matched retrieval metrics emitted (``metrics``/``per_song``/``per_query`` empty,
    ``n_queries == 0``) so the caller never persists a partial configuration as a complete outcome.

    A comparable real-catalog result also carries its durable SEMANTIC identity for the v2 scope
    writer: ``catalog_id``/``catalog_fingerprint`` (read from the compact ``catalog_metadata``
    singleton / :func:`catalog_identity.catalog_fingerprint`), the analyzed class's SEMANTIC
    ``search_representation_hash`` (:func:`catalog_identity.search_representation_hash` value of the
    analyzed search-representation class — NEVER the disposable view/keyset hash), the ordered
    per-member ``members`` records (``config_id`` + configured/effective threshold + ``bin_mode`` +
    ``exact_segmentation_hash``), and the DISPOSABLE per-run ``view_keyset_hash`` (the strategy-key
    keyset component) kept distinct from ``view_content_hash``.  A structural fixture result
    (``_report_seed`` / identity-less seed, no real catalog) leaves these fields at their empty
    defaults.
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
    evaluation_corpus: EvaluationCorpusIdentity | None = None
    comparable: bool = True
    missing_song_ids: tuple[str, ...] = ()
    missing_count: int = 0
    missing_digest: str | None = None
    catalog_id: str = ""
    catalog_fingerprint: str = ""
    search_representation_hash: str = ""
    view_keyset_hash: str = ""
    members: tuple = ()
    #: Independent-ruler aggregates + label-source/evidence identity (amended P3-S1),
    #: delivered at the RESULT level.  ``rulers`` maps ``"artist"`` / ``"genre"`` /
    #: ``"head"`` -> the ruler's :class:`RulerResult` (``n_queries`` per ruler).  At the RESULT
    #: level ``metrics`` / ``per_song`` ARE the ruler-suffixed artist vocabulary (``map_k_artist`` /
    #: ``mrr_artist`` / ``ndcg_k_artist`` / ``recall_k_artist`` / ``disc_artist``); ``rulers`` /
    #: ``ruler_sources`` carry the per-ruler aggregates + label-source identity.  These fields are
    #: the compute surface P3-S2 consumes.  Empty on a non-comparable result.
    rulers: dict[str, RulerResult] = field(default_factory=dict)
    ruler_sources: dict[str, RulerLabelSource] = field(default_factory=dict)


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
        config_ids=cfg.config_ids or None,
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


def _catalog_scope_identity(con, participating: tuple[int, ...], classes):
    """Durable v2 identity fields for a comparable analyzed class scope.

    Returns ``(catalog_id, catalog_fingerprint, semantic_hash, members)``.  ``semantic_hash`` is the
    analyzed class's ``catalog_identity.search_representation_hash`` value (NEVER the disposable
    view/keyset hash).  ``members`` are ``ScopeMemberIdentity`` records aligned to the sorted
    ``participating`` configs (configured/effective threshold + ``bin_mode`` from the compact
    ``seg_config`` row, plus each member's exact segmentation hash).  FAILS CLOSED: a real analyzed
    class whose compact catalog identity cannot be fully resolved (missing ``seg_config`` row for a
    participating config, missing ``catalog_metadata`` singleton, or unreadable fingerprint) raises
    rather than degrading to an empty/identity-less "apparently usable" result — the durable writer
    refuses an incomplete scope before any metric row is persisted.
    """
    from scripts.embedding_research.db.analyze_scope import ScopeMemberIdentity

    semantic_hash = ""
    participating_set = set(participating)
    for cls in classes:
        if set(cls.config_ids) == participating_set:
            semantic_hash = cls.search_representation_hash
            break
    else:
        if len(classes) == 1:
            semantic_hash = classes[0].search_representation_hash
    cfg_rows: dict[int, tuple] = {}
    for row in con.execute(
        "SELECT config_id, bin_mode, threshold_configured, threshold_effective FROM seg_config"
    ).fetchall():
        cfg_rows[int(row[0])] = row
    members = []
    for cid in participating:
        row = cfg_rows.get(cid)
        if row is None:
            raise ValueError(
                f"cannot derive complete analyze-scope identity: no compact seg_config row for "
                f"participating config_id {cid}"
            )
        exact = exact_segmentation_hash(con, cid)
        members.append(
            ScopeMemberIdentity(
                config_id=cid,
                threshold_configured=float(row[2]),
                threshold_effective=float(row[3]),
                bin_mode=str(row[1]),
                exact_segmentation_hash=exact,
            )
        )
    meta = con.execute("SELECT catalog_id, schema_version FROM catalog_metadata ORDER BY catalog_id LIMIT 1").fetchone()
    if meta is None:
        raise ValueError("cannot derive complete analyze-scope identity: compact catalog_metadata singleton missing")
    catalog_id = str(meta[0])
    catalog_fingerprint = _catalog_fingerprint(con, schema_version=int(meta[1]))
    if not catalog_id:
        raise ValueError("cannot derive complete analyze-scope identity: empty catalog_id")
    if not catalog_fingerprint:
        raise ValueError("cannot derive complete analyze-scope identity: empty catalog_fingerprint")
    return catalog_id, catalog_fingerprint, semantic_hash, tuple(members)


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
    if not cfg.config_ids and len(classes) > 1:
        # Distinct search representations must NEVER be unioned into one query/candidate pass.
        # Per-class scheduling is the caller's job (run.py loops classes and pins config_ids to a
        # single class's members each call).  An unpinned whole-backbone scope that spans multiple
        # distinct classes fails closed rather than silently merging them.
        raise CatalogRefusalError(
            f"backbone {cfg.backbone!r} participating configs collapse to {len(classes)} distinct "
            f"search representation classes (canonical ids "
            f"{[c.canonical_config_id for c in classes]}); schedule each class as its own retrieval "
            f"pass by pinning cfg.config_ids to a single class's members — distinct classes are "
            f"never unioned into one candidate pool"
        )
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
    corpus = cfg.evaluation_corpus
    if corpus is not None:
        # Per-representation comparability (missing-medoid invalidation — execution-reporting P1-S3):
        # every eligible whole-song song must still carry at least one canonical searchable medoid
        # row in THIS representation after collapse.  A song PTC absorption emptied (eligible whole
        # song but no searchable segment medoid here) makes the representation non-comparable: it
        # emits NO matched retrieval metric/delta, its structural evidence is the catalog rows
        # themselves (retained), and the loss is surfaced as missing-song evidence for the caller to
        # refuse persisting as a complete outcome.
        missing_songs = tuple(sorted(s for s in corpus.song_ids if s not in song_rows))
    else:
        missing_songs = ()
    comparable = not missing_songs
    if not comparable:
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
            metrics={},
            per_song={},
            per_query=(),
            n_queries=0,
            n_candidate_rows=len(p_addrs),
            evaluation_corpus=corpus,
            comparable=False,
            missing_song_ids=missing_songs,
            missing_count=len(missing_songs),
            missing_digest=song_ids_digest(missing_songs) if missing_songs else None,
        )

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
    rulers, ruler_sources = lenses.evaluate_rulers(per_query)
    # Amended P3-S2: the result's aggregate surface is the FINITE SUFFIXED vocabulary built from
    # the per-ruler results (never the bare generic keys).  The historical artist fail-closed
    # contract is preserved: a comparable class whose artist ruler produced NO relevance-bearing
    # query raises (no artist suffixed aggregates / per-song to emit) exactly as the bare path did.
    if not rulers["artist"].active:
        raise NonFiniteResultError("no query produced finite, relevance-bearing artist results")
    metrics = _suffixed_aggregate_metrics(rulers)
    _artist_ruler, per_song = lenses._reduce("artist", per_query, want_per_song=True)
    catalog_id, catalog_fingerprint, semantic_hash, member_records = _catalog_scope_identity(
        con, participating, classes
    )
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
        evaluation_corpus=corpus,
        comparable=True,
        missing_song_ids=(),
        missing_count=0,
        missing_digest=None,
        catalog_id=catalog_id,
        catalog_fingerprint=catalog_fingerprint,
        search_representation_hash=semantic_hash,
        view_keyset_hash=record.keyset_hash[:16],
        members=member_records,
        rulers=rulers,
        ruler_sources=ruler_sources,
    )


def analyze_catalog_corpus(store, catalog, cfg: CatalogAnalysisConfig, *, research_con=None) -> CatalogAnalysisResult:
    """Facade returning the finite run-scoped catalog-first analysis result (see run_catalog_analysis)."""
    return run_catalog_analysis(store, catalog, cfg, research_con=research_con)


def analyze_medoid_baseline(
    store,
    *,
    backbone: str,
    song_ids,
    artists,
    k: int = 10,
    working_memory: int = 32 * 1024 * 1024,
    evaluation_corpus: EvaluationCorpusIdentity | None = None,
    genres: Mapping[str, str] | None = None,
    head_labels: Mapping[str, HeadSongLabel] | None = None,
) -> dict[str, float] | None:
    """Score the observed global-medoid baseline for ``backbone`` and return its aggregate metrics.

    When ``evaluation_corpus`` is given, the baseline population is EXACTLY that identity's eligible
    ``song_ids`` (resolved once at the analyze boundary) — never re-derived from the raw ``song_ids``
    list or a later catalog.  Without it, the population is the committed/searchable subset of
    ``song_ids`` (legacy direct-call behavior).

    P1-S6 analyze-side PRODUCER: one additional scored retrieval per backbone that represents
    EACH cataloged searchable song by its observed whole-song ``global_pool:{backbone}:medoid``
    UNIT vector (selected from the song's committed observation group by
    ``baseline.observed_global_medoid_unit_vector`` over the committed ``mask == 1``
    population).  Zero-searchable songs (no medoid vector) are EXCLUDED from both the baseline
    population and candidate search.  It is NOT a catalog class: it never unions with class
    candidate pools, never alters per-class execution counts, and is never a winner candidate
    (downstream report keeps it out of candidacy).

    The scored pass reuses the SAME bounded scorer seam (``_score_query_vs_song``) and the SAME
    retrieval-metric lenses (:class:`_Lenses`) as the segmented class passes, over the SAME
    corpus, sim_metric (``cosine``) and ``k`` — so the emitted per-cell values (``map_k``,
    ``mrr``, ``ndcg_k``, ``recall_k``, ``disc_artist``) align EXACTLY with a
    segmented class's cell keys, which is what lets ``build_baseline_delta_rows`` do its
    exact-scope baseline/delta join.

    CPU-only (numpy + the bounded scorer); no durable cache, alias graph, synthetic/
    coordinate-wise medoid, or cross-backbone union.  Non-finite results raise
    :class:`NonFiniteResultError`.  Returns ``None`` when fewer than two searchable medoid
    songs make leave-one-out impossible (no baseline for that backbone) — the caller persists
    NOTHING in that case.
    """
    scored = _score_medoid_baseline(
        store,
        backbone=backbone,
        song_ids=song_ids,
        artists=artists,
        k=k,
        working_memory=working_memory,
        evaluation_corpus=evaluation_corpus,
        genres=genres,
        head_labels=head_labels,
    )
    if scored is None:
        return None
    cfg, per_query = scored
    rulers, _sources = _Lenses(cfg).evaluate_rulers(per_query)
    return _suffixed_aggregate_metrics(rulers)


def analyze_medoid_baseline_rulers(
    store,
    *,
    backbone: str,
    song_ids,
    artists,
    k: int = 10,
    working_memory: int = 32 * 1024 * 1024,
    evaluation_corpus: EvaluationCorpusIdentity | None = None,
    genres: Mapping[str, str] | None = None,
    head_labels: Mapping[str, HeadSongLabel] | None = None,
) -> tuple[dict[str, RulerResult], dict[str, RulerLabelSource]] | None:
    """Score the observed global-medoid baseline and return ALL THREE ruler aggregates.

    The observed whole-song medoid control carries the SAME three independent rulers (artist /
    genre / head) as the segmented class passes (amended P3-S1).  Returns ``(rulers, sources)``
    (each mapping ruler name -> its aggregate/source) or ``None`` when the baseline is not
    computable.  Compute-only — persistence of the per-ruler vocabulary is A2's surface.
    """
    scored = _score_medoid_baseline(
        store,
        backbone=backbone,
        song_ids=song_ids,
        artists=artists,
        k=k,
        working_memory=working_memory,
        evaluation_corpus=evaluation_corpus,
        genres=genres,
        head_labels=head_labels,
    )
    if scored is None:
        return None
    cfg, per_query = scored
    return _Lenses(cfg).evaluate_rulers(per_query)


def _score_medoid_baseline(
    store,
    *,
    backbone: str,
    song_ids,
    artists,
    k: int = 10,
    working_memory: int = 32 * 1024 * 1024,
    evaluation_corpus: EvaluationCorpusIdentity | None = None,
    genres: Mapping[str, str] | None = None,
    head_labels: Mapping[str, HeadSongLabel] | None = None,
) -> tuple[CatalogAnalysisConfig, list[PerQueryResult]] | None:
    """Shared observed-global-medoid scoring core used by the public baseline facades."""
    from scripts.embedding_research.baseline import observed_global_medoid_unit_vector
    from scripts.embedding_research.streams import StreamStoreError

    song_ids = tuple(song_ids)
    # The observed whole-song baseline MUST reuse the resolved corpus identity's eligible population
    # exactly when one is supplied (never a separately-derived population from a later view/catalog).
    population = tuple(evaluation_corpus.song_ids) if evaluation_corpus is not None else song_ids
    cfg = CatalogAnalysisConfig(
        run_id="",
        backbone=backbone,
        song_ids=population,
        artists=dict(artists),
        k=int(k),
        working_memory=working_memory,
        evaluation_corpus=evaluation_corpus,
        genres=dict(genres) if genres is not None else {},
        head_labels=dict(head_labels) if head_labels is not None else {},
    )
    # Gather each cataloged song's observed global medoid UNIT vector (exclude zero-searchable
    # songs and songs with no committed observation group).
    medoid_vectors: dict[str, np.ndarray] = {}
    for song in sorted(population):
        try:
            observation = store.load_committed_observation(song, backbone)
        except StreamStoreError:
            # No committed observation group -> the song is not searchable in this corpus
            # (metadata-only) -> no baseline vector, excluded from baseline + candidate search.
            continue
        vec = observed_global_medoid_unit_vector(observation)
        if vec is None:
            continue
        medoid_vectors[song] = vec
    searchable = sorted(medoid_vectors)
    if len(searchable) < 2:
        # Leave-one-out over a singleton/empty population is undefined -> no baseline.
        return None

    per_query: list[PerQueryResult] = []
    for query_song in searchable:
        q_vec = np.asarray(medoid_vectors[query_song], dtype=np.float32)[None, :]
        q_w = np.asarray([1.0], dtype=np.float32)
        cand_scores: dict[str, float] = {}
        all_keys: list[tuple[int, str, int, int]] = []
        for cand_song in searchable:
            if cand_song == query_song:
                continue
            c_vec = np.asarray(medoid_vectors[cand_song], dtype=np.float32)[None, :]
            keys = ((_MEDOID_ROW_CONFIG_ID, cand_song, _MEDOID_SEG_ID, 0),)
            score, _winners, _retained, _dropped = _score_query_vs_song(
                cfg, q_vec, q_w, c_vec, np.asarray([1.0], dtype=np.float32), keys
            )
            cand_scores[cand_song] = score
            all_keys.extend(keys)
        if not cand_scores:
            continue
        top = max(cand_scores.values())
        if not np.isfinite(top):
            raise NonFiniteResultError(f"query {query_song!r} non-finite medoid-baseline top candidate score")
        per_query.append(
            PerQueryResult(
                query_song_id=query_song,
                score=float(top),
                winner_counts={},
                candidate_scores=cand_scores,
                candidate_keys=tuple(all_keys),
                retained_count=0,
                dropped_count=0,
                variant=cfg.score_variant,
            )
        )
    if not per_query:
        return None
    return cfg, per_query


def run_and_persist_medoid_baseline(
    con,
    store,
    *,
    run_id: str,
    backbone: str,
    song_ids,
    artists,
    k: int = 10,
    working_memory: int = 32 * 1024 * 1024,
    evaluation_corpus: EvaluationCorpusIdentity | None = None,
    catalog_id: str = "",
    catalog_fingerprint: str = "",
    genres: Mapping[str, str] | None = None,
    head_labels: Mapping[str, HeadSongLabel] | None = None,
) -> dict[str, float] | None:
    """Score the observed global-medoid baseline and persist it run-scoped (the run.py seam).

    Convenience over :func:`analyze_medoid_baseline` that, when a baseline is computable
    (>= 2 searchable medoid songs), persists it as ``analyze_metrics`` rows under
    ``strategy_key == baseline.medoid_strategy_key_for(backbone)`` and the NON-``catalog``
    ``strategy_type == baseline.MEDOID_STRATEGY_TYPE`` (``"global_pool"``), run-scoped so a
    re-run replaces only its own rows.  The scope is recorded on the run's ``analyze``
    provenance (an ``analyze_scope_v2`` line carrying the evaluation-corpus identity when
    supplied, plus the catalog anchor ``catalog_id``/``catalog_fingerprint`` when the caller
    passes them) so every baseline row is tied to ONE explicit corpus — the baseline remains a
    NON-class ``global_pool`` row (never a winner candidate, never merged with class
    candidates).  Returns the emitted aggregate metrics (or ``None`` when no baseline is
    computable — nothing persisted; the mandatory-baseline runner fails closed on ``None``).
    Kept here (not in ``run.py``) because ``run.py`` derived-runner bodies may import only
    the narrow CPU root set; this module already owns the analyze scoring machinery and may
    reach ``db``/``baseline``.
    """
    from scripts.embedding_research import db
    from scripts.embedding_research.baseline import MEDOID_STRATEGY_TYPE, medoid_strategy_key_for
    from scripts.embedding_research.db.analyze_scope import (
        SCOPE_KIND_OBSERVED_BASELINE,
        AnalyzeScopeIdentity,
        decode_analyze_scope_v2,
        encode_analyze_scope_v2,
        record_analyze_run_scope,
    )

    metrics = analyze_medoid_baseline(
        store,
        backbone=backbone,
        song_ids=song_ids,
        artists=artists,
        k=int(k),
        working_memory=working_memory,
        evaluation_corpus=evaluation_corpus,
        genres=genres,
        head_labels=head_labels,
    )
    if metrics is None:
        return None
    medoid_key = medoid_strategy_key_for(backbone)
    # Tie the baseline rows to the run's ONE explicit evaluation corpus (Plan A P2-S3) and its
    # catalog anchor, as an analyze_scope_v2 NON-class identity (execution-reporting Plan B
    # P1-S2 / corrective P5): config_ids/canonical/alias/members/view keyset+content are empty,
    # it never enters the 'catalog' strategy type, per-class execution, or winner candidacy, and
    # it is explicitly TAGGED ``observed_baseline`` (scope_kind) — never an identity-less
    # exemption.
    identity = AnalyzeScopeIdentity(
        strategy_key=medoid_key,
        sim_metric="cosine",
        k=int(k),
        backbone=backbone,
        scope_kind=SCOPE_KIND_OBSERVED_BASELINE,
        catalog_id=catalog_id,
        catalog_fingerprint=catalog_fingerprint,
        score_variant=_PRIMARY_SCORE_VARIANT,
        scoring_semantics_version=SCORING_SEMANTICS_VERSION,
        evaluation_corpus_hash=evaluation_corpus.corpus_hash if evaluation_corpus is not None else None,
        evaluation_corpus_count=int(evaluation_corpus.count) if evaluation_corpus is not None else None,
        evaluation_corpus_comparable=bool(evaluation_corpus.comparable) if evaluation_corpus is not None else False,
        evaluation_corpus_missing_count=int(evaluation_corpus.missing_count) if evaluation_corpus is not None else 0,
        evaluation_corpus_missing_digest=(
            (evaluation_corpus.missing_digest or "") if evaluation_corpus is not None else ""
        ),
        evaluation_corpus_semantics_version=(
            int(evaluation_corpus.semantics_version) if evaluation_corpus is not None else None
        ),
        evaluation_corpus_eligible=bool(evaluation_corpus.eligible) if evaluation_corpus is not None else False,
        evaluation_corpus_eligible_digest=(
            (evaluation_corpus.eligible_digest or "") if evaluation_corpus is not None else ""
        ),
        evaluation_corpus_requested_count=(
            int(evaluation_corpus.requested_count) if evaluation_corpus is not None else None
        ),
        evaluation_corpus_requested_digest=(
            (evaluation_corpus.requested_digest or "") if evaluation_corpus is not None else ""
        ),
        evaluation_corpus_observation_digest=(
            (evaluation_corpus.observation_digest or "") if evaluation_corpus is not None else ""
        ),
        evaluation_corpus_complete=bool(evaluation_corpus.completeness) if evaluation_corpus is not None else False,
        evaluation_corpus_integrity=((evaluation_corpus.integrity or "") if evaluation_corpus is not None else ""),
    )
    # Fail-closed atomic boundary: preflight/encode/decode-validate the COMPLETE v2 scope BEFORE
    # the first metric insert so an incomplete baseline identity leaves ZERO metric rows (no
    # orphan/partial write, mirroring write_catalog_analyze_rows).
    _encoded = encode_analyze_scope_v2(identity)
    if decode_analyze_scope_v2(_encoded) != identity:
        raise ValueError("refusing to persist medoid baseline: scope identity did not round-trip")
    db.write_analyze_metrics(
        con,
        medoid_key,
        MEDOID_STRATEGY_TYPE,
        "cosine",
        int(k),
        metrics,
        run_id=run_id,
    )
    record_analyze_run_scope(
        con,
        run_id=run_id,
        identity=identity,
    )
    return metrics


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
    """Independent retrieval-metric lenses over the SAME per-query winner/score results.

    Each lens is finite-only.  AP/MRR/NDCG/Recall mirror ``similarity``'s ranked-list
    arithmetic (deliberately NOT rewritten) over a per-query candidate-song ranking;
    discrimination is mean-within minus mean-cross of the per-song values.  Per-song
    lenses are computed first; aggregates are their means.  Any non-finite value raises
    :class:`NonFiniteResultError`.

    Mirror guarantees mirror ``similarity.compute_retrieval_metrics`` exactly: NDCG
    discounts a 1-based top-ranked hit by log2(rank + 1) (== similarity's ``log2(r + 2)``
    over 0-based ``r``, so a single top-ranked relevant song yields NDCG 1.0), and MRR
    scans the FULL ranking -- a first same-label hit beyond ``k`` still contributes
    1/rank, matching similarity's full-matrix MRR (never k-truncated).  AP@k and Recall@k
    stay k-bounded as in similarity.

    Amended P3-S1 generalizes the machinery to THREE independent rulers (artist / genre /
    head).  ``evaluate`` emits the suffixed artist-ruler keys (``map_k_artist`` / ``mrr_artist`` /
    ``ndcg_k_artist`` / ``recall_k_artist`` / ``disc_artist``); ``evaluate_rulers`` computes every
    ruler's aggregates + label
    source identity for the RESULT level.  Every ruler independently restricts query and
    candidate membership to songs with that ruler's label; a ``None``/blank label or an
    absent head tuple is a MISSING label (per-ruler exclusion, never guessed); a query
    with no same-label candidate is excluded from that ruler's ``n_queries`` and
    aggregates.  The head ruler groups by the COMPLETE full tuple and applies the
    ``>= 2``-distinct-group + both-pair-sets discrimination guard (else finite guarded
    ``0.0`` with the reason visible in :class:`RulerResult.disc_guard`).
    """

    def __init__(self, cfg: CatalogAnalysisConfig) -> None:
        self._cfg = cfg
        # Label maps are normalised so a None/blank value is ABSENT (missing label).  ``Mapping``
        # value type keeps the per-ruler maps covariant (str keys, text OR full-tuple values).
        self._labels: dict[str, Mapping[str, object]] = {
            "artist": _norm_label_map(cfg.artists),
            "genre": _norm_label_map(cfg.genres),
        }
        head = {sid: hl.full_tuple for sid, hl in (cfg.head_labels or {}).items()}
        self._labels["head"] = head

    # ── historical artist emission surface (artist ruler only) ────────────────
    def evaluate(self, per_query: Sequence[PerQueryResult]) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
        metrics, per_song = self._reduce("artist", per_query, want_per_song=True)
        assert per_song is not None
        if not metrics.active:
            # Preserve the historical fail-closed contract: a corpus where NO query produced
            # an artist-relevance-bearing result cannot emit a valid artist suffixed surface.
            raise NonFiniteResultError("no query produced finite, relevance-bearing results")
        out: dict[str, float] = {
            "map_k_artist": metrics.map_k,
            "mrr_artist": metrics.mrr,
            "ndcg_k_artist": metrics.ndcg_k,
            "recall_k_artist": metrics.recall_k,
            "disc_artist": metrics.disc,
        }
        for key, value in out.items():
            _require_finite(value, f"aggregate {key}")
        return out, per_song

    # ── per-ruler aggregates + label-source identity (result-level compute) ──
    def evaluate_rulers(
        self, per_query: Sequence[PerQueryResult]
    ) -> tuple[dict[str, RulerResult], dict[str, RulerLabelSource]]:
        rulers: dict[str, RulerResult] = {}
        sources: dict[str, RulerLabelSource] = {}
        for ruler in ("artist", "genre", "head"):
            result, _per_song = self._reduce(ruler, per_query, want_per_song=False)
            rulers[ruler] = result
            sources[ruler] = self._label_source(ruler)
        return rulers, sources

    def _label_source(self, ruler: str) -> RulerLabelSource:
        """Deterministic label-source identity for *ruler* over the cfg label maps."""
        lmap = self._labels[ruler]
        song_count = len(lmap)
        if ruler == "artist":
            source, version = _ARTIST_SOURCE, _SONGS_LABEL_SOURCE_VERSION
            note = ""
        elif ruler == "genre":
            source, version = _GENRE_SOURCE, _SONGS_LABEL_SOURCE_VERSION
            note = ""
        else:
            source, version = _HEAD_SOURCE, _HEAD_SOURCE_VERSION
            note = self._head_source_note()
        missing = sum(1 for sid in self._cfg.song_ids if sid not in lmap)
        return RulerLabelSource(
            source=source,
            version=version,
            song_count=song_count,
            missing_count=missing,
            digest=_label_map_digest(lmap),
            note=note,
        )

    def _head_source_note(self) -> str:
        """Head-set/version evidence aggregated across the cfg head labels (empty when none)."""
        seen: set[tuple] = set()
        for hl in (self._cfg.head_labels or {}).values():
            seen.add(
                (
                    hl.head_set_fingerprint,
                    hl.head_ids,
                    hl.dim_by_head,
                    hl.alignment_version,
                )
            )
        if not seen:
            return "no head-labeled songs"
        fp, ids, dims, align = min(seen)
        return f"head_set_fingerprint={fp}; head_ids={ids}; dim_by_head={dims}; alignment_version={align}"

    def _reduce(self, ruler: str, per_query: Sequence[PerQueryResult], *, want_per_song: bool):
        """Per-ruler reduce over the ranked candidate songs (mirrors the artist arithmetic).

        Returns ``(RulerResult, per_song_or_None)``.  ``per_song`` (built only when
        ``want_per_song``) maps query song id -> the ruler-suffixed values
        ``{map_k_{ruler}, mrr_{ruler}, recall_k_{ruler}, disc_{ruler}}`` (``disc`` = mean-
        within minus mean-cross).
        """
        k = self._cfg.k
        lmap = self._labels[ruler]
        key_fn = lmap.get
        guard_disc = ruler == "head"
        totals = [0.0, 0.0, 0.0, 0.0]
        within_all: list[float] = []
        cross_all: list[float] = []
        within_pairs = 0
        cross_pairs = 0
        per_song: dict[str, dict[str, float]] | None = {} if want_per_song else None
        n = 0
        for pq in per_query:
            qk = key_fn(pq.query_song_id)
            if qk is None:
                # Missing label on the query -> excluded from this ruler's query set.
                continue
            ranked = sorted(pq.candidate_scores.items(), key=lambda kv: (-float(kv[1]), kv[0]))
            # Restrict the candidate ranking to songs with this ruler's label.
            ranked_l = [(s, v) for s, v in ranked if key_fn(s) is not None]
            rel = [s for s, _v in ranked_l if s != pq.query_song_id and key_fn(s) == qk]
            if not rel:
                # No same-label candidate -> no-relevant-candidate per-ruler exclusion.
                continue
            # AP@k
            hits = 0
            ap = 0.0
            for rank, (song, _v) in enumerate(ranked_l[:k], start=1):
                if song != pq.query_song_id and key_fn(song) == qk:
                    hits += 1
                    ap += hits / rank
            ap /= min(k, len(rel))
            # MRR — over the FULL ranking (never k-truncated).
            mrr = 0.0
            for rank, (song, _v) in enumerate(ranked_l, start=1):
                if song != pq.query_song_id and key_fn(song) == qk:
                    mrr = 1.0 / rank
                    break
            ndcg = _ndcg_at_k(ranked_l, k, qk, lmap, pq.query_song_id)
            rec_hits = sum(1 for song, _v in ranked_l[:k] if song != pq.query_song_id and key_fn(song) == qk)
            rec = rec_hits / min(k, len(rel))
            within = [v for s, v in pq.candidate_scores.items() if s != pq.query_song_id and key_fn(s) == qk]
            cross = [
                v
                for s, v in pq.candidate_scores.items()
                if s != pq.query_song_id and key_fn(s) is not None and key_fn(s) != qk
            ]
            wm = float(np.mean(within)) if within else 0.0
            xm = float(np.mean(cross)) if cross else 0.0
            within_pairs += len(within)
            cross_pairs += len(cross)
            values = {
                f"map_k_{ruler}": float(ap),
                f"mrr_{ruler}": float(mrr),
                f"recall_k_{ruler}": float(rec),
                f"disc_{ruler}": float(wm - xm),
            }
            for key, value in values.items():
                _require_finite(value, f"{ruler}.{pq.query_song_id}.{key}")
            if per_song is not None:
                per_song[pq.query_song_id] = values
            for i, val in enumerate((ap, mrr, ndcg, rec)):
                totals[i] += val
            within_all.append(wm)
            cross_all.append(xm)
            n += 1

        if n == 0:
            guard = "no ruler-labeled query produced a relevant candidate"
            return (
                RulerResult(
                    ruler=ruler,
                    active=False,
                    n_queries=0,
                    map_k=0.0,
                    mrr=0.0,
                    ndcg_k=0.0,
                    recall_k=0.0,
                    disc=0.0,
                    disc_guard=guard,
                ),
                per_song,
            )

        map_k, mrr, ndcg, recall = (total / n for total in totals)
        if guard_disc:
            distinct = len(set(lmap.values()))
            if distinct < 2:
                disc, guard = 0.0, f"<2 distinct tuple groups ({distinct})"
            elif within_pairs == 0:
                disc, guard = 0.0, "no within-tuple pair scores"
            elif cross_pairs == 0:
                disc, guard = 0.0, "no cross-tuple pair scores"
            else:
                disc = float(np.mean(within_all)) - float(np.mean(cross_all))
                guard = ""
        else:
            disc = float(np.mean(within_all)) - float(np.mean(cross_all))
            guard = ""
        _require_finite(disc, f"{ruler}.disc")
        return (
            RulerResult(
                ruler=ruler,
                active=True,
                n_queries=n,
                map_k=float(map_k),
                mrr=float(mrr),
                ndcg_k=float(ndcg),
                recall_k=float(recall),
                disc=disc,
                disc_guard=guard,
            ),
            per_song,
        )


def _ndcg_at_k(ranked, k: int, qkey: object, labels: Mapping[str, object], query_song_id: str) -> float:
    """NDCG@k over same-label relevance (mirrors ``similarity``'s discounted-gain arithmetic).

    ``labels`` is the ruler's label map (song_id -> label key); ``qkey`` is the query's
    label key (an artist/genre string or a head full tuple).  Discount is 1/log2(rank + 1)
    for 1-based ``rank`` -- equivalent to ``similarity``'s ``h / log2(r + 2)`` for 0-based
    ``r``, so a single top-ranked relevant song is NDCG 1.0.
    """
    dcg = 0.0
    for rank, (song, _v) in enumerate(ranked[:k], start=1):
        if song != query_song_id and labels.get(song) == qkey:
            dcg += 1.0 / np.log2(rank + 1)
    rel_total = sum(1 for s, a in labels.items() if s != query_song_id and a == qkey)
    n_rel = min(k, rel_total)
    idcg = sum(1.0 / np.log2(r + 1) for r in range(1, n_rel + 1))
    return float(dcg / idcg) if idcg > 0 else 0.0


def _norm_label_map(source: Mapping[str, str]) -> dict[str, str]:
    """Drop ``None``/blank labels from a raw song_id -> text label map.

    A missing/blank value is a MISSING label for that ruler (per-ruler exclusion), never
    substituted with a guessed label.
    """
    out: dict[str, str] = {}
    for sid, value in source.items():
        if value is None:
            continue
        text = str(value)
        if not text.strip():
            continue
        out[sid] = text
    return out


def _label_map_digest(lmap: Mapping[str, object]) -> str:
    """Deterministic sha256 digest over a song_id -> label-key map (label-map evidence)."""

    def _jsonable(key: object) -> object:
        if isinstance(key, tuple):
            return [_jsonable(item) for item in key]
        return key

    items = json.dumps(
        [[str(sid), _jsonable(key)] for sid, key in sorted(lmap.items())],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(items.encode("utf-8")).hexdigest()


def _require_finite(value: float, name: str) -> None:
    if not np.isfinite(value):
        raise NonFiniteResultError(f"non-finite {name}={value!r}; refusing to persist")


#: The independent rulers' canonical order (artist / genre / head) — the order in which the
#: suffixed aggregate retrieval vocabulary is produced and persisted.
_RULER_NAMES: tuple[str, ...] = ("artist", "genre", "head")

#: The five per-ruler aggregate RulerResult fields that become suffixed retrieval keys.
_RULER_AGG_FIELDS: tuple[str, ...] = ("map_k", "mrr", "ndcg_k", "recall_k", "disc")


def _suffixed_aggregate_metrics(rulers: Mapping[str, RulerResult]) -> dict[str, float]:
    """The finite suffixed aggregate retrieval dict built from per-ruler RulerResults.

    Emits the five suffixed retrieval aggregates (``map_k_X``/``mrr_X``/``ndcg_k_X``/
    ``recall_k_X``/``disc_X``) for EVERY ACTIVE ruler (``n_queries > 0``) plus
    ``n_queries_X`` for every ruler (``0`` when that ruler had no ruler-evaluable query after
    its missing-label and no-relevant-candidate exclusions).  An INACTIVE ruler never emits a
    fabricated zero retrieval value.  Keys use exactly the finite suffixed 18-key vocabulary
    — no generic unsuffixed or composite key.
    """
    out: dict[str, float] = {}
    for ruler in _RULER_NAMES:
        rr = rulers[ruler]
        out[f"n_queries_{ruler}"] = float(rr.n_queries)
        if not rr.active:
            continue
        for agg_field in _RULER_AGG_FIELDS:
            key = f"{agg_field}_{ruler}"
            value = getattr(rr, agg_field)
            _require_finite(value, key)
            out[key] = float(value)
    return out


def resolve_head_ruler_labels(store, out_root, song_ids, backbone: str = "effnet") -> dict[str, HeadSongLabel]:
    """Resolve the frozen semantic-head ruler label for every *song_ids* member (amended P3-S1).

    EffNet-only, CPU-only, read-only over the committed artifacts.  For each song the head
    suite is selected ONLY by the filesystem-authoritative ``heads/current/<song_id>.<backbone>.json``
    CURRENT marker, aligned to the song's current committed observation group.  Only committed
    whole-song searchable source rows ``i`` where the exact committed ``uint8[patch_count]`` mask
    ``== 1`` are pooled (never segment ``M_g`` rows, never legacy continuous score windows).  For
    each canonical head in canonical sorted head-suite order the mean frozen activation over those
    rows is taken; ``act[1]`` is the class-1 probability; the song is classified ``side index 1``
    iff that pooled value is finite and ``>= 0.5``, else index 0.  Canonical text is
    ``HEAD_LABELS[head][index]``.

    A song gets a :class:`HeadSongLabel` ONLY when: the CURRENT marker resolves AND is aligned to
    the committed group (stream + mask); every required head of the suite is present, binary
    (``dim == 2``), and canonical-labelable; at least one committed searchable row exists; and every
    pooled value is present and finite.  Missing marker/suite/stream/mask/row/label evidence is a
    MISSING label (excluded from the head ruler only — never an error, never substituted).  A
    PRESENT non-finite activation or pooled value raises :class:`NonFiniteResultError` (never
    coerced, never excluded).
    """
    import numpy as _np

    from scripts.embedding_research import config as _config
    from scripts.embedding_research.streams.heads_current import (
        HeadSuiteCurrentError,
        resolve_current_head_suite,
    )
    from scripts.embedding_research.streams.store import StreamStoreError

    out_root_path = Path(out_root)
    labels: dict[str, HeadSongLabel] = {}
    if backbone != "effnet":
        # The head ruler is EffNet-only (the semantic-head phase is EffNet-scoped).
        return labels
    for song_id in sorted(song_ids):
        try:
            selection = resolve_current_head_suite(out_root_path, song_id, backbone)
        except HeadSuiteCurrentError:
            continue  # missing marker / not aligned -> MISSING head label (per-ruler exclusion)
        try:
            observation = store.load_committed_observation(song_id, backbone)
        except StreamStoreError:
            continue
        record = selection.record
        identity = observation.identity
        mask = observation.mask
        if mask is None or identity is None:
            continue
        mask = _np.asarray(mask)
        if mask.ndim != 1 or mask.dtype not in ("uint8", "int8"):
            continue
        # Only committed whole-song searchable rows where the exact mask == 1.
        idx = _np.flatnonzero(mask == 1)
        if idx.size == 0:
            continue
        head_ids = tuple(h for h in str(record.head_ids).split(",") if h)
        if not head_ids:
            continue
        try:
            payload = _np.load(out_root_path / record.artifact_ref, allow_pickle=False)
        except (OSError, ValueError, TypeError):
            continue
        pooled: list[float] = []
        sides: list[tuple[str, int]] = []
        labelable = True
        for head in head_ids:
            canonical = _config.HEAD_LABELS.get(head)
            if canonical is None:
                labelable = False
                break
            if head not in payload.files:
                labelable = False
                break
            arr = payload[head]
            if not hasattr(arr, "ndim") or arr.ndim != 2:
                labelable = False
                break
            dim = arr.shape[1]
            if dim != 2:
                # Not a binary head -> not a labelable ruler head (missing label for this song).
                labelable = False
                break
            rows = _np.asarray(arr, dtype=_np.float32)[idx]
            if not _np.isfinite(rows).all():
                raise NonFiniteResultError(
                    f"head ruler: present non-finite activation for song {song_id!r} head {head!r}; "
                    f"refusing to classify"
                )
            mean = rows.mean(axis=0)
            pooled_value = float(mean[1])  # act[1] = class-1 probability
            _require_finite(pooled_value, f"head {head!r} song {song_id!r} pooled value")
            side = 1 if pooled_value >= 0.5 else 0
            pooled.append(pooled_value)
            sides.append((head, side))
        if not labelable or len(sides) != len(head_ids):
            continue
        full_tuple = tuple(sides)
        labels[song_id] = HeadSongLabel(
            song_id=song_id,
            backbone=backbone,
            full_tuple=full_tuple,
            labels=tuple(_config.HEAD_LABELS[head][side] for head, side in sides),
            pooled=tuple(pooled),
            searchable_rows=int(idx.size),
            head_set_fingerprint=getattr(record, "head_set_fingerprint", "") or "",
            head_ids=str(record.head_ids),
            dim_by_head=str(record.dim_by_head),
            alignment_version=str(record.alignment_version),
            stream_ref=str(identity.stream_ref),
            stream_digest=str(identity.stream_digest),
            mask_ref=str(identity.mask_ref),
            mask_digest=str(identity.mask_digest),
            commit_sha256=str(identity.commit_sha256),
        )
    return labels
