"""Geometry-owned corpus analysis contracts.

This module contains corpus loading and persistence orchestration for the
geometry experiment. Synthetic-only fixture production remains explicit, while
empirical requests publish only frozen-head-bound evidence. ``analyze_geometry_corpus``
loads committed observations, while ``write_geometry_corpus_analysis`` owns persistence;
real corpus and model execution remains outside this CPU-side seam.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field, replace
from types import MappingProxyType, SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import numpy as np

from scripts.embedding_research.bounded_scoring import (
    BoundedScoreResult,
    ScoringCandidateView,
    score_bounded_exact,
)
from scripts.embedding_research.common.head_ruler_labels import (
    HeadSongLabel,
    resolve_head_ruler_labels,
)
from scripts.embedding_research.common.threshold_analysis import (
    AllThresholdAnalysis,
    AnalysisEvidenceIdentity,
    PrimaryThresholdRequest,
    SecondaryChebyshevRequest,
    analyze_all_thresholds,
)
from scripts.embedding_research.db.geometry import (
    MAX_GRAM_BYTES,
    MAX_PATCH_COUNT,
    GeometryIdentity,
    GeometryRecord,
    IntegrityRefused,
    StaleRefused,
    enforce_geometry_resource_ceiling,
    preflight_geometry_binding,
    read_geometry,
    require_current_geometry,
    verify_geometry_binding,
    verify_geometry_current,
    write_geometry,
)
from scripts.embedding_research.db.geometry_profile import GeometryProfile
from scripts.embedding_research.db.songs import load_all_songs
from scripts.embedding_research.helpers.corpus_identity import (
    CorpusSongSearchInput,
    RepresentationState,
    classify_representation,
    search_representation_id,
)
from scripts.embedding_research.helpers.gram_segmentation import (
    observed_global_medoid_from_gram,
    require_exact_binary_mask,
)
from scripts.embedding_research.similarity import (
    K_ESTABLISHED,
    compute_retrieval_metrics,
    cosine_matrix,
)
from scripts.embedding_research.vector_types import RawTensor

if TYPE_CHECKING:
    from scripts.embedding_research.streams.store import StreamStore

_EXPERIMENTS = {"temporal_global", "temporal_perdim_chebyshev_secondary"}
_MAX_PATCH_COUNT = MAX_PATCH_COUNT
_MAX_GRAM_BYTES = MAX_GRAM_BYTES

#: Canonical non-comparable reason vocabulary for the normalized result surfaces.
_CANONICAL_RESULT_REASONS: frozenset[str] = frozenset(
    {"alignment_failed", "zero_searchable", "no_medoid", "no_candidates", "label_missing"}
)
_RESULT_RULERS: frozenset[str] = frozenset({"artist", "genre", "head"})
_RESULT_METRICS: frozenset[str] = frozenset({"map_k", "mrr", "ndcg_k", "recall_k", "disc"})
_RESULT_STATUSES: frozenset[str] = frozenset({"defined", "undefined"})


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _finite(value: object, name: str) -> float:
    if not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not np.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _readonly_array(value: Any, *, dtype: str, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.dtype(dtype), order="C")
    if array.ndim != 2 and name == "vectors":
        raise ValueError("vectors must be a two-dimensional array")
    if array.ndim != 1 and name == "weights":
        raise ValueError("weights must be one-dimensional")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain only finite values")
    result = np.array(array, dtype=array.dtype, order="C", copy=True)
    result.setflags(write=False)
    return result


def _mapping(value: Mapping[str, Any] | None, name: str) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    return MappingProxyType(dict(value))


@dataclass(frozen=True)
class GeometryIdentityAxes:
    """The complete identity axes carried by one analysis outcome."""

    geometry_id: str
    observation_group_sha256: str
    geometry_semantics_version: str
    numerical_profile_digest: str
    mask_digest: str
    threshold_id: str
    structural_identity: str
    search_representation_id: str
    evaluation_id: str
    scoring_semantics_version: int
    execution_id: str

    def __post_init__(self) -> None:
        for name in (
            "geometry_id",
            "observation_group_sha256",
            "geometry_semantics_version",
            "numerical_profile_digest",
            "mask_digest",
            "threshold_id",
            "structural_identity",
            "search_representation_id",
            "evaluation_id",
            "execution_id",
        ):
            _text(getattr(self, name), name)
        if isinstance(self.scoring_semantics_version, bool) or self.scoring_semantics_version < 1:
            raise ValueError("scoring_semantics_version must be positive")


@dataclass(frozen=True)
class GeometrySongRequest:
    """One ordered song/backbone analysis input with explicit evidence-mode provenance.

    Requests may use an explicit ``synthetic_fixture`` or a bounded
    ``empirical_request`` bound to complete frozen current-head semantic-head provenance;
    neither mode permits external corpus or inference execution in this CPU-side analysis seam.
    """

    song_id: str
    backbone: str
    geometry_identity: GeometryIdentity
    observation_evidence: Mapping[str, Any]
    artist: str | None = None
    genre: str | None = None
    head_label: Any | None = None
    head_suite_identity: str | None = None
    head_provenance: Any | None = None
    synthetic_only: bool = True

    def __post_init__(self) -> None:
        _text(self.song_id, "song_id")
        _text(self.backbone, "backbone")
        if not isinstance(self.geometry_identity, GeometryIdentity):
            raise ValueError("geometry_identity must be GeometryIdentity")
        object.__setattr__(self, "observation_evidence", _mapping(self.observation_evidence, "observation_evidence"))
        if not isinstance(self.synthetic_only, bool):
            raise ValueError("synthetic_only must be boolean evidence mode")
        if self.head_suite_identity is not None:
            _text(self.head_suite_identity, "head_suite_identity")
        if self.head_provenance is not None and not isinstance(self.head_provenance, HeadSongLabel):
            raise ValueError("head_provenance must be a HeadSongLabel")
        for name in ("artist", "genre"):
            value = getattr(self, name)
            if value is not None:
                _text(value, name)


@dataclass(frozen=True)
class GeometryCorpusRequest:
    """Complete deterministic corpus request and execution identity."""

    items: tuple[GeometrySongRequest, ...]
    threshold_request: PrimaryThresholdRequest | SecondaryChebyshevRequest
    experiment: str
    evaluation_id: str
    scoring_semantics_version: int
    run_id: str
    execution_id: str
    numerical_profile_digest: str
    synthetic_only: bool = True

    def __post_init__(self) -> None:
        items = tuple(self.items)
        if any(not isinstance(item, GeometrySongRequest) for item in items):
            raise ValueError("items must contain GeometrySongRequest values")
        if items != tuple(sorted(items, key=lambda item: (item.song_id, item.backbone))):
            raise ValueError("items must be deterministically ordered by song_id and backbone")
        if len({(item.song_id, item.backbone) for item in items}) != len(items):
            raise ValueError("items must have unique song_id/backbone identities")
        if not isinstance(self.threshold_request, (PrimaryThresholdRequest, SecondaryChebyshevRequest)):
            raise ValueError("threshold_request must be an explicit geometry threshold request")
        _text(self.experiment, "experiment")
        if self.experiment not in _EXPERIMENTS or self.experiment != self.threshold_request.experiment:
            raise ValueError("experiment does not match threshold request")
        for name in ("evaluation_id", "run_id", "execution_id", "numerical_profile_digest"):
            _text(getattr(self, name), name)
        if isinstance(self.scoring_semantics_version, bool) or self.scoring_semantics_version < 1:
            raise ValueError("scoring_semantics_version must be positive")
        if not isinstance(self.synthetic_only, bool):
            raise ValueError("synthetic_only must be boolean evidence mode")


@dataclass(frozen=True)
class FrozenSearchRepresentation:
    """One gathered, immutable representation shared by threshold members."""

    song_id: str
    backbone: str
    source_indices: tuple[int, ...]
    vectors: np.ndarray
    weights: np.ndarray
    search_representation_id: str
    geometry_id: str
    observation_group_sha256: str
    numerical_profile_digest: str
    mask_digest: str
    scoring_semantics_version: int
    experiment: str
    structural_member_threshold_indices: tuple[int, ...] = ()
    is_observed_baseline: bool = False

    def __post_init__(self) -> None:
        for name in (
            "song_id",
            "backbone",
            "search_representation_id",
            "geometry_id",
            "observation_group_sha256",
            "numerical_profile_digest",
            "mask_digest",
            "experiment",
        ):
            _text(getattr(self, name), name)
        if self.experiment not in _EXPERIMENTS:
            raise ValueError("unknown geometry experiment")
        indices = tuple(int(index) for index in self.source_indices)
        if any(index < 0 for index in indices) or indices != tuple(sorted(indices)):
            raise ValueError("source_indices must be sorted non-negative integers")
        object.__setattr__(self, "source_indices", indices)
        vectors = _readonly_array(self.vectors, dtype="<f4", name="vectors")
        weights = _readonly_array(self.weights, dtype="<f8", name="weights")
        if vectors.shape[0] != len(indices) or weights.shape[0] != len(indices):
            raise ValueError("source_indices, vectors, and weights must have matching row counts")
        object.__setattr__(self, "vectors", vectors)
        object.__setattr__(self, "weights", weights)
        object.__setattr__(
            self, "structural_member_threshold_indices", tuple(sorted(set(self.structural_member_threshold_indices)))
        )
        if isinstance(self.scoring_semantics_version, bool) or self.scoring_semantics_version < 1:
            raise ValueError("scoring_semantics_version must be positive")


@dataclass(frozen=True)
class GeometryRepresentationRoster:
    """Unique transient representations and the separately identified baseline."""

    representations: tuple[FrozenSearchRepresentation, ...]
    observed_baseline: FrozenSearchRepresentation | None = None

    def __post_init__(self) -> None:
        entries = tuple(self.representations)
        if any(not isinstance(item, FrozenSearchRepresentation) for item in entries):
            raise ValueError("representations must contain FrozenSearchRepresentation values")
        if any(item.is_observed_baseline for item in entries):
            raise ValueError("the observed baseline must be separate from scoring representations")
        if self.observed_baseline is not None and not self.observed_baseline.is_observed_baseline:
            raise ValueError("observed_baseline must be marked as a baseline")
        ids = [item.search_representation_id for item in entries]
        if len(ids) != len(set(ids)):
            raise ValueError("representations must have unique search_representation_id values")

    @property
    def unique_representation_count(self) -> int:
        return len(self.representations)


@dataclass(frozen=True)
class GeometryScoreBundle:
    """Finite bounded scores plus independent ruler and execution counters.

    ``scores`` contains winner-candidate representations only.  The optional
    ``baseline_score`` is deliberately separate: the observed whole-song
    medoid is evidence for comparison, never a winner candidate.
    """

    scores: Mapping[str, float]
    baseline_score: float | None = None
    baseline_representation_id: str | None = None
    per_song_metrics: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    artist_metrics: Mapping[str, float] = field(default_factory=dict)
    genre_metrics: Mapping[str, float] = field(default_factory=dict)
    head_metrics: Mapping[str, float] = field(default_factory=dict)
    evaluation_comparable: bool = True
    unique_representation_count: int = 0
    source_gather_count: int = 0
    scorer_call_count: int = 0
    segmentation_from_scorer_count: int = 0

    def __post_init__(self) -> None:
        if self.baseline_score is not None:
            _finite(self.baseline_score, "baseline_score")
        if self.baseline_representation_id is not None:
            _text(self.baseline_representation_id, "baseline_representation_id")
        for name in (
            "scores",
            "per_song_metrics",
            "artist_metrics",
            "genre_metrics",
            "head_metrics",
        ):
            value = getattr(self, name)
            object.__setattr__(self, name, _mapping(value, name))
            for metric in value.values():
                if isinstance(metric, Mapping):
                    for scalar in metric.values():
                        _finite(scalar, name)
                else:
                    _finite(metric, name)
        for name in (
            "unique_representation_count",
            "source_gather_count",
            "scorer_call_count",
            "segmentation_from_scorer_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.segmentation_from_scorer_count != 0:
            raise ValueError("scoring cannot perform segmentation")
        if not isinstance(self.evaluation_comparable, bool):
            raise ValueError("evaluation_comparable must be boolean")


def score_unique_geometry_representations(
    roster: GeometryRepresentationRoster,
    evaluation: FrozenGeometryEvaluation | Mapping[str, Any],
    scoring: Any = score_bounded_exact,
) -> GeometryScoreBundle:
    """Score frozen representations through the bounded CPU scorer boundary.

    ``evaluation`` is a transient payload with finite ``query_vectors`` and
    ``query_weights`` only.  Each winner representation is submitted exactly
    once as a :class:`ScoringCandidateView`; no segmentation, geometry decode,
    stream reload, further term, or pairwise matrix is owned here.  The
    separately identified observed baseline follows a separate call and is
    never inserted into ``scores``.
    """
    if not isinstance(roster, GeometryRepresentationRoster):
        raise TypeError("roster must be GeometryRepresentationRoster")
    if isinstance(evaluation, FrozenGeometryEvaluation):
        query_vectors = np.asarray(evaluation.query_vectors, dtype=np.float32)
        query_weights = np.asarray(evaluation.query_weights, dtype=np.float64)
        evaluation_comparable = evaluation.comparable
    elif isinstance(evaluation, Mapping):
        try:
            query_vectors = np.asarray(evaluation["query_vectors"], dtype=np.float32)
            query_weights = np.asarray(evaluation["query_weights"], dtype=np.float64)
        except KeyError as exc:
            raise ValueError(f"evaluation missing {exc.args[0]!r}") from exc
        evaluation_comparable = True
    else:
        raise TypeError("evaluation must be FrozenGeometryEvaluation or a mapping")
    if query_vectors.ndim != 2 or query_weights.ndim != 1:
        raise ValueError("evaluation query_vectors/query_weights have invalid dimensions")
    if query_vectors.shape[0] != query_weights.shape[0]:
        raise ValueError("evaluation query vectors and weights must be aligned")
    if not np.isfinite(query_vectors).all() or not np.isfinite(query_weights).all():
        raise ValueError("evaluation query payload must be finite")
    if not callable(scoring):
        raise TypeError("scoring must be callable")

    scores: dict[str, float] = {}
    for representation in roster.representations:
        result = scoring(
            query_vectors,
            query_weights,
            ScoringCandidateView(
                vectors=representation.vectors,
                row_addresses=tuple((0, representation.song_id, index, 0) for index in representation.source_indices),
                candidate_weights=representation.weights,
            ),
        )
        bounded_result = cast("BoundedScoreResult", result)
        if not bounded_result.finite or not np.isfinite(float(bounded_result.score)):
            raise ValueError(f"non-finite bounded score for {representation.search_representation_id}")
        scores[representation.search_representation_id] = float(bounded_result.score)

    baseline_score: float | None = None
    baseline_id: str | None = None
    baseline = roster.observed_baseline
    if baseline is not None:
        result = scoring(
            query_vectors,
            query_weights,
            ScoringCandidateView(
                vectors=baseline.vectors,
                row_addresses=tuple((0, baseline.song_id, index, 0) for index in baseline.source_indices),
                candidate_weights=baseline.weights,
            ),
        )
        bounded_result = cast("BoundedScoreResult", result)
        if not bounded_result.finite or not np.isfinite(float(bounded_result.score)):
            raise ValueError(f"non-finite bounded baseline score for {baseline.search_representation_id}")
        baseline_score = float(bounded_result.score)
        baseline_id = baseline.search_representation_id

    return GeometryScoreBundle(
        scores=scores,
        baseline_score=baseline_score,
        baseline_representation_id=baseline_id,
        evaluation_comparable=evaluation_comparable,
        unique_representation_count=len(roster.representations),
        source_gather_count=len(roster.representations) + (1 if baseline is not None else 0),
        scorer_call_count=len(roster.representations) + (1 if baseline is not None else 0),
        segmentation_from_scorer_count=0,
    )


@dataclass(frozen=True)
class GeometryAnalysisCounters:
    """Execution counters proving geometry is loaded once and scoring never segments."""

    geometry_load_count: int = 0
    observation_load_count: int = 0
    threshold_analysis_count: int = 0
    unique_representation_count: int = 0
    source_gather_count: int = 0
    scorer_call_count: int = 0
    segmentation_from_scorer_count: int = 0

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.segmentation_from_scorer_count != 0:
            raise ValueError("scoring cannot perform segmentation")


@dataclass(frozen=True)
class FrozenGeometryEvaluation:
    """Immutable query evaluation input with aligned read-only vectors and weights."""

    evaluation_id: str
    query_vectors: np.ndarray
    query_weights: np.ndarray
    eligible_song_ids: tuple[str, ...] = ()
    observation_evidence_digest: str = ""
    comparable: bool = True

    def __post_init__(self) -> None:
        _text(self.evaluation_id, "evaluation_id")
        object.__setattr__(self, "query_vectors", _readonly_array(self.query_vectors, dtype="<f4", name="vectors"))
        object.__setattr__(self, "query_weights", _readonly_array(self.query_weights, dtype="<f8", name="weights"))
        if self.query_vectors.shape[0] != self.query_weights.shape[0]:
            raise ValueError("query vectors and weights must be aligned")
        object.__setattr__(self, "eligible_song_ids", tuple(sorted(set(self.eligible_song_ids))))
        if not isinstance(self.comparable, bool):
            raise ValueError("comparable must be boolean")


@dataclass(frozen=True)
class GeometrySongAnalysis:
    """Per-query evidence scoped to one threshold/collapse hypothesis."""

    request: GeometrySongRequest
    thresholds: AllThresholdAnalysis
    roster: GeometryRepresentationRoster
    scores: GeometryScoreBundle
    state: RepresentationState = field(default_factory=lambda: RepresentationState(True, True, True, ()))
    neighborhood: tuple[NeighborhoodEntry, ...] = ()
    baseline_neighborhood: tuple[NeighborhoodEntry, ...] = ()
    threshold_id: str = ""
    collapse_class_id: str = ""


@dataclass(frozen=True)
class GeometryCorpusHypothesis:
    """Complete ordered same-threshold corpus representations and states."""

    threshold_id: str
    collapse_class_id: str
    members: tuple[GeometryCandidate, ...]

    def __post_init__(self) -> None:
        _text(self.threshold_id, "threshold_id")
        _text(self.collapse_class_id, "collapse_class_id")
        object.__setattr__(self, "members", tuple(self.members))
        if not self.members:
            raise ValueError("each corpus hypothesis must contain ordered members")


@dataclass(frozen=True)
class GeometryEvaluationCorpusEntry:
    """One fixed evaluation-corpus membership row for one ``(song_id, backbone)``.

    Membership is decided only by the whole-song observed-global-medoid baseline
    representation: a finite, strictly nonzero observed medoid row over a valid committed
    binary mask.  Artist, genre, and head labels never participate, so the corpus cannot be
    shaped by labels or by the configured threshold set.
    """

    song_id: str
    backbone: str
    geometry_id: str
    observation_group_sha256: str
    numerical_profile_digest: str
    searchable_count: int
    comparable: bool
    reasons: tuple[str, ...]
    baseline_valid: bool

    def __post_init__(self) -> None:
        for name in (
            "song_id",
            "backbone",
            "geometry_id",
            "observation_group_sha256",
            "numerical_profile_digest",
        ):
            _text(getattr(self, name), name)
        if isinstance(self.searchable_count, bool) or self.searchable_count < 0:
            raise ValueError("searchable_count must be a non-negative integer")
        for name in ("comparable", "baseline_valid"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        object.__setattr__(self, "reasons", tuple(str(reason) for reason in self.reasons))


@dataclass(frozen=True)
class GeometryThresholdClassRow:
    """One ``threshold_index -> corpus_search_class_id`` row per configured threshold.

    Equal ordered scoring preimages collapse into one class, but every configured
    threshold index still receives exactly one row.  ``corpus_search_class_id`` is the
    fixed-corpus search representation id; ``search_representation_id`` itself is never
    a column here and stays DTO-only on the representation.
    """

    threshold_index: int
    threshold_id: str
    threshold_value: float
    corpus_search_class_id: str
    comparable: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if isinstance(self.threshold_index, bool) or self.threshold_index < 0:
            raise ValueError("threshold_index must be a non-negative integer")
        _text(self.threshold_id, "threshold_id")
        _finite(self.threshold_value, "threshold_value")
        _text(self.corpus_search_class_id, "corpus_search_class_id")
        if not isinstance(self.comparable, bool):
            raise ValueError("comparable must be boolean")
        object.__setattr__(self, "reasons", tuple(str(reason) for reason in self.reasons))


@dataclass(frozen=True)
class GeometryThresholdStructuralRow:
    """One per-``(song, threshold)`` structural/search evidence row.

    The row carries structural and search topology only.  Retrieval metrics live on the
    class-scoped metric surfaces, never here, so the structural surface never grows with
    the number of thresholds squared.
    """

    song_id: str
    backbone: str
    threshold_index: int
    threshold_id: str
    structural_identity: str
    search_representation_id: str
    searchable_count: int
    medoid_defined: bool
    alignment_ok: bool
    comparable: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("song_id", "backbone", "threshold_id", "structural_identity", "search_representation_id"):
            _text(getattr(self, name), name)
        if isinstance(self.threshold_index, bool) or self.threshold_index < 0:
            raise ValueError("threshold_index must be a non-negative integer")
        if isinstance(self.searchable_count, bool) or self.searchable_count < 0:
            raise ValueError("searchable_count must be a non-negative integer")
        for name in ("medoid_defined", "alignment_ok", "comparable"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        object.__setattr__(self, "reasons", tuple(str(reason) for reason in self.reasons))


@dataclass(frozen=True)
class GeometryClassAggregateMetric:
    """One ``(class, ruler, metric)`` aggregate over the class's defined queries."""

    corpus_search_class_id: str
    ruler: str
    metric: str
    k: int
    value: float
    evaluable_query_count: int
    undefined_query_count: int

    def __post_init__(self) -> None:
        _text(self.corpus_search_class_id, "corpus_search_class_id")
        if self.ruler not in _RULER_NAMES:
            raise ValueError("ruler must be artist, genre, or head")
        if self.metric not in _CLASS_METRIC_NAMES:
            raise ValueError("metric must be a canonical class-scoped metric")
        for name in ("k", "evaluable_query_count", "undefined_query_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        _finite(self.value, "value")


@dataclass(frozen=True)
class GeometryClassQueryMetric:
    """One per-query class-scoped metric row with explicit definedness status."""

    corpus_search_class_id: str
    query_song_id: str
    ruler: str
    metric: str
    k: int
    value: float
    status: str

    def __post_init__(self) -> None:
        _text(self.corpus_search_class_id, "corpus_search_class_id")
        _text(self.query_song_id, "query_song_id")
        if self.ruler not in _RULER_NAMES:
            raise ValueError("ruler must be artist, genre, or head")
        if self.metric not in _CLASS_METRIC_NAMES:
            raise ValueError("metric must be a canonical class-scoped metric")
        if isinstance(self.k, bool) or self.k < 0:
            raise ValueError("k must be a non-negative integer")
        _finite(self.value, "value")
        if self.status not in {"defined", "undefined"}:
            raise ValueError("status must be defined or undefined")


@dataclass(frozen=True)
class GeometryClassNeighborhood:
    """One retained class-scoped browsing-window entry (never a metric input)."""

    corpus_search_class_id: str
    query_song_id: str
    candidate_song_id: str
    rank: int
    score: float

    def __post_init__(self) -> None:
        _text(self.corpus_search_class_id, "corpus_search_class_id")
        _text(self.query_song_id, "query_song_id")
        _text(self.candidate_song_id, "candidate_song_id")
        if isinstance(self.rank, bool) or self.rank < 0:
            raise ValueError("rank must be a non-negative integer")
        _finite(self.score, "score")


@dataclass(frozen=True)
class GeometryBaselineAggregateMetric:
    """One threshold-independent baseline ``(ruler, metric)`` aggregate."""

    backbone: str
    ruler: str
    metric: str
    k: int
    value: float
    evaluable_query_count: int
    undefined_query_count: int

    def __post_init__(self) -> None:
        _text(self.backbone, "backbone")
        if self.ruler not in _RULER_NAMES:
            raise ValueError("ruler must be artist, genre, or head")
        if self.metric not in _CLASS_METRIC_NAMES:
            raise ValueError("metric must be a canonical class-scoped metric")
        for name in ("k", "evaluable_query_count", "undefined_query_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        _finite(self.value, "value")


@dataclass(frozen=True)
class GeometryBaselineQueryMetric:
    """One per-query baseline metric row with explicit definedness status."""

    backbone: str
    query_song_id: str
    ruler: str
    metric: str
    k: int
    value: float
    status: str

    def __post_init__(self) -> None:
        _text(self.backbone, "backbone")
        _text(self.query_song_id, "query_song_id")
        if self.ruler not in _RULER_NAMES:
            raise ValueError("ruler must be artist, genre, or head")
        if self.metric not in _CLASS_METRIC_NAMES:
            raise ValueError("metric must be a canonical class-scoped metric")
        if isinstance(self.k, bool) or self.k < 0:
            raise ValueError("k must be a non-negative integer")
        _finite(self.value, "value")
        if self.status not in {"defined", "undefined"}:
            raise ValueError("status must be defined or undefined")


@dataclass(frozen=True)
class GeometryBaselineNeighborhood:
    """One retained threshold-independent baseline browsing-window entry."""

    backbone: str
    query_song_id: str
    candidate_song_id: str
    rank: int
    score: float

    def __post_init__(self) -> None:
        _text(self.backbone, "backbone")
        _text(self.query_song_id, "query_song_id")
        _text(self.candidate_song_id, "candidate_song_id")
        if isinstance(self.rank, bool) or self.rank < 0:
            raise ValueError("rank must be a non-negative integer")
        _finite(self.score, "score")


@dataclass(frozen=True)
class GeometryResultProvenanceRow:
    """The compact per-run provenance row persisted alongside the normalized surfaces."""

    execution_id: str
    evaluation_id: str
    experiment: str
    scoring_semantics_version: int
    geometry_semantics_version: str
    numerical_profile_digest: str
    evidence_mode: str
    synthetic_only: bool
    comparable: bool
    reasons: tuple[str, ...] = ()
    geometry_axes: tuple[Mapping[str, str], ...] = ()
    head_evidence_provenance: Mapping[str, Any] = field(default_factory=dict)
    counters: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "execution_id",
            "evaluation_id",
            "experiment",
            "geometry_semantics_version",
            "numerical_profile_digest",
            "evidence_mode",
        ):
            _text(getattr(self, name), name)
        if isinstance(self.scoring_semantics_version, bool) or self.scoring_semantics_version < 1:
            raise ValueError("scoring_semantics_version must be a positive integer")
        for name in ("synthetic_only", "comparable"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        object.__setattr__(self, "reasons", tuple(str(reason) for reason in self.reasons))
        object.__setattr__(self, "geometry_axes", tuple(dict(axis) for axis in self.geometry_axes))


@dataclass(frozen=True)
class GeometryNormalizedResult:
    """The class-scoped result read back from the normalized result surfaces.

    Unlike :class:`GeometryCorpusAnalysis` (the in-memory compute graph), this value object
    carries only what the normalized persistence surfaces can faithfully reproduce.  It is the
    symmetric counterpart of :func:`write_geometry_corpus_analysis`: every field written there
    round-trips here for the exact ten-axis identity.  There is no nested ``role="corpus"``
    evidence shape and no ``geometry_analysis_records`` row anywhere in this read path.
    """

    run_id: str
    provenance: GeometryResultProvenanceRow
    evaluation_corpus: tuple[GeometryEvaluationCorpusEntry, ...] = ()
    threshold_class_map: tuple[GeometryThresholdClassRow, ...] = ()
    threshold_structural: tuple[GeometryThresholdStructuralRow, ...] = ()
    class_aggregate_metrics: tuple[GeometryClassAggregateMetric, ...] = ()
    class_query_metrics: tuple[GeometryClassQueryMetric, ...] = ()
    class_neighborhoods: tuple[GeometryClassNeighborhood, ...] = ()
    baseline_aggregate_metrics: tuple[GeometryBaselineAggregateMetric, ...] = ()
    baseline_query_metrics: tuple[GeometryBaselineQueryMetric, ...] = ()
    baseline_neighborhoods: tuple[GeometryBaselineNeighborhood, ...] = ()
    head_label_provenance: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        _text(self.run_id, "run_id")
        for name in (
            "evaluation_corpus",
            "threshold_class_map",
            "threshold_structural",
            "class_aggregate_metrics",
            "class_query_metrics",
            "class_neighborhoods",
            "baseline_aggregate_metrics",
            "baseline_query_metrics",
            "baseline_neighborhoods",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "head_label_provenance", tuple(dict(row) for row in self.head_label_provenance))


@dataclass(frozen=True)
class GeometryCorpusAnalysis:
    """Complete geometry corpus result, including refusal and all provenance axes."""

    run_id: str
    execution_id: str
    experiment: str
    evaluation_id: str
    numerical_profile_digest: str
    scoring_semantics_version: int
    analyses: tuple[AllThresholdAnalysis, ...] = ()
    roster: GeometryRepresentationRoster | None = None
    scores: GeometryScoreBundle | None = None
    baseline: FrozenSearchRepresentation | None = None
    artist_metrics: Mapping[str, float] = field(default_factory=dict)
    genre_metrics: Mapping[str, float] = field(default_factory=dict)
    head_metrics: Mapping[str, float] = field(default_factory=dict)
    per_song_metrics: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    baseline_deltas: Mapping[str, float] = field(default_factory=dict)
    comparable: bool = True
    refusal_status: str | None = None
    counters: GeometryAnalysisCounters = field(default_factory=GeometryAnalysisCounters)
    synthetic_only: bool = True
    queries: tuple[GeometrySongAnalysis, ...] = ()
    # Representative queries retain one scored execution per collapse class; this
    # ordered view expands the same evidence under every threshold context for
    # canonical publication and reporting.
    threshold_queries: tuple[GeometrySongAnalysis, ...] = ()
    candidates: tuple[GeometryCandidate, ...] = ()
    noncomparable: tuple[NonComparableEvidence, ...] = ()
    reasons: tuple[str, ...] = ()
    hypotheses: tuple[GeometryCorpusHypothesis, ...] = ()
    evidence_mode: str = "synthetic_fixture"
    head_evidence_provenance: Mapping[str, Any] = field(default_factory=dict)
    evaluation_corpus: tuple[GeometryEvaluationCorpusEntry, ...] = ()
    threshold_class_map: tuple[GeometryThresholdClassRow, ...] = ()
    threshold_structural: tuple[GeometryThresholdStructuralRow, ...] = ()
    class_aggregate_metrics: tuple[GeometryClassAggregateMetric, ...] = ()
    class_query_metrics: tuple[GeometryClassQueryMetric, ...] = ()
    class_neighborhoods: tuple[GeometryClassNeighborhood, ...] = ()
    baseline_aggregate_metrics: tuple[GeometryBaselineAggregateMetric, ...] = ()
    baseline_query_metrics: tuple[GeometryBaselineQueryMetric, ...] = ()
    baseline_neighborhoods: tuple[GeometryBaselineNeighborhood, ...] = ()

    def __post_init__(self) -> None:
        for name in ("run_id", "execution_id", "experiment", "evaluation_id", "numerical_profile_digest"):
            _text(getattr(self, name), name)
        object.__setattr__(self, "evaluation_corpus", tuple(self.evaluation_corpus))
        object.__setattr__(self, "threshold_class_map", tuple(self.threshold_class_map))
        object.__setattr__(self, "threshold_structural", tuple(self.threshold_structural))
        object.__setattr__(self, "class_aggregate_metrics", tuple(self.class_aggregate_metrics))
        object.__setattr__(self, "class_query_metrics", tuple(self.class_query_metrics))
        object.__setattr__(self, "class_neighborhoods", tuple(self.class_neighborhoods))
        object.__setattr__(self, "baseline_aggregate_metrics", tuple(self.baseline_aggregate_metrics))
        object.__setattr__(self, "baseline_query_metrics", tuple(self.baseline_query_metrics))
        object.__setattr__(self, "baseline_neighborhoods", tuple(self.baseline_neighborhoods))
        if self.experiment not in _EXPERIMENTS:
            raise ValueError("unknown geometry experiment")
        if isinstance(self.scoring_semantics_version, bool) or self.scoring_semantics_version < 1:
            raise ValueError("scoring_semantics_version must be positive")
        if self.refusal_status is not None:
            _text(self.refusal_status, "refusal_status")
        if not isinstance(self.comparable, bool):
            raise ValueError("comparable must be boolean")
        if not isinstance(self.synthetic_only, bool):
            raise ValueError("synthetic_only must be boolean evidence mode")
        if self.evidence_mode not in {"synthetic_fixture", "empirical_request"}:
            raise ValueError("evidence_mode must identify synthetic_fixture or empirical_request")
        object.__setattr__(self, "head_evidence_provenance", dict(self.head_evidence_provenance))
        for name in ("artist_metrics", "genre_metrics", "head_metrics", "per_song_metrics", "baseline_deltas"):
            value = _mapping(getattr(self, name), name)
            object.__setattr__(self, name, value)
            for metric in value.values():
                if isinstance(metric, Mapping):
                    for scalar in metric.values():
                        _finite(scalar, name)
                else:
                    _finite(metric, name)
        object.__setattr__(self, "reasons", tuple(str(reason) for reason in self.reasons))
        object.__setattr__(self, "hypotheses", tuple(self.hypotheses))


def _ruler_label(value: Any) -> object | None:
    """Normalize one ruler label; null and blank labels are excluded locally.

    A blank string is missing.  A semantic-head label keeps its exact full tuple, but
    an empty tuple (or one made only of blank strings) is missing, never ``unknown``.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (tuple, list)):
        items = tuple(value)
        if not items:
            return None
        if all(isinstance(item, str) and not item.strip() for item in items):
            return None
        return tuple(item.strip() if isinstance(item, str) else item for item in items)
    return value


def _geometry_ruler_metrics(
    analyses: tuple[GeometrySongAnalysis, ...],
) -> tuple[
    dict[str, float],
    dict[str, float],
    dict[str, float],
    dict[str, dict[str, float]],
    dict[str, float],
]:
    """Compute independent ranking-relevance metrics for each frozen ruler.

    Labels define relevance among the ranked leave-one-out neighborhoods.  Each
    ruler is evaluated independently and only queries with a label and at least
    one labeled relevant candidate are eligible.  Score summaries remain in the
    per-query evidence for compatibility with the persistence surface, but are
    not used as ruler relevance metrics.
    """
    labels_by_ruler = {
        "artist": {a.request.song_id: _ruler_label(a.request.artist) for a in analyses},
        "genre": {a.request.song_id: _ruler_label(a.request.genre) for a in analyses},
        "head": {a.request.song_id: _ruler_label(a.request.head_label) for a in analyses},
    }
    per_song: dict[str, dict[str, float]] = {}
    for analysis in analyses:
        song_id = analysis.request.song_id
        bundle = analysis.scores
        winner = max((float(value) for value in bundle.scores.values()), default=0.0)
        baseline = None if bundle.baseline_score is None else float(bundle.baseline_score)
        comparable = bool(bundle.scores) and baseline is not None and bundle.evaluation_comparable
        defined = bool(bundle.scores) and bundle.evaluation_comparable
        entry: dict[str, float] = {
            "winner_score": winner,
            "comparable": 1.0 if comparable else 0.0,
            "defined": 1.0 if defined else 0.0,
        }
        for ruler, labels in labels_by_ruler.items():
            entry[f"eligible_{ruler}"] = 1.0 if defined and labels.get(song_id) is not None else 0.0
        if baseline is not None:
            entry["baseline_score"] = baseline
            if comparable:
                entry["baseline_delta"] = winner - baseline
        per_song[song_id] = entry

    aggregate: dict[str, dict[str, float]] = {}
    baseline_deltas: dict[str, float] = {}
    for ruler, labels in labels_by_ruler.items():
        winner_relevance: list[float] = []
        baseline_relevance: list[float] = []
        winner_mrr: list[float] = []
        baseline_mrr: list[float] = []
        winner_p1: list[float] = []
        baseline_p1: list[float] = []
        winner_scores: list[float] = []
        baseline_scores: list[float] = []
        deltas: list[float] = []
        eligible = 0
        missing = 0
        for analysis in analyses:
            query_label = labels.get(analysis.request.song_id)
            if query_label is None or not analysis.state.defined:
                missing += 1
                continue
            candidate_labels = {
                candidate.search_representation_id: labels.get(candidate.song_id)
                for candidate in analysis.roster.representations
            }
            relevant = {key for key, label in candidate_labels.items() if label == query_label}
            eligible += 1

            def ranking_metrics(
                neighborhood: tuple[NeighborhoodEntry, ...],
                relevant_ids: set[str],
            ) -> tuple[float, float, float]:
                hits = [entry for entry in neighborhood if entry.search_representation_id in relevant_ids]
                first_rank = hits[0].rank if hits else None
                return (
                    1.0 if hits else 0.0,
                    1.0 / float(first_rank + 1) if first_rank is not None else 0.0,
                    1.0 if neighborhood and neighborhood[0].search_representation_id in relevant_ids else 0.0,
                )

            wr, wmrr, wp1 = ranking_metrics(analysis.neighborhood, relevant)
            br, bmrr, bp1 = ranking_metrics(analysis.baseline_neighborhood, relevant)
            winner_relevance.append(wr)
            baseline_relevance.append(br)
            winner_mrr.append(wmrr)
            baseline_mrr.append(bmrr)
            winner_p1.append(wp1)
            baseline_p1.append(bp1)
            winner_scores.append(max(analysis.scores.scores.values(), default=0.0))
            baseline_scores.append(float(analysis.scores.baseline_score or 0.0))
            if analysis.scores.baseline_score is not None and analysis.scores.evaluation_comparable:
                deltas.append(
                    float(max(analysis.scores.scores.values(), default=0.0)) - float(analysis.scores.baseline_score)
                )

        def mean(values: list[float]) -> float:
            return float(np.mean(values)) if values else 0.0

        metrics = {
            "active": 1.0 if eligible else 0.0,
            "n_songs": float(eligible),
            "n_compared": float(len(deltas)),
            "missing_count": float(missing),
            "mean_winner": mean(winner_scores),
            "mean_baseline": mean(baseline_scores),
            "mean_delta": mean(deltas),
            "winner_recall": mean(winner_relevance),
            "baseline_recall": mean(baseline_relevance),
            "winner_mrr": mean(winner_mrr),
            "baseline_mrr": mean(baseline_mrr),
            "winner_precision_at_1": mean(winner_p1),
            "baseline_precision_at_1": mean(baseline_p1),
        }
        aggregate[ruler] = metrics
        baseline_deltas[ruler] = metrics["mean_delta"]
    return aggregate["artist"], aggregate["genre"], aggregate["head"], per_song, baseline_deltas


def _stable_id(*parts: object) -> str:
    import hashlib

    from scripts.embedding_research.db.identity_persistence import _json

    payload = _json(parts)
    # Hash the WHOLE preimage: truncating the hex of the preimage itself made distinct ids
    # collide as soon as they shared a long prefix (e.g. per-song observed-medoid ids).
    return "geometry-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:48]


def _observation_geometry_identity(observation: Any, profile: GeometryProfile) -> GeometryIdentity:
    identity = getattr(observation, "identity", None)
    if identity is None:
        raise ValueError("committed observation has no identity")
    observation_group = getattr(identity, "observation_group_sha256", None)
    if not observation_group:
        raise ValueError("committed observation has no observation-group identity")
    semantics = profile.to_manifest().get("geometry_semantics_version")
    if not semantics:
        raise ValueError("geometry profile has no geometry semantics version")
    return GeometryIdentity(
        str(identity.song_id),
        str(identity.backbone),
        str(observation_group),
        str(semantics),
        str(profile.digest),
    )


def _selected_geometry_items(con: Any, song_ids: Any, backbones: Any) -> tuple[tuple[dict[str, Any], str], ...]:
    """Deterministic ``(song_row, backbone)`` selection for the current corpus.

    ``song_ids``/``backbones`` are optional exact filters; the default backbone set is
    the canonical single EffNet default (mirrored from ``helpers.toml``) because the
    runner always passes the configured backbone list explicitly.
    """
    requested_songs = None if song_ids is None else {str(item) for item in song_ids}
    requested_backbones = None if backbones is None else {str(item) for item in backbones}
    rows: list[tuple[dict[str, Any], str]] = []
    for song in load_all_songs(con):
        sid = str(song["song_id"])
        if requested_songs is not None and sid not in requested_songs:
            continue
        selected_backbones = sorted(requested_backbones) if requested_backbones is not None else ["effnet"]
        rows.extend((song, backbone) for backbone in selected_backbones)
    return tuple(sorted(rows, key=lambda item: (str(item[0]["song_id"]), item[1])))


def _committed_geometry_observation(
    stream_store: StreamStore, song_id: str, backbone: str, profile: GeometryProfile
) -> tuple[Any, GeometryIdentity]:
    """Load exactly one committed observation and validate its mask/resource bounds."""
    observation = stream_store.load_committed_observation(song_id, backbone)
    identity = getattr(observation, "identity", None)
    if identity is None:
        raise ValueError("committed observation has no identity")
    patch_count = getattr(identity, "patch_count", 0)
    if isinstance(patch_count, bool) or not isinstance(patch_count, int) or patch_count <= 0:
        raise ValueError("committed observation has an invalid patch count")
    require_exact_binary_mask(getattr(observation, "mask", None), patch_count)
    enforce_geometry_resource_ceiling(patch_count)
    return observation, _observation_geometry_identity(observation, profile)


def resolve_geometry_evaluation_corpus(
    items: tuple[GeometrySongRequest, ...],
    *,
    resolve_record_mask: Callable[[GeometrySongRequest], tuple[Any, np.ndarray]],
) -> tuple[GeometryEvaluationCorpusEntry, ...]:
    """Resolve the ONE fixed evaluation corpus before any threshold evaluation.

    Each entry is selected per ``(song_id, backbone)`` purely from the whole-song
    observed-global-medoid baseline representation: a finite, strictly nonzero observed
    medoid row over a valid committed binary mask.  Artist, genre, and head labels are never
    consulted, so membership cannot depend on labels or on the configured threshold set.
    The resolver performs no stream load/gather of its own; the caller supplies the
    already-loaded ``(record, mask)`` pair, keeping resolution single and threshold-independent.
    """
    entries: list[GeometryEvaluationCorpusEntry] = []
    for item in items:
        record, mask = resolve_record_mask(item)
        committed_mask = require_exact_binary_mask(mask, record.matrix.shape[0])
        searchable_count = int(np.count_nonzero(committed_mask))
        medoid, _centrality = observed_global_medoid_from_gram(
            np.asarray(record.matrix, dtype=np.float32), committed_mask
        )
        if searchable_count == 0:
            reasons: tuple[str, ...] = ("zero_searchable",)
        elif medoid is None:
            reasons = ("no_medoid",)
        else:
            reasons = ()
        baseline_valid = not reasons
        entries.append(
            GeometryEvaluationCorpusEntry(
                song_id=str(item.song_id),
                backbone=str(item.backbone),
                geometry_id=str(record.geometry_id),
                observation_group_sha256=str(item.geometry_identity.observation_group_sha256),
                numerical_profile_digest=str(item.geometry_identity.numerical_profile_digest),
                searchable_count=searchable_count,
                comparable=baseline_valid,
                reasons=reasons,
                baseline_valid=baseline_valid,
            )
        )
    return tuple(entries)


def verify_geometry_evaluation_corpus(entries: tuple[GeometryEvaluationCorpusEntry, ...]) -> str:
    """Refuse an empty, invalid-baseline, or cross-backbone evaluation corpus.

    Returns the single resolved backbone.  Raising :class:`IntegrityRefused` refuses the
    analyze request instead of silently shrinking the corpus or crossing backbones.
    """
    if not entries:
        raise IntegrityRefused("INTEGRITY_REFUSED: geometry evaluation corpus is empty")
    backbones = {entry.backbone for entry in entries}
    if len(backbones) != 1:
        raise IntegrityRefused("INTEGRITY_REFUSED: geometry evaluation corpus spans multiple backbones")
    invalid = tuple(entry for entry in entries if not entry.baseline_valid)
    if invalid:
        detail = "; ".join(
            f"{entry.song_id}/{entry.backbone}:{','.join(entry.reasons) or 'baseline_invalid'}" for entry in invalid
        )
        raise IntegrityRefused(f"INTEGRITY_REFUSED: geometry evaluation corpus has no valid baseline for {detail}")
    return next(iter(backbones))


def analyze_geometry_corpus(
    request: GeometryCorpusRequest,
    *,
    con: Any,
    stream_store: StreamStore,
    profile: GeometryProfile,
    scoring: Any = score_bounded_exact,
) -> GeometryCorpusAnalysis:
    """Evaluate complete threshold-scoped corpus hypotheses with bounded leave-one-out scoring.

    Stage one loads exactly one committed observation and geometry per song/backbone
    and derives all requested thresholds before any scorer call.  Stage two builds the
    corpus-wide representations, collapses thresholds only when every included scoring
    input matches, and scores each query against every other candidate song with the
    canonical bounded max-per-candidate-segment scorer.  A query never receives its own
    song as a candidate; the observed whole-song medoid baseline is scored against the
    same leave-one-out population.
    """
    if not isinstance(request, GeometryCorpusRequest):
        raise ValueError("a geometry corpus request is required")
    if not isinstance(request.threshold_request, PrimaryThresholdRequest):
        raise ValueError("secondary geometry analysis owner is not available")
    semantics = str(profile.to_manifest().get("geometry_semantics_version") or "")
    if not semantics:
        raise ValueError("geometry profile has no geometry semantics version")
    tuple(item.song_id for item in request.items)

    geometry_loads = observation_loads = threshold_batches = gather_count = 0
    prepared: list[dict[str, Any]] = []
    for item in request.items:
        observation = stream_store.load_committed_observation(item.song_id, item.backbone)
        observation_loads += 1
        identity = _observation_geometry_identity(observation, profile)
        if identity != item.geometry_identity:
            raise StaleRefused("requested geometry identity is superseded by the committed observation")
        record = verify_geometry_current(con, observation, profile=profile, exact_identity=item.geometry_identity)
        geometry_loads += 1
        if record is None:
            raise IntegrityRefused("INTEGRITY_REFUSED: committed geometry is absent for the corpus request")
        mask = require_exact_binary_mask(observation.mask, record.matrix.shape[0])
        thresholds = analyze_all_thresholds(record, mask, request.threshold_request, experiment=request.experiment)
        threshold_batches += 1
        # Query vectors are populated after threshold representations are built;
        # this placeholder is never used for scoring.
        query_vectors = np.zeros((0, observation.stream.shape[1]), dtype=np.float32)
        query_weights = np.zeros(0, dtype=np.float64)
        prepared.append(
            {
                "item": item,
                "record": record,
                "mask": mask,
                "thresholds": thresholds,
                "query_vectors": query_vectors,
                "query_weights": query_weights,
                "searchable_count": int(np.count_nonzero(mask)),
                "baseline": None,
            }
        )

    # Resolve the ONE fixed evaluation corpus exactly once, before any threshold evaluation.
    # Membership depends only on the whole-song baseline representation; it is never
    # re-derived per threshold and never shrunken or crossed across backbones.
    prepared_by_item = {(prep["item"].song_id, prep["item"].backbone): prep for prep in prepared}
    evaluation_corpus = resolve_geometry_evaluation_corpus(
        tuple(request.items),
        resolve_record_mask=lambda item: (
            prepared_by_item[(item.song_id, item.backbone)]["record"],
            prepared_by_item[(item.song_id, item.backbone)]["mask"],
        ),
    )
    verify_geometry_evaluation_corpus(evaluation_corpus)

    # Resolve every configured threshold's identity and materialize its complete ordered
    # preimage before any gather or scorer call.  Equal preimages are one collapse class;
    # structural threshold membership stays out of the class key.
    specs_by_index = {int(spec.index): spec for spec in request.threshold_request.thresholds}
    threshold_rows: dict[
        int,
        tuple[
            tuple[CorpusSongSearchInput, ...],
            tuple[tuple[dict[str, Any], Any, tuple[int, ...], tuple[float, ...]], ...],
        ],
    ] = {}
    class_ids: dict[int, str] = {}
    threshold_states: dict[int, tuple[bool, tuple[str, ...]]] = {}
    structural_rows: list[GeometryThresholdStructuralRow] = []
    for threshold_index in request.threshold_request.indices:
        index = int(threshold_index)
        spec = specs_by_index[index]
        search_rows: list[tuple[dict[str, Any], Any, tuple[int, ...], tuple[float, ...]]] = []
        for prep in prepared:
            result = next(result for result in prep["thresholds"].results if int(result.threshold.index) == index)
            indices, weights = _representation_scoring_pairs(result.search)
            search_rows.append((prep, result, indices, weights))
        ordered_inputs = tuple(
            CorpusSongSearchInput(
                song_id=prep["item"].song_id,
                observation_group_sha256=prep["item"].geometry_identity.observation_group_sha256,
                mask_identity=str(prep["thresholds"].mask_digest),
                medoid_source_indices=indices,
                normalized_searchable_weights=weights,
                searchable_count=int(result.search.total_searchable),
            )
            for prep, result, indices, weights in search_rows
        )
        class_ids[index] = search_representation_id(
            experiment=request.experiment,
            scoring_semantics_version=request.scoring_semantics_version,
            geometry_semantics_version=semantics,
            numerical_profile_digest=request.numerical_profile_digest,
            ordered_song_inputs=ordered_inputs,
        )
        threshold_rows[index] = (ordered_inputs, tuple(search_rows))

        threshold_comparable = True
        threshold_reasons: list[str] = []
        for prep, result, indices, weights in search_rows:
            item = prep["item"]
            alignment_ok = _alignment_ok(indices, weights)
            state = classify_representation(
                alignment_ok=alignment_ok,
                searchable_count=int(result.search.total_searchable),
                medoid_defined=bool(indices),
                candidate_count=len(request.items) - 1,
                label_defined=_label_defined(item),
            )
            if not state.comparable:
                threshold_comparable = False
            for reason in state.reasons:
                if reason not in threshold_reasons:
                    threshold_reasons.append(reason)
            structural_rows.append(
                GeometryThresholdStructuralRow(
                    song_id=item.song_id,
                    backbone=item.backbone,
                    threshold_index=index,
                    threshold_id=str(spec.threshold_id),
                    structural_identity=str(result.structural.identity),
                    search_representation_id=str(result.search.search_representation_id),
                    searchable_count=int(result.search.total_searchable),
                    medoid_defined=bool(indices),
                    alignment_ok=alignment_ok,
                    comparable=state.comparable,
                    reasons=state.reasons,
                )
            )
        threshold_states[index] = (threshold_comparable, tuple(threshold_reasons))

    class_thresholds: dict[str, list[int]] = {}
    for threshold_index in request.threshold_request.indices:
        class_thresholds.setdefault(class_ids[int(threshold_index)], []).append(int(threshold_index))

    # One map row per configured threshold, even when equal preimages collapse the class.
    threshold_class_map: list[GeometryThresholdClassRow] = []
    for class_id, threshold_indices in class_thresholds.items():
        class_comparable = all(threshold_states[index][0] for index in threshold_indices)
        class_reasons: list[str] = []
        for index in threshold_indices:
            for reason in threshold_states[index][1]:
                if reason not in class_reasons:
                    class_reasons.append(reason)
        for index in threshold_indices:
            spec = specs_by_index[index]
            threshold_class_map.append(
                GeometryThresholdClassRow(
                    threshold_index=index,
                    threshold_id=str(spec.threshold_id),
                    threshold_value=float(spec.value),
                    corpus_search_class_id=class_id,
                    comparable=class_comparable,
                    reasons=tuple(class_reasons),
                )
            )

    threshold_hypotheses: list[GeometryCorpusHypothesis] = []
    threshold_rosters: dict[str, tuple[GeometryCandidate, ...]] = {}
    threshold_members: dict[tuple[str, int], tuple[GeometryCandidate, ...]] = {}
    representative_members: dict[str, tuple[GeometryCandidate, ...]] = {}
    noncomparable: list[NonComparableEvidence] = []
    baseline_roster: dict[tuple[str, str], FrozenSearchRepresentation] = {}
    representation_cache: dict[tuple[str, str, str], FrozenSearchRepresentation] = {}

    for collapse_class_id, threshold_indices in class_thresholds.items():
        representative_threshold = threshold_indices[0]
        _ordered_inputs, stored_rows = threshold_rows[representative_threshold]
        class_members: list[GeometryCandidate] = []
        for prep, result, indices, weights in stored_rows:
            item = prep["item"]
            state = classify_representation(
                alignment_ok=_alignment_ok(indices, weights),
                searchable_count=int(result.search.total_searchable),
                medoid_defined=bool(indices),
                candidate_count=len(request.items) - 1,
                label_defined=_label_defined(item),
            )
            cache_key = (item.song_id, item.backbone, collapse_class_id)
            representation = representation_cache.get(cache_key)
            if representation is None:
                if state.comparable:
                    vectors = stream_store.batch_gather(item.song_id, item.backbone, indices, forbid_duplicates=True)
                    gather_count += 1
                else:
                    vectors = np.zeros((0, prep["record"].matrix.shape[1]), dtype=np.float32)
                    indices = ()
                    weights = ()
                representation = FrozenSearchRepresentation(
                    item.song_id,
                    item.backbone,
                    indices,
                    vectors,
                    np.asarray(weights, dtype=np.float64),
                    f"{collapse_class_id}:{item.song_id}:{item.backbone}",
                    prep["record"].geometry_id,
                    item.geometry_identity.observation_group_sha256,
                    str(result.search.profile_digest),
                    str(result.search.mask_digest),
                    int(result.search.scoring_semantics_version),
                    request.experiment,
                    tuple(threshold_indices),
                )
                representation_cache[cache_key] = representation
            class_members.append(
                GeometryCandidate(
                    representation,
                    state,
                    str(result.structural.identity),
                    tuple(threshold_indices),
                    int(result.search.total_searchable),
                )
            )
        representative_members[collapse_class_id] = tuple(class_members)
        for threshold_index in threshold_indices:
            _inputs, rows = threshold_rows[threshold_index]
            members_list: list[GeometryCandidate] = []
            for prep, result, indices, weights in rows:
                item = prep["item"]
                state = classify_representation(
                    alignment_ok=_alignment_ok(indices, weights),
                    searchable_count=int(result.search.total_searchable),
                    medoid_defined=bool(indices),
                    candidate_count=len(request.items) - 1,
                    label_defined=_label_defined(item),
                )
                if not state.comparable:
                    noncomparable.append(
                        NonComparableEvidence(
                            item.song_id,
                            item.backbone,
                            (int(threshold_index),),
                            str(result.structural.identity),
                            collapse_class_id,
                            state.reasons,
                        )
                    )
                representation = next(
                    member.representation for member in class_members if member.representation.song_id == item.song_id
                )
                members_list.append(
                    GeometryCandidate(
                        representation,
                        state,
                        str(result.structural.identity),
                        (int(threshold_index),),
                        int(result.search.total_searchable),
                    )
                )
            members = tuple(members_list)
            threshold_members[(collapse_class_id, int(threshold_index))] = members
            threshold_hypotheses.append(GeometryCorpusHypothesis(str(threshold_index), collapse_class_id, members))
            threshold_rosters[str(threshold_index)] = members

    # Build the observed global-medoid roster independently of winner representations.
    for prep in prepared:
        item = prep["item"]
        medoid, _centrality = observed_global_medoid_from_gram(
            np.asarray(prep["record"].matrix, dtype=np.float32), prep["mask"]
        )
        if medoid is None:
            continue
        baseline_indices = (int(medoid),)
        baseline_vectors = stream_store.batch_gather(
            item.song_id, item.backbone, baseline_indices, forbid_duplicates=True
        )
        gather_count += 1
        baseline_roster[(item.song_id, item.backbone)] = FrozenSearchRepresentation(
            item.song_id,
            item.backbone,
            baseline_indices,
            baseline_vectors,
            np.ones(1, dtype=np.float64),
            _stable_id("observed-medoid", item.geometry_identity.observation_group_sha256, medoid),
            prep["record"].geometry_id,
            item.geometry_identity.observation_group_sha256,
            str(profile.digest),
            str(item.observation_evidence.get("mask_payload_sha256", "")),
            request.scoring_semantics_version,
            request.experiment,
            (),
            True,
        )

    # Evaluate once per collapse class and song, never once per threshold copy.
    queries: list[GeometrySongAnalysis] = []
    scorer_count = 0
    public_candidates: list[GeometryCandidate] = []
    scored_queries: dict[tuple[str, str], GeometrySongAnalysis] = {}
    for collapse_class_id, representative_members_for_class in representative_members.items():
        public_candidates.extend(member for member in representative_members_for_class if member.state.comparable)
        # Collapse may reuse equal scoring inputs, but each threshold is evaluated and published independently.
        for threshold_index in class_thresholds[collapse_class_id]:
            members = threshold_members[(collapse_class_id, threshold_index)]
            for member in members:
                cached_query = scored_queries.get((collapse_class_id, member.representation.song_id))
                if cached_query is not None:
                    threshold_roster = GeometryRepresentationRoster(
                        tuple(
                            candidate.representation
                            for candidate in members
                            if candidate.state.comparable
                            and candidate.representation.song_id != member.representation.song_id
                        )
                    )
                    queries.append(
                        replace(
                            cached_query,
                            roster=threshold_roster,
                            state=member.state,
                            threshold_id=str(threshold_index),
                        )
                    )
                    continue
                item = next(
                    item
                    for item in request.items
                    if item.song_id == member.representation.song_id and item.backbone == member.representation.backbone
                )
                winner_others = tuple(
                    candidate
                    for candidate in members
                    if candidate.state.comparable and candidate.representation.song_id != item.song_id
                )
                winner_roster = GeometryRepresentationRoster(
                    tuple(candidate.representation for candidate in winner_others)
                )
                query_state = member.state
                if not query_state.comparable or not winner_roster.representations:
                    queries.append(
                        GeometrySongAnalysis(
                            item,
                            next(prep["thresholds"] for prep in prepared if prep["item"] == item),
                            winner_roster,
                            GeometryScoreBundle(scores={}, evaluation_comparable=False),
                            state=query_state,
                            threshold_id=str(threshold_index),
                            collapse_class_id=collapse_class_id,
                        )
                    )
                    continue
                evaluation = FrozenGeometryEvaluation(
                    evaluation_id=request.evaluation_id,
                    query_vectors=member.representation.vectors,
                    query_weights=member.representation.weights,
                    eligible_song_ids=tuple(sorted(candidate.representation.song_id for candidate in winner_others)),
                    observation_evidence_digest="|".join(
                        sorted({candidate.representation.observation_group_sha256 for candidate in winner_others})
                    ),
                    comparable=True,
                )
                winner_bundle = score_unique_geometry_representations(winner_roster, evaluation, scoring)
                scorer_count += winner_bundle.scorer_call_count
                baseline_query = baseline_roster.get((item.song_id, item.backbone))
                baseline_scores: Mapping[str, float] = MappingProxyType({})
                baseline_calls = 0
                baseline_neighborhood: tuple[NeighborhoodEntry, ...] = ()
                if baseline_query is not None:
                    baseline_others = tuple(
                        rep
                        for rep in baseline_roster.values()
                        if rep.song_id != item.song_id and rep.song_id in evaluation.eligible_song_ids
                    )
                    baseline_roster_for_query = GeometryRepresentationRoster(
                        tuple(
                            FrozenSearchRepresentation(
                                rep.song_id,
                                rep.backbone,
                                rep.source_indices,
                                rep.vectors,
                                rep.weights,
                                f"{rep.search_representation_id}:baseline:{rep.song_id}:{rep.backbone}",
                                rep.geometry_id,
                                rep.observation_group_sha256,
                                rep.numerical_profile_digest,
                                rep.mask_digest,
                                rep.scoring_semantics_version,
                                rep.experiment,
                                rep.structural_member_threshold_indices,
                                False,
                            )
                            for rep in baseline_others
                        )
                    )
                    baseline_bundle = score_unique_geometry_representations(
                        baseline_roster_for_query,
                        FrozenGeometryEvaluation(
                            request.evaluation_id,
                            baseline_query.vectors,
                            baseline_query.weights,
                            evaluation.eligible_song_ids,
                            evaluation.observation_evidence_digest,
                            True,
                        ),
                        scoring,
                    )
                    baseline_scores = baseline_bundle.scores
                    baseline_calls = baseline_bundle.scorer_call_count
                    scorer_count += baseline_calls
                    baseline_lookup = {
                        rep.search_representation_id: rep for rep in baseline_roster_for_query.representations
                    }
                    baseline_neighborhood = _select_neighborhood(baseline_scores, baseline_lookup)
                lookup = {candidate.search_representation_id: candidate for candidate in winner_roster.representations}
                query_result = GeometrySongAnalysis(
                    item,
                    next(prep["thresholds"] for prep in prepared if prep["item"] == item),
                    winner_roster,
                    GeometryScoreBundle(
                        scores=winner_bundle.scores,
                        baseline_score=max(baseline_scores.values()) if baseline_scores else None,
                        baseline_representation_id=baseline_query.search_representation_id if baseline_query else None,
                        evaluation_comparable=True,
                        unique_representation_count=len(winner_roster.representations),
                        source_gather_count=len(winner_roster.representations) + len(baseline_scores),
                        scorer_call_count=winner_bundle.scorer_call_count + baseline_calls,
                    ),
                    state=query_state,
                    neighborhood=_select_neighborhood(winner_bundle.scores, lookup),
                    baseline_neighborhood=baseline_neighborhood,
                    threshold_id=str(threshold_index),
                    collapse_class_id=collapse_class_id,
                )
                scored_queries[(collapse_class_id, member.representation.song_id)] = query_result
                queries.append(query_result)
                continue

    selected_baseline = dict(baseline_roster)
    selected_members = tuple(public_candidates)
    threshold_queries = tuple(queries)
    # The canonical result is the complete threshold-scoped publication view.
    # Equal collapse classes may reuse scorer work, but no threshold evidence is
    # discarded or relabeled as a representative query.

    # Re-read the current committed tuple at the execution boundary; a superseding
    # publication must refuse before any result escapes the owner.
    for prep in prepared:
        preflight_geometry_binding(prep["record"], profile, store=stream_store)

    artist_metrics, genre_metrics, head_metrics, per_song_metrics, baseline_deltas = _geometry_ruler_metrics(
        tuple(queries)
    )
    (
        class_aggregate_metrics,
        class_query_metrics,
        class_neighborhoods,
        baseline_aggregate_metrics,
        baseline_query_metrics,
        baseline_neighborhoods,
    ) = _geometry_class_scoped_metrics(
        request=request,
        scored_queries=scored_queries,
        baseline_roster=baseline_roster,
    )
    candidates = tuple(member for member in selected_members if member.state.comparable)
    counters = GeometryAnalysisCounters(
        geometry_loads,
        observation_loads,
        threshold_batches,
        len(representation_cache),
        gather_count,
        scorer_count,
        0,
    )
    corpus_roster = GeometryRepresentationRoster(tuple(member.representation for member in candidates))
    first_baseline = next(iter(selected_baseline.values()), None)
    return GeometryCorpusAnalysis(
        request.run_id,
        request.execution_id,
        request.experiment,
        request.evaluation_id,
        request.numerical_profile_digest,
        request.scoring_semantics_version,
        analyses=tuple(prep["thresholds"] for prep in prepared),
        roster=corpus_roster,
        scores=None,
        baseline=first_baseline,
        artist_metrics=artist_metrics,
        genre_metrics=genre_metrics,
        head_metrics=head_metrics,
        per_song_metrics=per_song_metrics,
        baseline_deltas=baseline_deltas,
        comparable=bool(queries) and all(query.state.comparable for query in queries),
        counters=counters,
        synthetic_only=request.synthetic_only,
        queries=tuple(queries),
        threshold_queries=threshold_queries,
        candidates=candidates,
        noncomparable=tuple(noncomparable),
        hypotheses=tuple(threshold_hypotheses),
        evidence_mode="synthetic_fixture" if request.synthetic_only else "empirical_request",
        head_evidence_provenance=_corpus_head_provenance(request),
        evaluation_corpus=evaluation_corpus,
        threshold_class_map=tuple(threshold_class_map),
        threshold_structural=tuple(structural_rows),
        class_aggregate_metrics=class_aggregate_metrics,
        class_query_metrics=class_query_metrics,
        class_neighborhoods=class_neighborhoods,
        baseline_aggregate_metrics=baseline_aggregate_metrics,
        baseline_query_metrics=baseline_query_metrics,
        baseline_neighborhoods=baseline_neighborhoods,
    )


def _corpus_head_provenance(request: GeometryCorpusRequest) -> Mapping[str, Any]:
    """Head-suite identity provenance, kept SEPARATE from the semantic head label.

    Only items that resolved a current suite carry suite identity; items whose frozen
    semantic-head evidence is missing are omitted here (the missing case is a per-song HEAD
    ruler exclusion, never a fabricated identity or ``"unknown"`` label).
    """
    if request.synthetic_only:
        return {}
    bound = [item for item in request.items if item.head_suite_identity]
    return {
        "head_suite_identities": sorted({str(item.head_suite_identity) for item in bound}),
        "head_labels_bound": sum(item.head_label is not None for item in request.items),
        "current_head_bindings": [
            {
                "song_id": str(item.song_id),
                "backbone": str(item.backbone),
                "head_suite_identity": str(item.head_suite_identity),
            }
            for item in bound
        ],
        "source": "current_committed_head_suite",
    }


def build_geometry_corpus_request(
    con: Any,
    *,
    stream_store: StreamStore,
    profile: GeometryProfile,
    threshold_request: PrimaryThresholdRequest | SecondaryChebyshevRequest,
    experiment: str,
    evaluation_id: str,
    run_id: str,
    execution_id: str,
    scoring_semantics_version: int,
    song_ids: Any = None,
    backbones: Any = None,
    head_store: Any = None,
    synthetic_only: bool = False,
) -> GeometryCorpusRequest:
    """Construct a deterministic fixture or empirical corpus request.

    Empirical mode resolves only the CURRENT committed head suite through the supplied
    store seam; fixture mode may provide labels directly on its request items.
    """
    if not isinstance(synthetic_only, bool):
        raise ValueError("synthetic_only must be boolean evidence mode")
    if not synthetic_only and head_store is None:
        raise ValueError("empirical geometry requests require a current head store")
    if not isinstance(profile, GeometryProfile):
        raise ValueError("profile must be GeometryProfile")
    items: list[GeometrySongRequest] = []
    for song, backbone in _selected_geometry_items(con, song_ids, backbones):
        song_id = str(song["song_id"])
        observation, identity = _committed_geometry_observation(stream_store, song_id, backbone, profile)
        record = verify_geometry_current(con, observation, profile=profile, exact_identity=identity)
        if record is None:
            raise IntegrityRefused("INTEGRITY_REFUSED: committed geometry is absent for the corpus request")
        head_label = None
        head_suite_identity = None
        head_provenance = None
        if synthetic_only:
            head_label = song.get("head_label")
        else:
            head_provenance = resolve_head_ruler_labels(
                head_store=head_store,
                stream_store=stream_store,
                song_id=song_id,
                backbone=backbone,
            )
            if head_provenance is not None:
                # The ruler label is the song's ACTIVATION-DERIVED frozen semantic tuple.
                head_label = head_provenance.full_tuple
                # Head-suite identity is retained SEPARATELY as provenance only.
                head_suite_identity = head_provenance.head_set_fingerprint
        items.append(
            GeometrySongRequest(
                song_id=song_id,
                backbone=backbone,
                geometry_identity=identity,
                observation_evidence=dict(record.evidence),
                artist=str(song["artist"]) if song.get("artist") else None,
                genre=str(song["genre"]) if song.get("genre") else None,
                head_label=head_label,
                head_suite_identity=head_suite_identity,
                head_provenance=head_provenance,
                synthetic_only=synthetic_only,
            )
        )
    return GeometryCorpusRequest(
        items=tuple(items),
        threshold_request=threshold_request,
        experiment=experiment,
        evaluation_id=evaluation_id,
        scoring_semantics_version=scoring_semantics_version,
        run_id=run_id,
        execution_id=execution_id,
        numerical_profile_digest=profile.digest,
        synthetic_only=synthetic_only,
    )


_CORPUS_THRESHOLD_ID = "corpus"
_CORPUS_SEARCH_REPRESENTATION_ID = "corpus"
_GEOMETRY_CORPUS_STRATEGY_TYPE = "geometry"
_GEOMETRY_CORPUS_SIM_METRIC = "geometry"
_GEOMETRY_CORPUS_K = 0


def _assert_finite_tree(value: Any, *, where: str) -> None:
    from collections.abc import Mapping

    if isinstance(value, Mapping):
        for item in value.values():
            _assert_finite_tree(item, where=where)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _assert_finite_tree(item, where=where)
        return
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)) and not np.isfinite(float(value)):
        raise ValueError(f"non-finite geometry corpus evidence: {where}")


def _corpus_representations(result: GeometryCorpusAnalysis) -> tuple[Any, ...]:
    reps: list[Any] = []
    if result.roster is not None:
        reps.extend(result.roster.representations)
    if result.baseline is not None:
        reps.append(result.baseline)
    return tuple(reps)


def _corpus_backbones(result: GeometryCorpusAnalysis) -> tuple[str, ...]:
    backbones = {str(rep.backbone) for rep in _corpus_representations(result) if getattr(rep, "backbone", None)}
    backbones.update(str(query.request.backbone) for query in result.queries if query.request.backbone)
    ordered = tuple(sorted(backbones))
    if not ordered:
        raise ValueError("geometry corpus analysis has no backbone identity to publish")
    return ordered


def _analysis_query_pairs(result: GeometryCorpusAnalysis) -> tuple[tuple[Any, Any], ...]:
    """Align each published threshold query with its song's all-threshold analysis."""
    source_queries = result.threshold_queries or result.queries
    if not source_queries:
        return ()
    pairs: list[tuple[Any, Any]] = []
    for query in source_queries:
        analysis = query.thresholds
        if analysis not in result.analyses:
            raise ValueError("geometry corpus analyses and queries are misaligned")
        pairs.append((analysis, query))
    return tuple(pairs)


def _threshold_searchable_count(analysis: Any, threshold_id: str) -> int:
    """Exact ``total_searchable`` for one threshold, never a max across the sweep.

    ``_analysis_query_pairs`` yields one pair per ``(song, threshold)``; each pair must
    report the count of that exact ``ThresholdAnalysisResult``, not the maximum count any
    threshold in the song's sweep happened to reach.  The threshold identity is resolved
    by its canonical id or, when the query carries the bare index, by threshold index.
    """
    wanted = str(threshold_id)
    for result in analysis.results:
        if str(result.threshold.threshold_id) == wanted:
            return int(result.search.total_searchable)
    try:
        index = int(wanted)
    except ValueError:
        raise ValueError(f"threshold {threshold_id} is not present in its corpus analysis") from None
    for result in analysis.results:
        if int(result.threshold.index) == index:
            return int(result.search.total_searchable)
    raise ValueError(f"threshold {threshold_id} is not present in its corpus analysis")


def _geometry_versions(result: GeometryCorpusAnalysis) -> dict[tuple[str, str, str], str]:
    versions: dict[tuple[str, str, str], str] = {}
    for analysis in result.analyses:
        version = str(getattr(analysis, "geometry_semantics_version", ""))
        if not version:
            raise ValueError("geometry corpus analysis is missing a geometry semantics version")
        key = (str(analysis.geometry_id), str(analysis.observation_group_sha256), str(analysis.profile_digest))
        existing = versions.setdefault(key, version)
        if existing != version:
            raise ValueError("mixed geometry semantics version across corpus analyses")
    return versions


def _geometry_axes_payload(result: GeometryCorpusAnalysis) -> list[dict[str, str]]:
    """Per-song geometry axes; falls back to threshold analyses when no candidate is searchable."""
    versions = _geometry_versions(result)
    reps = _corpus_representations(result)
    if reps:
        axes: list[dict[str, str]] = []
        for rep in reps:
            key = (str(rep.geometry_id), str(rep.observation_group_sha256), str(rep.numerical_profile_digest))
            version = versions.get(key)
            if version is None:
                raise ValueError("representation has no matching corpus geometry identity")
            axes.append(
                {
                    "song_id": str(rep.song_id),
                    "backbone": str(rep.backbone),
                    "geometry_id": str(rep.geometry_id),
                    "observation_group_sha256": str(rep.observation_group_sha256),
                    "geometry_semantics_version": version,
                    "numerical_profile_digest": str(rep.numerical_profile_digest),
                }
            )
        return axes
    pairs = _analysis_query_pairs(result)
    if not pairs:
        raise ValueError("geometry corpus analysis has no representation evidence to publish")
    return [
        {
            "song_id": str(query.request.song_id),
            "backbone": str(query.request.backbone),
            "geometry_id": str(analysis.geometry_id),
            "observation_group_sha256": str(analysis.observation_group_sha256),
            "geometry_semantics_version": str(analysis.geometry_semantics_version),
            "numerical_profile_digest": str(analysis.profile_digest),
        }
        for analysis, query in pairs
    ]


def _revalidate_geometry_bindings(
    result: GeometryCorpusAnalysis,
    con: Any,
    *,
    stream_store: Any = None,
    profile: GeometryProfile | None = None,
) -> None:
    for axis in _geometry_axes_payload(result):
        identity = GeometryIdentity(
            axis["song_id"],
            axis["backbone"],
            axis["observation_group_sha256"],
            axis["geometry_semantics_version"],
            axis["numerical_profile_digest"],
        )
        if stream_store is not None and profile is not None:
            record, _observation = require_current_geometry(
                str(axis["song_id"]), str(axis["backbone"]), con, store=stream_store, profile=profile
            )
        else:
            record = read_geometry(identity, con)
        if str(record.geometry_id) != axis["geometry_id"]:
            raise ValueError("stale geometry binding for corpus representation")


def build_geometry_corpus_identity(result: GeometryCorpusAnalysis) -> AnalysisEvidenceIdentity:
    """Deterministic corpus-level identity over every ordered member geometry.

    Multi-song corpora carry a distinct per-song ``geometry_id``; the corpus scope is
    therefore identified by a canonical digest of the ordered member geometry/observation
    identities, never by one arbitrary song's geometry row.
    """
    if not result.analyses:
        raise ValueError("geometry corpus analysis has no threshold analyses")
    members = sorted(
        (
            str(analysis.geometry_id),
            str(analysis.observation_group_sha256),
            str(analysis.profile_digest),
            str(analysis.geometry_semantics_version),
        )
        for analysis in result.analyses
    )
    versions = {member[3] for member in members}
    if len(versions) != 1:
        raise ValueError("mixed geometry semantics version across corpus analyses")
    digests = {member[2] for member in members}
    if len(digests) != 1:
        raise ValueError("mixed numerical profile digest across corpus analyses")
    return AnalysisEvidenceIdentity(
        geometry_id=_stable_id("corpus-geometry", [member[0] for member in members]),
        observation_group_sha256=_stable_id("corpus-observation", [member[1] for member in members]),
        geometry_semantics_version=next(iter(versions)),
        numerical_profile_digest=next(iter(digests)),
        threshold_id=_CORPUS_THRESHOLD_ID,
        structural_identity=f"{result.experiment}:corpus",
        evaluation_id=str(result.evaluation_id),
        search_representation_id=_CORPUS_SEARCH_REPRESENTATION_ID,
        scoring_semantics_version=int(result.scoring_semantics_version),
        execution_id=str(result.execution_id),
    )


def _corpus_evidence_identity(result: GeometryCorpusAnalysis) -> Any:
    return build_geometry_corpus_identity(result)


def _corpus_reasons(result: GeometryCorpusAnalysis) -> tuple[str, ...]:
    reasons = {str(reason) for query in result.queries for reason in query.state.reasons}
    reasons.update(str(reason) for evidence in result.noncomparable for reason in evidence.reasons)
    return tuple(sorted(reasons))


def _membership_entries(result: GeometryCorpusAnalysis) -> tuple[GeometryMembershipEntry, ...]:
    pairs = _analysis_query_pairs(result)
    if pairs:
        return tuple(
            GeometryMembershipEntry(
                song_id=str(query.request.song_id),
                backbone=str(query.request.backbone),
                observation_group_sha256=str(query.request.geometry_identity.observation_group_sha256),
                geometry_id=str(analysis.geometry_id),
                numerical_profile_digest=str(analysis.profile_digest),
                comparable=query.state.comparable,
                defined=query.state.defined,
                eligible=query.state.eligible,
                reasons=query.state.reasons,
                searchable_count=_threshold_searchable_count(analysis, str(query.threshold_id)),
            )
            for analysis, query in pairs
        )
    entries: list[GeometryMembershipEntry] = []
    for candidate in result.candidates:
        representation = candidate.representation
        entries.append(
            GeometryMembershipEntry(
                song_id=str(representation.song_id),
                backbone=str(representation.backbone),
                observation_group_sha256=str(representation.observation_group_sha256),
                geometry_id=str(representation.geometry_id),
                numerical_profile_digest=str(representation.numerical_profile_digest),
                comparable=candidate.state.comparable,
                defined=candidate.state.defined,
                eligible=candidate.state.eligible,
                reasons=candidate.state.reasons,
                searchable_count=int(candidate.searchable_count),
            )
        )
    return tuple(entries)


def _query_evidence_entries(result: GeometryCorpusAnalysis) -> tuple[GeometryQueryEvidence, ...]:
    source_queries = result.threshold_queries or result.queries
    # Key searchable counts by (song, threshold) so a threshold-scoped query never inherits
    # another threshold's count through a song-only lookup.
    searchable = {
        (str(query.request.song_id), str(query.threshold_id)): _threshold_searchable_count(
            analysis, str(query.threshold_id)
        )
        for analysis, query in _analysis_query_pairs(result)
    }
    if not searchable:
        for entry in _membership_entries(result):
            searchable[(str(entry.song_id), "")] = entry.searchable_count
    entries: list[GeometryQueryEvidence] = []
    for query in source_queries:
        bundle = query.scores
        winner = max((float(value) for value in bundle.scores.values()), default=0.0)
        baseline = None if bundle.baseline_score is None else float(bundle.baseline_score)
        delta = winner - baseline if (baseline is not None and query.state.comparable) else None
        entries.append(
            GeometryQueryEvidence(
                song_id=str(query.request.song_id),
                backbone=str(query.request.backbone),
                comparable=query.state.comparable,
                defined=query.state.defined,
                eligible=query.state.eligible,
                reasons=query.state.reasons,
                winner_score=winner,
                baseline_score=baseline,
                baseline_delta=delta,
                searchable_count=int(searchable.get((str(query.request.song_id), str(query.threshold_id)), 0)),
                neighborhood=query.neighborhood,
                baseline_neighborhood=query.baseline_neighborhood,
                threshold_id=str(query.threshold_id),
                collapse_class_id=str(query.collapse_class_id),
            )
        )
    return tuple(entries)


def _corpus_metrics(result: GeometryCorpusAnalysis) -> dict[str, float]:
    from dataclasses import asdict

    metrics: dict[str, float] = {}
    for prefix, mapping in (
        ("artist", result.artist_metrics),
        ("genre", result.genre_metrics),
        ("head", result.head_metrics),
    ):
        for key, value in mapping.items():
            metrics[f"{prefix}_{key}"] = float(value)
    for key, value in result.baseline_deltas.items():
        metrics[f"delta_{key}"] = float(value)
    for key, value in asdict(result.counters).items():
        metrics[f"counter_{key}"] = float(value)
    return metrics


def _hypothesis_payload(hypothesis: GeometryCorpusHypothesis) -> dict[str, Any]:
    """Encode ordered threshold/collapse members without persisting vector arrays."""
    members: list[dict[str, Any]] = []
    for member in hypothesis.members:
        representation = member.representation
        members.append(
            {
                "song_id": str(representation.song_id),
                "backbone": str(representation.backbone),
                "search_representation_id": str(representation.search_representation_id),
                "geometry_id": str(representation.geometry_id),
                "observation_group_sha256": str(representation.observation_group_sha256),
                "numerical_profile_digest": str(representation.numerical_profile_digest),
                "mask_digest": str(representation.mask_digest),
                "experiment": str(representation.experiment),
                "source_indices": [int(value) for value in representation.source_indices],
                "weights": [float(value) for value in representation.weights],
                "structural_member_threshold_indices": [
                    int(value) for value in representation.structural_member_threshold_indices
                ],
                "comparable": bool(member.state.comparable),
                "defined": bool(member.state.defined),
                "eligible": bool(member.state.eligible),
                "reasons": list(member.state.reasons),
                "structural_identity": str(member.structural_identity),
                "threshold_indices": [int(value) for value in member.threshold_indices],
                "searchable_count": int(member.searchable_count),
            }
        )
    return {
        "threshold_id": hypothesis.threshold_id,
        "collapse_class_id": hypothesis.collapse_class_id,
        "members": members,
    }


def _corpus_evidence(result: GeometryCorpusAnalysis) -> dict[str, Any]:
    from dataclasses import asdict

    membership = _membership_entries(result)
    hypotheses = [_hypothesis_payload(item) for item in result.hypotheses]
    return {
        "role": "corpus",
        "run_id": str(result.run_id),
        "execution_id": str(result.execution_id),
        "evaluation_id": str(result.evaluation_id),
        "experiment": str(result.experiment),
        "numerical_profile_digest": str(result.numerical_profile_digest),
        "scoring_semantics_version": int(result.scoring_semantics_version),
        "comparable": bool(result.comparable),
        "reasons": list(_corpus_reasons(result)),
        "counters": asdict(result.counters),
        "artist_metrics": {key: float(value) for key, value in result.artist_metrics.items()},
        "genre_metrics": {key: float(value) for key, value in result.genre_metrics.items()},
        "head_metrics": {key: float(value) for key, value in result.head_metrics.items()},
        "per_song_metrics": {
            str(song): {key: float(value) for key, value in values.items()}
            for song, values in result.per_song_metrics.items()
        },
        "baseline_deltas": {key: float(value) for key, value in result.baseline_deltas.items()},
        "threshold_map": [
            {
                "song_id": str(query.request.song_id),
                "backbone": str(query.request.backbone),
                "threshold_id": str(item.threshold.threshold_id),
                "structural_identity": str(getattr(item.structural, "identity", "")),
                "search_representation_id": str(item.search.search_representation_id),
                "comparable": (str(query.request.song_id), str(item.search.search_representation_id))
                not in {(ev.song_id, ev.search_representation_id) for ev in result.noncomparable},
            }
            for analysis, query in _analysis_query_pairs(result)
            for item in analysis.results
        ],
        "membership": [asdict(entry) for entry in membership],
        "missing_searchable": sorted({entry.song_id for entry in membership if entry.searchable_count == 0}),
        "queries": [asdict(entry) for entry in _query_evidence_entries(result)],
        "noncomparable": [asdict(evidence) for evidence in result.noncomparable],
        "geometry_axes": _geometry_axes_payload(result),
        "hypotheses": hypotheses,
        "evidence_mode": str(result.evidence_mode),
        "synthetic_only": bool(result.synthetic_only),
        "head_evidence_provenance": dict(result.head_evidence_provenance),
    }


def _head_label_provenance_rows(result: GeometryCorpusAnalysis) -> tuple[Any, ...]:
    """Build per-song head-label provenance rows for an empirical run.

    Synthetic fixtures carry no frozen head-suite provenance, so they persist nothing here.
    An empirical request whose frozen head evidence is missing persists ``present=False`` for
    that ``(song, backbone)`` so the HEAD ruler exclusion is explicit, never an "unknown" label.
    """
    if result.synthetic_only:
        return ()
    rows: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for query in (*result.queries, *result.threshold_queries):
        request = query.request
        key = (str(request.song_id), str(request.backbone))
        if key in seen:
            continue
        seen.add(key)
        label = request.head_provenance
        if label is None:
            rows.append(SimpleNamespace(song_id=key[0], backbone=key[1], present=False))
        else:
            rows.append(label)
    return tuple(rows)


def _result_provenance_row(result: GeometryCorpusAnalysis) -> GeometryResultProvenanceRow:
    """Assemble the ONE compact provenance row for a corpus result."""
    versions = set(_geometry_versions(result).values())
    if len(versions) != 1:
        raise ValueError("geometry corpus provenance requires a single geometry semantics version")
    return GeometryResultProvenanceRow(
        execution_id=str(result.execution_id),
        evaluation_id=str(result.evaluation_id),
        experiment=str(result.experiment),
        scoring_semantics_version=int(result.scoring_semantics_version),
        geometry_semantics_version=next(iter(versions)),
        numerical_profile_digest=str(result.numerical_profile_digest),
        evidence_mode=str(result.evidence_mode),
        synthetic_only=bool(result.synthetic_only),
        comparable=bool(result.comparable),
        reasons=_corpus_reasons(result),
        geometry_axes=tuple(_geometry_axes_payload(result)),
        head_evidence_provenance=result.head_evidence_provenance,
        counters=asdict(result.counters),
    )


def write_geometry_corpus_analysis(
    con: Any,
    *,
    run_id: str,
    result: GeometryCorpusAnalysis,
    stream_store: Any = None,
    profile: GeometryProfile | None = None,
) -> None:
    """Publish one complete finite geometry corpus analysis atomically.

    Every geometry/observation/profile/mask/threshold/structural/search/evaluation/scoring/
    execution identity and finite value is preflighted, the mandatory observed baseline is
    persisted before any other aggregate evidence, every geometry binding is revalidated
    before commit, and the invocation is terminalized only after complete publication.  Any
    refusal rolls back every output; there is no threshold-result table or compatibility path.
    """
    from types import SimpleNamespace

    from scripts.embedding_research.db.analyze_scope import (
        invocation_state,
        record_analyze_invocation,
        terminalize_analyze_completed,
        unresolved_obligations,
    )
    from scripts.embedding_research.db.identity_persistence import (
        write_analysis_rows_in_transaction,
        write_evaluation_corpus_in_transaction,
        write_head_label_provenance_in_transaction,
        write_threshold_class_map_in_transaction,
        write_threshold_structural_in_transaction,
    )
    from scripts.embedding_research.db.result_surfaces import (
        write_baseline_aggregate_metrics_in_transaction,
        write_baseline_neighborhoods_in_transaction,
        write_baseline_query_metrics_in_transaction,
        write_class_aggregate_metrics_in_transaction,
        write_class_neighborhoods_in_transaction,
        write_class_query_metrics_in_transaction,
        write_result_provenance_in_transaction,
    )

    if not isinstance(result, GeometryCorpusAnalysis) or result.refusal_status:
        raise ValueError("refused geometry analysis cannot be published")
    expected_mode = "synthetic_fixture" if result.synthetic_only else "empirical_request"
    if result.evidence_mode != expected_mode:
        raise ValueError("geometry corpus evidence mode does not match request mode")
    if not result.synthetic_only:
        provenance = result.head_evidence_provenance
        if not provenance or provenance.get("source") != "current_committed_head_suite":
            raise IntegrityRefused("INTEGRITY_REFUSED: empirical geometry evidence lacks frozen-head provenance")
        identities = provenance.get("head_suite_identities")
        if not isinstance(identities, (tuple, list)) or not identities or any(not str(item) for item in identities):
            raise IntegrityRefused("INTEGRITY_REFUSED: empirical geometry evidence has incomplete head provenance")
    if not run_id or str(result.run_id) != str(run_id):
        raise ValueError("geometry corpus run identity does not match the publication run")

    corpus_identity = _corpus_evidence_identity(result)
    corpus_metrics = _corpus_metrics(result)
    corpus_evidence = _corpus_evidence(result)
    _assert_finite_tree(corpus_metrics, where="corpus")
    _assert_finite_tree(corpus_evidence, where="corpus-evidence")

    # Structural/search evidence is one row per (song, threshold): iterate each song's
    # all-threshold analysis exactly once. Collapse-class queries reuse the same analysis,
    # so they must not multiply the O(N x T) evidence writes or duplicate the analysis identity.
    contexts: list[tuple[Any, str, str]] = []
    seen_analyses: set[int] = set()
    for query in result.threshold_queries or result.queries:
        analysis = query.thresholds
        if id(analysis) in seen_analyses:
            continue
        seen_analyses.add(id(analysis))
        contexts.append((analysis, str(query.request.song_id), str(query.request.backbone)))
    if not contexts:
        contexts = [(analysis, "", "") for analysis in result.analyses]
    noncomparable_ids = {(ev.song_id, ev.search_representation_id) for ev in result.noncomparable}
    per_threshold: list[tuple[Any, dict[str, float], dict[str, Any]]] = []
    for analysis, song_id, backbone in contexts:
        for item in analysis.results:
            threshold_identity = SimpleNamespace(
                geometry_id=str(item.search.geometry_id),
                observation_group_sha256=str(item.search.observation_group_sha256),
                geometry_semantics_version=str(analysis.geometry_semantics_version),
                numerical_profile_digest=str(item.search.profile_digest),
                threshold_id=str(item.threshold.threshold_id),
                structural_identity=str(getattr(item.structural, "identity", "")),
                evaluation_id=str(result.evaluation_id),
                search_representation_id=str(item.search.search_representation_id),
                scoring_semantics_version=int(item.search.scoring_semantics_version),
                execution_id=str(result.execution_id),
            )
            metrics = {
                "total_searchable": float(item.search.total_searchable),
                "searchable_weight_sum": float(np.sum(np.asarray(item.search.searchable_weights, dtype=np.float64))),
            }
            _assert_finite_tree(metrics, where="threshold")
            per_threshold.append(
                (
                    threshold_identity,
                    metrics,
                    {
                        "role": "threshold",
                        "experiment": str(result.experiment),
                        "song_id": song_id,
                        "backbone": backbone,
                        "comparable": (song_id, str(item.search.search_representation_id)) not in noncomparable_ids,
                        "geometry_semantics_version": str(analysis.geometry_semantics_version),
                        "mask_digest": str(analysis.mask_digest),
                        "structural_identity": str(getattr(item.structural, "identity", "")),
                        "scoring_semantics_version": int(item.search.scoring_semantics_version),
                    },
                )
            )

    backbones = _corpus_backbones(result)
    pairs = _analysis_query_pairs(result)
    if pairs:
        baseline_backbones = tuple(
            sorted(
                {
                    str(query.request.backbone)
                    for _analysis, query in pairs
                    if query.scores.baseline_score is not None and query.scores.baseline_representation_id is not None
                }
            )
        )
    elif result.baseline is not None:
        baseline_backbones = backbones
    else:
        baseline_backbones = ()
    _revalidate_geometry_bindings(result, con, stream_store=stream_store, profile=profile)

    con.execute("BEGIN")
    try:
        state = invocation_state(con, run_id=run_id)
        if state["terminal_completed"]:
            raise ValueError("geometry corpus run is already terminalized")
        if not state["obligations_present"]:
            record_analyze_invocation(
                con,
                run_id=run_id,
                backbones=[(backbone, str(corpus_identity.geometry_id)) for backbone in baseline_backbones],
            )
        for threshold_identity, metrics, evidence in per_threshold:
            write_analysis_rows_in_transaction(
                con, run_id=run_id, identity=threshold_identity, metrics=metrics, evidence=evidence
            )
        if baseline_backbones:
            baseline_metrics: dict[str, float] = {"baseline_present": 1.0}
            for key, value in result.baseline_deltas.items():
                baseline_metrics[f"baseline_delta_{key}"] = float(value)
            _assert_finite_tree(baseline_metrics, where="baseline")
            for backbone in baseline_backbones:
                baseline_identity = SimpleNamespace(
                    geometry_id=str(corpus_identity.geometry_id),
                    observation_group_sha256=str(corpus_identity.observation_group_sha256),
                    geometry_semantics_version=str(corpus_identity.geometry_semantics_version),
                    numerical_profile_digest=str(corpus_identity.numerical_profile_digest),
                    threshold_id=f"observed-baseline:{backbone}",
                    structural_identity=f"{result.experiment}:observed-medoid:{backbone}",
                    search_representation_id=f"observed-medoid:{backbone}",
                    evaluation_id=str(result.evaluation_id),
                    scoring_semantics_version=int(result.scoring_semantics_version),
                    execution_id=str(result.execution_id),
                )
                write_analysis_rows_in_transaction(
                    con,
                    run_id=run_id,
                    identity=baseline_identity,
                    metrics=baseline_metrics,
                    evidence={"role": "mandatory-observed-baseline", "backbone": backbone},
                )
        write_analysis_rows_in_transaction(
            con, run_id=run_id, identity=corpus_identity, metrics=corpus_metrics, evidence=corpus_evidence
        )
        write_evaluation_corpus_in_transaction(
            con,
            run_id=run_id,
            evaluation_id=str(result.evaluation_id),
            experiment=str(result.experiment),
            execution_id=str(result.execution_id),
            entries=result.evaluation_corpus,
        )
        write_threshold_class_map_in_transaction(
            con,
            run_id=run_id,
            evaluation_id=str(result.evaluation_id),
            execution_id=str(result.execution_id),
            experiment=str(result.experiment),
            rows=result.threshold_class_map,
        )
        write_threshold_structural_in_transaction(
            con,
            run_id=run_id,
            evaluation_id=str(result.evaluation_id),
            rows=result.threshold_structural,
        )
        # Normalized Experiment One result surfaces B-G + one compact provenance row.  These
        # replace the retired nested corpus blob; the prior-format corpus/analysis records above
        # are still written so Plan A Phase 7's hard cut can delete both surfaces in one step.
        write_class_aggregate_metrics_in_transaction(
            con,
            run_id=run_id,
            execution_id=str(result.execution_id),
            evaluation_id=str(result.evaluation_id),
            rows=result.class_aggregate_metrics,
        )
        write_class_query_metrics_in_transaction(con, run_id=run_id, rows=result.class_query_metrics)
        write_class_neighborhoods_in_transaction(con, run_id=run_id, rows=result.class_neighborhoods)
        write_baseline_aggregate_metrics_in_transaction(
            con,
            run_id=run_id,
            execution_id=str(result.execution_id),
            evaluation_id=str(result.evaluation_id),
            rows=result.baseline_aggregate_metrics,
        )
        write_baseline_query_metrics_in_transaction(con, run_id=run_id, rows=result.baseline_query_metrics)
        write_baseline_neighborhoods_in_transaction(con, run_id=run_id, rows=result.baseline_neighborhoods)
        head_rows = _head_label_provenance_rows(result)
        if head_rows:
            write_head_label_provenance_in_transaction(
                con,
                run_id=run_id,
                evaluation_id=str(result.evaluation_id),
                rows=head_rows,
            )
        write_result_provenance_in_transaction(con, run_id=run_id, row=_result_provenance_row(result))
        _revalidate_geometry_bindings(result, con, stream_store=stream_store, profile=profile)
        # Multi-backbone runs declare every backbone obligation up front; each execution writes
        # its own backbone-scoped baseline, and the run terminalizes exactly once, when the last
        # obligation resolves.  A single-execution write resolves immediately.
        if not unresolved_obligations(con, run_id=run_id):
            terminalize_analyze_completed(con, run_id=run_id)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def _revalidate_geometry_axis_payloads(
    axes: Any,
    con: Any,
    *,
    stream_store: Any = None,
    profile: GeometryProfile | None = None,
) -> None:
    if not isinstance(axes, list):
        raise ValueError("geometry corpus axis evidence must be a list")
    for axis in axes:
        if not isinstance(axis, dict):
            raise ValueError("geometry corpus axis evidence must be mappings")
        identity = GeometryIdentity(
            str(axis["song_id"]),
            str(axis["backbone"]),
            str(axis["observation_group_sha256"]),
            str(axis["geometry_semantics_version"]),
            str(axis["numerical_profile_digest"]),
        )
        if stream_store is not None and profile is not None:
            record, _observation = require_current_geometry(
                str(axis["song_id"]), str(axis["backbone"]), con, store=stream_store, profile=profile
            )
        else:
            record = read_geometry(identity, con)
        if str(record.geometry_id) != str(axis["geometry_id"]):
            raise ValueError("stale geometry corpus evidence")


def _validated_corpus_evidence(
    con: Any,
    *,
    run_id: str,
    identity: Any,
    stream_store: Any = None,
    profile: GeometryProfile | None = None,
) -> dict[str, Any]:
    """Read and validate the one exact corpus evidence row-set; no alternate scope."""
    from scripts.embedding_research.db.analyze_scope import invocation_state
    from scripts.embedding_research.db.identity_persistence import read_analysis_rows

    state = invocation_state(con, run_id=run_id)
    if not state["obligations_present"] or not state["terminal_completed"]:
        raise ValueError("geometry corpus invocation state is incomplete")
    rows = read_analysis_rows(con, run_id=run_id, identity=identity)
    metrics = [str(row["metric"]) for row in rows]
    if len(set(metrics)) != len(metrics):
        raise ValueError("duplicate geometry corpus evidence rows")
    for row in rows:
        if not np.isfinite(float(row["value"])):
            raise ValueError("non-finite geometry evidence")
    evidence_rows = [row["evidence"] for row in rows if isinstance(row["evidence"], dict)]
    corpus_evidence = next((ev for ev in evidence_rows if ev.get("role") == "corpus"), None)
    if corpus_evidence is None:
        raise ValueError("geometry corpus scope is missing its corpus evidence")
    if any(ev != corpus_evidence for ev in evidence_rows):
        raise ValueError("mixed geometry corpus evidence rows")
    if str(corpus_evidence.get("run_id")) != str(run_id):
        raise ValueError("geometry corpus evidence belongs to a different run")
    if str(corpus_evidence.get("execution_id")) != str(identity.execution_id):
        raise ValueError("geometry corpus evidence belongs to a different execution")
    if str(corpus_evidence.get("evaluation_id")) != str(identity.evaluation_id):
        raise ValueError("geometry corpus evidence belongs to a different evaluation")
    mode = corpus_evidence.get("evidence_mode")
    synthetic_only = corpus_evidence.get("synthetic_only")
    if mode not in {"synthetic_fixture", "empirical_request"} or not isinstance(synthetic_only, bool):
        raise ValueError("geometry corpus evidence mode is missing or malformed")
    if (mode == "synthetic_fixture") != synthetic_only:
        raise ValueError("geometry corpus evidence mode does not match synthetic_only")
    provenance = corpus_evidence.get("head_evidence_provenance")
    if mode == "empirical_request":
        if not isinstance(provenance, dict) or provenance.get("source") != "current_committed_head_suite":
            raise ValueError("empirical geometry evidence is missing frozen-head provenance")
        identities = provenance.get("head_suite_identities")
        if not isinstance(identities, list) or not identities or any(not str(item) for item in identities):
            raise ValueError("empirical geometry evidence has incomplete frozen-head provenance")
    _revalidate_geometry_axis_payloads(
        corpus_evidence.get("geometry_axes"), con, stream_store=stream_store, profile=profile
    )
    membership = corpus_evidence.get("membership")
    hypotheses = corpus_evidence.get("hypotheses")
    threshold_map = corpus_evidence.get("threshold_map")
    queries = corpus_evidence.get("queries")
    if not isinstance(membership, list) or not membership:
        raise ValueError("geometry corpus membership is missing")
    if not isinstance(hypotheses, list) or not hypotheses:
        raise ValueError("geometry corpus hypotheses are missing")
    if not isinstance(threshold_map, list) or not threshold_map:
        raise ValueError("geometry corpus threshold map is missing")
    if not isinstance(queries, list) or not queries:
        raise ValueError("geometry corpus queries are missing")
    ordered_membership = [
        (str(item.get("song_id", "")), str(item.get("backbone", ""))) for item in membership if isinstance(item, dict)
    ]
    if len(ordered_membership) != len(membership) or any(
        not song or not backbone for song, backbone in ordered_membership
    ):
        raise ValueError("geometry corpus membership is malformed")
    if len(set(ordered_membership)) != len(ordered_membership):
        raise ValueError("geometry corpus membership contains duplicate songs")
    hypothesis_context: set[tuple[str, str]] = set()
    for hypothesis in hypotheses:
        if (
            not isinstance(hypothesis, dict)
            or not hypothesis.get("threshold_id")
            or not hypothesis.get("collapse_class_id")
        ):
            raise ValueError("geometry corpus hypothesis is malformed")
        key = (str(hypothesis["threshold_id"]), str(hypothesis["collapse_class_id"]))
        if key in hypothesis_context:
            raise ValueError("geometry corpus hypothesis context is duplicated")
        hypothesis_context.add(key)
        members = hypothesis.get("members")
        if not isinstance(members, list) or not members:
            raise ValueError("geometry corpus hypothesis must contain ordered members")
        ordered = [
            (str(member.get("song_id", "")), str(member.get("backbone", "")))
            for member in members
            if isinstance(member, dict)
        ]
        if len(ordered) != len(members) or ordered != ordered_membership or len(set(ordered)) != len(ordered):
            raise ValueError("geometry corpus hypothesis omits or reorders an ordered corpus member")
        for member in members:
            indices = member.get("threshold_indices")
            source_indices = member.get("source_indices")
            weights = member.get("weights")
            if not isinstance(indices, list) or not indices:
                raise ValueError("geometry corpus hypothesis is missing threshold context")
            if any(isinstance(value, bool) or not isinstance(value, int) for value in indices):
                raise ValueError("geometry corpus hypothesis threshold indices are malformed")
            if (
                not isinstance(source_indices, list)
                or not isinstance(weights, list)
                or len(source_indices) != len(weights)
            ):
                raise ValueError("geometry corpus hypothesis source/weight alignment is malformed")
            if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in source_indices):
                raise ValueError("geometry corpus hypothesis source indices are malformed")
            if any(
                not isinstance(value, (int, float)) or isinstance(value, bool) or not np.isfinite(float(value))
                for value in weights
            ):
                raise ValueError("geometry corpus hypothesis weights are malformed")
    context_keys = set(hypothesis_context)
    for query in queries:
        if not isinstance(query, dict) or not query.get("threshold_id") or not query.get("collapse_class_id"):
            raise ValueError("geometry corpus query is missing threshold context")
        if (str(query["threshold_id"]), str(query["collapse_class_id"])) not in context_keys:
            raise ValueError("geometry corpus query mixes threshold/collapse context")
        if any(
            str(reason) not in {"alignment_failed", "zero_searchable", "no_medoid", "no_candidates", "label_missing"}
            for reason in query.get("reasons", [])
        ):
            raise ValueError("geometry corpus query has non-canonical reasons")
        query_song = str(query.get("song_id", ""))
        for key in ("neighborhood", "baseline_neighborhood"):
            neighborhood = query.get(key)
            if not isinstance(neighborhood, list):
                raise ValueError("geometry corpus neighborhood is missing")
            candidate_ids = [str(item.get("song_id", "")) for item in neighborhood if isinstance(item, dict)]
            if (
                len(candidate_ids) != len(neighborhood)
                or len(candidate_ids) != len(set(candidate_ids))
                or query_song in candidate_ids
            ):
                raise ValueError("geometry corpus neighborhood candidates must be unique and non-self")
            if key == "baseline_neighborhood" and any(
                "observed-medoid" not in str(item.get("search_representation_id", "")) for item in neighborhood
            ):
                raise ValueError("geometry corpus baseline neighborhood must use global medoid representations")
    if any("raw-query" in str(corpus_evidence) or "raw_query" in str(corpus_evidence) for _ in (0,)):
        raise ValueError("raw-query markers are forbidden in geometry corpus evidence")
    return corpus_evidence


def read_geometry_threshold_map(
    con: Any,
    *,
    run_id: str,
    identity: Any,
) -> tuple[GeometryThresholdMapEntry, ...]:
    """Read the ordered threshold map embedded in the canonical corpus evidence."""
    raw = _validated_corpus_evidence(con, run_id=run_id, identity=identity)
    return tuple(GeometryThresholdMapEntry(**item) for item in _require_evidence_list(raw, "threshold_map"))


def read_geometry_corpus_evidence(
    con: Any,
    *,
    run_id: str,
    identity: Any,
    stream_store: Any = None,
    profile: GeometryProfile | None = None,
) -> GeometryCorpusEvidence:
    """Read the complete canonical corpus evidence for one exact publication identity."""
    raw = _validated_corpus_evidence(con, run_id=run_id, identity=identity, stream_store=stream_store, profile=profile)
    membership = tuple(GeometryMembershipEntry(**item) for item in _require_evidence_list(raw, "membership"))
    threshold_map = tuple(GeometryThresholdMapEntry(**item) for item in _require_evidence_list(raw, "threshold_map"))
    queries: list[GeometryQueryEvidence] = []
    for item in _require_evidence_list(raw, "queries"):
        if not isinstance(item, dict):
            raise ValueError("geometry corpus query evidence must be a mapping")
        queries.append(
            GeometryQueryEvidence(
                **{key: value for key, value in item.items() if key not in {"neighborhood", "baseline_neighborhood"}},
                neighborhood=_parse_neighborhood(item.get("neighborhood")),
                baseline_neighborhood=_parse_neighborhood(item.get("baseline_neighborhood")),
            )
        )
    noncomparable = tuple(
        NonComparableEvidence(
            str(item["song_id"]),
            str(item["backbone"]),
            tuple(int(value) for value in item["threshold_indices"]),
            str(item["structural_identity"]),
            str(item["search_representation_id"]),
            tuple(str(v) for v in item["reasons"]),
        )
        for item in _require_evidence_list(raw, "noncomparable")
    )
    counters = raw.get("counters")
    if not isinstance(counters, dict):
        raise ValueError("geometry corpus counters are missing")
    raw_hypotheses = _require_evidence_list(raw, "hypotheses")
    {str(item.get("threshold_id")) for item in raw_hypotheses if isinstance(item, dict)}
    {
        (str(item.get("threshold_id")), str(item.get("collapse_class_id")))
        for item in raw.get("queries", [])
        if isinstance(item, dict)
    }
    for hypothesis in raw_hypotheses:
        if (
            not isinstance(hypothesis, dict)
            or not hypothesis.get("threshold_id")
            or not hypothesis.get("collapse_class_id")
        ):
            raise ValueError("geometry corpus hypothesis is malformed")
        members = hypothesis.get("members")
        if not isinstance(members, list) or not members:
            raise ValueError("geometry corpus hypothesis must contain ordered members")
        ids = [str(member.get("song_id", "")) for member in members if isinstance(member, dict)]
        if len(ids) != len(members) or len(ids) != len(set(ids)):
            raise ValueError("geometry corpus hypothesis members must be unique and ordered")
        member_thresholds = {int(value) for member in members for value in member.get("threshold_indices", [])}
        if any(
            not isinstance(value, int) or isinstance(value, bool)
            for member in members
            for value in member.get("threshold_indices", [])
        ):
            raise ValueError("geometry corpus hypothesis threshold indices are malformed")
        if not member_thresholds:
            raise ValueError("geometry corpus hypothesis is missing threshold context")
    canonical_reasons = {"alignment_failed", "zero_searchable", "no_medoid", "no_candidates", "label_missing"}
    for query in raw.get("queries", []):
        if not isinstance(query, dict) or not query.get("threshold_id") or not query.get("collapse_class_id"):
            raise ValueError("geometry corpus query is missing threshold context")
        if any(str(reason) not in canonical_reasons for reason in query.get("reasons", [])):
            raise ValueError("geometry corpus query has non-canonical reasons")
        for key in ("neighborhood", "baseline_neighborhood"):
            neighborhood = query.get(key)
            if not isinstance(neighborhood, list):
                raise ValueError("geometry corpus neighborhood is missing")
            candidate_ids = [str(item.get("song_id", "")) for item in neighborhood if isinstance(item, dict)]
            if len(candidate_ids) != len(set(candidate_ids)):
                raise ValueError("geometry corpus neighborhood candidates must be unique")
            if str(query.get("song_id")) in candidate_ids:
                raise ValueError("geometry corpus neighborhood cannot contain the query song")
            if (
                key == "baseline_neighborhood"
                and neighborhood
                and any("observed-medoid" not in str(item.get("search_representation_id", "")) for item in neighborhood)
            ):
                raise ValueError("geometry corpus baseline neighborhood must use global medoid representations")
    return GeometryCorpusEvidence(
        run_id=str(raw["run_id"]),
        execution_id=str(raw["execution_id"]),
        evaluation_id=str(raw["evaluation_id"]),
        experiment=str(raw["experiment"]),
        numerical_profile_digest=str(raw["numerical_profile_digest"]),
        scoring_semantics_version=int(raw["scoring_semantics_version"]),
        comparable=bool(raw["comparable"]),
        reasons=tuple(str(v) for v in raw.get("reasons", ())),
        membership=membership,
        missing_searchable=tuple(str(v) for v in raw.get("missing_searchable", ())),
        queries=tuple(queries),
        noncomparable=noncomparable,
        threshold_map=threshold_map,
        artist_metrics={str(k): float(v) for k, v in raw["artist_metrics"].items()},
        genre_metrics={str(k): float(v) for k, v in raw["genre_metrics"].items()},
        head_metrics={str(k): float(v) for k, v in raw["head_metrics"].items()},
        per_song_metrics={
            str(k): {str(n): float(v) for n, v in values.items()} for k, values in raw["per_song_metrics"].items()
        },
        baseline_deltas={str(k): float(v) for k, v in raw["baseline_deltas"].items()},
        counters=GeometryAnalysisCounters(**counters),
        hypotheses=tuple(dict(item) for item in _require_evidence_list(raw, "hypotheses")),
        evidence_mode=str(raw["evidence_mode"]),
        head_evidence_provenance=dict(raw["head_evidence_provenance"]),
    )


def read_geometry_corpus_analysis(
    con: Any,
    *,
    run_id: str,
    identity: Any,
    stream_store: Any = None,
    profile: GeometryProfile | None = None,
) -> GeometryCorpusAnalysis:
    """Read exactly one complete geometry corpus scope; no alternate scope is selected."""
    corpus_evidence = read_geometry_corpus_evidence(
        con, run_id=run_id, identity=identity, stream_store=stream_store, profile=profile
    )
    counters = corpus_evidence.counters
    return GeometryCorpusAnalysis(
        run_id=str(run_id),
        execution_id=str(identity.execution_id),
        experiment=corpus_evidence.experiment,
        evaluation_id=str(identity.evaluation_id),
        numerical_profile_digest=str(identity.numerical_profile_digest),
        scoring_semantics_version=corpus_evidence.scoring_semantics_version,
        analyses=(),
        roster=None,
        scores=None,
        baseline=None,
        artist_metrics=corpus_evidence.artist_metrics,
        genre_metrics=corpus_evidence.genre_metrics,
        head_metrics=corpus_evidence.head_metrics,
        per_song_metrics=corpus_evidence.per_song_metrics,
        baseline_deltas=corpus_evidence.baseline_deltas,
        comparable=corpus_evidence.comparable,
        reasons=corpus_evidence.reasons,
        counters=counters,
        evidence_mode=corpus_evidence.evidence_mode,
        head_evidence_provenance=corpus_evidence.head_evidence_provenance,
    )


def _normalized_reasons(value: Any, where: str) -> tuple[str, ...]:
    """Return the canonical reason tuple, refusing any reason outside the vocabulary."""
    reasons = tuple(str(reason) for reason in (value or ()))
    for reason in reasons:
        if reason not in _CANONICAL_RESULT_REASONS:
            raise IntegrityRefused(f"INTEGRITY_REFUSED: {where} carries a non-canonical reason")
    return reasons


def _normalized_finite(value: Any, where: str) -> float:
    """Return a finite float, refusing a missing/non-finite metric value."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise IntegrityRefused(f"INTEGRITY_REFUSED: {where} must be a finite number") from None
    if not bool(np.isfinite(result)):
        raise IntegrityRefused(f"INTEGRITY_REFUSED: {where} must be a finite number")
    return result


def _normalized_index(value: Any, where: str) -> int:
    """Return a non-negative int index, refusing booleans and negatives."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise IntegrityRefused(f"INTEGRITY_REFUSED: {where} must be a non-negative integer")
    return value


def _normalized_positive(value: Any, where: str) -> int:
    """Return a positive int, refusing anything below one."""
    result = _normalized_index(value, where)
    if result < 1:
        raise IntegrityRefused(f"INTEGRITY_REFUSED: {where} must be a positive integer")
    return result


def _normalized_choice(value: Any, allowed: frozenset[str], where: str) -> str:
    """Return a value constrained to the canonical vocabulary for its column."""
    result = str(value)
    if result not in allowed:
        raise IntegrityRefused(f"INTEGRITY_REFUSED: {where} is not a canonical value")
    return result


def _normalized_unique(keys: Iterable[Any], where: str) -> None:
    """Refuse a surface whose rows do not carry a unique identity."""
    materialized = list(keys)
    if len(materialized) != len(set(materialized)):
        raise IntegrityRefused(f"INTEGRITY_REFUSED: duplicate {where} identity rows")


def _normalized_neighborhood_key(row: Mapping[str, Any], scope_column: str, where: str) -> tuple[str, str, str]:
    """Return a neighborhood identity, refusing a query that is its own candidate."""
    query = str(row["query_song_id"])
    candidate = str(row["candidate_song_id"])
    if query == candidate:
        raise IntegrityRefused(f"INTEGRITY_REFUSED: {where} row is self-referential")
    return (str(row[scope_column]), query, candidate)


def _normalized_provenance_row(row: Mapping[str, Any]) -> GeometryResultProvenanceRow:
    """Rebuild the ONE compact provenance row from its decoded surface columns."""
    return GeometryResultProvenanceRow(
        execution_id=str(row["execution_id"]),
        evaluation_id=str(row["evaluation_id"]),
        experiment=str(row["experiment"]),
        scoring_semantics_version=_normalized_positive(row["scoring_semantics_version"], "scoring_semantics_version"),
        geometry_semantics_version=str(row["geometry_semantics_version"]),
        numerical_profile_digest=str(row["numerical_profile_digest"]),
        evidence_mode=str(row["evidence_mode"]),
        synthetic_only=bool(row["synthetic_only"]),
        comparable=bool(row["comparable"]),
        reasons=_normalized_reasons(row.get("reasons"), "result provenance"),
        geometry_axes=tuple(dict(axis) for axis in row.get("geometry_axes", ())),
        head_evidence_provenance=dict(row.get("head_evidence_provenance", {})),
        counters=dict(row.get("counters", {})),
    )


def _verify_normalized_identity(identity: AnalysisEvidenceIdentity, provenance: GeometryResultProvenanceRow) -> None:
    """Refuse unless every reconstructible axis of the exact ten-axis identity matches."""
    axes = (
        ("execution_id", identity.execution_id, provenance.execution_id),
        ("evaluation_id", identity.evaluation_id, provenance.evaluation_id),
        ("scoring_semantics_version", identity.scoring_semantics_version, provenance.scoring_semantics_version),
        ("numerical_profile_digest", identity.numerical_profile_digest, provenance.numerical_profile_digest),
        ("geometry_semantics_version", identity.geometry_semantics_version, provenance.geometry_semantics_version),
        ("threshold_id", identity.threshold_id, _CORPUS_THRESHOLD_ID),
        ("structural_identity", identity.structural_identity, f"{provenance.experiment}:corpus"),
        ("search_representation_id", identity.search_representation_id, _CORPUS_SEARCH_REPRESENTATION_ID),
    )
    for name, expected, actual in axes:
        if str(expected) != str(actual):
            raise IntegrityRefused(f"INTEGRITY_REFUSED: result identity axis {name} does not match the exact scope")


def _verify_normalized_corpus_digest(
    identity: AnalysisEvidenceIdentity,
    provenance: GeometryResultProvenanceRow,
    evaluation_rows: tuple[Mapping[str, Any], ...],
) -> None:
    """Reconstruct the corpus geometry/observation digests from the fixed evaluation corpus."""
    members = sorted(
        (
            str(row["geometry_id"]),
            str(row["observation_group_sha256"]),
            str(row["numerical_profile_digest"]),
            str(provenance.geometry_semantics_version),
        )
        for row in evaluation_rows
    )
    if _stable_id("corpus-geometry", [member[0] for member in members]) != str(identity.geometry_id):
        raise IntegrityRefused("INTEGRITY_REFUSED: evaluation corpus does not reproduce the exact geometry identity")
    if _stable_id("corpus-observation", [member[1] for member in members]) != str(identity.observation_group_sha256):
        raise IntegrityRefused("INTEGRITY_REFUSED: evaluation corpus does not reproduce the exact observation identity")


def _normalized_corpus_entry(row: Mapping[str, Any]) -> GeometryEvaluationCorpusEntry:
    return GeometryEvaluationCorpusEntry(
        song_id=str(row["song_id"]),
        backbone=str(row["backbone"]),
        geometry_id=str(row["geometry_id"]),
        observation_group_sha256=str(row["observation_group_sha256"]),
        numerical_profile_digest=str(row["numerical_profile_digest"]),
        searchable_count=_normalized_index(row["searchable_count"], "searchable_count"),
        comparable=bool(row["comparable"]),
        reasons=_normalized_reasons(row.get("reasons"), "evaluation corpus"),
        baseline_valid=bool(row["baseline_valid"]),
    )


def _normalized_threshold_class_row(row: Mapping[str, Any]) -> GeometryThresholdClassRow:
    return GeometryThresholdClassRow(
        threshold_index=_normalized_index(row["threshold_index"], "threshold_index"),
        threshold_id=str(row["threshold_id"]),
        threshold_value=_normalized_finite(row["threshold_value"], "threshold_value"),
        corpus_search_class_id=str(row["corpus_search_class_id"]),
        comparable=bool(row["comparable"]),
        reasons=_normalized_reasons(row.get("reasons"), "threshold class map"),
    )


def _normalized_threshold_structural_row(row: Mapping[str, Any]) -> GeometryThresholdStructuralRow:
    return GeometryThresholdStructuralRow(
        song_id=str(row["song_id"]),
        backbone=str(row["backbone"]),
        threshold_index=_normalized_index(row["threshold_index"], "threshold_index"),
        threshold_id=str(row["threshold_id"]),
        structural_identity=str(row["structural_identity"]),
        search_representation_id=str(row["search_representation_id"]),
        searchable_count=_normalized_index(row["searchable_count"], "searchable_count"),
        medoid_defined=bool(row["medoid_defined"]),
        alignment_ok=bool(row["alignment_ok"]),
        comparable=bool(row["comparable"]),
        reasons=_normalized_reasons(row.get("reasons"), "threshold structural evidence"),
    )


def _normalized_class_aggregate(row: Mapping[str, Any]) -> GeometryClassAggregateMetric:
    return GeometryClassAggregateMetric(
        corpus_search_class_id=str(row["corpus_search_class_id"]),
        ruler=_normalized_choice(row["ruler"], _RESULT_RULERS, "ruler"),
        metric=_normalized_choice(row["metric"], _RESULT_METRICS, "metric"),
        k=_normalized_index(row["k"], "k"),
        value=_normalized_finite(row["value"], "class aggregate metric"),
        evaluable_query_count=_normalized_index(row["evaluable_query_count"], "evaluable_query_count"),
        undefined_query_count=_normalized_index(row["undefined_query_count"], "undefined_query_count"),
    )


def _normalized_class_query(row: Mapping[str, Any]) -> GeometryClassQueryMetric:
    return GeometryClassQueryMetric(
        corpus_search_class_id=str(row["corpus_search_class_id"]),
        query_song_id=str(row["query_song_id"]),
        ruler=_normalized_choice(row["ruler"], _RESULT_RULERS, "ruler"),
        metric=_normalized_choice(row["metric"], _RESULT_METRICS, "metric"),
        k=_normalized_index(row["k"], "k"),
        value=_normalized_finite(row["value"], "class query metric"),
        status=_normalized_choice(row["status"], _RESULT_STATUSES, "status"),
    )


def _normalized_class_neighborhood(row: Mapping[str, Any]) -> GeometryClassNeighborhood:
    return GeometryClassNeighborhood(
        corpus_search_class_id=str(row["corpus_search_class_id"]),
        query_song_id=str(row["query_song_id"]),
        candidate_song_id=str(row["candidate_song_id"]),
        rank=_normalized_index(row["rank"], "rank"),
        score=_normalized_finite(row["score"], "neighborhood score"),
    )


def _normalized_baseline_aggregate(row: Mapping[str, Any]) -> GeometryBaselineAggregateMetric:
    return GeometryBaselineAggregateMetric(
        backbone=str(row["backbone"]),
        ruler=_normalized_choice(row["ruler"], _RESULT_RULERS, "ruler"),
        metric=_normalized_choice(row["metric"], _RESULT_METRICS, "metric"),
        k=_normalized_index(row["k"], "k"),
        value=_normalized_finite(row["value"], "baseline aggregate metric"),
        evaluable_query_count=_normalized_index(row["evaluable_query_count"], "evaluable_query_count"),
        undefined_query_count=_normalized_index(row["undefined_query_count"], "undefined_query_count"),
    )


def _normalized_baseline_query(row: Mapping[str, Any]) -> GeometryBaselineQueryMetric:
    return GeometryBaselineQueryMetric(
        backbone=str(row["backbone"]),
        query_song_id=str(row["query_song_id"]),
        ruler=_normalized_choice(row["ruler"], _RESULT_RULERS, "ruler"),
        metric=_normalized_choice(row["metric"], _RESULT_METRICS, "metric"),
        k=_normalized_index(row["k"], "k"),
        value=_normalized_finite(row["value"], "baseline query metric"),
        status=_normalized_choice(row["status"], _RESULT_STATUSES, "status"),
    )


def _normalized_baseline_neighborhood(row: Mapping[str, Any]) -> GeometryBaselineNeighborhood:
    return GeometryBaselineNeighborhood(
        backbone=str(row["backbone"]),
        query_song_id=str(row["query_song_id"]),
        candidate_song_id=str(row["candidate_song_id"]),
        rank=_normalized_index(row["rank"], "rank"),
        score=_normalized_finite(row["score"], "neighborhood score"),
    )


def read_geometry_corpus_analysis_normalized(
    con: Any,
    *,
    run_id: str,
    identity: AnalysisEvidenceIdentity,
) -> GeometryNormalizedResult:
    """Reconstruct the class-scoped result from the normalized result surfaces, fail-closed.

    This is the symmetric counterpart of :func:`write_geometry_corpus_analysis`: it reads ONLY
    the normalized result surfaces (fixed evaluation corpus, threshold class map, threshold
    structural evidence, class/baseline aggregate/per-query/neighborhood metrics, head-label
    provenance and the ONE compact provenance row) under the exact ten-axis ``identity``.  It
    never reads the retired nested ``role="corpus"`` evidence or the ``geometry_analysis_records``
    table, so a pre-cut database (nested rows only) refuses instead of silently falling back.

    Raises :class:`IntegrityRefused` when the invocation has no obligation/terminal record, a
    required surface is empty, an identity axis does not match, a metric identity is duplicated,
    a value is non-finite, a neighborhood row is self-referential or duplicated, or a reason is
    outside the canonical vocabulary.
    """
    from scripts.embedding_research.db.analyze_scope import invocation_state
    from scripts.embedding_research.db.identity_persistence import (
        read_evaluation_corpus,
        read_head_label_provenance,
        read_threshold_class_map,
        read_threshold_structural,
    )
    from scripts.embedding_research.db.result_surfaces import (
        read_baseline_aggregate_metrics,
        read_baseline_neighborhoods,
        read_baseline_query_metrics,
        read_class_aggregate_metrics,
        read_class_neighborhoods,
        read_class_query_metrics,
        read_result_provenance,
    )

    run_id = _text(run_id, "run_id")
    state = invocation_state(con, run_id=run_id)
    if not state["obligations_present"]:
        raise IntegrityRefused("INTEGRITY_REFUSED: analyze invocation obligation record is missing")
    if not state["terminal_completed"]:
        raise IntegrityRefused("INTEGRITY_REFUSED: analyze completed terminal record is missing")

    provenance_rows = read_result_provenance(con, run_id=run_id)
    if len(provenance_rows) != 1:
        raise IntegrityRefused("INTEGRITY_REFUSED: result provenance surface must hold exactly one row")
    provenance = _normalized_provenance_row(provenance_rows[0])
    _verify_normalized_identity(identity, provenance)

    evaluation_rows = read_evaluation_corpus(
        con, run_id=run_id, evaluation_id=str(identity.evaluation_id), execution_id=str(identity.execution_id)
    )
    threshold_class_rows = read_threshold_class_map(
        con, run_id=run_id, evaluation_id=str(identity.evaluation_id), execution_id=str(identity.execution_id)
    )
    threshold_structural_rows = read_threshold_structural(con, run_id=run_id, evaluation_id=str(identity.evaluation_id))
    class_aggregate_rows = read_class_aggregate_metrics(con, run_id=run_id)
    class_query_rows = read_class_query_metrics(con, run_id=run_id)
    class_neighborhood_rows = read_class_neighborhoods(con, run_id=run_id)
    baseline_aggregate_rows = read_baseline_aggregate_metrics(con, run_id=run_id)
    baseline_query_rows = read_baseline_query_metrics(con, run_id=run_id)
    baseline_neighborhood_rows = read_baseline_neighborhoods(con, run_id=run_id)
    head_rows = read_head_label_provenance(con, run_id=run_id, evaluation_id=str(identity.evaluation_id))

    for rows, where in (
        (evaluation_rows, "evaluation corpus"),
        (threshold_class_rows, "threshold class map"),
        (threshold_structural_rows, "threshold structural evidence"),
        (baseline_aggregate_rows, "baseline aggregate metrics"),
    ):
        if not rows:
            raise IntegrityRefused(f"INTEGRITY_REFUSED: required {where} surface is empty")
    if provenance.evidence_mode == "empirical_request" and not head_rows:
        raise IntegrityRefused("INTEGRITY_REFUSED: empirical result head-label provenance surface is empty")

    _verify_normalized_corpus_digest(identity, provenance, evaluation_rows)

    _normalized_unique(
        (
            (str(row["corpus_search_class_id"]), str(row["ruler"]), str(row["metric"]), str(row["k"]))
            for row in class_aggregate_rows
        ),
        "class aggregate metric",
    )
    _normalized_unique(
        (
            (
                str(row["corpus_search_class_id"]),
                str(row["query_song_id"]),
                str(row["ruler"]),
                str(row["metric"]),
                str(row["k"]),
            )
            for row in class_query_rows
        ),
        "class query metric",
    )
    _normalized_unique(
        (
            (str(row["backbone"]), str(row["ruler"]), str(row["metric"]), str(row["k"]))
            for row in baseline_aggregate_rows
        ),
        "baseline aggregate metric",
    )
    _normalized_unique(
        (
            (str(row["backbone"]), str(row["query_song_id"]), str(row["ruler"]), str(row["metric"]), str(row["k"]))
            for row in baseline_query_rows
        ),
        "baseline query metric",
    )
    _normalized_unique(
        (
            _normalized_neighborhood_key(row, "corpus_search_class_id", "class neighborhood")
            for row in class_neighborhood_rows
        ),
        "class neighborhood",
    )
    _normalized_unique(
        (_normalized_neighborhood_key(row, "backbone", "baseline neighborhood") for row in baseline_neighborhood_rows),
        "baseline neighborhood",
    )

    return GeometryNormalizedResult(
        run_id=run_id,
        provenance=provenance,
        evaluation_corpus=tuple(_normalized_corpus_entry(row) for row in evaluation_rows),
        threshold_class_map=tuple(_normalized_threshold_class_row(row) for row in threshold_class_rows),
        threshold_structural=tuple(_normalized_threshold_structural_row(row) for row in threshold_structural_rows),
        class_aggregate_metrics=tuple(_normalized_class_aggregate(row) for row in class_aggregate_rows),
        class_query_metrics=tuple(_normalized_class_query(row) for row in class_query_rows),
        class_neighborhoods=tuple(_normalized_class_neighborhood(row) for row in class_neighborhood_rows),
        baseline_aggregate_metrics=tuple(_normalized_baseline_aggregate(row) for row in baseline_aggregate_rows),
        baseline_query_metrics=tuple(_normalized_baseline_query(row) for row in baseline_query_rows),
        baseline_neighborhoods=tuple(_normalized_baseline_neighborhood(row) for row in baseline_neighborhood_rows),
        head_label_provenance=tuple(dict(row) for row in head_rows),
    )


def _require_evidence_list(corpus_evidence: dict[str, Any], key: str) -> list[Any]:
    value = corpus_evidence.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"geometry corpus evidence {key} must be a list")
    return value


