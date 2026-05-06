"""Database layer for Nomarr (ArangoDB)."""

from __future__ import annotations

import logging
import os

import yaml

from nomarr.persistence.arango_client import SafeDatabase, create_arango_client
from nomarr.persistence.base import VectorCollection, bind_all_collections, reattach_vector_cascades
from nomarr.persistence.collections import (
    CalibrationHistory,
    CalibrationState,
    FileHasSegmentStats,
    FileHasState,
    FileHasVectors,
    FileStates,
    HasNdId,
    HasPlays,
    Health,
    Libraries,
    LibraryContainsFile,
    LibraryContainsFolder,
    LibraryFiles,
    LibraryFolders,
    LibraryHasPipelineState,
    LibraryHasScan,
    LibraryPipelineStates,
    LibraryScans,
    Locks,
    Meta,
    Migrations,
    MlCapacity,
    MlModelOutputs,
    MlModels,
    ModelHasCalibration,
    ModelHasOutput,
    NavidromePlaycounts,
    NavidromeTracks,
    SegmentScoresStats,
    Sessions,
    SongHasTags,
    TagModelOutput,
    Tags,
    VectorsTrackCold,
    VectorsTrackHot,
    VramPromises,
    WorkerClaims,
    WorkerRestartPolicy,
)

__all__ = ["Database"]

_VECTOR_TEMPLATE_COLLECTIONS: tuple[type[VectorCollection], ...] = (
    VectorsTrackHot,
    VectorsTrackCold,
)


_VECTOR_TEMPLATE_CLASSES: dict[str, type[VectorCollection]] = {
    vector_cls.NAME_PATTERN.split("__{", maxsplit=1)[0]: vector_cls for vector_cls in _VECTOR_TEMPLATE_COLLECTIONS
}


def _matches_name_pattern(resolved_name: str, name_pattern: str) -> bool:
    """Return whether a resolved collection name fits a class ``NAME_PATTERN``."""
    expected_parts = name_pattern.split("__")
    resolved_parts = resolved_name.split("__")

    if len(expected_parts) != len(resolved_parts):
        return False

    for expected, resolved in zip(expected_parts, resolved_parts, strict=True):
        if expected.startswith("{") and expected.endswith("}"):
            if not resolved:
                return False
            continue
        if expected != resolved:
            return False

    return True


# ==================== SCHEMA VERSIONING POLICY ====================
# Schema versioning uses forward-only migrations with semver strings (alpha policy).
#
# The current schema version is the MIGRATION_VERSION of the last applied
# migration (a semver string, e.g. "0.14.0"). Stored in meta.version.
# See nomarr/components/platform/migration_runner_comp.run_pending_migrations().
#
# Migration system:
#   - Migrations live in nomarr/migrations/ as V*.py modules
#   - Each migration declares MIGRATION_VERSION (semver string), DESCRIPTION, upgrade()
#   - Applied migrations tracked in applied_migrations collection
#   - Schema version stored in meta collection under key "version"
#   - Startup aborts if DB schema is ahead of code (__version__)
#
# Schema changes require:
#   1. Create migration file in nomarr/migrations/
#   2. Set MIGRATION_VERSION to next semver, implement upgrade()
#   3. See docs/dev/migrations.md for full migration architecture
#
# Alpha: Breaking changes allowed pre-1.0, but migrations provide self-repair.
# Post-1.0: Strict migration requirements with deprecation paths.
# ==================================================================


