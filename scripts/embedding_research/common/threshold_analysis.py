"""One-load, threshold-independent analysis over persisted Gram geometry.

This module is deliberately pure and research-only.  Structure is derived from the
verified Gram bytes before any representation/scoring work; searchable projections
are then derived from the one exact committed mask.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import numpy as np

from scripts.embedding_research.helpers.chebyshev_segmentation import (
    ChebyshevRefusalError,
    temporal_perdim_from_coordinates,
)
from scripts.embedding_research.helpers.gram_segmentation import (
    GramRefusalError,
    derive_all_temporal_global,
    require_exact_binary_mask,
    search_projection_from_gram,
)

PRIMARY_EXPERIMENT = "temporal_global"
SECONDARY_EXPERIMENT = "temporal_perdim_chebyshev_secondary"
PRIMARY_THRESHOLD_COUNT = 171
PRIMARY_THRESHOLD_START = np.float32(0.30)
PRIMARY_THRESHOLD_STEP = np.float32(0.01)
PRIMARY_THRESHOLD_END = np.float32(2.00)
PRIMARY_EXPERIMENT_VERSION = "experiment_one_v1"


def primary_experiment_manifest() -> dict[str, object]:
    """Return the immutable identity used by default analysis/report evidence.

    The manifest is deliberately derived from the indexed request rather than from
    a configurable range.  Callers may serialize it, but cannot alter the default
    grid by changing report or CLI settings.
    """
    request = PrimaryThresholdRequest.dense_default()
    values = tuple(spec.value for spec in request.thresholds)
    return {
        "experiment": PRIMARY_EXPERIMENT,
        "experiment_version": PRIMARY_EXPERIMENT_VERSION,
        "threshold_indices": request.indices,
        "threshold_values": values,
        "threshold_start": float(PRIMARY_THRESHOLD_START),
        "threshold_step": float(PRIMARY_THRESHOLD_STEP),
        "threshold_end": float(PRIMARY_THRESHOLD_END),
        "threshold_count": PRIMARY_THRESHOLD_COUNT,
    }


def _threshold_value(index: int) -> np.float32:
    """Materialize one Experiment One value using pinned float32 arithmetic."""
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < PRIMARY_THRESHOLD_COUNT:
        raise ValueError(f"threshold index must be in 0..170; got {index!r}")
    return np.float32(PRIMARY_THRESHOLD_START + np.float32(np.float32(index) * PRIMARY_THRESHOLD_STEP))


def _digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ThresholdSpec:
    """Stable indexed threshold identity and its canonical float32 value."""

    index: int
    value: float
    threshold_id: str


@dataclass(frozen=True)
class PrimaryThresholdRequest:
    """An ordered integer-indexed primary request."""

    indices: tuple[int, ...]
    experiment: str = PRIMARY_EXPERIMENT

    def __post_init__(self) -> None:
        if self.experiment != PRIMARY_EXPERIMENT:
            raise ValueError("primary threshold requests must use temporal_global")
        if self.indices != tuple(range(PRIMARY_THRESHOLD_COUNT)):
            raise ValueError("the primary request is exactly threshold indices 0..170")

    @classmethod
    def dense_default(cls) -> PrimaryThresholdRequest:
        return cls(tuple(range(PRIMARY_THRESHOLD_COUNT)))

    @property
    def thresholds(self) -> tuple[ThresholdSpec, ...]:
        return tuple(
            ThresholdSpec(
                i, float(_threshold_value(i)), f"{self.experiment}:threshold:{i}:{float(_threshold_value(i))}"
            )
            for i in self.indices
        )


@dataclass(frozen=True)
class SecondaryChebyshevRequest:
    """Explicit coordinate-input request; it can never be treated as Gram-primary."""

    thresholds: tuple[float, ...]
    experiment: str = SECONDARY_EXPERIMENT

    def __post_init__(self) -> None:
        if self.experiment != SECONDARY_EXPERIMENT:
            raise ValueError("Chebyshev requests must use the explicit secondary experiment")
        values = np.asarray(self.thresholds)
        if values.ndim != 1 or not np.issubdtype(values.dtype, np.number) or not np.isfinite(values).all():
            raise ValueError("secondary Chebyshev thresholds must be finite numeric values")
        if (values < 0).any():
            raise ValueError("secondary Chebyshev thresholds must be non-negative")


def analyze_secondary_all_thresholds(
    coordinate_stream: Any,
    committed_mask: Any,
    threshold_request: SecondaryChebyshevRequest,
) -> AllThresholdAnalysis:
    """Derive explicit secondary Chebyshev thresholds from coordinate evidence."""
    request = validate_secondary_chebyshev_request(threshold_request)
    values = np.asarray(coordinate_stream)
    if values.ndim != 2 or not values.size or values.dtype != np.dtype("float32") or not np.isfinite(values).all():
        raise ChebyshevRefusalError("coordinate stream must be finite float32 evidence")
    mask = np.asarray(committed_mask)
    if mask.dtype != np.dtype("uint8") or mask.ndim != 1 or mask.shape[0] != values.shape[0]:
        raise ChebyshevRefusalError("mask must be exactly uint8[patch_count]")
    if not np.isin(mask, np.asarray((0, 1), dtype=np.uint8)).all():
        raise ChebyshevRefusalError("mask values must be exactly 0 or 1")
    normalized = np.zeros_like(values)
    for row_index, row in enumerate(values):
        norm = np.float32(np.sqrt(np.sum(row * row, dtype=np.float32), dtype=np.float32))
        if norm > np.float32(0.0):
            normalized[row_index] = row / norm
    geometry_id = "secondary-coordinate:" + _digest(normalized.tolist())
    observation_id = "secondary-observation:" + _digest([values.shape, mask.tolist()])
    profile_digest = "secondary-profile:" + _digest([str(values.dtype), values.shape[1]])
    mask_digest = _digest(mask.tolist())
    results: list[ThresholdAnalysisResult] = []
    for index, value in enumerate(request.thresholds):
        spec = ThresholdSpec(
            index, float(np.float32(value)), f"{request.experiment}:threshold:{index}:{float(np.float32(value))}"
        )
        structural = temporal_perdim_from_coordinates(values, spec.value)
        structural_id = _digest(
            [
                request.experiment,
                spec.threshold_id,
                structural.ranges,
                tuple(s.absorbed_indices for s in structural.segments),
            ]
        )
        medoids: list[int | None] = []
        counts: list[int] = []
        for segment in structural.segments:
            candidates = tuple(i for i in segment.indices if mask[i] == 1 and i not in segment.absorbed_indices)
            counts.append(len(candidates))
            if candidates:
                scores = [float(np.mean(normalized[i] @ normalized[list(candidates)].T)) for i in candidates]
                medoids.append(candidates[int(np.argmax(scores))])
            else:
                medoids.append(None)
        total = sum(counts)
        weights = tuple(count / total if total else 0.0 for count in counts)
        search_id = _digest(
            [
                request.experiment,
                structural_id,
                geometry_id,
                observation_id,
                profile_digest,
                mask_digest,
                tuple(medoids),
                weights,
                total,
            ]
        )
        projection = tuple(
            (segment, tuple(i for i in segment.indices if mask[i] == 1 and i not in segment.absorbed_indices))
            for segment in structural.segments
        )
        results.append(
            ThresholdAnalysisResult(
                spec,
                StructuralIdentity(
                    spec.threshold_id,
                    index,
                    structural.ranges,
                    tuple(s.absorbed_indices for s in structural.segments),
                    structural_id,
                ),
                SearchRepresentation(
                    structural_id,
                    tuple(medoids),
                    weights,
                    total,
                    geometry_id,
                    observation_id,
                    profile_digest,
                    mask_digest,
                    1,
                    request.experiment,
                    search_id,
                ),
                projection,
            )
        )
    return AllThresholdAnalysis(
        request.experiment,
        geometry_id,
        observation_id,
        profile_digest,
        mask_digest,
        tuple(results),
        "secondary-coordinate-v1",
        "evaluation:secondary",
        "execution:secondary",
        geometry_decode_count=0,
        mask_validation_count=1,
    )


def dense_primary_threshold_request() -> PrimaryThresholdRequest:
    """Return the exact 171-hypothesis default request."""
    return PrimaryThresholdRequest.dense_default()


def validate_secondary_chebyshev_request(request: object) -> SecondaryChebyshevRequest:
    """Require an explicit secondary request, never silently coerce a primary one."""
    if not isinstance(request, SecondaryChebyshevRequest):
        raise ValueError("temporal_perdim_chebyshev_secondary requires an explicit SecondaryChebyshevRequest")
    return request


@dataclass(frozen=True)
class StructuralIdentity:
    """Canonical structural segmentation identity for one primary threshold."""

    threshold_id: str
    threshold_index: int
    ranges: tuple[tuple[int, int], ...]
    absorbed_indices: tuple[tuple[int, ...], ...]
    identity: str


@dataclass(frozen=True)
class SearchRepresentation:
    """Canonical searchable membership and observed-medoid representation for a threshold."""

    structural_identity: str
    medoid_source_indices: tuple[int | None, ...]
    searchable_weights: tuple[float, ...]
    total_searchable: int
    geometry_id: str
    observation_id: str
    profile_digest: str
    mask_digest: str
    scoring_semantics_version: int
    experiment: str
    search_representation_id: str


@dataclass(frozen=True)
class ThresholdAnalysisResult:
    """Pair one threshold's structural identity with its searchable projection."""

    threshold: ThresholdSpec
    structural: StructuralIdentity
    search: SearchRepresentation
    search_projection: Any


