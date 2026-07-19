"""Database preparation workflow.

Orchestrates the full database startup sequence: schema migration execution.
Called once from Application.__init__ before service initialization.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import TYPE_CHECKING

from nomarr.workflows.platform.register_ml_models_wf import (
    register_ml_models_workflow,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def _run_alembic_upgrade() -> None:
    """Run Alembic migrations to bring the database schema up to date.

    Executes ``alembic upgrade head`` as a subprocess. This applies all
    pending migrations, including the baseline schema on fresh databases.

    Raises:
        SystemExit: If Alembic migration fails. Startup is fail-fast.

    """
    logger.info("Running Alembic migrations (alembic upgrade head)")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        logger.critical(
            "Alembic migration failed (exit code %d). Application cannot start.\nstdout: %s\nstderr: %s",
            result.returncode,
            result.stdout,
            result.stderr,
        )
        raise SystemExit(1)

    logger.info("Alembic migrations completed successfully")


def prepare_database_workflow(
    db: Database,
    *,
    models_dir: str | None = None,
) -> None:
    """Prepare the database for application startup.

    Runs the full startup sequence:
    1. Run Alembic migrations (creates schema on fresh databases, applies
       pending migrations on existing databases)
    2. Register ML models and seed known labels

    Args:
        db: Database instance (provides both raw db handle and operations).
        models_dir: Path to ML models directory for vector collections.

    Raises:
        SystemExit: If any step fails. Startup is fail-fast.

    """
    # Step 1: Run Alembic migrations (handles both fresh and existing databases)
    _run_alembic_upgrade()

    # Step 2: Prune orphaned song documents (no ownership edge).
    # Runs before ML model registration so any orphan-related vector data
    # are already clean before models are re-registered.
    try:
        from nomarr.workflows.platform.prune_orphaned_files_wf import prune_orphaned_files_workflow

        prune_orphaned_files_workflow(db)
    except Exception as exc:
        logger.warning("Orphaned file pruning failed (non-fatal): %s", exc, exc_info=True)

    # Step 3: Register ML models and seed known labels
    if models_dir is not None:
        register_ml_models_workflow(db, models_dir)
