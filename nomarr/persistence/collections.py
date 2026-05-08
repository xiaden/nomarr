"""Typed persistence collection declarations derived from ``schema.py``."""

from __future__ import annotations

from typing import Any, ClassVar, Literal, Protocol, cast

from nomarr.persistence.accessors import FieldAccessor
from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.base_types import CASCADE, DETACH, INBOUND, OUTBOUND, EdgeDef
from nomarr.persistence.collections_base import (
    DocumentCollection,
    EdgeCollection,
    StateGraphCollection,
    VectorCollection,
)


class TraversalAccessor(Protocol):
    def __call__(self, start_id: str, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]: ...

    def by_ids(
        self,
        start_ids: list[str],
        *,
        limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> list[dict[str, Any]]: ...


class Meta(DocumentCollection):
    key: FieldAccessor  # str, unique
    value: FieldAccessor  # str

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "meta")
        self.key = self._field("key", unique=True)
        self.value = self._field("value")


class Migrations(DocumentCollection):
    """Tracks migration records.

    The ArangoDB collection name is ``applied_migrations`` rather than a name derived from ``Migrations``. Each document records the name, status, timing, and version of one migration entry.
    """

    name: FieldAccessor  # str, unique
    status: FieldAccessor  # str
    applied_at: FieldAccessor  # str | None
    started_at: FieldAccessor  # str
    migration_version: FieldAccessor  # str
    duration_ms: FieldAccessor  # int | None

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "applied_migrations")
        self.name = self._field("name", unique=True)
        self.status = self._field("status")
        self.applied_at = self._field("applied_at")
        self.started_at = self._field("started_at")
        self.migration_version = self._field("migration_version")
        self.duration_ms = self._field("duration_ms")


class Health(DocumentCollection):
    component: FieldAccessor  # str, unique
    component_id: FieldAccessor  # str, unique
    component_type: FieldAccessor  # str
    status: FieldAccessor  # str
    message: FieldAccessor  # str | None
    last_heartbeat: FieldAccessor  # int
    current_job: FieldAccessor  # str | None
    metadata: FieldAccessor  # dict[str, Any] | None
    pid: FieldAccessor  # int | None
    exit_code: FieldAccessor  # int | None
    restart_count: FieldAccessor  # int | None
    last_restart: FieldAccessor  # int | None
    error: FieldAccessor  # str | None
    last_snapshot: FieldAccessor  # int | None
    created_at: FieldAccessor  # int | None
    snapshot_type: FieldAccessor  # str | None

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "health")
        self.component = self._field("component", unique=True)
        self.component_id = self._field("component_id", unique=True)
        self.component_type = self._field("component_type")
        self.status = self._field("status")
        self.message = self._field("message")
        self.last_heartbeat = self._field("last_heartbeat")
        self.current_job = self._field("current_job")
        self.metadata = self._field("metadata")
        self.pid = self._field("pid")
        self.exit_code = self._field("exit_code")
        self.restart_count = self._field("restart_count")
        self.last_restart = self._field("last_restart")
        self.error = self._field("error")
        self.last_snapshot = self._field("last_snapshot")
        self.created_at = self._field("created_at")
        self.snapshot_type = self._field("snapshot_type")


class Sessions(DocumentCollection):
    session_id: FieldAccessor  # str, unique
    user_id: FieldAccessor  # str
    expiry_timestamp: FieldAccessor  # int

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "sessions")
        self.session_id = self._field("session_id", unique=True)
        self.user_id = self._field("user_id")
        self.expiry_timestamp = self._field("expiry_timestamp")


class Locks(DocumentCollection):
    document_reference: FieldAccessor  # str, unique
    lock_type: FieldAccessor  # str
    expires_at: FieldAccessor  # float
    acquired_at: FieldAccessor  # float
    holder: FieldAccessor  # str
    status: FieldAccessor  # str

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "locks")
        self.document_reference = self._field("document_reference", unique=True)
        self.lock_type = self._field("lock_type")
        self.expires_at = self._field("expires_at")
        self.acquired_at = self._field("acquired_at")
        self.holder = self._field("holder")
        self.status = self._field("status")


class VramPromises(DocumentCollection):
    """Per-worker VRAM reservation records ("promises").

    Each document stores an active worker's self-reported ``promised_mb`` alongside measured ``used_mb`` and ``total_mb`` values. These records coordinate model loading across workers.
    """

    worker_id: FieldAccessor  # str
    pid: FieldAccessor  # int
    model_path: FieldAccessor  # str
    promised_mb: FieldAccessor  # float
    total_mb: FieldAccessor  # float
    used_mb: FieldAccessor  # float
    last_seen_ms: FieldAccessor  # int

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "vram_promises")
        self.worker_id = self._field("worker_id")
        self.pid = self._field("pid")
        self.model_path = self._field("model_path")
        self.promised_mb = self._field("promised_mb")
        self.total_mb = self._field("total_mb")
        self.used_mb = self._field("used_mb")
        self.last_seen_ms = self._field("last_seen_ms")


