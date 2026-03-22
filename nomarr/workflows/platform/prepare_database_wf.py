"""Database preparation workflow.

Orchestrates the full database startup sequence: schema creation,
migration execution, and ML model registration.
Called once from Application.__init__ before service initialization.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.platform.arango_bootstrap_comp import ensure_schema
from nomarr.components.platform.migration_runner_comp import (
    MigrationError,
    SchemaVersionMismatchError,
    run_pending_migrations,
)
from nomarr.workflows.platform.register_ml_models_wf import (
    register_ml_models_workflow,
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
    2. Discover and apply pending migrations
    3. Register ML models and seed known labels

    Args:
        db: Database instance (provides both raw db handle and operations).
        models_dir: Path to ML models directory for vector collections.

    Raises:
        SystemExit: If any step fails. Startup is fail-fast.

    """
    # Step 1: Ensure schema (collections, indexes, graphs) - always idempotent
    ensure_schema(db.db, models_dir=models_dir)

    # Step 2: Run all pending migrations (owns version read/compare/apply cycle)
    try:
        run_pending_migrations(db)
    except SchemaVersionMismatchError as exc:
        logger.critical(
            "Database schema is newer than the running application. "
            "Upgrade the application or restore the database from backup. Error: %s",
            exc,
        )
        raise SystemExit(1) from exc
    except MigrationError as exc:
        logger.critical(
            "Database migration failed: %s. Application cannot start.",
            exc,
        )
        raise SystemExit(1) from exc

    # Step 3: Register ML models and seed known labels
    if models_dir is not None:
        register_ml_models_workflow(db, models_dir)
