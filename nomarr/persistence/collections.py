"""Typed persistence collection declarations derived from ``schema.py``."""

from __future__ import annotations

from typing import Any, ClassVar, Literal, cast

from nomarr.persistence.base import (
    CASCADE,
    DETACH,
    INBOUND,
    OUTBOUND,
    DocumentCollection,
    EdgeCollection,
    EdgeDef,
    Field,
    StateGraphCollection,
    UniqueField,
    VectorCollection,
)


class Meta(DocumentCollection):
    key: UniqueField[str]
    value: Field[str]


class Migrations(DocumentCollection):
    _name: ClassVar[str] = "applied_migrations"

    name: UniqueField[str]
    status: Field[str]
    applied_at: Field[str | None]
    started_at: Field[str]
    migration_version: Field[str]
    duration_ms: Field[int | None]


class Health(DocumentCollection):
    component: UniqueField[str]
    component_id: UniqueField[str]
    component_type: Field[str]
    status: Field[str]
    message: Field[str | None]
    last_heartbeat: Field[int]
    current_job: Field[str | None]
    metadata: Field[dict[str, Any] | None]
    pid: Field[int | None]
    exit_code: Field[int | None]
    restart_count: Field[int | None]
    last_restart: Field[int | None]
    error: Field[str | None]
    last_snapshot: Field[int | None]
    created_at: Field[int | None]
    snapshot_type: Field[str | None]


class Sessions(DocumentCollection):
    session_id: UniqueField[str]
    user_id: Field[str]
    expiry_timestamp: Field[int]


class Locks(DocumentCollection):
    document_reference: UniqueField[str]
    lock_type: Field[str]
    expires_at: Field[float]
    acquired_at: Field[float]
    holder: Field[str]
    status: Field[str]


class VramPromises(DocumentCollection):
    worker_id: Field[str]
    pid: Field[int]
    model_path: Field[str]
    promised_mb: Field[float]
    total_mb: Field[float]
    used_mb: Field[float]
    last_seen_ms: Field[int]


class WorkerClaims(DocumentCollection):
    file_id: UniqueField[str]
    worker_id: Field[str]
    claimed_at: Field[int]
    claim_type: Field[str | None]


class WorkerRestartPolicy(DocumentCollection):
    component_id: UniqueField[str]
    restart_count: Field[int]
    last_restart_wall_ms: Field[int | None]
    failed_at_wall_ms: Field[int | None]
    failure_reason: Field[str | None]
    updated_at_wall_ms: Field[int]


class MlCapacity(DocumentCollection):
    """Stores measured ML capacity estimates per model-set hash.

    The ArangoDB collection name is ``ml_capacity_estimates`` (overrides the default
    derived from the class name). Each record captures VRAM and RAM measurements from
    a capacity-probe run for a specific combination of loaded models.
    """

    _name: ClassVar[str] = "ml_capacity_estimates"

    model_set_hash: UniqueField[str]
    measured_backbone_vram_mb: Field[int]
    estimated_worker_ram_mb: Field[int]
    probe_duration_s: Field[float]
    probed_by: Field[str]
    created_at: Field[int | None]
    updated_at: Field[int | None]


class LibraryPipelineStates(DocumentCollection):
    library_key: UniqueField[str]
    pipeline_state: Field[str]


class LibraryScans(DocumentCollection):
    library_key: UniqueField[str]
    status: Field[str]
    files_processed: Field[int]
    files_total: Field[int]
    completed_at: Field[int | None]
    started_at: Field[int | None]
    error: Field[str | None]
    scan_type: Field[str | None]


class LibraryFolders(DocumentCollection):
    path: UniqueField[str]
    library_key: Field[str]


class Libraries(DocumentCollection):
    name: UniqueField[str]
    root_path: UniqueField[str]
    is_enabled: Field[bool]
    watch_mode: Field[str]
    file_write_mode: Field[str]
    library_auto_write: Field[bool]
    created_at: Field[int]
    updated_at: Field[int]
    vector_group_size: Field[int | None]
    vector_search_thoroughness: Field[int | None]


class LibraryFiles(DocumentCollection):
    path: UniqueField[str]
    normalized_path: Field[str]
    library_key: Field[str]
    status: Field[str]
    modified_time: Field[int]
    duration_seconds: Field[float]
    file_size: Field[int]
    album: Field[str | None]
    title: Field[str | None]
    artist: Field[str | None]
    artists: Field[list[str] | None]
    labels: Field[list[str] | None]
    genres: Field[list[str] | None]
    year: Field[int | None]
    scanned_at: Field[int | None]
    chromaprint: Field[str | None]
    is_valid: Field[bool | None]
    last_tagged_at: Field[int | None]


class Tags(DocumentCollection):
    name: Field[str]
    value: Field[str]


class FileStates(StateGraphCollection):
    pass


