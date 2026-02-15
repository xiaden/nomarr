"""Database layer for Nomarr (ArangoDB)."""

import os

import yaml

from nomarr.persistence.arango_client import SafeDatabase, create_arango_client

# Import operation classes (AQL versions)
from nomarr.persistence.database.calibration_history_aql import CalibrationHistoryOperations
from nomarr.persistence.database.calibration_state_aql import CalibrationStateOperations
from nomarr.persistence.database.health_aql import HealthOperations
from nomarr.persistence.database.libraries_aql import LibrariesOperations
from nomarr.persistence.database.library_files_aql import LibraryFilesOperations
from nomarr.persistence.database.library_folders_aql import LibraryFoldersOperations
from nomarr.persistence.database.meta_aql import MetaOperations
from nomarr.persistence.database.migrations_aql import MigrationOperations
from nomarr.persistence.database.ml_capacity_aql import MLCapacityOperations
from nomarr.persistence.database.segment_scores_stats_aql import SegmentScoresStatsOperations
from nomarr.persistence.database.sessions_aql import SessionOperations
from nomarr.persistence.database.tags_aql import TagOperations
from nomarr.persistence.database.vectors_track_aql import VectorsTrackOperations
from nomarr.persistence.database.worker_claims_aql import WorkerClaimsOperations
from nomarr.persistence.database.worker_restart_policy_aql import WorkerRestartPolicyOperations

__all__ = ["SCHEMA_VERSION", "Database"]

SCHEMA_VERSION = 6  # applied_migrations collection for database migration tracking

# ==================== SCHEMA VERSIONING POLICY ====================
# Schema versioning uses forward-only migrations (alpha policy).
#
# SCHEMA_VERSION tracks the target schema version in code.
# Migrations auto-run on startup via prepare_database_workflow().
#
# Migration system (starting SCHEMA_VERSION=6):
#   - Migrations live in nomarr/migrations/ as V{NNN}_*.py modules
#   - Applied migrations tracked in applied_migrations collection
#   - Schema version stored in meta collection
#   - Startup aborts if DB schema is ahead of code
#
# Schema changes require:
#   1. Increment SCHEMA_VERSION
#   2. Create migration file in nomarr/migrations/
#   3. Implement upgrade() function with data transformations
#   4. See docs/dev/migrations.md for full migration architecture
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

    # Hardcoded credentials (not user-configurable)
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
        # Host is REQUIRED - no silent default to avoid dev env footguns
        self.hosts = hosts or os.getenv("ARANGO_HOST")
        if not self.hosts:
            msg = (
                "ARANGO_HOST environment variable required. "
                "Set to 'http://nomarr-arangodb:8529' for Docker Compose or 'http://localhost:8529' for dev."
            )
            raise RuntimeError(
                msg,
            )

        # Username and db_name are hardcoded
        self.username = self.USERNAME
        self.db_name = self.DB_NAME

        # Password: constructor arg > config file
        self.password = password or self._load_password_from_config()

        if not self.password:
            msg = (
                "Database password not available. "
                "On first run, ensure ARANGO_ROOT_PASSWORD is set for provisioning. "
                "After first run, password is read from /app/config/nomarr.yaml."
            )
            raise RuntimeError(
                msg,
            )

        # Create ArangoDB connection (SafeDatabase wraps StandardDatabase with JSON serialization)
        self.db: SafeDatabase = create_arango_client(
            hosts=self.hosts,
            username=self.username,
            password=self.password,
            db_name=self.db_name,
        )

        # Initialize operation classes - one per collection
        self.meta = MetaOperations(self.db)
        self.libraries = LibrariesOperations(self.db)
        self.library_files = LibraryFilesOperations(self.db)
        self.library_folders = LibraryFoldersOperations(self.db)
        self.sessions = SessionOperations(self.db)
        self.calibration_state = CalibrationStateOperations(self.db)
        self.calibration_history = CalibrationHistoryOperations(self.db)
        self.health = HealthOperations(self.db)
        self.worker_restart_policy = WorkerRestartPolicyOperations(self.db)
        self.worker_claims = WorkerClaimsOperations(self.db)
        self.ml_capacity = MLCapacityOperations(self.db)
        self.segment_scores_stats = SegmentScoresStatsOperations(self.db)
        # Unified tag operations (TAG_UNIFICATION_REFACTOR)
        self.tags = TagOperations(self.db)
        # Migration tracking operations (database migration system)
        self.migrations = MigrationOperations(self.db)

        # Vectors track — one Operations instance per backbone, created lazily
        self.vectors_track: dict[str, VectorsTrackOperations] = {}

        # Lazy import to avoid circular dependency
        # from nomarr.persistence.database.joined_queries_aql import JoinedQueryOperations
        # self.joined_queries = JoinedQueryOperations(self.db)

    def register_vectors_track_backbone(self, backbone_id: str) -> VectorsTrackOperations:
        """Get or create a VectorsTrackOperations instance for a backbone.

        Lazily creates and caches the Operations instance on first access.

        Args:
            backbone_id: Backbone identifier (e.g., "effnet", "yamnet").

        Returns:
            The cached VectorsTrackOperations for this backbone.

        """
        if backbone_id not in self.vectors_track:
            self.vectors_track[backbone_id] = VectorsTrackOperations(self.db, backbone_id)
        return self.vectors_track[backbone_id]

    def ensure_schema_version(self) -> int:
        """Read current schema version, initializing if needed.

        For fresh databases (no version recorded), records the current
        SCHEMA_VERSION. For existing databases, returns the stored version
        without modification.

        Should be called AFTER ensure_schema() has created collections.

        Returns:
            Current schema version as integer.

        """
        current_version = self.meta.get("schema_version")
        if not current_version:
            # Fresh database — record current version
            self.meta.set("schema_version", str(SCHEMA_VERSION))
            return SCHEMA_VERSION
        return int(current_version)

    def update_schema_version(self, version: int) -> None:
        """Update the stored schema version.

        Called after migrations complete to record the new version.

        Args:
            version: New schema version to record.

        """
        self.meta.set("schema_version", str(version))

    def close(self) -> None:
        """Close database connection (cleanup)."""
        # ArangoDB client handles connection cleanup automatically

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
                except Exception:
                    pass

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