class Database:
    """Application database (ArangoDB).

    Handles all data persistence: queue, library, sessions, meta config.
    Single source of truth for database operations across all services.

    Connection pooling is handled automatically by python-arango.
    Thread-safe within a single process. Each process creates its own pool.

    Credential Flow:
    - First run: App provisions DB with root password, generates app password,
      stores in config file. Database is NOT usable until first-run completes.
    - After first run: Password read from config file (/app/config/nomarr.yaml).
    - Username and db_name are hardcoded as 'nomarr' (not configurable).
    """

    meta: type[Meta]
    libraries: type[Libraries]
    library_files: type[LibraryFiles]
    tags: type[Tags]
    library_folders: type[LibraryFolders]
    library_scans: type[LibraryScans]
    sessions: type[Sessions]
    calibration_state: type[CalibrationState]
    calibration_history: type[CalibrationHistory]
    health: type[Health]
    worker_restart_policy: type[WorkerRestartPolicy]
    navidrome_tracks: type[NavidromeTracks]
    navidrome_playcounts: type[NavidromePlaycounts]
    file_states: type[FileStates]
    file_has_state: type[FileHasState]
    song_has_tags: type[SongHasTags]
    file_has_vectors: type[FileHasVectors]
    library_has_scan: type[LibraryHasScan]
    library_contains_file: type[LibraryContainsFile]
    library_contains_folder: type[LibraryContainsFolder]
    library_pipeline_states: type[LibraryPipelineStates]
    library_has_pipeline_state: type[LibraryHasPipelineState]
    worker_claims: type[WorkerClaims]
    vram_promises: type[VramPromises]
    locks: type[Locks]
    ml_capacity: type[MlCapacity]
    ml_models: type[MlModels]
    model_has_output: type[ModelHasOutput]
    model_has_calibration: type[ModelHasCalibration]
    ml_model_outputs: type[MlModelOutputs]
    tag_model_output: type[TagModelOutput]
    segment_scores_stats: type[SegmentScoresStats]
    file_has_segment_stats: type[FileHasSegmentStats]
    has_nd_id: type[HasNdId]
    has_plays: type[HasPlays]
    migrations: type[Migrations]

    USERNAME = "nomarr"
    DB_NAME = "nomarr"

    def __init__(
        self,
        hosts: str | None = None,
        password: str | None = None,
    ) -> None:
        """Initialize database connection.

        Args:
            hosts: ArangoDB server URL(s). Read from ARANGO_HOST env var if not provided.
            password: Database password. Read from config file if not provided.

        Raises:
            RuntimeError: If password not available or ARANGO_HOST not set

        """
        self.hosts = hosts or os.getenv("ARANGO_HOST")
        if not self.hosts:
            msg = (
                "ARANGO_HOST environment variable required. "
                "Set to 'http://nomarr-arangodb:8529' for Docker Compose or 'http://localhost:8529' for dev."
            )
            raise RuntimeError(msg)

        self.username = self.USERNAME
        self.db_name = self.DB_NAME
        self.password = password or self._load_password_from_config()

        if not self.password:
            msg = (
                "Database password not available. "
                "On first run, ensure ARANGO_ROOT_PASSWORD is set for provisioning. "
                "After first run, password is read from /app/config/nomarr.yaml."
            )
            raise RuntimeError(msg)

        self.db: SafeDatabase = create_arango_client(
            hosts=self.hosts,
            username=self.username,
            password=self.password,
            db_name=self.db_name,
        )
        bind_all_collections(self.db)

        self.meta = Meta
        self.libraries = Libraries
        self.library_files = LibraryFiles
        self.tags = Tags
        self.library_folders = LibraryFolders
        self.library_scans = LibraryScans
        self.sessions = Sessions
        self.calibration_state = CalibrationState
        self.calibration_history = CalibrationHistory
        self.health = Health
        self.worker_restart_policy = WorkerRestartPolicy
        self.navidrome_tracks = NavidromeTracks
        self.navidrome_playcounts = NavidromePlaycounts
        self.file_states = FileStates
        self.file_has_state = FileHasState
        self.song_has_tags = SongHasTags
        self.file_has_vectors = FileHasVectors
        self.library_has_scan = LibraryHasScan
        self.library_contains_file = LibraryContainsFile
        self.library_contains_folder = LibraryContainsFolder
        self.library_pipeline_states = LibraryPipelineStates
        self.library_has_pipeline_state = LibraryHasPipelineState
        self.worker_claims = WorkerClaims
        self.vram_promises = VramPromises
        self.locks = Locks
        self.ml_capacity = MlCapacity
        self.ml_models = MlModels
        self.model_has_output = ModelHasOutput
        self.model_has_calibration = ModelHasCalibration
        self.ml_model_outputs = MlModelOutputs
        self.tag_model_output = TagModelOutput
        self.segment_scores_stats = SegmentScoresStats
        self.file_has_segment_stats = FileHasSegmentStats
        self.has_nd_id = HasNdId
        self.has_plays = HasPlays
        self.migrations = Migrations

        self._registered: dict[str, type[VectorCollection]] = {}

    def register(self, collection_name: str, template_name: str) -> type[VectorCollection]:
        """Register a dynamic typed vector collection class on the database.

        If the collection is already registered, returns the cached class.

        Args:
            collection_name: Name of the ArangoDB collection to register.
            template_name: Template family name identifying the vector collection class.

        Returns:
            The registered runtime-bound collection class.

        Raises:
            ValueError: If ``collection_name`` does not exist in ArangoDB.
            ValueError: If ``template_name`` is not a supported template collection.

        """
        if collection_name in self._registered:
            return self._registered[collection_name]
        if not self.db.has_collection(collection_name):
            raise ValueError(f"Collection {collection_name!r} does not exist in ArangoDB")

        vector_template_cls = _VECTOR_TEMPLATE_CLASSES.get(template_name)
        if vector_template_cls is None:
            raise ValueError(f"{template_name!r} is not a supported template collection")
        if not _matches_name_pattern(collection_name, vector_template_cls.NAME_PATTERN):
            msg = f"Collection {collection_name!r} does not match template pattern {vector_template_cls.NAME_PATTERN!r}"
            raise ValueError(msg)

        dyn_cls = type(
            f"{vector_template_cls.__name__}__{collection_name}",
            (vector_template_cls,),
            {"_name": collection_name},
        )
        self._registered[collection_name] = dyn_cls
        setattr(self, collection_name, dyn_cls)
        reattach_vector_cascades(list(self._registered.keys()))
        return dyn_cls

    def get_version(self) -> str | None:
        """Read the current schema version from the meta store."""
        version_doc = self.meta.get(key="version")
        if not isinstance(version_doc, dict):
            return None
        value = version_doc.get("value")
        return value if isinstance(value, str) else None

    def set_version(self, version: str) -> None:
        """Persist the schema version to the meta store."""
        self.meta.upsert(key="version", fields={"value": version})

    def close(self) -> None:
        """Close database connection (cleanup)."""

    @staticmethod
    def _load_password_from_config() -> str | None:
        """Load arango_password from config file.

        Checks standard config locations in order:
        1. /app/config/nomarr.yaml (Docker container)
        2. ./config/nomarr.yaml (local dev)

        Returns:
            Password string if found, None otherwise

        """
        config_paths = [
            "/app/config/nomarr.yaml",
            os.path.join(os.getcwd(), "config", "nomarr.yaml"),
        ]

        for path in config_paths:
            if os.path.exists(path):
                try:
                    with open(path, encoding="utf-8") as f:
                        config = yaml.safe_load(f) or {}
                    password = config.get("arango_password")
                    if isinstance(password, str) and password:
                        return password
                except Exception as e:
                    logging.getLogger(__name__).debug("[db] Failed to read config file %s: %s", path, e)

        return None