class CalibrationState(DocumentCollection):
    head_name: Field[str]
    label: Field[str]
    calibration_def_hash: Field[str]
    histogram: Field[dict[str, Any]]
    histogram_bins: Field[list[dict[str, Any]] | None]
    p5: Field[float]
    p95: Field[float]
    n: Field[int]
    underflow_count: Field[int]
    overflow_count: Field[int]
    updated_at: Field[int | None]


class CalibrationHistory(DocumentCollection):
    calibration_key: Field[str]
    snapshot_at: Field[int]
    p5: Field[float]
    p95: Field[float]
    n: Field[int]
    underflow_count: Field[int]
    overflow_count: Field[int]
    p5_delta: Field[float | None]
    p95_delta: Field[float | None]
    n_delta: Field[int | None]


class MlModels(DocumentCollection):
    path: UniqueField[str]
    backbone: Field[str]
    head_type: Field[str]
    model_stem: Field[str]
    output_count: Field[int]
    fully_configured: Field[bool]
    is_known: Field[bool]
    source: Field[str]
    head_release_date: Field[str]
    embedder_release_date: Field[str]
    registered_at: Field[int]
    updated_at: Field[int]


class MlModelOutputs(DocumentCollection):
    output_index: Field[int]
    label: Field[str | None]
    fully_labeled: Field[bool]


class NavidromeTracks(DocumentCollection):
    pass


class NavidromePlaycounts(DocumentCollection):
    playcount: Field[int]
    userid: Field[str]


class SegmentScoresStats(DocumentCollection):
    head_name: Field[str]
    tagger_version: Field[str]
    num_segments: Field[int]
    pooling_strategy: Field[str]
    label_stats: Field[list[dict[str, Any]]]
    processed_at: Field[int]


class VectorsTrackHot(VectorCollection):
    """Hot-tier track embedding vectors, partitioned by backbone and library.

    ``NAME_PATTERN`` is a template; one ArangoDB collection is created per
    ``(backbone_id, library_key)`` combination.  The hot tier holds embeddings for
    recently active or high-priority tracks and is the primary target for
    nearest-neighbour search queries.
    """

    VECTOR_TIER: ClassVar[Literal["hot"]] = "hot"
    NAME_PATTERN: ClassVar[str] = "vectors_track_hot__{backbone_id}__{library_key}"

    file_id: Field[str]
    vector: Field[list[float]]


class VectorsTrackCold(VectorCollection):
    """Cold-tier track embedding vectors, partitioned by backbone and library.

    ``NAME_PATTERN`` is a template; one ArangoDB collection is created per
    ``(backbone_id, library_key)`` combination.  The cold tier holds embeddings for
    less-active tracks that are deprioritised in nearest-neighbour search queries.
    """

    VECTOR_TIER: ClassVar[Literal["cold"]] = "cold"
    NAME_PATTERN: ClassVar[str] = "vectors_track_cold__{backbone_id}__{library_key}"

    file_id: Field[str]
    vector: Field[list[float]]


class SongHasTags(EdgeCollection):
    FROM_COLLECTION = LibraryFiles
    TO_COLLECTION = Tags


class FileHasState(EdgeCollection):
    FROM_COLLECTION = LibraryFiles
    TO_COLLECTION = FileStates


class TagModelOutput(EdgeCollection):
    """Edge from a ``Tags`` document to an ``MlModelOutputs`` document.

    Carries a ``score`` payload representing the confidence assigned to the tag by
    the linked model output, along with creation and update timestamps.
    """

    FROM_COLLECTION = Tags
    TO_COLLECTION = MlModelOutputs

    score: Field[float]
    created_at: Field[int]
    updated_at: Field[int]


class LibraryContainsFile(EdgeCollection):
    FROM_COLLECTION = Libraries
    TO_COLLECTION = LibraryFiles


class LibraryContainsFolder(EdgeCollection):
    FROM_COLLECTION = Libraries
    TO_COLLECTION = LibraryFolders


class LibraryHasScan(EdgeCollection):
    FROM_COLLECTION = Libraries
    TO_COLLECTION = LibraryScans


class FileHasVectors(EdgeCollection):
    FROM_COLLECTION = LibraryFiles
    TO_COLLECTION = cast("type[DocumentCollection]", VectorCollection)


class FileHasSegmentStats(EdgeCollection):
    FROM_COLLECTION = LibraryFiles
    TO_COLLECTION = SegmentScoresStats


class ModelHasOutput(EdgeCollection):
    FROM_COLLECTION = MlModels
    TO_COLLECTION = MlModelOutputs


class ModelHasCalibration(EdgeCollection):
    FROM_COLLECTION = MlModels
    TO_COLLECTION = CalibrationState


class LibraryHasPipelineState(EdgeCollection):
    FROM_COLLECTION = Libraries
    TO_COLLECTION = LibraryPipelineStates