class WorkerClaims(DocumentCollection):
    file_id: FieldAccessor  # str, unique
    worker_id: FieldAccessor  # str
    claimed_at: FieldAccessor  # int
    claim_type: FieldAccessor  # str | None

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "worker_claims")
        self.file_id = self._field("file_id", unique=True)
        self.worker_id = self._field("worker_id")
        self.claimed_at = self._field("claimed_at")
        self.claim_type = self._field("claim_type")


class WorkerRestartPolicy(DocumentCollection):
    """Runtime restart-state tracker for managed worker components.

    Despite the name, this is not static policy configuration; it records ``restart_count``, restart timing, and failure details for each ``component_id``.
    """

    component_id: FieldAccessor  # str, unique
    restart_count: FieldAccessor  # int
    last_restart_wall_ms: FieldAccessor  # int | None
    failed_at_wall_ms: FieldAccessor  # int | None
    failure_reason: FieldAccessor  # str | None
    updated_at_wall_ms: FieldAccessor  # int

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "worker_restart_policy")
        self.component_id = self._field("component_id", unique=True)
        self.restart_count = self._field("restart_count")
        self.last_restart_wall_ms = self._field("last_restart_wall_ms")
        self.failed_at_wall_ms = self._field("failed_at_wall_ms")
        self.failure_reason = self._field("failure_reason")
        self.updated_at_wall_ms = self._field("updated_at_wall_ms")


class MlCapacity(DocumentCollection):
    """Stores measured ML capacity estimates per model-set hash.

    The ArangoDB collection name is ``ml_capacity_estimates`` (overrides the default
    derived from the class name). Each record captures VRAM and RAM measurements from
    a capacity-probe run for a specific combination of loaded models.
    """

    model_set_hash: FieldAccessor  # str, unique
    measured_backbone_vram_mb: FieldAccessor  # int
    estimated_worker_ram_mb: FieldAccessor  # int
    probe_duration_s: FieldAccessor  # float
    probed_by: FieldAccessor  # str
    created_at: FieldAccessor  # int | None
    updated_at: FieldAccessor  # int | None

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "ml_capacity_estimates")
        self.model_set_hash = self._field("model_set_hash", unique=True)
        self.measured_backbone_vram_mb = self._field("measured_backbone_vram_mb")
        self.estimated_worker_ram_mb = self._field("estimated_worker_ram_mb")
        self.probe_duration_s = self._field("probe_duration_s")
        self.probed_by = self._field("probed_by")
        self.created_at = self._field("created_at")
        self.updated_at = self._field("updated_at")


class LibraryPipelineStates(DocumentCollection):
    library_key: FieldAccessor  # str, unique
    pipeline_state: FieldAccessor  # str

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "library_pipeline_states")
        self.library_key = self._field("library_key", unique=True)
        self.pipeline_state = self._field("pipeline_state")


class LibraryScans(DocumentCollection):
    library_key: FieldAccessor  # str, unique
    status: FieldAccessor  # str
    files_processed: FieldAccessor  # int
    files_total: FieldAccessor  # int
    completed_at: FieldAccessor  # int | None
    started_at: FieldAccessor  # int | None
    error: FieldAccessor  # str | None
    scan_type: FieldAccessor  # str | None

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "library_scans")
        self.library_key = self._field("library_key", unique=True)
        self.status = self._field("status")
        self.files_processed = self._field("files_processed")
        self.files_total = self._field("files_total")
        self.completed_at = self._field("completed_at")
        self.started_at = self._field("started_at")
        self.error = self._field("error")
        self.scan_type = self._field("scan_type")


class LibraryFolders(DocumentCollection):
    path: FieldAccessor  # str, unique
    library_key: FieldAccessor  # str

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "library_folders")
        self.path = self._field("path", unique=True)
        self.library_key = self._field("library_key")


