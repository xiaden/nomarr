"""Database layer for Nomarr (ArangoDB)."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any, TypeVar

import yaml

from nomarr.persistence.arango_client import SafeDatabase, create_arango_client
from nomarr.persistence.base_types import CASCADE, OUTBOUND, EdgeDef
from nomarr.persistence.cascade import _compile_cascade_aql, gather_concrete_names
from nomarr.persistence.collections import (
    CalibrationHistory,
    CalibrationState,
    FileHasOutputStream,
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
    MlModelOutputs,
    MlModels,
    MlOutputStreams,
    ModelHasCalibration,
    ModelHasOutput,
    NavidromePlaycounts,
    NavidromeTracks,
    OutputHasStream,
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
from nomarr.persistence.collections_base import DocumentCollection, EdgeCollection, VectorCollection
from nomarr.persistence.database import LibrariesAqlOperations, LibraryFilesAqlOperations

__all__ = ["Database"]

_VECTOR_TEMPLATE_COLLECTIONS: tuple[type[VectorCollection], ...] = (
    VectorsTrackHot,
    VectorsTrackCold,
)


_VECTOR_TEMPLATE_CLASSES: dict[str, type[VectorCollection]] = {
    vector_cls.NAME_PATTERN.split("__{", maxsplit=1)[0]: vector_cls for vector_cls in _VECTOR_TEMPLATE_COLLECTIONS
}

TCollection = TypeVar("TCollection", DocumentCollection, EdgeCollection, VectorCollection)

_COLLECTION_FIRST_ROOTS: tuple[str, ...] = (
    "get",
    "insert",
    "update",
    "upsert",
    "delete",
    "count",
    "aggregate",
    "truncate",
)

_STATIC_DOCUMENT_COLLECTIONS: tuple[tuple[str, Callable[[SafeDatabase], DocumentCollection]], ...] = (
    ("meta", Meta),
    ("libraries", Libraries),
    ("library_files", LibraryFiles),
    ("tags", Tags),
    ("library_folders", LibraryFolders),
    ("library_scans", LibraryScans),
    ("sessions", Sessions),
    ("calibration_state", CalibrationState),
    ("calibration_history", CalibrationHistory),
    ("health", Health),
    ("worker_restart_policy", WorkerRestartPolicy),
    ("navidrome_tracks", NavidromeTracks),
    ("navidrome_playcounts", NavidromePlaycounts),
    ("file_states", FileStates),
    ("library_pipeline_states", LibraryPipelineStates),
    ("worker_claims", WorkerClaims),
    ("vram_promises", VramPromises),
    ("locks", Locks),
    ("ml_models", MlModels),
    ("ml_model_outputs", MlModelOutputs),
    ("ml_output_streams", MlOutputStreams),
    ("migrations", Migrations),
)

_STATIC_EDGE_COLLECTIONS: tuple[tuple[str, Callable[[SafeDatabase], EdgeCollection]], ...] = (
    ("file_has_state", FileHasState),
    ("song_has_tags", SongHasTags),
    ("file_has_vectors", FileHasVectors),
    ("library_has_scan", LibraryHasScan),
    ("library_contains_file", LibraryContainsFile),
    ("library_contains_folder", LibraryContainsFolder),
    ("library_has_pipeline_state", LibraryHasPipelineState),
    ("model_has_output", ModelHasOutput),
    ("model_has_calibration", ModelHasCalibration),
    ("tag_model_output", TagModelOutput),
    ("file_has_output_stream", FileHasOutputStream),
    ("output_has_stream", OutputHasStream),
    ("has_nd_id", HasNdId),
    ("has_plays", HasPlays),
)


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

    meta: Meta
    libraries: Libraries
    library_files: LibraryFiles
    tags: Tags
    library_folders: LibraryFolders
    library_scans: LibraryScans
    sessions: Sessions
    calibration_state: CalibrationState
    calibration_history: CalibrationHistory
    health: Health
    worker_restart_policy: WorkerRestartPolicy
    navidrome_tracks: NavidromeTracks
    navidrome_playcounts: NavidromePlaycounts
    file_states: FileStates
    file_has_state: FileHasState
    song_has_tags: SongHasTags
    file_has_vectors: FileHasVectors
    library_has_scan: LibraryHasScan
    library_contains_file: LibraryContainsFile
    library_contains_folder: LibraryContainsFolder
    library_pipeline_states: LibraryPipelineStates
    library_has_pipeline_state: LibraryHasPipelineState
    worker_claims: WorkerClaims
    vram_promises: VramPromises
    locks: Locks
    ml_models: MlModels
    model_has_output: ModelHasOutput
    model_has_calibration: ModelHasCalibration
    ml_model_outputs: MlModelOutputs
    ml_output_streams: MlOutputStreams
    tag_model_output: TagModelOutput
    file_has_output_stream: FileHasOutputStream
    output_has_stream: OutputHasStream
    has_nd_id: HasNdId
    has_plays: HasPlays
    migrations: Migrations
    _libraries_aql: LibrariesAqlOperations
    _library_files_aql: LibraryFilesAqlOperations

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
        self._libraries_aql = LibrariesAqlOperations(self.db)
        self._library_files_aql = LibraryFilesAqlOperations(self.db)

        self._document_collections: list[DocumentCollection] = []
        self._edge_collections: list[EdgeCollection] = []
        self._vector_collections: list[VectorCollection] = []
        self._registered: dict[str, VectorCollection] = {}

        self._bind_static_collections()
        self._compile_all_cascades()

    def add_library(self, payload: dict[str, Any]) -> str:
        """Insert one library document."""
        return self._libraries_aql.insert_library(payload)

    def get_library(self, library_id_or_key: str) -> dict[str, Any] | None:
        """Get one library by full ``_id`` or bare ``_key``."""
        if library_id_or_key.startswith("libraries/"):
            return self._libraries_aql.get_library_by_id(library_id_or_key)
        return self._libraries_aql.get_library_by_key(library_id_or_key)

    def get_library_by_name(self, name: str) -> dict[str, Any] | None:
        """Get one library by unique name."""
        return self._libraries_aql.get_library_by_name(name)

    def list_libraries(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        """List library documents, optionally restricted to enabled rows."""
        return self._libraries_aql.list_libraries(enabled_only=enabled_only)

    def list_library_keys(self) -> list[str]:
        """Return all library document keys."""
        return self._libraries_aql.list_library_keys()

    def update_library(self, library_id: str, fields: dict[str, Any]) -> None:
        """Update one library by id (accepts ``libraries/<key>`` or bare key)."""
        normalized_id = library_id if library_id.startswith("libraries/") else f"libraries/{library_id}"
        self._libraries_aql.update_library_by_id(normalized_id, fields)

    def list_library_file_ids(self, *, limit: int | None = None) -> list[str]:
        """Return ordered library-file document ids."""
        return self._library_files_aql.list_all_file_ids(limit=limit)

    def count_files_by_tag(self, tag_key: str, target_value: float | str) -> int:
        """Count files matching tag criteria."""
        return self._library_files_aql.count_files_by_tag(tag_key, target_value)

    def get_tracks_for_matching(self, *, library_id: str | None = None) -> list[dict[str, Any]]:
        """Return fuzzy matching track projection rows."""
        return self._library_files_aql.get_tracks_for_matching(library_id=library_id)

    def register(self, collection_name: str, template_name: str) -> VectorCollection:
        """Compatibility-only seam for runtime vector collection registration.

        If the collection is already registered, returns the cached instance.

        Args:
            collection_name: Name of the ArangoDB collection to register.
            template_name: Template family name identifying the vector collection class.

        Returns:
            The registered runtime-bound collection instance.

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

        instance = self._bind_collection_instance(
            collection_name,
            vector_template_cls(self.db, collection_name),
        )
        self._registered[collection_name] = instance
        self._vector_collections.append(instance)
        self._reattach_vector_cascades()
        return instance

    def _bind_static_collections(self) -> None:
        """Instantiate and expose the fixed collection wrappers on the facade."""
        for attribute_name, document_factory in _STATIC_DOCUMENT_COLLECTIONS:
            document_instance = self._bind_collection_instance(attribute_name, document_factory(self.db))
            self._document_collections.append(document_instance)

        for attribute_name, edge_factory in _STATIC_EDGE_COLLECTIONS:
            edge_instance = self._bind_collection_instance(attribute_name, edge_factory(self.db))
            self._edge_collections.append(edge_instance)

    @staticmethod
    def _assert_collection_first_surface(
        attribute_name: str,
        instance: DocumentCollection | EdgeCollection | VectorCollection,
    ) -> None:
        """Guard that bound collections expose the normalized collection-first roots."""
        missing_roots = [root_name for root_name in _COLLECTION_FIRST_ROOTS if not hasattr(instance, root_name)]
        if missing_roots:
            missing_list = ", ".join(missing_roots)
            msg = f"Collection {attribute_name!r} is missing collection-first roots: {missing_list}"
            raise TypeError(msg)

    def _bind_collection_instance(
        self,
        attribute_name: str,
        instance: TCollection,
    ) -> TCollection:
        """Attach one collection wrapper to the facade after surface validation."""
        self._assert_collection_first_surface(attribute_name, instance)
        setattr(self, attribute_name, instance)
        return instance

    def _compile_all_cascades(self) -> None:
        from nomarr.persistence.constructor import verbs

        target_names, all_edge_names = gather_concrete_names(
            self._document_collections,
            self._edge_collections,
        )
        for coll_instance in self._document_collections:
            edges: list[EdgeDef] = getattr(coll_instance.__class__, "EDGES", [])
            cascade_defs = [
                edge_def for edge_def in edges if edge_def.on_delete == CASCADE and edge_def.direction == OUTBOUND
            ]
            if not cascade_defs:
                continue
            compiled = _compile_cascade_aql(
                coll_instance._name,
                coll_instance.__class__,
                target_names,
                all_edge_names,
            )
            db = self.db

            def make_fn(aql: str, db: SafeDatabase = db) -> Callable[[list[str]], int]:
                def cascade_delete(ids: list[str]) -> int:
                    if not ids:
                        raise ValueError("cascade delete requires a non-empty list of ids")
                    list(verbs._execute_aql(db, aql, bind_vars={"starts": ids}))
                    return len(ids)

                return cascade_delete

            coll_instance._attach_cascade(make_fn(compiled))

    def _reattach_vector_cascades(self) -> None:
        from nomarr.persistence.constructor import verbs

        registered_names = [collection._name for collection in self._vector_collections]
        target_names, all_edge_names = gather_concrete_names(
            self._document_collections,
            self._edge_collections,
            extra_vector_names=registered_names,
        )
        for coll_instance in self._document_collections:
            edges: list[EdgeDef] = getattr(coll_instance.__class__, "EDGES", [])
            if not any(
                edge_def.on_delete == CASCADE
                and edge_def.direction == OUTBOUND
                and issubclass(edge_def.target, VectorCollection)
                for edge_def in edges
            ):
                continue
            compiled = _compile_cascade_aql(
                coll_instance._name,
                coll_instance.__class__,
                target_names,
                all_edge_names,
            )
            db = self.db

            def make_fn(aql: str, db: SafeDatabase = db) -> Callable[[list[str]], int]:
                def cascade_delete(ids: list[str]) -> int:
                    if not ids:
                        raise ValueError("cascade delete requires a non-empty list of ids")
                    list(verbs._execute_aql(db, aql, bind_vars={"starts": ids}))
                    return len(ids)

                return cascade_delete

            coll_instance._attach_cascade(make_fn(compiled))

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
