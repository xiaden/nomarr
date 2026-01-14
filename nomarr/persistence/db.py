"""Database layer for Nomarr (ArangoDB)."""

from arango.database import StandardDatabase

from nomarr.persistence.arango_client import create_arango_client

# Import operation classes (AQL versions)
from nomarr.persistence.database.calibration_queue_aql import CalibrationQueueOperations
from nomarr.persistence.database.calibration_runs_aql import CalibrationRunsOperations
from nomarr.persistence.database.file_tags_aql import FileTagOperations
from nomarr.persistence.database.health_aql import HealthOperations
from nomarr.persistence.database.libraries_aql import LibrariesOperations
from nomarr.persistence.database.library_files_aql import LibraryFilesOperations
from nomarr.persistence.database.library_tags_aql import LibraryTagOperations
from nomarr.persistence.database.meta_aql import MetaOperations
from nomarr.persistence.database.sessions_aql import SessionOperations
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
    """

    def __init__(
        self,
        hosts: str | None = None,
        username: str | None = None,
        password: str | None = None,
        db_name: str | None = None,
    ):
        """Initialize database connection.

        Args:
            hosts: ArangoDB server URL(s). Read from ARANGO_HOST env var if not provided.
            username: Database username. Defaults to ARANGO_USERNAME env var or 'nomarr'.
            password: Database password. Read from ARANGO_PASSWORD env var (required).
            db_name: Database name. Defaults to ARANGO_DBNAME env var or 'nomarr'.

        Raises:
            RuntimeError: If password not provided or ARANGO_HOST not set
        """
        import os

        # Host is REQUIRED - no silent default to avoid dev env footguns
        self.hosts = hosts or os.getenv("ARANGO_HOST")
        if not self.hosts:
            raise RuntimeError(
                "ARANGO_HOST environment variable required. "
                "Set to 'http://nomarr-arangodb:8529' for docker-compose or 'http://localhost:8529' for dev."
            )

        self.username = username or os.getenv("ARANGO_USERNAME", "nomarr")
        self.password = password or os.getenv("ARANGO_PASSWORD")
        self.db_name = db_name or os.getenv("ARANGO_DBNAME", "nomarr")

        if not self.password:
            raise RuntimeError(
                "Database password required. Set via ARANGO_PASSWORD environment variable or constructor parameter."
            )

        # Create ArangoDB connection
        self.db: StandardDatabase = create_arango_client(
            hosts=self.hosts,
            username=self.username or "nomarr",  # Fallback for mypy (already checked to be non-None)
            password=self.password,
            db_name=self.db_name or "nomarr",  # Fallback for mypy (already checked to be non-None)
        )

        # Initialize operation classes - one per collection
        self.meta = MetaOperations(self.db)
        self.libraries = LibrariesOperations(self.db)
        self.tag_queue = QueueOperations(self.db)
        self.library_files = LibraryFilesOperations(self.db)
        self.library_tags = LibraryTagOperations(self.db)
        self.file_tags = FileTagOperations(self.db)
        self.sessions = SessionOperations(self.db)
        self.calibration_queue = CalibrationQueueOperations(self.db)
        self.calibration_runs = CalibrationRunsOperations(self.db)
        self.health = HealthOperations(self.db)

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