@dataclass(frozen=True)
class SearchRepresentationClass:
    """Transient equivalence class of equal per-song scoring inputs.

    The key is deliberately derived only from the scoring representation and experiment
    identity; structural threshold identity remains on each member result.  Classes are
    recomputed in memory and never persisted as relationships.
    """

    key: tuple[object, ...]
    canonical_threshold_index: int
    member_threshold_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        members = tuple(sorted({int(index) for index in self.member_threshold_indices}))
        if not members:
            raise ValueError("a search-representation class must have members")
        if int(self.canonical_threshold_index) != members[0]:
            raise ValueError("canonical threshold must be the lowest member index")
        object.__setattr__(self, "member_threshold_indices", members)

    @property
    def canonical_member_index(self) -> int:
        return self.canonical_threshold_index


@dataclass(frozen=True)
class AnalysisEvidenceIdentity:
    """Complete identity tuple for one disposable analysis execution.

    These values are evidence, not executable threshold-result identities.  A
    writer must have all members before publishing any metric row.
    """

    geometry_id: str
    observation_id: str
    geometry_semantics_version: str
    numerical_profile_digest: str
    threshold_id: str
    structural_identity: str
    evaluation_id: str
    search_representation_id: str
    scoring_semantics_version: int
    execution_id: str

    def __post_init__(self) -> None:
        fields = {
            "geometry_id": self.geometry_id,
            "observation_id": self.observation_id,
            "geometry_semantics_version": self.geometry_semantics_version,
            "numerical_profile_digest": self.numerical_profile_digest,
            "threshold_id": self.threshold_id,
            "structural_identity": self.structural_identity,
            "evaluation_id": self.evaluation_id,
            "search_representation_id": self.search_representation_id,
            "execution_id": self.execution_id,
        }
        missing = [name for name, value in fields.items() if not isinstance(value, str) or not value]
        if missing:
            raise ValueError("analysis evidence identity is incomplete: " + ", ".join(missing))
        if isinstance(self.scoring_semantics_version, bool) or self.scoring_semantics_version < 1:
            raise ValueError("scoring_semantics_version must be positive")


