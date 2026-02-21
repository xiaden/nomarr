"""Migration tracking operations for ArangoDB.

Tracks which migrations have been applied to support the database migration system.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor

logger = logging.getLogger(__name__)


class MigrationOperations:
    """Operations for the applied_migrations collection."""

    COLLECTION = "applied_migrations"

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
        self.collection = db.collection(self.COLLECTION)

    def get_applied_migrations(self) -> list[dict[str, Any]]:
        """Get all applied migrations ordered by name.

        Returns:
            List of migration records, each containing:
            - _key: migration name (e.g., "V006_example")
            - name: same as _key
            - applied_at: ISO 8601 timestamp
            - schema_version_before: int
            - schema_version_after: int
            - duration_ms: int

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR m IN applied_migrations
                SORT m._key ASC
                RETURN m
            """,
            ),
        )
        return list(cursor)

    def get_applied_migration_names(self) -> set[str]:
        """Get the set of successfully applied migration names (keys).

        Only returns migrations that completed successfully (status='applied').
        In-progress records (from a crashed run) are intentionally excluded
        so the runner retries them on the next startup.  Idempotent migrations
        (which filter already-processed data) are therefore safe to re-run.

        Returns:
            Set of migration name strings.

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR m IN applied_migrations
                FILTER m.status == 'applied'
                RETURN m._key
            """,
            ),
        )
        return set(cursor)

    def get_in_progress_migration_names(self) -> list[str]:
        """Get names of migrations currently in-progress (started but not completed).

        A migration is in-progress if it was recorded with status='in_progress'
        but never updated to status='applied'. This indicates a crash between
        upgrade() running and the completion record being written.

        Returns:
            List of migration name strings with status='in_progress'.

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR m IN applied_migrations
                FILTER m.status == 'in_progress'
                RETURN m._key
            """,
            ),
        )
        return list(cursor)

    def record_migration_started(
        self,
        name: str,
        *,
        schema_version_before: int,
        schema_version_after: int,
        started_at: str,
    ) -> None:
        """Record that a migration has started (pre-upgrade record).

        Inserted (or replaced if a previous in_progress record exists from a
        crashed run) before upgrade() runs to ensure a record exists even if
        the process crashes mid-migration. Use mark_migration_applied() after
        upgrade() completes successfully.

        Args:
            name: Migration identifier (filename without .py).
            schema_version_before: Schema version before migration.
            schema_version_after: Schema version after migration.
            started_at: ISO 8601 timestamp when execution began.

        """
        self.collection.insert(
            {
                "_key": name,
                "name": name,
                "status": "in_progress",
                "started_at": started_at,
                "schema_version_before": schema_version_before,
                "schema_version_after": schema_version_after,
            },
            overwrite=True,
        )
        logger.debug("Recorded migration %s as in_progress", name)

    def mark_migration_applied(
        self,
        name: str,
        *,
        duration_ms: int,
        applied_at: str,
    ) -> None:
        """Mark an in-progress migration as successfully applied.

        Updates the record created by record_migration_started() with
        completion timing and sets status='applied'.

        Args:
            name: Migration identifier (filename without .py).
            duration_ms: Execution duration in milliseconds.
            applied_at: ISO 8601 timestamp of completion.

        """
        self.collection.update(
            {
                "_key": name,
                "status": "applied",
                "applied_at": applied_at,
                "duration_ms": duration_ms,
            },
        )
        logger.debug("Marked migration %s as applied (%dms)", name, duration_ms)

    def record_migration(
        self,
        name: str,
        *,
        schema_version_before: int,
        schema_version_after: int,
        duration_ms: int,
        applied_at: str,
    ) -> None:
        """Record a successfully applied migration.

        Uses _key = name for automatic duplicate prevention.

        Args:
            name: Migration identifier (filename without .py).
            schema_version_before: Schema version before migration.
            schema_version_after: Schema version after migration.
            duration_ms: Execution duration in milliseconds.
            applied_at: ISO 8601 timestamp of application.

        """
        self.collection.insert(
            {
                "_key": name,
                "name": name,
                "applied_at": applied_at,
                "schema_version_before": schema_version_before,
                "schema_version_after": schema_version_after,
                "duration_ms": duration_ms,
            },
        )
        logger.info(
            "Recorded migration %s (v%d -> v%d, %dms)",
            name,
            schema_version_before,
            schema_version_after,
            duration_ms,
        )

    def is_migration_applied(self, name: str) -> bool:
        """Check if a specific migration has been applied.

        Args:
            name: Migration identifier.

        Returns:
            True if migration record exists.

        """
        return bool(self.collection.has(name))
