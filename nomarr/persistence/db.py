"""Database layer for Nomarr (ArangoDB)."""

from arango.database import StandardDatabase

from nomarr.persistence.arango_client import create_arango_client

# Import operation classes (AQL versions)
from nomarr.persistence.database.calibration_history_aql import CalibrationHistoryOperations
from nomarr.persistence.database.calibration_state_aql import CalibrationStateOperations
from nomarr.persistence.database.entities_aql import EntityOperations
from nomarr.persistence.database.file_tags_aql import FileTagOperations
from nomarr.persistence.database.health_aql import HealthOperations
from nomarr.persistence.database.libraries_aql import LibrariesOperations
from nomarr.persistence.database.library_files_aql import LibraryFilesOperations
from nomarr.persistence.database.library_tags_aql import LibraryTagOperations
from nomarr.persistence.database.meta_aql import MetaOperations
from nomarr.persistence.database.sessions_aql import SessionOperations
from nomarr.persistence.database.song_tag_edges_aql import SongTagEdgeOperations
from nomarr.persistence.database.tag_queue_aql import QueueOperations

__all__ = ["SCHEMA_VERSION", "Database"]

SCHEMA_VERSION = 2  # Incremented for ArangoDB migration

# ==================== SCHEMA VERSIONING POLICY ====================
# Schema versioning is ADDITIVE ONLY.
#
# SCHEMA_VERSION is stored in meta but NOT enforced at runtime.
# Schema bootstrap (ensure_schema) is idempotent and creates missing
# collections/indexes, but does NOT handle:
#   - Index changes (must drop manually)
#   - Collection renames (manual intervention)
#   - Data migrations (not supported)
#
# Future schema changes require:
#   1. Increment SCHEMA_VERSION
#   2. Add new collections/indexes to bootstrap
#   3. Document manual intervention steps if destructive
#
# Pre-alpha: Breaking changes are acceptable.
# Post-1.0: Must build migration framework or maintain additive-only.
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
    ):
        """Initialize database connection.

        Args:
            hosts: ArangoDB server URL(s). Read from ARANGO_HOST env var if not provided.
            password: Database password. Read from config file if not provided.

        Raises:
            RuntimeError: If password not available or ARANGO_HOST not set
        """
        import os

        # Host is REQUIRED - no silent default to avoid dev env footguns
        self.hosts = hosts or os.getenv("ARANGO_HOST")
        if not self.hosts:
            raise RuntimeError(
                "ARANGO_HOST environment variable required. "
                "Set to 'http://nomarr-arangodb:8529' for docker-compose or 'http://localhost:8529' for dev."
            )

        # Username and db_name are hardcoded
        self.username = self.USERNAME
        self.db_name = self.DB_NAME

        # Password: constructor arg > config file
        self.password = password or self._load_password_from_config()

        if not self.password:
            raise RuntimeError(
                "Database password not available. "
                "On first run, ensure ARANGO_ROOT_PASSWORD is set for provisioning. "
                "After first run, password is read from /app/config/nomarr.yaml."
            )

        # Create ArangoDB connection
        self.db: StandardDatabase = create_arango_client(
            hosts=self.hosts,
            username=self.username,
            password=self.password,
            db_name=self.db_name,
        )

        # Initialize operation classes - one per collection
        self.meta = MetaOperations(self.db)
        self.libraries = LibrariesOperations(self.db)
        self.tag_queue = QueueOperations(self.db)
        self.library_files = LibraryFilesOperations(self.db)
        self.library_tags = LibraryTagOperations(self.db)
        self.file_tags = FileTagOperations(self.db)
        self.sessions = SessionOperations(self.db)
        self.calibration_state = CalibrationStateOperations(self.db)
        self.calibration_history = CalibrationHistoryOperations(self.db)
        self.health = HealthOperations(self.db)
        # Metadata entity operations (hybrid graph model)
        self.entities = EntityOperations(self.db)
        self.song_tag_edges = SongTagEdgeOperations(self.db)

        # Lazy import to avoid circular dependency
        # from nomarr.persistence.database.joined_queries_aql import JoinedQueryOperations
        # self.joined_queries = JoinedQueryOperations(self.db)

        # Store schema version for reference
        current_version = self.meta.get("schema_version")
        if not current_version:
            self.meta.set("schema_version", str(SCHEMA_VERSION))

    def close(self):
        """Close database connection (cleanup)."""
        # ArangoDB client handles connection cleanup automatically
        pass

    @staticmethod
    def _load_password_from_config() -> str | None:
        """Load arango_password from config file.

        Checks standard config locations in order:
        1. /app/config/nomarr.yaml (Docker container)
        2. ./config/nomarr.yaml (local dev)

        Returns:
            Password string if found, None otherwise
        """
        import os

        import yaml

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