@dataclass(frozen=True)
class AllThresholdAnalysis:
    """Complete 171-grid threshold analysis with exact identity and execution counters."""

    experiment: str
    geometry_id: str
    observation_id: str
    profile_digest: str
    mask_digest: str
    results: tuple[ThresholdAnalysisResult, ...]
    geometry_semantics_version: str = ""
    evaluation_id: str = ""
    execution_id: str = ""
    geometry_decode_count: int = 1
    mask_validation_count: int = 1
    stream_gather_count: int = 0
    segmentation_from_scorer_count: int = 0

    def __post_init__(self) -> None:
        if not self.geometry_id or not self.observation_id or not self.profile_digest or not self.mask_digest:
            raise ValueError("analysis evidence requires complete geometry/observation/profile/mask identity")
        if not self.geometry_semantics_version:
            raise ValueError("analysis evidence requires geometry_semantics_version")
        if not self.evaluation_id or not self.execution_id:
            raise ValueError("analysis evidence requires evaluation_id and execution_id")
        if any(
            count < 0
            for count in (
                self.geometry_decode_count,
                self.mask_validation_count,
                self.stream_gather_count,
                self.segmentation_from_scorer_count,
            )
        ):
            raise ValueError("analysis counters must be non-negative")

    @property
    def representation_classes(self) -> tuple[SearchRepresentationClass, ...]:
        """Recompute transient threshold classes from the current result tuple."""
        return collapse_search_representations(self)

    @property
    def unique_search_representations(self) -> tuple[SearchRepresentation, ...]:
        """Return one canonical search payload per transient class, in class order."""
        by_index = {int(result.threshold.index): result.search for result in self.results}
        return tuple(by_index[item.canonical_threshold_index] for item in self.representation_classes)

    @property
    def unique_representation_count(self) -> int:
        return len(self.representation_classes)