def _parse_neighborhood(raw: Any) -> tuple[NeighborhoodEntry, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("geometry corpus neighborhood must be a list")
    return tuple(
        NeighborhoodEntry(
            int(item["rank"]),
            str(item["song_id"]),
            str(item["backbone"]),
            str(item["search_representation_id"]),
            float(item["score"]),
        )
        for item in raw
    )


def write_geometries_for_current_songs(
    con: Any,
    *,
    stream_store: StreamStore,
    profile: GeometryProfile,
    run_id: str,
    lock: object,
    song_ids: Any = None,
    backbones: Any = None,
) -> tuple[GeometryRecord, ...]:
    """Build and atomically publish one exact-key geometry for every selected observation.

    Every item is loaded and mask/resource-checked before the first write; each row is
    published through the existing ``write_geometry`` transaction and then re-read and
    verified through ``verify_geometry_binding`` before it is returned.
    """
    if not hasattr(lock, "__enter__"):
        raise ValueError("an existing exclusive run lock is required")
    if not isinstance(profile, GeometryProfile):
        raise ValueError("profile must be GeometryProfile")
    prepared: list[tuple[Any, GeometryIdentity]] = []
    for song, backbone in _selected_geometry_items(con, song_ids, backbones):
        prepared.append(_committed_geometry_observation(stream_store, str(song["song_id"]), backbone, profile))
    written: list[GeometryRecord] = []
    for observation, identity in prepared:
        write_geometry(observation, profile, run_id, lock=lock)
        record = read_geometry(identity, con)
        verify_geometry_binding(record, observation, profile)
        written.append(record)
    return tuple(written)


_NEIGHBORHOOD_SIZE = 100


@dataclass(frozen=True)
class NeighborhoodEntry:
    """One deterministically ranked leave-one-out candidate neighbor."""

    rank: int
    song_id: str
    backbone: str
    search_representation_id: str
    score: float

    def __post_init__(self) -> None:
        if isinstance(self.rank, bool) or self.rank < 0:
            raise ValueError("rank must be a non-negative integer")
        for name in ("song_id", "backbone", "search_representation_id"):
            _text(getattr(self, name), name)
        _finite(self.score, "score")


@dataclass(frozen=True)
class GeometryCandidate:
    """One corpus-wide searchable candidate with its explicit comparability state."""

    representation: FrozenSearchRepresentation
    state: RepresentationState
    structural_identity: str
    threshold_indices: tuple[int, ...]
    searchable_count: int


@dataclass(frozen=True)
class NonComparableEvidence:
    """Explicit non-comparable threshold evidence retained instead of a silent drop."""

    song_id: str
    backbone: str
    threshold_indices: tuple[int, ...]
    structural_identity: str
    search_representation_id: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class GeometryMembershipEntry:
    """One persisted corpus member with its explicit comparability state."""

    song_id: str
    backbone: str
    observation_group_sha256: str
    geometry_id: str
    numerical_profile_digest: str
    comparable: bool
    defined: bool
    eligible: bool
    reasons: tuple[str, ...]
    searchable_count: int

    def __post_init__(self) -> None:
        for name in (
            "song_id",
            "backbone",
            "observation_group_sha256",
            "geometry_id",
            "numerical_profile_digest",
        ):
            _text(getattr(self, name), name)
        for name in ("comparable", "defined", "eligible"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        object.__setattr__(self, "reasons", tuple(str(reason) for reason in self.reasons))
        if isinstance(self.searchable_count, bool) or self.searchable_count < 0:
            raise ValueError("searchable_count must be a non-negative integer")


@dataclass(frozen=True)
class GeometryThresholdMapEntry:
    """One persisted threshold-to-representation mapping (never a scored matrix)."""

    song_id: str
    backbone: str
    threshold_id: str
    structural_identity: str
    search_representation_id: str
    comparable: bool


@dataclass(frozen=True)
class GeometryQueryEvidence:
    """One persisted per-query evidence record, including bounded neighborhoods."""

    song_id: str
    backbone: str
    comparable: bool
    defined: bool
    eligible: bool
    reasons: tuple[str, ...]
    winner_score: float
    baseline_score: float | None
    baseline_delta: float | None
    searchable_count: int
    neighborhood: tuple[NeighborhoodEntry, ...]
    baseline_neighborhood: tuple[NeighborhoodEntry, ...]
    threshold_id: str = ""
    collapse_class_id: str = ""

    def __post_init__(self) -> None:
        _text(self.song_id, "song_id")
        _text(self.backbone, "backbone")
        for name in ("comparable", "defined", "eligible"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        object.__setattr__(self, "reasons", tuple(str(reason) for reason in self.reasons))
        _finite(self.winner_score, "winner_score")
        if self.baseline_score is not None:
            _finite(self.baseline_score, "baseline_score")
        if self.baseline_delta is not None:
            _finite(self.baseline_delta, "baseline_delta")
        object.__setattr__(self, "neighborhood", tuple(self.neighborhood))
        object.__setattr__(self, "baseline_neighborhood", tuple(self.baseline_neighborhood))


@dataclass(frozen=True)
class GeometryCorpusEvidence:
    """The complete persisted corpus evidence read back without re-running geometry."""

    run_id: str
    execution_id: str
    evaluation_id: str
    experiment: str
    numerical_profile_digest: str
    scoring_semantics_version: int
    comparable: bool
    reasons: tuple[str, ...]
    membership: tuple[GeometryMembershipEntry, ...]
    missing_searchable: tuple[str, ...]
    queries: tuple[GeometryQueryEvidence, ...]
    noncomparable: tuple[NonComparableEvidence, ...]
    threshold_map: tuple[GeometryThresholdMapEntry, ...] = ()
    artist_metrics: Mapping[str, float] = field(default_factory=dict)
    genre_metrics: Mapping[str, float] = field(default_factory=dict)
    head_metrics: Mapping[str, float] = field(default_factory=dict)
    per_song_metrics: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    baseline_deltas: Mapping[str, float] = field(default_factory=dict)
    counters: GeometryAnalysisCounters = field(default_factory=GeometryAnalysisCounters)
    hypotheses: tuple[dict[str, Any], ...] = ()
    evidence_mode: str = "synthetic_fixture"
    head_evidence_provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("run_id", "execution_id", "evaluation_id", "experiment", "numerical_profile_digest"):
            _text(getattr(self, name), name)
        if isinstance(self.scoring_semantics_version, bool) or self.scoring_semantics_version < 1:
            raise ValueError("scoring_semantics_version must be positive")
        if not isinstance(self.comparable, bool):
            raise ValueError("comparable must be boolean")
        object.__setattr__(self, "reasons", tuple(str(reason) for reason in self.reasons))
        object.__setattr__(self, "missing_searchable", tuple(str(song) for song in self.missing_searchable))
        object.__setattr__(self, "membership", tuple(self.membership))
        object.__setattr__(self, "queries", tuple(self.queries))
        object.__setattr__(self, "noncomparable", tuple(self.noncomparable))
        object.__setattr__(self, "threshold_map", tuple(self.threshold_map))
        object.__setattr__(self, "artist_metrics", dict(self.artist_metrics))
        object.__setattr__(self, "genre_metrics", dict(self.genre_metrics))
        object.__setattr__(self, "head_metrics", dict(self.head_metrics))
        object.__setattr__(self, "per_song_metrics", {str(k): dict(v) for k, v in self.per_song_metrics.items()})
        object.__setattr__(self, "baseline_deltas", dict(self.baseline_deltas))
        if self.evidence_mode not in {"synthetic_fixture", "empirical_request"}:
            raise ValueError("evidence_mode must identify synthetic_fixture or empirical_request")
        object.__setattr__(self, "head_evidence_provenance", dict(self.head_evidence_provenance))
        object.__setattr__(self, "hypotheses", tuple(dict(item) for item in self.hypotheses))
        if self.evidence_mode not in {"synthetic_fixture", "empirical_request"}:
            raise ValueError("evidence_mode must identify synthetic_fixture or empirical_request")
        object.__setattr__(self, "head_evidence_provenance", dict(self.head_evidence_provenance))


def _representation_scoring_pairs(search: Any) -> tuple[tuple[int, ...], tuple[float, ...]]:
    """Filter one threshold's segments to the aligned, medoid-bearing scoring inputs."""
    indices: list[int] = []
    weights: list[float] = []
    for index, weight in zip(search.medoid_source_indices, search.searchable_weights, strict=True):
        if index is None or not np.isfinite(float(weight)) or float(weight) <= 0.0:
            continue
        indices.append(int(index))
        weights.append(float(weight))
    total = float(sum(weights))
    if total > 0.0:
        weights = [weight / total for weight in weights]
    return tuple(indices), tuple(weights)


def _alignment_ok(indices: tuple[int, ...], weights: tuple[float, ...]) -> bool:
    return bool(indices) and len(indices) == len(weights) and all(weight > 0.0 for weight in weights)


def _label_defined(item: GeometrySongRequest) -> bool:
    """Member-level label presence for ``classify_representation``.

    A member is label-defined when ANY of the artist/genre/head rulers has a label for it.
    A missing HEAD label is therefore NOT a member-level ``label_missing`` that would drop
    the ``(song, class)`` member: it excludes the song from the HEAD ruler only, while the
    artist/genre rulers stay defined/eligible for that same song.  ``classify_representation``
    still returns ``comparable=True`` for a ``label_missing`` member, so the population is
    never shrunk by an absent head label.
    """
    return any(_ruler_label(getattr(item, name)) is not None for name in ("artist", "genre", "head_label"))


_RULER_NAMES: tuple[str, ...] = ("artist", "genre", "head")
_CLASS_METRIC_NAMES: tuple[str, ...] = ("map_k", "mrr", "ndcg_k", "recall_k", "disc")

# A per-ruler missing label must never collide with a real label, so it is encoded
# with a NUL prefix that is excluded from the oracle's relevance comparison.
_MISSING_LABEL_PREFIX = "\x00missing:"

# (canonical metric name, oracle aggregate key, oracle per_song key or None).
_ORACLE_METRIC_KEYS: tuple[tuple[str, str, str | None], ...] = (
    ("map_k", "map_k_artist", "ap_k"),
    ("mrr", "mrr", "mrr"),
    ("ndcg_k", "ndcg_k_artist", None),
    ("recall_k", "recall_k_artist", "recall_k"),
    ("disc", "disc_artist", "disc_artist_contrib"),
)


def _canonical_ruler_label(item: GeometrySongRequest, ruler: str) -> str | None:
    """Return the ruler's canonical string label for a song, or None when missing."""
    field_name = {"artist": "artist", "genre": "genre", "head": "head_label"}[ruler]
    value = _ruler_label(getattr(item, field_name))
    if value is None:
        return None
    if ruler == "head":
        from scripts.embedding_research.db.identity_persistence import _json

        return _json(value)
    return str(value)


def _ruler_label_array(items: tuple[GeometrySongRequest, ...], ruler: str) -> tuple[list[str], list[bool]]:
    """Build the oracle label array and per-query definedness for one ruler.

    ``defined`` is true iff the query's label is present AND at least one other
    evaluation-corpus song shares that exact label.  Missing labels are encoded
    with a unique sentinel so the oracle never treats two absent labels as equal;
    a missing (or solo) label excludes the query from that ruler only.
    """
    present = [_canonical_ruler_label(item, ruler) for item in items]
    counts: dict[str, int] = {}
    for label in present:
        if label is not None:
            counts[label] = counts.get(label, 0) + 1
    labels = [
        label if label is not None else f"{_MISSING_LABEL_PREFIX}{items[i].song_id}" for i, label in enumerate(present)
    ]
    defined = [label is not None and counts[label] >= 2 for label in present]
    return labels, defined


def _class_similarity_matrix(
    items: tuple[GeometrySongRequest, ...],
    by_song: Mapping[str, GeometrySongAnalysis],
    index: Mapping[str, int],
) -> np.ndarray:
    """Assemble one full ``[n, n]`` class-scoped similarity matrix over the corpus.

    Row ``i`` holds query song ``i``'s established bounded-scorer similarity to every
    candidate song ``j`` in the class's T-derived searchable representations (the
    canonical cosine-derived song-pair retrieval score).  Self similarity is left at
    zero; the oracle's ``_rankings_from_sim`` excludes the diagonal regardless.  The
    matrix is transient and is used only to drive the established oracle arithmetic.
    """
    n = len(items)
    matrix = np.zeros((n, n), dtype=np.float32)
    for song_id, query in by_song.items():
        row = index[song_id]
        for representation in query.roster.representations:
            column = index[representation.song_id]
            matrix[row, column] = float(query.scores.scores[representation.search_representation_id])
    return matrix


def _ruler_oracle(
    matrix: np.ndarray, items: tuple[GeometrySongRequest, ...], ruler: str
) -> tuple[dict[str, Any], list[bool]]:
    """Call the established oracle once for one ruler with the pinned K."""
    labels, defined = _ruler_label_array(items, ruler)
    result = compute_retrieval_metrics(
        matrix,
        labels,
        k=K_ESTABLISHED,
        sids=[item.song_id for item in items],
    )
    return result, defined


def _geometry_class_scoped_metrics(
    *,
    request: GeometryCorpusRequest,
    scored_queries: Mapping[tuple[str, str], GeometrySongAnalysis],
    baseline_roster: Mapping[tuple[str, str], FrozenSearchRepresentation],
) -> tuple[
    tuple[GeometryClassAggregateMetric, ...],
    tuple[GeometryClassQueryMetric, ...],
    tuple[GeometryClassNeighborhood, ...],
    tuple[GeometryBaselineAggregateMetric, ...],
    tuple[GeometryBaselineQueryMetric, ...],
    tuple[GeometryBaselineNeighborhood, ...],
]:
    """Compute class-scoped metrics and the once-per-corpus baseline.

    For every COMPARABLE class exactly one full ``[n, n]`` similarity matrix is built
    over the fixed evaluation corpus and passed to the established oracle once per
    ruler.  A class is comparable here iff every corpus song was scored (a member
    that was never scored means the whole class is non-comparable).  The retained
    top-``_NEIGHBORHOOD_SIZE`` neighborhoods are collected AFTER the metrics and are
    never a metric input.  The observed global-medoid baseline is computed exactly
    once for the fixed corpus, independent of any threshold.
    """
    items = tuple(request.items)
    n = len(items)
    if n == 0:
        return ((), (), (), (), (), ())
    ordered_song_ids = [item.song_id for item in items]
    index = {song_id: position for position, song_id in enumerate(ordered_song_ids)}

    grouped: dict[str, dict[str, GeometrySongAnalysis]] = {}
    for (class_id, song_id), query in scored_queries.items():
        grouped.setdefault(class_id, {})[song_id] = query

    class_aggregate: list[GeometryClassAggregateMetric] = []
    class_query: list[GeometryClassQueryMetric] = []
    class_neighborhood: list[GeometryClassNeighborhood] = []
    for class_id, by_song in grouped.items():
        if set(by_song) != set(ordered_song_ids):
            # A member was never scored, so the class is non-comparable: no metrics.
            continue
        matrix = _class_similarity_matrix(items, by_song, index)
        for ruler in _RULER_NAMES:
            result, defined = _ruler_oracle(matrix, items, ruler)
            evaluable = sum(defined)
            undefined = n - evaluable
            per_song = result["per_song"]
            for metric, aggregate_key, _per_song_key in _ORACLE_METRIC_KEYS:
                class_aggregate.append(
                    GeometryClassAggregateMetric(
                        class_id,
                        ruler,
                        metric,
                        K_ESTABLISHED,
                        float(result[aggregate_key]),
                        evaluable,
                        undefined,
                    )
                )
            for position, song_id in enumerate(ordered_song_ids):
                status = "defined" if defined[position] else "undefined"
                for metric, _aggregate_key, per_song_key in _ORACLE_METRIC_KEYS:
                    if per_song_key is None:
                        continue
                    raw = per_song[per_song_key][position]
                    if raw is None or not np.isfinite(raw):
                        continue
                    class_query.append(
                        GeometryClassQueryMetric(
                            class_id,
                            song_id,
                            ruler,
                            metric,
                            K_ESTABLISHED,
                            float(raw),
                            status,
                        )
                    )
        # Neighborhoods are a browsing window persisted after the metrics above.
        class_neighborhood.extend(
            GeometryClassNeighborhood(class_id, song_id, entry.song_id, entry.rank, entry.score)
            for song_id, query in by_song.items()
            for entry in query.neighborhood
        )

    baseline_aggregate: list[GeometryBaselineAggregateMetric] = []
    baseline_query: list[GeometryBaselineQueryMetric] = []
    baseline_neighborhood: list[GeometryBaselineNeighborhood] = []
    backbone = items[0].backbone
    baseline_rows: list[np.ndarray] = []
    for item in items:
        representation = baseline_roster.get((item.song_id, item.backbone))
        if representation is None:
            raise IntegrityRefused("baseline representation missing for a corpus song")
        baseline_rows.append(np.asarray(representation.vectors[0], dtype=np.float32))
    baseline_matrix = cosine_matrix(RawTensor(np.stack(baseline_rows)))
    baseline_lookup = {
        representation.search_representation_id: representation for representation in baseline_roster.values()
    }
    for ruler in _RULER_NAMES:
        result, defined = _ruler_oracle(baseline_matrix, items, ruler)
        evaluable = sum(defined)
        undefined = n - evaluable
        per_song = result["per_song"]
        for metric, aggregate_key, _per_song_key in _ORACLE_METRIC_KEYS:
            baseline_aggregate.append(
                GeometryBaselineAggregateMetric(
                    backbone,
                    ruler,
                    metric,
                    K_ESTABLISHED,
                    float(result[aggregate_key]),
                    evaluable,
                    undefined,
                )
            )
        for position, song_id in enumerate(ordered_song_ids):
            status = "defined" if defined[position] else "undefined"
            for metric, _aggregate_key, per_song_key in _ORACLE_METRIC_KEYS:
                if per_song_key is None:
                    continue
                raw = per_song[per_song_key][position]
                if raw is None or not np.isfinite(raw):
                    continue
                baseline_query.append(
                    GeometryBaselineQueryMetric(
                        backbone,
                        song_id,
                        ruler,
                        metric,
                        K_ESTABLISHED,
                        float(raw),
                        status,
                    )
                )
    for position, song_id in enumerate(ordered_song_ids):
        scores: dict[str, float] = {}
        for other_position, other_song_id in enumerate(ordered_song_ids):
            if other_position == position:
                continue
            other = baseline_roster[(other_song_id, backbone)]
            scores[other.search_representation_id] = float(baseline_matrix[position, other_position])
        baseline_neighborhood.extend(
            GeometryBaselineNeighborhood(backbone, song_id, entry.song_id, entry.rank, entry.score)
            for entry in _select_neighborhood(scores, baseline_lookup)
        )

    return (
        tuple(class_aggregate),
        tuple(class_query),
        tuple(class_neighborhood),
        tuple(baseline_aggregate),
        tuple(baseline_query),
        tuple(baseline_neighborhood),
    )


def _normalized_query_vectors(_stream: Any, _mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Reject the retired raw whole-song query representation."""
    raise RuntimeError("raw whole-song query vectors are not a geometry representation")


def _song_search_identity(
    *,
    request: GeometryCorpusRequest,
    item: GeometrySongRequest,
    search: Any,
    indices: tuple[int, ...],
    weights: tuple[float, ...],
    _ordered_song_ids: tuple[str, ...],
) -> str:
    """Build a corpus-ready identity for one ordered song input."""
    ordered_inputs = tuple(
        CorpusSongSearchInput(
            song_id=member.song_id,
            observation_group_sha256=member.geometry_identity.observation_group_sha256,
            mask_identity=str(
                next(
                    (
                        candidate.observation_evidence.get("mask_payload_sha256", "")
                        for candidate in request.items
                        if candidate.song_id == member.song_id and candidate.backbone == member.backbone
                    ),
                    "",
                )
            ),
            medoid_source_indices=indices if member.song_id == item.song_id else (),
            normalized_searchable_weights=weights if member.song_id == item.song_id else (),
            searchable_count=int(search.total_searchable) if member.song_id == item.song_id else 0,
        )
        for member in request.items
    )
    return search_representation_id(
        experiment=request.experiment,
        scoring_semantics_version=int(search.scoring_semantics_version),
        geometry_semantics_version=str(request.experiment),
        numerical_profile_digest=str(search.profile_digest),
        ordered_song_inputs=ordered_inputs,
    )


def _select_neighborhood(
    scores: Mapping[str, float],
    lookup: Mapping[str, FrozenSearchRepresentation],
    *,
    limit: int = _NEIGHBORHOOD_SIZE,
) -> tuple[NeighborhoodEntry, ...]:
    """Deterministic descending-score top-N with a search-identity tie-break."""
    ranked = sorted(((str(key), float(value)) for key, value in scores.items()), key=lambda pair: (-pair[1], pair[0]))
    entries: list[NeighborhoodEntry] = []
    seen_songs: set[str] = set()
    for _rank, (key, value) in enumerate(ranked[:limit]):
        representation = lookup.get(key)
        if representation is None or representation.song_id in seen_songs:
            continue
        seen_songs.add(representation.song_id)
        _finite(value, "score")
        entries.append(
            NeighborhoodEntry(
                len(entries),
                representation.song_id,
                representation.backbone,
                key,
                value,
            )
        )
    return tuple(entries)