class Libraries(DocumentCollection):
    library_contains_file: TraversalAccessor
    library_contains_folder: TraversalAccessor
    name: FieldAccessor  # str, unique
    root_path: FieldAccessor  # str, unique
    is_enabled: FieldAccessor  # bool
    watch_mode: FieldAccessor  # str
    file_write_mode: FieldAccessor  # str
    library_auto_write: FieldAccessor  # bool
    created_at: FieldAccessor  # int
    updated_at: FieldAccessor  # int
    vector_group_size: FieldAccessor  # int | None
    vector_search_thoroughness: FieldAccessor  # int | None

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "libraries")
        self.name = self._field("name", unique=True)
        self.root_path = self._field("root_path", unique=True)
        self.is_enabled = self._field("is_enabled")
        self.watch_mode = self._field("watch_mode")
        self.file_write_mode = self._field("file_write_mode")
        self.library_auto_write = self._field("library_auto_write")
        self.created_at = self._field("created_at")
        self.updated_at = self._field("updated_at")
        self.vector_group_size = self._field("vector_group_size")
        self.vector_search_thoroughness = self._field("vector_search_thoroughness")


class LibraryFiles(DocumentCollection):
    song_has_tags: TraversalAccessor
    file_has_state: TraversalAccessor
    file_has_segment_stats: TraversalAccessor
    path: FieldAccessor  # str, unique
    normalized_path: FieldAccessor  # str
    library_key: FieldAccessor  # str
    status: FieldAccessor  # str
    modified_time: FieldAccessor  # int
    duration_seconds: FieldAccessor  # float
    file_size: FieldAccessor  # int
    album: FieldAccessor  # str | None
    title: FieldAccessor  # str | None
    artist: FieldAccessor  # str | None
    artists: FieldAccessor  # list[str] | None
    labels: FieldAccessor  # list[str] | None
    genres: FieldAccessor  # list[str] | None
    year: FieldAccessor  # int | None
    scanned_at: FieldAccessor  # int | None
    chromaprint: FieldAccessor  # str | None
    is_valid: FieldAccessor  # bool | None
    last_tagged_at: FieldAccessor  # int | None

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "library_files")
        self.path = self._field("path", unique=True)
        self.normalized_path = self._field("normalized_path")
        self.library_key = self._field("library_key")
        self.status = self._field("status")
        self.modified_time = self._field("modified_time")
        self.duration_seconds = self._field("duration_seconds")
        self.file_size = self._field("file_size")
        self.album = self._field("album")
        self.title = self._field("title")
        self.artist = self._field("artist")
        self.artists = self._field("artists")
        self.labels = self._field("labels")
        self.genres = self._field("genres")
        self.year = self._field("year")
        self.scanned_at = self._field("scanned_at")
        self.chromaprint = self._field("chromaprint")
        self.is_valid = self._field("is_valid")
        self.last_tagged_at = self._field("last_tagged_at")

    def get_files_by_paths_bulk(self, paths: list[str]) -> dict[str, dict[str, Any]]:
        """Return exact path matches keyed by the original requested path.

        Exact lookup mirrors ``get_library_file()`` semantics:
        prefer ``normalized_path`` matches over absolute ``path`` matches for the
        same requested value, while still performing the database work in a
        single query.
        """
        if not paths:
            return {}

        requested_paths = list(dict.fromkeys(paths))
        cursor = self._db.aql.execute(
            """
            FOR doc IN @@collection
                FILTER doc.normalized_path IN @paths OR doc.path IN @paths
                SORT doc._key
                RETURN doc
            """,
            bind_vars={"@collection": self._name, "paths": requested_paths},
        )

        requested_path_set = set(requested_paths)
        result: dict[str, dict[str, Any]] = {}
        for file_doc in cast("list[dict[str, Any]]", list(cursor)):
            normalized_path = file_doc.get("normalized_path")
            if isinstance(normalized_path, str) and normalized_path in requested_path_set:
                result.setdefault(normalized_path, file_doc)

            absolute_path = file_doc.get("path")
            if isinstance(absolute_path, str) and absolute_path in requested_path_set:
                result.setdefault(absolute_path, file_doc)

        return result


class Tags(DocumentCollection):
    name: FieldAccessor  # str
    value: FieldAccessor  # str

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "tags")
        self.name = self._field("name")
        self.value = self._field("value")


class FileStates(StateGraphCollection):
    """State graph tracking the processing state of every file.

    This subclasses ``StateGraphCollection`` rather than a plain document collection. It pairs document collection ``file_states`` with edge collection ``file_has_state`` to model valid state transitions.
    """

    file_has_state: TraversalAccessor

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "file_states", "file_has_state")