def _search_representation_key(search: SearchRepresentation) -> tuple[object, ...]:
    """Return the canonical transient key for one song's search representation."""
    # Threshold-independent collapse is allowed only within one observation and mode.
    # Structural identity and threshold ids are intentionally absent: they describe
    # geometry, not the exact source-index/weight inputs consumed by scoring.
    return (
        search.experiment,
        search.observation_id,
        search.profile_digest,
        search.mask_digest,
        tuple(search.medoid_source_indices),
        tuple(float(weight) for weight in search.searchable_weights),
        int(search.total_searchable),
        int(search.scoring_semantics_version),
    )


def collapse_search_representations(
    analysis: AllThresholdAnalysis,
) -> tuple[SearchRepresentationClass, ...]:
    """Collapse equal transient search inputs, preserving structural members.

    The returned classes are sorted by their lowest threshold index.  No durable
    relationship is created, and equal numeric thresholds from the secondary Chebyshev
    experiment cannot collapse with primary L2 representations because ``experiment``
    is part of the key.
    """
    buckets: dict[tuple[object, ...], list[int]] = {}
    for result in analysis.results:
        buckets.setdefault(_search_representation_key(result.search), []).append(int(result.threshold.index))
    classes = [SearchRepresentationClass(key, min(indices), tuple(sorted(indices))) for key, indices in buckets.items()]
    return tuple(sorted(classes, key=lambda item: item.canonical_threshold_index))


def _observation_id(record: Any) -> str:
    identity = getattr(record, "identity", None)
    if identity is None:
        return ""
    return _digest({"identity": dict(vars(identity))})


def _verified_geometry_decode(record: Any) -> np.ndarray:
    blob = bytes(record.gram_blob)
    matrix = np.frombuffer(blob, dtype="<f4")
    side = int(np.sqrt(matrix.size))
    if side <= 0 or side * side != matrix.size:
        raise GramRefusalError("geometry BLOB is not a complete square matrix")
    decoded = np.asarray(matrix.reshape((side, side), order="C"), dtype="<f4", order="C")
    if not np.isfinite(decoded).all():
        raise GramRefusalError("geometry BLOB is non-finite")
    stored = np.asarray(record.matrix, dtype="<f4", order="C")
    if stored.shape != decoded.shape or not np.array_equal(stored, decoded):
        raise GramRefusalError("geometry BLOB and decoded matrix disagree")
    return decoded


