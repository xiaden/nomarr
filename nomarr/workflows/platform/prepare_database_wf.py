"""Database preparation workflow.

Orchestrates the full database startup sequence: schema creation,
migration execution, and ML model registration.
Called once from Application.__init__ before service initialization.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.platform.arango_bootstrap_comp import (
    ensure_schema_from_database,
    list_template_collection_names,
    seed_state_documents,
)
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


def _is_fresh_database(db: Database) -> bool:
    """Check if this is a fresh database with no schema version.

    A fresh database has either no ``meta`` collection at all, or a ``meta``
    collection with no version entry. Either case means ``ensure_schema``
    must run to bootstrap the baseline schema before migrations execute.

    Args:
        db: Database facade with raw handle and collection operations.

    Returns:
        True if this is a fresh (uninitialized) database.

    """
    return db.app.get_schema_version() is None


def _discover_template_collections(db: Database) -> None:
    """Scan ArangoDB and register all collections matching template name patterns."""
    template_names = list_template_collection_names()
    registered = 0

    for name in db.app.list_collections():
        if name.startswith("_"):
            continue

        for template_name in template_names:
            if name.startswith(f"{template_name}__"):
                try:
                    db.ml.add_vector_collection(name, template_name)
                    registered += 1
                except ValueError:
                    logger.warning(
                        "Skipping template collection %r: registration failed",
                        name,
                    )
                break

    logger.info("Discovered and registered %d template collection(s)", registered)


def prepare_database_workflow(
    db: Database,
    *,
    models_dir: str | None = None,
) -> None:
    """Prepare the database for application startup.

    Runs the full startup sequence:
    1. Ensure schema (collections, indexes, graphs) — only on fresh databases
    2. Discover and apply pending migrations
    3. Discover and register existing dynamic template collections
    4. Register ML models and seed known labels

    Args:
        db: Database instance (provides both raw db handle and operations).
        models_dir: Path to ML models directory for vector collections.

    Raises:
        SystemExit: If any step fails. Startup is fail-fast.

    """
    # Step 1: Bootstrap schema only on fresh databases.
    # ensure_schema is a frozen baseline — running it on existing databases
    # would recreate indexes that migrations have intentionally dropped.
    if _is_fresh_database(db):
        logger.info("Fresh database detected — bootstrapping schema")
        ensure_schema_from_database(db, models_dir=models_dir)
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

    # Step 3: Discover and register existing dynamic template collections
    _discover_template_collections(db)

    # Step 4: Prune orphaned library_files documents (no ownership edge).
    # Runs before ML model registration so any orphan-related vector collections
    # are already clean before models are re-registered.
    try:
        from nomarr.workflows.platform.prune_orphaned_files_wf import prune_orphaned_files_workflow

        prune_orphaned_files_workflow(db)
    except Exception as exc:
        logger.warning("Orphaned file pruning failed (non-fatal): %s", exc, exc_info=True)

    # Step 5: Reseed singleton state vertex documents.
    # file_states and library_pipeline_states vertices are fixed sets that
    # should always exist.  This is idempotent and repairs any accidental deletion.
    seed_state_documents(db)

    # Step 6: Register ML models and seed known labels
    if models_dir is not None:
        register_ml_models_workflow(db, models_dir)