class CalibrationState(DocumentCollection):
    """Stores the current calibration histogram state for each ``(head_name, label)`` combination.

    The collection name matches the class name as ``calibration_state``. Each document holds cumulative score-distribution data including histogram bins, ``p5``/``p95``, and underflow or overflow counts.
    """

    head_name: FieldAccessor  # str
    label: FieldAccessor  # str
    calibration_def_hash: FieldAccessor  # str
    histogram: FieldAccessor  # dict[str, Any]
    histogram_bins: FieldAccessor  # list[dict[str, Any]] | None
    p5: FieldAccessor  # float
    p95: FieldAccessor  # float
    n: FieldAccessor  # int
    underflow_count: FieldAccessor  # int
    overflow_count: FieldAccessor  # int
    updated_at: FieldAccessor  # int | None

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "calibration_state")
        self.head_name = self._field("head_name")
        self.label = self._field("label")
        self.calibration_def_hash = self._field("calibration_def_hash")
        self.histogram = self._field("histogram")
        self.histogram_bins = self._field("histogram_bins")
        self.p5 = self._field("p5")
        self.p95 = self._field("p95")
        self.n = self._field("n")
        self.underflow_count = self._field("underflow_count")
        self.overflow_count = self._field("overflow_count")
        self.updated_at = self._field("updated_at")


class CalibrationHistory(DocumentCollection):
    """Append-only snapshots of calibration percentiles for historical tracking.

    Each document captures ``p5``, ``p95``, and ``n`` at a ``snapshot_at`` timestamp. Optional delta fields record the change since the previous snapshot.
    """

    calibration_key: FieldAccessor  # str
    snapshot_at: FieldAccessor  # int
    p5: FieldAccessor  # float
    p95: FieldAccessor  # float
    n: FieldAccessor  # int
    underflow_count: FieldAccessor  # int
    overflow_count: FieldAccessor  # int
    p5_delta: FieldAccessor  # float | None
    p95_delta: FieldAccessor  # float | None
    n_delta: FieldAccessor  # int | None

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "calibration_history")
        self.calibration_key = self._field("calibration_key")
        self.snapshot_at = self._field("snapshot_at")
        self.p5 = self._field("p5")
        self.p95 = self._field("p95")
        self.n = self._field("n")
        self.underflow_count = self._field("underflow_count")
        self.overflow_count = self._field("overflow_count")
        self.p5_delta = self._field("p5_delta")
        self.p95_delta = self._field("p95_delta")
        self.n_delta = self._field("n_delta")


class MlModels(DocumentCollection):
    path: FieldAccessor  # str, unique
    backbone: FieldAccessor  # str
    head_type: FieldAccessor  # str
    model_stem: FieldAccessor  # str
    output_count: FieldAccessor  # int
    fully_configured: FieldAccessor  # bool
    is_known: FieldAccessor  # bool
    source: FieldAccessor  # str
    head_release_date: FieldAccessor  # str
    embedder_release_date: FieldAccessor  # str
    registered_at: FieldAccessor  # int
    updated_at: FieldAccessor  # int

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "ml_models")
        self.path = self._field("path", unique=True)
        self.backbone = self._field("backbone")
        self.head_type = self._field("head_type")
        self.model_stem = self._field("model_stem")
        self.output_count = self._field("output_count")
        self.fully_configured = self._field("fully_configured")
        self.is_known = self._field("is_known")
        self.source = self._field("source")
        self.head_release_date = self._field("head_release_date")
        self.embedder_release_date = self._field("embedder_release_date")
        self.registered_at = self._field("registered_at")
        self.updated_at = self._field("updated_at")


class MlModelOutputs(DocumentCollection):
    output_index: FieldAccessor  # int
    label: FieldAccessor  # str | None
    fully_labeled: FieldAccessor  # bool

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "ml_model_outputs")
        self.output_index = self._field("output_index")
        self.label = self._field("label")
        self.fully_labeled = self._field("fully_labeled")


class NavidromeTracks(DocumentCollection):
    has_nd_id: TraversalAccessor
    has_plays: TraversalAccessor

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "navidrome_tracks")


class NavidromePlaycounts(DocumentCollection):
    playcount: FieldAccessor  # int
    userid: FieldAccessor  # str

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "navidrome_playcounts")
        self.playcount = self._field("playcount")
        self.userid = self._field("userid")


class SegmentScoresStats(DocumentCollection):
    """Aggregate statistics from an ML segment-scoring run keyed by ``head_name`` and ``tagger_version``.

    Each document stores per-label distribution summaries in ``label_stats`` together with the segment count and pooling strategy used.
    """

    head_name: FieldAccessor  # str
    tagger_version: FieldAccessor  # str
    num_segments: FieldAccessor  # int
    pooling_strategy: FieldAccessor  # str
    label_stats: FieldAccessor  # list[dict[str, Any]]
    processed_at: FieldAccessor  # int

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "segment_scores_stats")
        self.head_name = self._field("head_name")
        self.tagger_version = self._field("tagger_version")
        self.num_segments = self._field("num_segments")
        self.pooling_strategy = self._field("pooling_strategy")
        self.label_stats = self._field("label_stats")
        self.processed_at = self._field("processed_at")