def analyze_all_thresholds(
    geometry_record: Any,
    committed_mask: Any,
    threshold_request: PrimaryThresholdRequest,
    experiment: str = PRIMARY_EXPERIMENT,
) -> AllThresholdAnalysis:
    """Decode geometry once, derive every structure and search projection, and return ordered results.

    No stream loader, gather seam, segmentation callback, or similarity/scorer is
    reachable from this function.  Scoring consumes the returned unique search
    representations in a later phase.
    """
    if experiment != PRIMARY_EXPERIMENT:
        raise ValueError("analyze_all_thresholds only accepts the primary Gram experiment")
    if not isinstance(threshold_request, PrimaryThresholdRequest):
        raise ValueError("analyze_all_thresholds requires PrimaryThresholdRequest")
    gram = _verified_geometry_decode(geometry_record)
    mask = require_exact_binary_mask(committed_mask, gram.shape[0])
    structures = derive_all_temporal_global(gram, threshold_request.indices)
    observation_id = _observation_id(geometry_record)
    geometry_id = str(geometry_record.geometry_id)
    evidence = getattr(geometry_record, "evidence", {})
    record_identity = getattr(geometry_record, "identity", None)
    profile_digest = str(getattr(record_identity, "numerical_profile_digest", ""))
    geometry_semantics_version = str(getattr(record_identity, "geometry_semantics_version", ""))
    mask_digest = str(evidence.get("mask_payload_sha256", evidence.get("mask_digest", "")))
    evaluation_id = str(evidence.get("evaluation_id", "evaluation:unbound"))
    execution_id = str(evidence.get("execution_id", "execution:analysis"))
    if not geometry_id or not observation_id or not profile_digest or not geometry_semantics_version or not mask_digest:
        raise GramRefusalError("complete geometry-era analysis identity is required")
    results: list[ThresholdAnalysisResult] = []
    for spec, structural in zip(threshold_request.thresholds, structures, strict=True):
        projection = search_projection_from_gram(structural, gram, mask)
        structural_payload = {
            "experiment": experiment,
            "threshold_id": spec.threshold_id,
            "threshold_index": spec.index,
            "ranges": structural.ranges,
            "absorbed_indices": structural.absorbed_indices,
        }
        structural_id = _digest(structural_payload)
        medoids = tuple(segment.medoid_source_index for segment in projection.segments)
        weights = tuple(float(segment.searchable_weight) for segment in projection.segments)
        search_payload = {
            "medoid_source_indices": medoids,
            "searchable_weights": weights,
            "geometry_id": geometry_id,
            "observation_id": observation_id,
            "profile_digest": profile_digest,
            "mask_digest": mask_digest,
            "scoring_semantics_version": 1,
            "experiment": experiment,
        }
        search_id = _digest(search_payload)
        results.append(
            ThresholdAnalysisResult(
                spec,
                StructuralIdentity(
                    spec.threshold_id, spec.index, structural.ranges, structural.absorbed_indices, structural_id
                ),
                SearchRepresentation(
                    structural_id,
                    medoids,
                    weights,
                    projection.total_searchable,
                    geometry_id,
                    observation_id,
                    profile_digest,
                    mask_digest,
                    1,
                    experiment,
                    search_id,
                ),
                projection,
            )
        )
    return AllThresholdAnalysis(
        experiment,
        geometry_id,
        observation_id,
        profile_digest,
        mask_digest,
        tuple(results),
        geometry_semantics_version,
        evaluation_id,
        execution_id,
    )


__all__ = [
    "AllThresholdAnalysis",
    "AnalysisEvidenceIdentity",
    "PrimaryThresholdRequest",
    "SearchRepresentation",
    "SearchRepresentationClass",
    "SecondaryChebyshevRequest",
    "StructuralIdentity",
    "ThresholdAnalysisResult",
    "ThresholdSpec",
    "analyze_all_thresholds",
    "dense_primary_threshold_request",
    "primary_experiment_manifest",
    "validate_secondary_chebyshev_request",
]