class HasNdId(EdgeCollection):
    FROM_COLLECTION = NavidromeTracks
    TO_COLLECTION = LibraryFiles


class HasPlays(EdgeCollection):
    FROM_COLLECTION = NavidromeTracks
    TO_COLLECTION = NavidromePlaycounts

    last_played: Field[int]


Libraries.EDGES = [
    EdgeDef(via=LibraryContainsFile, direction=OUTBOUND, target=LibraryFiles, on_delete=CASCADE),
    EdgeDef(via=LibraryContainsFolder, direction=OUTBOUND, target=LibraryFolders, on_delete=CASCADE),
    EdgeDef(via=LibraryHasScan, direction=OUTBOUND, target=LibraryScans, on_delete=CASCADE),
    EdgeDef(via=LibraryHasPipelineState, direction=OUTBOUND, target=LibraryPipelineStates, on_delete=CASCADE),
]
LibraryFiles.EDGES = [
    EdgeDef(via=SongHasTags, direction=OUTBOUND, target=Tags, on_delete=CASCADE),
    EdgeDef(via=FileHasState, direction=OUTBOUND, target=FileStates, on_delete=CASCADE),
    EdgeDef(via=FileHasVectors, direction=OUTBOUND, target=VectorCollection, on_delete=CASCADE),
    EdgeDef(via=FileHasSegmentStats, direction=OUTBOUND, target=SegmentScoresStats, on_delete=CASCADE),
    EdgeDef(via=LibraryContainsFile, direction=INBOUND, target=Libraries, on_delete=CASCADE),
]
LibraryFolders.EDGES = [
    EdgeDef(via=LibraryContainsFolder, direction=INBOUND, target=Libraries, on_delete=CASCADE),
]
LibraryScans.EDGES = [
    EdgeDef(via=LibraryHasScan, direction=INBOUND, target=Libraries, on_delete=DETACH),
]
LibraryPipelineStates.EDGES = [
    EdgeDef(via=LibraryHasPipelineState, direction=INBOUND, target=Libraries, on_delete=DETACH),
]
Tags.EDGES = [
    EdgeDef(via=SongHasTags, direction=INBOUND, target=LibraryFiles, on_delete=CASCADE),
    EdgeDef(via=TagModelOutput, direction=OUTBOUND, target=MlModelOutputs, on_delete=CASCADE),
]
FileStates.EDGES = [
    EdgeDef(via=FileHasState, direction=INBOUND, target=LibraryFiles, on_delete=DETACH),
]
CalibrationState.EDGES = [
    EdgeDef(via=ModelHasCalibration, direction=INBOUND, target=MlModels, on_delete=CASCADE),
]
MlModels.EDGES = [
    EdgeDef(via=ModelHasOutput, direction=OUTBOUND, target=MlModelOutputs, on_delete=CASCADE),
    EdgeDef(via=ModelHasCalibration, direction=OUTBOUND, target=CalibrationState, on_delete=CASCADE),
]
MlModelOutputs.EDGES = [
    EdgeDef(via=ModelHasOutput, direction=INBOUND, target=MlModels, on_delete=CASCADE),
]
NavidromeTracks.EDGES = [
    EdgeDef(via=HasNdId, direction=OUTBOUND, target=LibraryFiles, on_delete=CASCADE),
    EdgeDef(via=HasPlays, direction=OUTBOUND, target=NavidromePlaycounts, on_delete=CASCADE),
]
NavidromePlaycounts.EDGES = [
    EdgeDef(via=HasPlays, direction=INBOUND, target=NavidromeTracks, on_delete=DETACH),
]
SegmentScoresStats.EDGES = [
    EdgeDef(via=FileHasSegmentStats, direction=INBOUND, target=LibraryFiles, on_delete=CASCADE),
]


__all__ = [
    "CalibrationHistory",
    "CalibrationState",
    "FileHasSegmentStats",
    "FileHasState",
    "FileHasVectors",
    "FileStates",
    "HasNdId",
    "HasPlays",
    "Health",
    "Libraries",
    "LibraryContainsFile",
    "LibraryContainsFolder",
    "LibraryFiles",
    "LibraryFolders",
    "LibraryHasPipelineState",
    "LibraryHasScan",
    "LibraryPipelineStates",
    "LibraryScans",
    "Locks",
    "Meta",
    "Migrations",
    "MlCapacity",
    "MlModelOutputs",
    "MlModels",
    "ModelHasCalibration",
    "ModelHasOutput",
    "NavidromePlaycounts",
    "NavidromeTracks",
    "SegmentScoresStats",
    "Sessions",
    "SongHasTags",
    "TagModelOutput",
    "Tags",
    "VectorsTrackCold",
    "VectorsTrackHot",
    "VramPromises",
    "WorkerClaims",
    "WorkerRestartPolicy",
]