class VectorsTrackHot(VectorCollection):
    """Hot-tier track embedding vectors, partitioned by backbone and library.

    ``NAME_PATTERN`` is a template; one ArangoDB collection is created per
    ``(backbone_id, library_key)`` combination.  The hot tier holds embeddings for
    recently active or high-priority tracks and is the primary target for
    nearest-neighbour search queries.
    """

    VECTOR_TIER: ClassVar[Literal["hot"]] = "hot"
    NAME_PATTERN: ClassVar[str] = "vectors_track_hot__{backbone_id}__{library_key}"

    file_id: FieldAccessor  # str
    vector: FieldAccessor  # list[float]

    def __init__(self, db: SafeDatabase, name: str) -> None:
        super().__init__(db, name)


class VectorsTrackCold(VectorCollection):
    """Cold-tier track embedding vectors, partitioned by backbone and library.

    ``NAME_PATTERN`` is a template; one ArangoDB collection is created per
    ``(backbone_id, library_key)`` combination.  The cold tier holds embeddings for
    less-active tracks that are deprioritised in nearest-neighbour search queries.
    """

    VECTOR_TIER: ClassVar[Literal["cold"]] = "cold"
    NAME_PATTERN: ClassVar[str] = "vectors_track_cold__{backbone_id}__{library_key}"

    file_id: FieldAccessor  # str
    vector: FieldAccessor  # list[float]

    def __init__(self, db: SafeDatabase, name: str) -> None:
        super().__init__(db, name)


class SongHasTags(EdgeCollection):
    FROM_COLLECTION = LibraryFiles
    TO_COLLECTION = Tags

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "song_has_tags")


class FileHasState(EdgeCollection):
    FROM_COLLECTION = LibraryFiles
    TO_COLLECTION = FileStates

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "file_has_state")


class TagModelOutput(EdgeCollection):
    """Edge from a ``Tags`` document to an ``MlModelOutputs`` document.

    Carries a ``score`` payload representing the confidence assigned to the tag by
    the linked model output, along with creation and update timestamps.
    """

    FROM_COLLECTION = Tags
    TO_COLLECTION = MlModelOutputs

    score: FieldAccessor  # float
    created_at: FieldAccessor  # int
    updated_at: FieldAccessor  # int

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "tag_model_output")
        self.score = self._field("score")
        self.created_at = self._field("created_at")
        self.updated_at = self._field("updated_at")


class LibraryContainsFile(EdgeCollection):
    FROM_COLLECTION = Libraries
    TO_COLLECTION = LibraryFiles

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "library_contains_file")


class LibraryContainsFolder(EdgeCollection):
    FROM_COLLECTION = Libraries
    TO_COLLECTION = LibraryFolders

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "library_contains_folder")


class LibraryHasScan(EdgeCollection):
    FROM_COLLECTION = Libraries
    TO_COLLECTION = LibraryScans

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "library_has_scan")


class FileHasVectors(EdgeCollection):
    FROM_COLLECTION = LibraryFiles
    TO_COLLECTION = cast("type[DocumentCollection]", VectorCollection)

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "file_has_vectors")


class FileHasSegmentStats(EdgeCollection):
    FROM_COLLECTION = LibraryFiles
    TO_COLLECTION = SegmentScoresStats

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "file_has_segment_stats")


class ModelHasOutput(EdgeCollection):
    FROM_COLLECTION = MlModels
    TO_COLLECTION = MlModelOutputs

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "model_has_output")


class ModelHasCalibration(EdgeCollection):
    FROM_COLLECTION = MlModels
    TO_COLLECTION = CalibrationState

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "model_has_calibration")


class LibraryHasPipelineState(EdgeCollection):
    FROM_COLLECTION = Libraries
    TO_COLLECTION = LibraryPipelineStates

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "library_has_pipeline_state")


class HasNdId(EdgeCollection):
    FROM_COLLECTION = NavidromeTracks
    TO_COLLECTION = LibraryFiles

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "has_nd_id")


class HasPlays(EdgeCollection):
    FROM_COLLECTION = NavidromeTracks
    TO_COLLECTION = NavidromePlaycounts

    last_played: FieldAccessor  # int

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "has_plays")
        self.last_played = self._field("last_played")


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
