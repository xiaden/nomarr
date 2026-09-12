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
from scripts.embedding_research.helpers.gram_segmentation import (
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
    observation_id: str
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
            "observation_id",
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
    observation_id: str
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
            "observation_id",
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
    """Per-song geometry analysis combining threshold structure, roster, and scores."""

    request: GeometrySongRequest
    thresholds: AllThresholdAnalysis
    roster: GeometryRepresentationRoster
    scores: GeometryScoreBundle


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
    """Aggregate finite per-song winner/baseline scores into three independent rulers.

    The geometry corpus owns one bounded winner score and one separate observed
    whole-song medoid baseline score per song; there is no cross-class retrieval pool
    to borrow from.  Each ruler (artist, genre, and the frozen semantic-head full
    tuple) builds its own labeled population from that song's labels.  A ``None`` or
    blank label is locally absent (never an ``unknown`` bucket), so the song is
    excluded from that ruler only.  A baseline delta is retained only when the
    evaluation identity is comparable and the baseline score exists.  No other
    vocabulary, IO, or segmentation is owned here.
    """
    labels_by_ruler = {
        "artist": {analysis.request.song_id: _ruler_label(analysis.request.artist) for analysis in analyses},
        "genre": {analysis.request.song_id: _ruler_label(analysis.request.genre) for analysis in analyses},
        "head": {analysis.request.song_id: _ruler_label(analysis.request.head_label) for analysis in analyses},
    }
    per_song: dict[str, dict[str, float]] = {}
    for analysis in analyses:
        song_id = analysis.request.song_id
        bundle = analysis.scores
        winner = max((float(value) for value in bundle.scores.values()), default=0.0)
        baseline = None if bundle.baseline_score is None else float(bundle.baseline_score)
        comparable = bool(bundle.scores) and baseline is not None and bundle.evaluation_comparable
        entry: dict[str, float] = {"winner_score": winner, "comparable": 1.0 if comparable else 0.0}
        if baseline is not None:
            entry["baseline_score"] = baseline
            if comparable:
                entry["baseline_delta"] = winner - baseline
        per_song[song_id] = entry

    aggregate: dict[str, dict[str, float]] = {}
    baseline_deltas: dict[str, float] = {}
    all_song_ids = tuple(sorted(per_song))
    for ruler, labels in labels_by_ruler.items():
        labeled = [song_id for song_id in all_song_ids if labels.get(song_id) is not None]
        winners = [per_song[song_id]["winner_score"] for song_id in labeled]
        baselines = [
            per_song[song_id]["baseline_score"] for song_id in labeled if "baseline_score" in per_song[song_id]
        ]
        deltas = [per_song[song_id]["baseline_delta"] for song_id in labeled if "baseline_delta" in per_song[song_id]]
        mean_delta = float(np.mean(deltas)) if deltas else 0.0
        aggregate[ruler] = {
            "active": 1.0 if labeled else 0.0,
            "n_songs": float(len(labeled)),
            "n_compared": float(len(deltas)),
            "missing_count": float(len(all_song_ids) - len(labeled)),
            "mean_winner": float(np.mean(winners)) if winners else 0.0,
            "mean_baseline": float(np.mean(baselines)) if baselines else 0.0,
            "mean_delta": mean_delta,
        }
        baseline_deltas[ruler] = mean_delta
    return aggregate["artist"], aggregate["genre"], aggregate["head"], per_song, baseline_deltas


def _stable_id(*parts: object) -> str:
    from scripts.embedding_research.db.identity_persistence import _json

    payload = _json(parts)
    return "geometry-" + payload.encode("utf-8").hex()[:48]


def _observation_geometry_identity(observation: Any, profile: GeometryProfile) -> GeometryIdentity:
    identity = getattr(observation, "identity", None)
    if identity is None:
        raise ValueError("committed observation has no identity")
    commit = getattr(identity, "commit_sha256", None)
    if not commit:
        raise ValueError("committed observation has no commit identity")
    semantics = profile.to_manifest().get("geometry_semantics_version")
    if not semantics:
        raise ValueError("geometry profile has no geometry semantics version")
    return GeometryIdentity(
        str(identity.song_id),
        str(identity.backbone),
        str(commit),
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
    """Run the complete geometry-owned CPU analysis without a compatibility path."""
    if not isinstance(request, GeometryCorpusRequest) or not request.synthetic_only:
        raise ValueError("a synthetic geometry corpus request is required")
    song_results: list[GeometrySongAnalysis] = []
    final_scores: GeometryScoreBundle | None = None
    geometry_loads = observation_loads = threshold_batches = gather_count = scorer_count = 0
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
        if not isinstance(request.threshold_request, PrimaryThresholdRequest):
            raise ValueError("secondary geometry analysis owner is not available")
        thresholds = analyze_all_thresholds(record, mask, request.threshold_request, experiment=request.experiment)
        threshold_batches += 1
        buckets: dict[tuple[object, ...], list[Any]] = {}
        for result in thresholds.results:
            search = result.search
            key = (
                request.experiment,
                search.geometry_id,
                search.observation_id,
                search.profile_digest,
                search.mask_digest,
                search.medoid_source_indices,
                search.searchable_weights,
                search.total_searchable,
                search.scoring_semantics_version,
            )
            buckets.setdefault(key, []).append(result)
        representations: list[FrozenSearchRepresentation] = []
        for _key, members in sorted(buckets.items(), key=lambda pair: int(pair[1][0].threshold.index)):
            search = members[0].search
            indices = tuple(int(index) for index in search.medoid_source_indices if index is not None)
            if not indices:
                continue
            weights = np.asarray(search.searchable_weights, dtype=np.float64)
            vectors = stream_store.batch_gather(item.song_id, item.backbone, indices, forbid_duplicates=True)
            gather_count += 1
            rep = FrozenSearchRepresentation(
                item.song_id,
                item.backbone,
                indices,
                vectors,
                weights,
                search.search_representation_id,
                search.geometry_id,
                search.observation_id,
                search.profile_digest,
                search.mask_digest,
                search.scoring_semantics_version,
                request.experiment,
                tuple(int(member.threshold.index) for member in members),
            )
            representations.append(rep)
        gram = np.asarray(record.matrix, dtype=np.float32)
        medoid, _centrality = observed_global_medoid_from_gram(gram, mask)
        baseline = None
        if medoid is not None:
            baseline_indices = (int(medoid),)
            baseline_vectors = stream_store.batch_gather(
                item.song_id, item.backbone, baseline_indices, forbid_duplicates=True
            )
            gather_count += 1
            baseline = FrozenSearchRepresentation(
                item.song_id,
                item.backbone,
                baseline_indices,
                baseline_vectors,
                np.ones(1, dtype=np.float64),
                _stable_id("baseline", item.geometry_identity.observation_commit_sha256, medoid),
                _stable_id(
                    record.identity.song_id, record.identity.backbone, record.identity.observation_commit_sha256
                ),
                item.geometry_identity.observation_commit_sha256,
                profile.digest,
                str(item.observation_evidence.get("mask_payload_sha256", "")),
                request.scoring_semantics_version,
                request.experiment,
                (),
                True,
            )
        roster = GeometryRepresentationRoster(tuple(representations), baseline)
        evidence_digest = str(
            item.observation_evidence.get(
                "observation_id", item.observation_evidence.get("observation_commit_sha256", "")
            )
        )
        evaluation = FrozenGeometryEvaluation(
            evaluation_id=request.evaluation_id,
            query_vectors=np.asarray(observation.stream, dtype=np.float32),
            query_weights=np.ones(observation.stream.shape[0], dtype=np.float64),
            eligible_song_ids=tuple(entry.song_id for entry in request.items),
            observation_evidence_digest=evidence_digest,
            comparable=bool(evidence_digest),
        )
        scores = score_unique_geometry_representations(roster, evaluation, scoring)
        # Re-read the CURRENT committed tuple at the execution boundary; a superseding
        # publication must refuse before any result escapes the owner.
        preflight_geometry_binding(record, profile, store=stream_store)
        final_scores = scores
        scorer_count += scores.scorer_call_count
        song_results.append(GeometrySongAnalysis(item, thresholds, roster, scores))
    all_rosters = tuple(result.roster for result in song_results)
    combined = GeometryRepresentationRoster(
        tuple(rep for roster in all_rosters for rep in roster.representations), None
    )
    counters = GeometryAnalysisCounters(
        geometry_loads,
        observation_loads,
        threshold_batches,
        sum(r.unique_representation_count for r in all_rosters),
        gather_count,
        scorer_count,
        0,
    )
    artist_metrics, genre_metrics, head_metrics, per_song_metrics, baseline_deltas = _geometry_ruler_metrics(
        tuple(song_results)
    )
    return GeometryCorpusAnalysis(
        request.run_id,
        request.execution_id,
        request.experiment,
        request.evaluation_id,
        request.numerical_profile_digest,
        request.scoring_semantics_version,
        tuple(result.thresholds for result in song_results),
        combined,
        final_scores if len(song_results) == 1 else None,
        all_rosters[0].observed_baseline if len(song_results) == 1 else None,
        artist_metrics=artist_metrics,
        genre_metrics=genre_metrics,
        head_metrics=head_metrics,
        per_song_metrics=per_song_metrics,
        baseline_deltas=baseline_deltas,
        comparable=all(result.scores.evaluation_comparable for result in song_results),
        counters=counters,
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
    if not reps:
        raise ValueError("geometry corpus analysis has no representation evidence to publish")
    return tuple(reps)


def _corpus_backbones(result: GeometryCorpusAnalysis) -> tuple[str, ...]:
    backbones = sorted({str(rep.backbone) for rep in _corpus_representations(result) if getattr(rep, "backbone", None)})
    if not backbones:
        raise ValueError("geometry corpus analysis has no backbone identity to publish")
    return tuple(backbones)


def _geometry_versions(result: GeometryCorpusAnalysis) -> dict[tuple[str, str, str], str]:
    versions: dict[tuple[str, str, str], str] = {}
    for analysis in result.analyses:
        version = str(getattr(analysis, "geometry_semantics_version", ""))
        if not version:
            raise ValueError("geometry corpus analysis is missing a geometry semantics version")
        key = (str(analysis.geometry_id), str(analysis.observation_id), str(analysis.profile_digest))
        existing = versions.setdefault(key, version)
        if existing != version:
            raise ValueError("mixed geometry semantics version across corpus analyses")
    return versions


def _geometry_axes_payload(result: GeometryCorpusAnalysis) -> list[dict[str, str]]:
    versions = _geometry_versions(result)
    axes: list[dict[str, str]] = []
    for rep in _corpus_representations(result):
        key = (str(rep.geometry_id), str(rep.observation_id), str(rep.numerical_profile_digest))
        version = versions.get(key)
        if version is None:
            raise ValueError("representation has no matching corpus geometry identity")
        axes.append(
            {
                "song_id": str(rep.song_id),
                "backbone": str(rep.backbone),
                "geometry_id": str(rep.geometry_id),
                "observation_id": str(rep.observation_id),
                "geometry_semantics_version": version,
                "numerical_profile_digest": str(rep.numerical_profile_digest),
            }
        )
    return axes


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
            axis["observation_id"],
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


def _uniform_corpus_analysis(result: GeometryCorpusAnalysis) -> Any:
    if not result.analyses:
        raise ValueError("geometry corpus analysis has no threshold analyses")
    first = result.analyses[0]
    signature = (
        str(first.geometry_id),
        str(first.observation_id),
        str(first.profile_digest),
        str(getattr(first, "geometry_semantics_version", "")),
    )
    for analysis in result.analyses:
        current = (
            str(analysis.geometry_id),
            str(analysis.observation_id),
            str(analysis.profile_digest),
            str(getattr(analysis, "geometry_semantics_version", "")),
        )
        if current != signature:
            raise ValueError("mixed geometry scope across corpus analyses")
    return first


def _corpus_evidence_identity(result: GeometryCorpusAnalysis) -> Any:
    from types import SimpleNamespace

    first = _uniform_corpus_analysis(result)
    return SimpleNamespace(
        geometry_id=str(first.geometry_id),
        observation_id=str(first.observation_id),
        geometry_semantics_version=str(first.geometry_semantics_version),
        numerical_profile_digest=str(first.profile_digest),
        threshold_id=_CORPUS_THRESHOLD_ID,
        structural_identity=f"{result.experiment}:corpus",
        evaluation_id=str(result.evaluation_id),
        search_representation_id=_CORPUS_SEARCH_REPRESENTATION_ID,
        scoring_semantics_version=int(result.scoring_semantics_version),
        execution_id=str(result.execution_id),
    )


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

    return {
        "role": "corpus",
        "run_id": str(result.run_id),
        "execution_id": str(result.execution_id),
        "evaluation_id": str(result.evaluation_id),
        "experiment": str(result.experiment),
        "scoring_semantics_version": int(result.scoring_semantics_version),
        "comparable": bool(result.comparable),
        "counters": asdict(result.counters),
        "artist_metrics": {key: float(value) for key, value in result.artist_metrics.items()},
        "genre_metrics": {key: float(value) for key, value in result.genre_metrics.items()},
        "head_metrics": {key: float(value) for key, value in result.head_metrics.items()},
        "per_song_metrics": {
            str(song): {key: float(value) for key, value in values.items()}
            for song, values in result.per_song_metrics.items()
        },
        "baseline_deltas": {key: float(value) for key, value in result.baseline_deltas.items()},
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

    per_threshold: list[tuple[Any, dict[str, float], dict[str, Any]]] = []
    for analysis in result.analyses:
        for item in analysis.results:
            threshold_identity = SimpleNamespace(
                geometry_id=str(item.search.geometry_id),
                observation_id=str(item.search.observation_id),
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
                        "geometry_semantics_version": str(analysis.geometry_semantics_version),
                        "mask_digest": str(analysis.mask_digest),
                        "structural_identity": str(getattr(item.structural, "identity", "")),
                        "scoring_semantics_version": int(item.search.scoring_semantics_version),
                    },
                )
            )

    backbones = _corpus_backbones(result)
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
                backbones=[(backbone, str(corpus_identity.geometry_id)) for backbone in backbones],
            )
        for threshold_identity, metrics, evidence in per_threshold:
            write_analysis_rows_in_transaction(
                con, run_id=run_id, identity=threshold_identity, metrics=metrics, evidence=evidence
            )
        if result.baseline is None:
            raise ValueError("geometry corpus analysis has no mandatory observed baseline")
        baseline_metrics: dict[str, float] = {"baseline_present": 1.0}
        for key, value in result.baseline_deltas.items():
            baseline_metrics[f"baseline_delta_{key}"] = float(value)
        _assert_finite_tree(baseline_metrics, where="baseline")
        for backbone in backbones:
            baseline_identity = SimpleNamespace(
                geometry_id=str(corpus_identity.geometry_id),
                observation_id=str(corpus_identity.observation_id),
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
        if not result.comparable:
            raise ValueError(
                "refusing to publish non-comparable geometry corpus analysis: the geometry-era "
                "incomplete-diagnostics owner is not available"
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
            str(axis["observation_id"]),
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


def read_geometry_corpus_analysis(
    con: Any,
    *,
    run_id: str,
    identity: Any,
    stream_store: Any = None,
    profile: GeometryProfile | None = None,
) -> GeometryCorpusAnalysis:
    """Read exactly one complete geometry corpus scope; no alternate scope is selected."""
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
    counters = corpus_evidence.get("counters")
    if not isinstance(counters, dict):
        raise ValueError("geometry corpus counters are missing")
    return GeometryCorpusAnalysis(
        run_id=str(run_id),
        execution_id=str(identity.execution_id),
        experiment=str(corpus_evidence["experiment"]),
        evaluation_id=str(identity.evaluation_id),
        numerical_profile_digest=str(identity.numerical_profile_digest),
        scoring_semantics_version=int(corpus_evidence["scoring_semantics_version"]),
        analyses=(),
        roster=None,
        scores=None,
        baseline=None,
        artist_metrics={str(k): float(v) for k, v in corpus_evidence["artist_metrics"].items()},
        genre_metrics={str(k): float(v) for k, v in corpus_evidence["genre_metrics"].items()},
        head_metrics={str(k): float(v) for k, v in corpus_evidence["head_metrics"].items()},
        per_song_metrics={
            str(song): {str(k): float(v) for k, v in values.items()}
            for song, values in corpus_evidence["per_song_metrics"].items()
        },
        baseline_deltas={str(k): float(v) for k, v in corpus_evidence["baseline_deltas"].items()},
        comparable=bool(corpus_evidence["comparable"]),
        counters=GeometryAnalysisCounters(**counters),
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
