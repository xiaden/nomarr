"""CPU-only geometry head-analysis owner.

Head analysis consumes already committed geometry projections and aligned head evidence.  It
never discovers audio, loads models, segments streams, or touches accelerator runtimes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

__all__ = [
    "GeometryHeadAnalysisManifest",
    "GeometryHeadOutput",
    "GeometryHeadRefusalError",
    "run_shared_geometry_head_analysis",
]

SCORING_SEMANTICS_VERSION = 1


class GeometryHeadRefusalError(ValueError):
    """Fail-closed refusal for incomplete, stale, or misaligned head evidence."""


@dataclass(frozen=True)
class GeometryHeadOutput:
    """One validated class-1 head result keyed to exact geometry and threshold evidence."""

    geometry_id: str
    observation_group_sha256: str
    geometry_semantics_version: str
    numerical_profile_digest: str
    threshold_id: str
    structural_identity: str
    search_representation_id: str
    evaluation_id: str
    scoring_semantics_version: int
    execution_id: str
    head: str
    segment_id: int
    member_patch_indices: tuple[int, ...]
    class1: float
    searchable_weight: float
    observed_medoid_source_index: int | None
    observed_medoid_centrality: float | None
    collapse_class_id: str = ""
    collapse_member_threshold_indices: tuple[int, ...] = ()
    status: str = "done"

    def __post_init__(self) -> None:
        for name in (
            "geometry_id",
            "observation_group_sha256",
            "geometry_semantics_version",
            "numerical_profile_digest",
            "threshold_id",
            "structural_identity",
            "search_representation_id",
            "evaluation_id",
            "execution_id",
            "head",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise GeometryHeadRefusalError(f"head output evidence {name} is incomplete")
        if self.status != "done" or self.scoring_semantics_version < 1 or self.segment_id < 0:
            raise GeometryHeadRefusalError("head output has invalid lifecycle evidence")
        if not self.collapse_class_id or not self.collapse_member_threshold_indices:
            raise GeometryHeadRefusalError("head output is missing collapse evidence")
        if not np.isfinite(self.class1) or not np.isfinite(self.searchable_weight):
            raise GeometryHeadRefusalError("head output is non-finite")
        if self.observed_medoid_centrality is not None and not np.isfinite(self.observed_medoid_centrality):
            raise GeometryHeadRefusalError("observed medoid evidence is non-finite")

    def to_dict(self) -> dict[str, Any]:
        return {key: ([*value] if isinstance(value, tuple) else value) for key, value in self.__dict__.items()}


@dataclass(frozen=True)
class GeometryHeadAnalysisManifest:
    """Completed head-analysis outputs and their exact geometry/evaluation provenance."""

    run_id: str
    geometry_id: str
    observation_group_sha256: str
    evaluation_id: str
    execution_id: str
    geometry_semantics_version: str
    numerical_profile_digest: str
    scoring_semantics_version: int
    outputs: tuple[GeometryHeadOutput, ...]
    observed_medoid_source_index: int | None
    observed_medoid_centrality: float | None
    status: str = "done"
    refusal: str | None = None

    def __post_init__(self) -> None:
        if (
            self.status != "done"
            or self.refusal is not None
            or not all(
                (
                    self.run_id,
                    self.geometry_id,
                    self.observation_group_sha256,
                    self.evaluation_id,
                    self.execution_id,
                    self.geometry_semantics_version,
                    self.numerical_profile_digest,
                )
            )
        ):
            raise GeometryHeadRefusalError("head-analysis manifest evidence is incomplete")
        if self.observed_medoid_centrality is not None and not np.isfinite(self.observed_medoid_centrality):
            raise GeometryHeadRefusalError("global observed medoid evidence is non-finite")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "geometry_id": self.geometry_id,
            "observation_group_sha256": self.observation_group_sha256,
            "evaluation_id": self.evaluation_id,
            "execution_id": self.execution_id,
            "geometry_semantics_version": self.geometry_semantics_version,
            "numerical_profile_digest": self.numerical_profile_digest,
            "scoring_semantics_version": self.scoring_semantics_version,
            "observed_medoid_source_index": self.observed_medoid_source_index,
            "observed_medoid_centrality": self.observed_medoid_centrality,
            "status": self.status,
            "outputs": [item.to_dict() for item in self.outputs],
        }


def _head_matrix(store: Any, song_id: str, backbone: str) -> tuple[Any, np.ndarray]:
    loader = next(
        (
            getattr(store, name, None)
            for name in ("load_all", "read_all", "load", "read")
            if getattr(store, name, None) is not None
        ),
        None,
    )
    if loader is None:
        raise GeometryHeadRefusalError("aligned head evidence requires a read payload seam")
    payload = loader(song_id, backbone)
    if payload is None:
        raise GeometryHeadRefusalError("aligned head evidence is missing")
    matrix = next(
        (
            getattr(payload, name, None)
            for name in ("activations", "matrix", "values", "array")
            if getattr(payload, name, None) is not None
        ),
        None,
    )
    if matrix is None and isinstance(payload, np.ndarray):
        matrix = payload
    if matrix is None:
        raise GeometryHeadRefusalError("aligned head payload has no activation matrix")
    return payload, np.asarray(matrix, dtype=np.float32)


def run_shared_geometry_head_analysis(
    geometry_record: Any,
    head_store: Any,
    *,
    analysis: Any,
    run_id: str,
    evaluation_id: str | None = None,
    execution_id: str | None = None,
    current_observation: Any = None,
    profile: Any = None,
    stream_store: Any = None,
) -> GeometryHeadAnalysisManifest:
    """Run geometry-keyed head analysis over one persisted geometry record.

    Consumes verified geometry-derived structural/search membership plus aligned
    committed head evidence, and returns the manifest of per-segment head outputs.
    The caller is responsible for persisting those outputs; this function performs
    no model inference work and refuses incomplete geometry/observation/evaluation/
    execution evidence before any head row is scored.
    """
    from scripts.embedding_research.db.geometry import (
        GeometryRecord,
        preflight_geometry_binding,
    )

    if current_observation is not None:
        if not isinstance(geometry_record, GeometryRecord):
            raise GeometryHeadRefusalError("head analysis requires a complete persisted geometry record")
        preflight_geometry_binding(geometry_record, profile, observation=current_observation)
    evidence = dict(getattr(geometry_record, "evidence", {}) or {})
    geometry_id = str(getattr(geometry_record, "geometry_id", evidence.get("geometry_id", "")))
    identity_obj = getattr(geometry_record, "identity", geometry_record)
    song_id = str(getattr(identity_obj, "song_id", ""))
    backbone = str(getattr(identity_obj, "backbone", ""))
    observation_group_sha256 = str(getattr(analysis, "observation_group_sha256", ""))
    semantics = str(getattr(analysis, "geometry_semantics_version", ""))
    profile_digest = str(getattr(analysis, "profile_digest", ""))
    evaluation = evaluation_id or str(getattr(analysis, "evaluation_id", ""))
    execution = execution_id or str(getattr(analysis, "execution_id", ""))
    if not all((geometry_id, observation_group_sha256, semantics, profile_digest, evaluation, execution, run_id)):
        raise GeometryHeadRefusalError("complete geometry/evaluation/execution evidence is required")
    payload, matrix = _head_matrix(head_store, song_id, backbone)
    if matrix.ndim != 2 or not matrix.shape[0] or not np.isfinite(matrix).all():
        raise GeometryHeadRefusalError("aligned head payload must be finite two-dimensional evidence")
    from scripts.embedding_research.streams.records import parse_dim_by_head, parse_head_ids

    heads = parse_head_ids(getattr(payload, "head_ids", "") or "")
    dims = parse_dim_by_head(getattr(payload, "dim_by_head", "") or "")
    if set(heads) != set(dims) or sum(int(dims[h]) for h in heads) != matrix.shape[1]:
        raise GeometryHeadRefusalError("head identity and dimensions are misaligned")
    medoid = evidence.get("observed_medoid_source_index", getattr(analysis, "observed_medoid_source_index", None))
    centrality = evidence.get("observed_medoid_centrality", getattr(analysis, "observed_medoid_centrality", None))
    classes = tuple(getattr(analysis, "representation_classes", ()) or ())
    collapse: dict[int, tuple[str, tuple[int, ...]]] = {}
    for item in classes:
        members = tuple(int(x) for x in (getattr(item, "member_threshold_indices", ()) or ()))
        for index in members:
            collapse[index] = (str(getattr(item, "key", "class")), members)
    outputs: list[GeometryHeadOutput] = []
    offsets: dict[str, tuple[int, int]] = {}
    cursor = 0
    for head in heads:
        offsets[head] = (cursor, cursor + int(dims[head]))
        cursor += int(dims[head])
    for result in tuple(getattr(analysis, "results", ())):
        for segment_id, segment in enumerate(result.search_projection.segments):
            members = tuple(int(x) for x in segment.searchable_indices)
            if not members:
                continue
            rows = matrix[np.asarray(members, dtype=np.intp)]
            for head in heads:
                start, end = offsets[head]
                pooled = rows[:, start:end].mean(axis=0, dtype=np.float32)
                if pooled.size < 2 or not np.isfinite(pooled).all():
                    raise GeometryHeadRefusalError("head pooling produced incomplete evidence")
                cls = collapse.get(
                    int(result.threshold.index),
                    (str(result.search.search_representation_id), (int(result.threshold.index),)),
                )
                outputs.append(
                    GeometryHeadOutput(
                        geometry_id,
                        observation_group_sha256,
                        semantics,
                        profile_digest,
                        str(result.threshold.threshold_id),
                        result.structural.identity,
                        result.search.search_representation_id,
                        evaluation,
                        int(result.search.scoring_semantics_version),
                        execution,
                        head,
                        segment_id,
                        members,
                        float(pooled[1]),
                        float(segment.searchable_weight),
                        int(segment.medoid_source_index) if segment.medoid_source_index is not None else None,
                        float(segment.medoid_centrality) if segment.medoid_centrality is not None else None,
                        cls[0],
                        cls[1],
                    )
                )
    if current_observation is not None:
        # Re-read the CURRENT committed tuple after computation; a supersession that
        # occurred while pooling must refuse before any head evidence escapes.
        preflight_geometry_binding(geometry_record, profile, store=stream_store, observation=current_observation)
    return GeometryHeadAnalysisManifest(
        run_id,
        geometry_id,
        observation_group_sha256,
        evaluation,
        execution,
        semantics,
        profile_digest,
        SCORING_SEMANTICS_VERSION,
        tuple(outputs),
        int(medoid) if medoid is not None else None,
        float(centrality) if centrality is not None else None,
    )
