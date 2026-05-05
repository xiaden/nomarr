"""Database layer for Nomarr (ArangoDB)."""

from __future__ import annotations

import logging
import os
from typing import Any

import yaml

from nomarr.persistence.arango_client import SafeDatabase, create_arango_client
from nomarr.persistence.base import DocumentCollection, EdgeCollection, VectorCollection
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
from nomarr.persistence.constructor.builder import Builder

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

    # Builder wires collection-level verbs and traversals onto these instances at runtime,
    # so the application-facing attribute types are intentionally broad for static checking.
    meta: Any
    libraries: Any
    library_files: Any
    tags: Any
    library_folders: Any
    library_scans: Any
    sessions: Any
    calibration_state: Any
    calibration_history: Any
    health: Any
    worker_restart_policy: Any
    navidrome_tracks: Any
    navidrome_playcounts: Any
    file_states: Any
    file_has_state: Any
    song_has_tags: Any
    file_has_vectors: Any
    library_has_scan: Any
    library_contains_file: Any
    library_contains_folder: Any
    library_pipeline_states: Any
    library_has_pipeline_state: Any
    worker_claims: Any
    vram_promises: Any
    locks: Any
    ml_capacity: Any
    ml_models: Any
    model_has_output: Any
    model_has_calibration: Any
    ml_model_outputs: Any
    tag_model_output: Any
    segment_scores_stats: Any
    file_has_segment_stats: Any
    has_nd_id: Any
    has_plays: Any
    migrations: Any

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

        builder = Builder(self.db)
        self._builder: Builder = builder

        self.meta = Meta()
        self._wire_collection("meta", self.meta, builder)
        self.libraries = Libraries()
        self._wire_collection("libraries", self.libraries, builder)
        self.library_files = LibraryFiles()
        self._wire_collection("library_files", self.library_files, builder)
        self.tags = Tags()
        self._wire_collection("tags", self.tags, builder)
        self.library_folders = LibraryFolders()
        self._wire_collection("library_folders", self.library_folders, builder)
        self.library_scans = LibraryScans()
        self._wire_collection("library_scans", self.library_scans, builder)
        self.sessions = Sessions()
        self._wire_collection("sessions", self.sessions, builder)
        self.calibration_state = CalibrationState()
        self._wire_collection("calibration_state", self.calibration_state, builder)
        self.calibration_history = CalibrationHistory()
        self._wire_collection("calibration_history", self.calibration_history, builder)
        self.health = Health()
        self._wire_collection("health", self.health, builder)
        self.worker_restart_policy = WorkerRestartPolicy()
        self._wire_collection("worker_restart_policy", self.worker_restart_policy, builder)
        self.navidrome_tracks = NavidromeTracks()
        self._wire_collection("navidrome_tracks", self.navidrome_tracks, builder)
        self.navidrome_playcounts = NavidromePlaycounts()
        self._wire_collection("navidrome_playcounts", self.navidrome_playcounts, builder)
        self.file_states = FileStates()
        self._wire_collection("file_states", self.file_states, builder)
        self.file_has_state = FileHasState()
        self._wire_collection("file_has_state", self.file_has_state, builder)
        self.song_has_tags = SongHasTags()
        self._wire_collection("song_has_tags", self.song_has_tags, builder)
        self.file_has_vectors = FileHasVectors()
        self._wire_collection("file_has_vectors", self.file_has_vectors, builder)
        self.library_has_scan = LibraryHasScan()
        self._wire_collection("library_has_scan", self.library_has_scan, builder)
        self.library_contains_file = LibraryContainsFile()
        self._wire_collection("library_contains_file", self.library_contains_file, builder)
        self.library_contains_folder = LibraryContainsFolder()
        self._wire_collection("library_contains_folder", self.library_contains_folder, builder)
        self.library_pipeline_states = LibraryPipelineStates()
        self._wire_collection("library_pipeline_states", self.library_pipeline_states, builder)
        self.library_has_pipeline_state = LibraryHasPipelineState()
        self._wire_collection("library_has_pipeline_state", self.library_has_pipeline_state, builder)
        self.worker_claims = WorkerClaims()
        self._wire_collection("worker_claims", self.worker_claims, builder)
        self.vram_promises = VramPromises()
        self._wire_collection("vram_promises", self.vram_promises, builder)
        self.locks = Locks()
        self._wire_collection("locks", self.locks, builder)
        self.ml_capacity = MlCapacity()
        self._wire_collection("ml_capacity", self.ml_capacity, builder)
        self.ml_models = MlModels()
        self._wire_collection("ml_models", self.ml_models, builder)
        self.model_has_output = ModelHasOutput()
        self._wire_collection("model_has_output", self.model_has_output, builder)
        self.model_has_calibration = ModelHasCalibration()
        self._wire_collection("model_has_calibration", self.model_has_calibration, builder)
        self.ml_model_outputs = MlModelOutputs()
        self._wire_collection("ml_model_outputs", self.ml_model_outputs, builder)
        self.tag_model_output = TagModelOutput()
        self._wire_collection("tag_model_output", self.tag_model_output, builder)
        self.segment_scores_stats = SegmentScoresStats()
        self._wire_collection("segment_scores_stats", self.segment_scores_stats, builder)
        self.file_has_segment_stats = FileHasSegmentStats()
        self._wire_collection("file_has_segment_stats", self.file_has_segment_stats, builder)
        self.has_nd_id = HasNdId()
        self._wire_collection("has_nd_id", self.has_nd_id, builder)
        self.has_plays = HasPlays()
        self._wire_collection("has_plays", self.has_plays, builder)
        self.migrations = Migrations()
        self._wire_collection("migrations", self.migrations, builder)

        self._template_namespaces: dict[str, VectorCollection] = {}

    def _wire_collection(
        self,
        attr_name: str,
        collection: DocumentCollection | EdgeCollection | VectorCollection,
        builder: Builder,
    ) -> None:
        """Builder-wire a typed collection instance with its physical collection name."""
        declared_name = getattr(type(collection), "_name", None)
        if not isinstance(declared_name, str) or not declared_name:
            collection_any: Any = collection
            collection_any._name = attr_name
        builder.construct(collection)

    def register(self, collection_name: str, template_name: str) -> Any:
        """Register a dynamic typed collection instance on the database.

        If the collection is already registered, returns the cached instance.

        Args:
            collection_name: Name of the ArangoDB collection to register.
            template_name: Template family name identifying the vector collection class.

        Returns:
            The registered runtime-wired collection instance.

        Raises:
            ValueError: If ``collection_name`` does not exist in ArangoDB.
            ValueError: If ``template_name`` is not a supported template collection.

        """
        if collection_name in self._template_namespaces:
            return self._template_namespaces[collection_name]
        if not self.db.has_collection(collection_name):
            raise ValueError(f"Collection {collection_name!r} does not exist in ArangoDB")

        vector_template_cls = _VECTOR_TEMPLATE_CLASSES.get(template_name)
        if vector_template_cls is None:
            raise ValueError(f"{template_name!r} is not a supported template collection")
        if not _matches_name_pattern(collection_name, vector_template_cls.NAME_PATTERN):
            msg = f"Collection {collection_name!r} does not match template pattern {vector_template_cls.NAME_PATTERN!r}"
            raise ValueError(msg)

        instance = vector_template_cls()
        collection_any: Any = instance
        collection_any._name = collection_name
        self._builder.construct(instance)
        setattr(self, collection_name, instance)
        self._template_namespaces[collection_name] = instance
        self._builder.reattach_vector_cascades(list(self._template_namespaces.keys()))
        return instance

    def get_version(self) -> str | None:
        """Read the current schema version from the meta store."""
        meta: Any = self.meta
        version_doc = meta.get(key="version")
        if not isinstance(version_doc, dict):
            return None
        value = version_doc.get("value")
        return value if isinstance(value, str) else None

    def set_version(self, version: str) -> None:
        """Persist the schema version to the meta store."""
        meta: Any = self.meta
        meta.upsert(key="version", fields={"value": version})

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
