"""Database layer for Nomarr (ArangoDB)."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, cast

import yaml

from nomarr.persistence.arango_client import SafeDatabase, create_arango_client
from nomarr.persistence.constructor import SchemaConstructor
from nomarr.persistence.constructor.namespaces import CollectionNamespace
from nomarr.persistence.schema import SCHEMA, CollectionType

if TYPE_CHECKING:
    from nomarr.persistence.stubs.calibration_history import CalibrationHistoryNamespace
    from nomarr.persistence.stubs.calibration_state import CalibrationStateNamespace
    from nomarr.persistence.stubs.file_has_state import FileHasStateNamespace
    from nomarr.persistence.stubs.file_states import FileStatesNamespace
    from nomarr.persistence.stubs.health import HealthNamespace
    from nomarr.persistence.stubs.libraries import LibrariesNamespace
    from nomarr.persistence.stubs.library_contains_file import LibraryContainsFileNamespace
    from nomarr.persistence.stubs.library_files import LibraryFilesNamespace
    from nomarr.persistence.stubs.library_folders import LibraryFoldersNamespace
    from nomarr.persistence.stubs.library_pipeline_states import LibraryPipelineStatesNamespace
    from nomarr.persistence.stubs.library_scans import LibraryScansNamespace
    from nomarr.persistence.stubs.locks import LocksNamespace
    from nomarr.persistence.stubs.meta import MetaNamespace
    from nomarr.persistence.stubs.migrations import MigrationsNamespace
    from nomarr.persistence.stubs.ml_capacity import MlCapacityNamespace
    from nomarr.persistence.stubs.ml_model_outputs import MlModelOutputsNamespace
    from nomarr.persistence.stubs.ml_models import MlModelsNamespace
    from nomarr.persistence.stubs.model_has_calibration import ModelHasCalibrationNamespace
    from nomarr.persistence.stubs.model_has_output import ModelHasOutputNamespace
    from nomarr.persistence.stubs.navidrome_playcounts import NavidromePlaycountsNamespace
    from nomarr.persistence.stubs.navidrome_tracks import NavidromeTracksNamespace
    from nomarr.persistence.stubs.segment_scores_stats import SegmentScoresStatsNamespace
    from nomarr.persistence.stubs.sessions import SessionsNamespace
    from nomarr.persistence.stubs.tag_model_output import TagModelOutputNamespace
    from nomarr.persistence.stubs.tags import TagsNamespace
    from nomarr.persistence.stubs.vram_promises import VramPromisesNamespace
    from nomarr.persistence.stubs.worker_claims import WorkerClaimsNamespace
    from nomarr.persistence.stubs.worker_restart_policy import WorkerRestartPolicyNamespace

__all__ = ["Database"]

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

        self.meta: MetaNamespace = cast("MetaNamespace", self._build_namespace("meta"))
        self.libraries: LibrariesNamespace = cast("LibrariesNamespace", self._build_namespace("libraries"))
        self.library_files: LibraryFilesNamespace = cast(
            "LibraryFilesNamespace",
            self._build_namespace("library_files"),
        )
        self.tags: TagsNamespace = cast("TagsNamespace", self._build_namespace("tags"))
        self.library_folders: LibraryFoldersNamespace = cast(
            "LibraryFoldersNamespace",
            self._build_namespace("library_folders"),
        )
        self.library_scans: LibraryScansNamespace = cast(
            "LibraryScansNamespace",
            self._build_namespace("library_scans"),
        )
        self.sessions: SessionsNamespace = cast("SessionsNamespace", self._build_namespace("sessions"))
        self.calibration_state: CalibrationStateNamespace = cast(
            "CalibrationStateNamespace",
            self._build_namespace("calibration_state"),
        )
        self.calibration_history: CalibrationHistoryNamespace = cast(
            "CalibrationHistoryNamespace",
            self._build_namespace("calibration_history"),
        )
        self.health: HealthNamespace = cast("HealthNamespace", self._build_namespace("health"))
        self.worker_restart_policy: WorkerRestartPolicyNamespace = cast(
            "WorkerRestartPolicyNamespace",
            self._build_namespace("worker_restart_policy"),
        )
        self.navidrome_tracks: NavidromeTracksNamespace = cast(
            "NavidromeTracksNamespace",
            self._build_namespace("navidrome_tracks"),
        )
        self.navidrome_playcounts: NavidromePlaycountsNamespace = cast(
            "NavidromePlaycountsNamespace",
            self._build_namespace("navidrome_playcounts"),
        )
        self.file_states: FileStatesNamespace = cast("FileStatesNamespace", self._build_namespace("file_states"))
        self.file_has_state: FileHasStateNamespace = cast(
            "FileHasStateNamespace",
            self._build_namespace("file_has_state"),
        )
        self.song_has_tags: Any = self._build_namespace("song_has_tags")
        self.file_has_vectors: Any = self._build_namespace("file_has_vectors")
        self.library_has_scan: Any = self._build_namespace("library_has_scan")
        self.library_contains_file: LibraryContainsFileNamespace = cast(
            "LibraryContainsFileNamespace",
            self._build_namespace("library_contains_file"),
        )
        self.library_contains_folder: Any = self._build_namespace("library_contains_folder")
        self.library_pipeline_states: LibraryPipelineStatesNamespace = cast(
            "LibraryPipelineStatesNamespace",
            self._build_namespace("library_pipeline_states"),
        )
        self.worker_claims: WorkerClaimsNamespace = cast(
            "WorkerClaimsNamespace",
            self._build_namespace("worker_claims"),
        )
        self.vram_promises: VramPromisesNamespace = cast(
            "VramPromisesNamespace",
            self._build_namespace("vram_promises"),
        )
        self.locks: LocksNamespace = cast("LocksNamespace", self._build_namespace("locks"))
        self.ml_capacity: MlCapacityNamespace = cast("MlCapacityNamespace", self._build_namespace("ml_capacity"))
        self.ml_models: MlModelsNamespace = cast("MlModelsNamespace", self._build_namespace("ml_models"))
        self.model_has_output: ModelHasOutputNamespace = cast(
            "ModelHasOutputNamespace",
            self._build_namespace("model_has_output"),
        )
        self.model_has_calibration: ModelHasCalibrationNamespace = cast(
            "ModelHasCalibrationNamespace",
            self._build_namespace("model_has_calibration"),
        )
        self.ml_model_outputs: MlModelOutputsNamespace = cast(
            "MlModelOutputsNamespace",
            self._build_namespace("ml_model_outputs"),
        )
        self.tag_model_output: TagModelOutputNamespace = cast(
            "TagModelOutputNamespace",
            self._build_namespace("tag_model_output"),
        )
        self.segment_scores_stats: SegmentScoresStatsNamespace = cast(
            "SegmentScoresStatsNamespace",
            self._build_namespace("segment_scores_stats"),
        )
        self.migrations: MigrationsNamespace = cast("MigrationsNamespace", self._build_namespace("migrations"))

        self._template_namespaces: dict[str, CollectionNamespace] = {}

    def register(self, collection_name: str, template_name: str) -> CollectionNamespace:
        """Register a dynamic collection namespace on the database.

        If the collection is already registered, returns the cached namespace.
        Validates that the collection exists in ArangoDB and that ``template_name``
        is a TEMPLATE-type entry in the schema.

        Args:
            collection_name: Name of the ArangoDB collection to register.
            template_name: Schema key identifying the template definition to use.

        Returns:
            The registered ``CollectionNamespace`` for the collection.

        Raises:
            ValueError: If ``collection_name`` does not exist in ArangoDB.
            ValueError: If ``template_name`` is not a TEMPLATE collection in SCHEMA.

        """
        if collection_name in self._template_namespaces:
            return self._template_namespaces[collection_name]
        if not self.db.has_collection(collection_name):
            raise ValueError(f"Collection {collection_name!r} does not exist in ArangoDB")
        template_spec = cast("dict[str, Any] | None", SCHEMA.get(template_name))
        if template_spec is None or template_spec.get("type") != CollectionType.TEMPLATE:
            raise ValueError(f"{template_name!r} is not a TEMPLATE collection in SCHEMA")
        ns = SchemaConstructor(self.db).build_template_namespace(collection_name, template_name)
        setattr(self, collection_name, ns)
        self._template_namespaces[collection_name] = ns
        return ns

    def get_version(self) -> str | None:
        """Read the current schema version from the meta store."""
        version_doc = cast("dict[str, Any] | None", self.meta.key.get("version"))
        if version_doc is None:
            return None
        return cast("str | None", version_doc.get("value"))

    def set_version(self, version: str) -> None:
        """Persist the schema version to the meta store."""
        self.meta.key.upsert([{"key": "version", "value": version}], match_field="key")

    def _build_namespace(self, name: str) -> CollectionNamespace:
        """Build a constructor-backed namespace for a schema collection."""
        return SchemaConstructor(self.db).build_collection_namespace(name, SCHEMA[name])

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
                    password: str | None = config.get("arango_password")
                    if password:
                        return password
                except Exception as e:
                    logging.getLogger(__name__).debug("[db] Failed to read config file %s: %s", path, e)

        return None


# ==================== ARCHITECTURAL NOTE ====================
# Database class is a service locator pattern:
#   - Every consumer gets all persistence capabilities
#   - Weakens ability to reason about which workflows touch which data
#   - Consistent with existing architecture, but has implications
#
# Future consideration:
#   - joined_queries module will accumulate graph-heavy queries
#   - Discipline required to prevent it from ballooning
#   - Consider splitting into domain-specific query modules if needed
# ============================================================
