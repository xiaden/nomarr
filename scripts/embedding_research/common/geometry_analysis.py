"""Geometry-owned corpus analysis contracts.

This module contains the corpus loading and persistence orchestration for the
synthetic geometry experiment. ``analyze_geometry_corpus`` loads committed
observations, while ``write_geometry_corpus_analysis`` owns persistence; model
execution remains outside this CPU-side analysis seam.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

import numpy as np

from scripts.embedding_research.bounded_scoring import (
    BoundedScoreResult,
    ScoringCandidateView,
    score_bounded_exact,
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
    RepresentationState,
    classify_representation,
    search_representation_id,
)
from scripts.embedding_research.helpers.gram_segmentation import (
    normalize_float32,
    observed_global_medoid_from_gram,
    require_exact_binary_mask,
)

if TYPE_CHECKING:
    from scripts.embedding_research.streams.store import StreamStore

_EXPERIMENTS = {"temporal_global", "temporal_perdim_chebyshev_secondary"}
_MAX_PATCH_COUNT = MAX_PATCH_COUNT
_MAX_GRAM_BYTES = MAX_GRAM_BYTES


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
    """One ordered synthetic song/backbone analysis input."""

    song_id: str
    backbone: str
    geometry_identity: GeometryIdentity
    observation_evidence: Mapping[str, Any]
    artist: str | None = None
    genre: str | None = None
    head_label: Any | None = None
    synthetic_only: bool = True

    def __post_init__(self) -> None:
        _text(self.song_id, "song_id")
        _text(self.backbone, "backbone")
        if not isinstance(self.geometry_identity, GeometryIdentity):
            raise ValueError("geometry_identity must be GeometryIdentity")
        object.__setattr__(self, "observation_evidence", _mapping(self.observation_evidence, "observation_evidence"))
        if not isinstance(self.synthetic_only, bool) or not self.synthetic_only:
            raise ValueError("geometry analysis requests are synthetic-only")
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
        if not isinstance(self.synthetic_only, bool) or not self.synthetic_only:
            raise ValueError("geometry analysis requests are synthetic-only")


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
    """Per-query geometry analysis: threshold structure, candidate roster, and scores."""

    request: GeometrySongRequest
    thresholds: AllThresholdAnalysis
    roster: GeometryRepresentationRoster
    scores: GeometryScoreBundle
    state: RepresentationState = field(default_factory=lambda: RepresentationState(True, True, True, ()))
    neighborhood: tuple[NeighborhoodEntry, ...] = ()
    baseline_neighborhood: tuple[NeighborhoodEntry, ...] = ()


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
    candidates: tuple[GeometryCandidate, ...] = ()
    noncomparable: tuple[NonComparableEvidence, ...] = ()
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("run_id", "execution_id", "experiment", "evaluation_id", "numerical_profile_digest"):
            _text(getattr(self, name), name)
        if self.experiment not in _EXPERIMENTS:
            raise ValueError("unknown geometry experiment")
        if isinstance(self.scoring_semantics_version, bool) or self.scoring_semantics_version < 1:
            raise ValueError("scoring_semantics_version must be positive")
        if self.refusal_status is not None:
            _text(self.refusal_status, "refusal_status")
        if not isinstance(self.comparable, bool):
            raise ValueError("comparable must be boolean")
        if not isinstance(self.synthetic_only, bool) or not self.synthetic_only:
            raise ValueError("geometry analyses are synthetic-only")
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
    from scripts.embedding_research.db.identity_persistence import _json

    payload = _json(parts)
    return "geometry-" + payload.encode("utf-8").hex()[:48]


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


def analyze_geometry_corpus(
    request: GeometryCorpusRequest,
    *,
    con: Any,
    stream_store: StreamStore,
    profile: GeometryProfile,
    scoring: Any = score_bounded_exact,
) -> GeometryCorpusAnalysis:
    """Run corpus-wide leave-one-out geometry analysis without a compatibility path.

    Stage one loads exactly one committed observation and geometry per song/backbone
    and derives all requested thresholds before any scorer call.  Stage two builds the
    corpus-wide representations, collapses thresholds only when every included scoring
    input matches, and scores each query against every other candidate song with the
    canonical bounded max-per-candidate-segment scorer.  A query never receives its own
    song as a candidate; the observed whole-song medoid baseline is scored against the
    same leave-one-out population.
    """
    if not isinstance(request, GeometryCorpusRequest) or not request.synthetic_only:
        raise ValueError("a synthetic geometry corpus request is required")
    if not isinstance(request.threshold_request, PrimaryThresholdRequest):
        raise ValueError("secondary geometry analysis owner is not available")
    semantics = str(profile.to_manifest().get("geometry_semantics_version") or "")
    if not semantics:
        raise ValueError("geometry profile has no geometry semantics version")
    ordered_song_ids = tuple(item.song_id for item in request.items)

    geometry_loads = observation_loads = threshold_batches = gather_count = 0
    prepared: list[dict[str, Any]] = []
    for item in request.items:
        observation = stream_store.load_committed_observation(item.song_id, item.backbone)
        observation_loads += 1
        identity = _observation_geometry_identity(observation, profile)
        if identity != item.geometry_identity:
            raise ValueError("committed observation identity does not match corpus request")
        record = verify_geometry_current(con, observation, profile=profile, exact_identity=item.geometry_identity)
        geometry_loads += 1
        if record is None:
            raise IntegrityRefused("INTEGRITY_REFUSED: committed geometry is absent for the corpus request")
        mask = require_exact_binary_mask(observation.mask, record.matrix.shape[0])
        thresholds = analyze_all_thresholds(record, mask, request.threshold_request, experiment=request.experiment)
        threshold_batches += 1
        query_vectors, query_weights = _normalized_query_vectors(observation.stream, mask)
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

    candidate_records: list[dict[str, Any]] = []
    noncomparable: list[NonComparableEvidence] = []
    for prep in prepared:
        item = prep["item"]
        record = prep["record"]
        buckets: dict[str, list[Any]] = {}
        for result in prep["thresholds"].results:
            search = result.search
            indices, weights = _representation_scoring_pairs(search)
            sid = search_representation_id(
                experiment=request.experiment,
                scoring_semantics_version=int(search.scoring_semantics_version),
                geometry_semantics_version=semantics,
                numerical_profile_digest=str(search.profile_digest),
                observation_group_sha256=item.geometry_identity.observation_group_sha256,
                mask_identity=str(search.mask_digest),
                ordered_corpus_song_ids=ordered_song_ids,
                medoid_source_indices=indices,
                normalized_searchable_weights=weights,
                searchable_count=int(search.total_searchable),
            )
            buckets.setdefault(sid, []).append(result)
        for sid, members in sorted(buckets.items(), key=lambda pair: int(pair[1][0].threshold.index)):
            first = members[0]
            search = first.search
            indices, weights = _representation_scoring_pairs(search)
            threshold_indices = tuple(int(member.threshold.index) for member in members)
            state = classify_representation(
                alignment_ok=_alignment_ok(indices, weights),
                searchable_count=int(search.total_searchable),
                medoid_defined=bool(indices),
                candidate_count=len(request.items) - 1,
                label_defined=_label_defined(item),
            )
            if not state.comparable:
                noncomparable.append(
                    NonComparableEvidence(
                        item.song_id,
                        item.backbone,
                        threshold_indices,
                        str(first.structural.identity),
                        sid,
                        state.reasons,
                    )
                )
                continue
            vectors = stream_store.batch_gather(item.song_id, item.backbone, indices, forbid_duplicates=True)
            gather_count += 1
            representation = FrozenSearchRepresentation(
                item.song_id,
                item.backbone,
                indices,
                vectors,
                np.asarray(weights, dtype=np.float64),
                sid,
                record.geometry_id,
                item.geometry_identity.observation_group_sha256,
                str(search.profile_digest),
                str(search.mask_digest),
                int(search.scoring_semantics_version),
                request.experiment,
                threshold_indices,
            )
            candidate_records.append(
                {
                    "representation": representation,
                    "state": state,
                    "structural_identity": str(first.structural.identity),
                    "threshold_indices": threshold_indices,
                    "searchable_count": int(search.total_searchable),
                }
            )
        medoid, _centrality = observed_global_medoid_from_gram(
            np.asarray(record.matrix, dtype=np.float32), prep["mask"]
        )
        if medoid is not None:
            baseline_indices = (int(medoid),)
            baseline_vectors = stream_store.batch_gather(
                item.song_id, item.backbone, baseline_indices, forbid_duplicates=True
            )
            gather_count += 1
            prep["baseline"] = FrozenSearchRepresentation(
                item.song_id,
                item.backbone,
                baseline_indices,
                baseline_vectors,
                np.ones(1, dtype=np.float64),
                _stable_id("baseline", item.geometry_identity.observation_group_sha256, medoid),
                _stable_id(item.song_id, item.backbone, item.geometry_identity.observation_group_sha256),
                item.geometry_identity.observation_group_sha256,
                str(profile.digest),
                str(item.observation_evidence.get("mask_payload_sha256", "")),
                request.scoring_semantics_version,
                request.experiment,
                (),
                True,
            )

    candidates = tuple(
        GeometryCandidate(
            record["representation"],
            record["state"],
            record["structural_identity"],
            record["threshold_indices"],
            record["searchable_count"],
        )
        for record in sorted(
            candidate_records,
            key=lambda record: (
                record["representation"].song_id,
                record["representation"].backbone,
                record["representation"].search_representation_id,
            ),
        )
    )

    queries: list[GeometrySongAnalysis] = []
    scorer_count = 0
    for prep in prepared:
        item = prep["item"]
        other_candidates = tuple(
            candidate for candidate in candidates if candidate.representation.song_id != item.song_id
        )
        candidate_roster = GeometryRepresentationRoster(
            tuple(candidate.representation for candidate in other_candidates)
        )
        eligible_song_ids = tuple(sorted({candidate.representation.song_id for candidate in other_candidates}))
        evidence_digest = "|".join(
            sorted({str(candidate.representation.observation_group_sha256) for candidate in other_candidates})
        )
        query_state = classify_representation(
            alignment_ok=prep["query_vectors"].shape[0] > 0,
            searchable_count=int(prep["searchable_count"]),
            medoid_defined=prep["baseline"] is not None,
            candidate_count=len(other_candidates),
            label_defined=_label_defined(item),
        )
        if not query_state.comparable:
            queries.append(
                GeometrySongAnalysis(
                    item,
                    prep["thresholds"],
                    GeometryRepresentationRoster(()),
                    GeometryScoreBundle(scores={}, evaluation_comparable=False),
                    state=query_state,
                )
            )
            continue
        evaluation = FrozenGeometryEvaluation(
            evaluation_id=request.evaluation_id,
            query_vectors=prep["query_vectors"],
            query_weights=prep["query_weights"],
            eligible_song_ids=eligible_song_ids,
            observation_evidence_digest=evidence_digest,
            comparable=query_state.comparable,
        )
        winner_bundle = score_unique_geometry_representations(candidate_roster, evaluation, scoring)
        scorer_count += winner_bundle.scorer_call_count
        baseline = prep["baseline"]
        baseline_scores: Mapping[str, float] = MappingProxyType({})
        baseline_neighborhood: tuple[NeighborhoodEntry, ...] = ()
        baseline_calls = 0
        if baseline is not None and other_candidates:
            baseline_evaluation = FrozenGeometryEvaluation(
                evaluation_id=request.evaluation_id,
                query_vectors=baseline.vectors,
                query_weights=baseline.weights,
                eligible_song_ids=eligible_song_ids,
                observation_evidence_digest=evidence_digest,
                comparable=query_state.comparable,
            )
            baseline_bundle = score_unique_geometry_representations(candidate_roster, baseline_evaluation, scoring)
            baseline_calls = baseline_bundle.scorer_call_count
            scorer_count += baseline_calls
            baseline_scores = baseline_bundle.scores
        lookup = {
            candidate.representation.search_representation_id: candidate.representation
            for candidate in other_candidates
        }
        neighborhood = _select_neighborhood(winner_bundle.scores, lookup)
        if baseline_scores:
            baseline_neighborhood = _select_neighborhood(baseline_scores, lookup)
        baseline_score = max(baseline_scores.values()) if baseline_scores else None
        bundle = GeometryScoreBundle(
            scores=winner_bundle.scores,
            baseline_score=baseline_score,
            baseline_representation_id=baseline.search_representation_id if baseline is not None else None,
            evaluation_comparable=query_state.comparable,
            unique_representation_count=len(other_candidates),
            source_gather_count=len(other_candidates),
            scorer_call_count=winner_bundle.scorer_call_count + baseline_calls,
            segmentation_from_scorer_count=0,
        )
        queries.append(
            GeometrySongAnalysis(
                item,
                prep["thresholds"],
                candidate_roster,
                bundle,
                state=query_state,
                neighborhood=neighborhood,
                baseline_neighborhood=baseline_neighborhood,
            )
        )

    # Re-read the CURRENT committed tuple at the execution boundary; a superseding
    # publication must refuse before any result escapes the owner.
    for prep in prepared:
        preflight_geometry_binding(prep["record"], profile, store=stream_store)

    artist_metrics, genre_metrics, head_metrics, per_song_metrics, baseline_deltas = _geometry_ruler_metrics(
        tuple(queries)
    )
    counters = GeometryAnalysisCounters(
        geometry_loads,
        observation_loads,
        threshold_batches,
        len(candidates),
        gather_count,
        scorer_count,
        0,
    )
    corpus_roster = GeometryRepresentationRoster(tuple(candidate.representation for candidate in candidates))
    first_baseline = next((prep["baseline"] for prep in prepared if prep["baseline"] is not None), None)
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
        queries=tuple(queries),
        candidates=candidates,
        noncomparable=tuple(noncomparable),
    )


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
    synthetic_only: bool = True,
) -> GeometryCorpusRequest:
    """Construct the exact, deterministic corpus request from committed evidence."""
    if not synthetic_only:
        raise ValueError("geometry analysis requests are synthetic-only")
    if not isinstance(profile, GeometryProfile):
        raise ValueError("profile must be GeometryProfile")
    items: list[GeometrySongRequest] = []
    for song, backbone in _selected_geometry_items(con, song_ids, backbones):
        song_id = str(song["song_id"])
        observation, identity = _committed_geometry_observation(stream_store, song_id, backbone, profile)
        record = verify_geometry_current(con, observation, profile=profile, exact_identity=identity)
        if record is None:
            raise IntegrityRefused("INTEGRITY_REFUSED: committed geometry is absent for the corpus request")
        items.append(
            GeometrySongRequest(
                song_id=song_id,
                backbone=backbone,
                geometry_identity=identity,
                observation_evidence=dict(record.evidence),
                artist=str(song["artist"]) if song.get("artist") else None,
                genre=str(song["genre"]) if song.get("genre") else None,
                synthetic_only=True,
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
        synthetic_only=True,
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
    """Aligned ``(AllThresholdAnalysis, GeometrySongAnalysis)`` pairs in request order."""
    if not result.queries:
        return ()
    if len(result.analyses) != len(result.queries):
        raise ValueError("geometry corpus analyses and queries are misaligned")
    return tuple(zip(result.analyses, result.queries, strict=True))


def _analysis_searchable_count(analysis: Any) -> int:
    return max((int(result.search.total_searchable) for result in analysis.results), default=0)


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
                searchable_count=_analysis_searchable_count(analysis),
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
    searchable = {entry.song_id: entry.searchable_count for entry in _membership_entries(result)}
    entries: list[GeometryQueryEvidence] = []
    for query in result.queries:
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
                searchable_count=int(searchable.get(str(query.request.song_id), 0)),
                neighborhood=query.neighborhood,
                baseline_neighborhood=query.baseline_neighborhood,
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


def _corpus_evidence(result: GeometryCorpusAnalysis) -> dict[str, Any]:
    from dataclasses import asdict

    membership = _membership_entries(result)
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
    }


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
    )
    from scripts.embedding_research.db.identity_persistence import write_analysis_rows_in_transaction

    if not isinstance(result, GeometryCorpusAnalysis) or result.refusal_status:
        raise ValueError("refused geometry analysis cannot be published")
    if not result.synthetic_only:
        raise ValueError("geometry corpus publication is synthetic-only")
    if not run_id or str(result.run_id) != str(run_id):
        raise ValueError("geometry corpus run identity does not match the publication run")

    corpus_identity = _corpus_evidence_identity(result)
    corpus_metrics = _corpus_metrics(result)
    corpus_evidence = _corpus_evidence(result)
    _assert_finite_tree(corpus_metrics, where="corpus")
    _assert_finite_tree(corpus_evidence, where="corpus-evidence")

    analysis_pairs = _analysis_query_pairs(result)
    if not analysis_pairs and result.analyses:
        analysis_pairs = tuple((analysis, None) for analysis in result.analyses)
    noncomparable_ids = {(ev.song_id, ev.search_representation_id) for ev in result.noncomparable}
    per_threshold: list[tuple[Any, dict[str, float], dict[str, Any]]] = []
    for analysis, query in analysis_pairs:
        song_id = "" if query is None else str(query.request.song_id)
        backbone = "" if query is None else str(query.request.backbone)
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
        _revalidate_geometry_bindings(result, con, stream_store=stream_store, profile=profile)
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
    _revalidate_geometry_axis_payloads(
        corpus_evidence.get("geometry_axes"), con, stream_store=stream_store, profile=profile
    )
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
    return any(_ruler_label(getattr(item, name)) is not None for name in ("artist", "genre", "head_label"))


def _normalized_query_vectors(stream: Any, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Row-normalize the exact searchable observation rows into a finite query manifest."""
    values = np.asarray(stream, dtype=np.float32)
    searchable = values[np.asarray(mask, dtype=np.uint8) == 1]
    if searchable.shape[0] == 0:
        return np.zeros((0, values.shape[1]), dtype=np.float32), np.zeros(0, dtype=np.float64)
    normalized = normalize_float32(searchable)
    array = np.asarray(normalized, dtype=np.float32)
    norms = np.linalg.norm(array, axis=1)
    keep = np.isfinite(norms) & (norms > 0)
    array = array[keep]
    return np.array(array, dtype=np.float32, order="C", copy=True), np.ones(array.shape[0], dtype=np.float64)


def _select_neighborhood(
    scores: Mapping[str, float],
    lookup: Mapping[str, FrozenSearchRepresentation],
    *,
    limit: int = _NEIGHBORHOOD_SIZE,
) -> tuple[NeighborhoodEntry, ...]:
    """Deterministic descending-score top-N with a search-identity tie-break."""
    ranked = sorted(((str(key), float(value)) for key, value in scores.items()), key=lambda pair: (-pair[1], pair[0]))
    entries: list[NeighborhoodEntry] = []
    for rank, (key, value) in enumerate(ranked[:limit]):
        representation = lookup.get(key)
        if representation is None:
            continue
        _finite(value, "score")
        entries.append(
            NeighborhoodEntry(
                rank,
                representation.song_id,
                representation.backbone,
                key,
                value,
            )
        )
    return tuple(entries)
