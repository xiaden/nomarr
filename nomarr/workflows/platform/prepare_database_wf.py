"""Database preparation workflow.

Orchestrates the full database startup sequence: schema creation,
version management, and migration execution. Called once from
Application.__init__ before service initialization.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.platform.arango_bootstrap_comp import ensure_schema
from nomarr.components.platform.migration_runner_comp import (
    MigrationChainError,
    MigrationError,
    SchemaVersionMismatchError,
    apply_migration,
    check_schema_version_mismatch,
    discover_migrations,
    get_pending_migrations,
    validate_version_chain,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def prepare_database_workflow(
    db: Database,
    *,
    models_dir: str | None = None,
) -> None:
    """Prepare the database for application startup.

    Runs the full startup sequence:
    1. Ensure schema (collections, indexes, graphs)
    2. Read/initialize schema version
    3. Validate version compatibility
    4. Discover and apply pending migrations
    5. Update stored schema version

    Args:
        db: Database instance (provides both raw db handle and operations).
        models_dir: Path to ML models directory for vector collections.

    Raises:
        SystemExit: If any step fails. Startup is fail-fast.

    """
    from nomarr.persistence.db import SCHEMA_VERSION

    # Step 1: Ensure schema (collections, indexes, graphs)
    ensure_schema(db.db, models_dir=models_dir)

    # Step 2: Read current schema version (initializes on fresh DB)
    current_db_version = db.ensure_schema_version()
    logger.info(
        "Database schema version: %d, code schema version: %d",
        current_db_version,
        SCHEMA_VERSION,
    )

    # Step 3: Validate version compatibility
    try:
        check_schema_version_mismatch(current_db_version, SCHEMA_VERSION)
    except SchemaVersionMismatchError as exc:
        logger.critical(
            "Database schema version (%d) is newer than code (%d). "
            "Upgrade the application or restore the database from backup.",
            current_db_version,
            SCHEMA_VERSION,
        )
        raise SystemExit(1) from exc

    # Step 4: Discover, validate, and apply pending migrations
    try:
        all_migrations = discover_migrations()
        if not all_migrations:
            logger.info("No migrations found")
            final_version = current_db_version
        else:
            applied_names = db.migrations.get_applied_migration_names()
            pending = get_pending_migrations(all_migrations, applied_names)
            if not pending:
                logger.info("All migrations already applied")
                final_version = current_db_version
            else:
                validate_version_chain(pending, current_db_version)

                logger.info(
                    "Running %d pending migration(s) (v%d -> v%d)",
                    len(pending),
                    current_db_version,
                    pending[-1][1].SCHEMA_VERSION_AFTER,
                )

                final_version = current_db_version
                for name, module in pending:
                    apply_migration(name, module, db.db, db.migrations)
                    final_version = module.SCHEMA_VERSION_AFTER

                logger.info(
                    "All migrations completed. Schema version: %d",
                    final_version,
                )
    except (MigrationError, MigrationChainError) as exc:
        logger.critical(
            "Database migration failed: %s. Application cannot start.",
            exc,
        )
        raise SystemExit(1) from exc

    # Step 5: Update stored schema version
    if final_version != current_db_version:
        db.update_schema_version(final_version)
        logger.info(
            "Schema version updated: %d -> %d",
            current_db_version,
            final_version,
        )
