"""Database preparation workflow.

Orchestrates the full database startup sequence: schema creation,
migration execution, and ML model registration.
Called once from Application.__init__ before service initialization.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

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


def _is_fresh_database(raw_db: Any) -> bool:
    """Check if this is a fresh database with no schema version.

    A fresh database has either no ``meta`` collection at all, or a ``meta``
    collection with no version entry. Either case means ``ensure_schema``
    must run to bootstrap the baseline schema before migrations execute.

    Args:
        raw_db: Raw ArangoDB database handle (``db.db``).

    Returns:
        True if this is a fresh (uninitialized) database.

    """
    if not raw_db.has_collection("meta"):
        return True
    cursor = raw_db.aql.execute("FOR doc IN meta FILTER doc.key == 'version' LIMIT 1 RETURN doc.value")
    return next(cursor, None) is None


def prepare_database_workflow(
    db: Database,
    *,
    models_dir: str | None = None,
) -> None:
    """Prepare the database for application startup.

    Runs the full startup sequence:
    1. Ensure schema (collections, indexes, graphs) — only on fresh databases
    2. Discover and apply pending migrations
    3. Register ML models and seed known labels

    Args:
        db: Database instance (provides both raw db handle and operations).
        models_dir: Path to ML models directory for vector collections.

    Raises:
        SystemExit: If any step fails. Startup is fail-fast.

    """
    # Step 1: Bootstrap schema only on fresh databases.
    # ensure_schema is a frozen baseline — running it on existing databases
    # would recreate indexes that migrations have intentionally dropped.
    if _is_fresh_database(db.db):
        logger.info("Fresh database detected — bootstrapping schema")
        ensure_schema(db.db, models_dir=models_dir)
    else:
        logger.info("Existing database detected — skipping schema bootstrap")

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
