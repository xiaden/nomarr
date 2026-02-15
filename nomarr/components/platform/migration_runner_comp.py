"""Migration runner component.

Discovers, validates, and executes database migrations in order.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

from nomarr.helpers.time_helper import format_wall_timestamp, internal_ms, now_ms

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike
    from nomarr.persistence.database.migrations_aql import MigrationOperations

logger = logging.getLogger(__name__)

# Directory containing migration files
MIGRATIONS_PACKAGE = "nomarr.migrations"
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"

# Required attributes in each migration module
_REQUIRED_ATTRS = ("SCHEMA_VERSION_BEFORE", "SCHEMA_VERSION_AFTER", "DESCRIPTION", "upgrade")


class MigrationError(Exception):
    """Raised when a migration fails during execution."""


class MigrationChainError(Exception):
    """Raised when the migration version chain is broken."""


class SchemaVersionMismatchError(Exception):
    """Raised when the database schema is newer than the code."""


def _validate_migration_module(module: ModuleType, filename: str) -> None:
    """Validate that a migration module has all required attributes.

    Args:
        module: Imported migration module.
        filename: Filename for error messages.

    Raises:
        MigrationError: If required attributes are missing or wrong type.

    """
    for attr in _REQUIRED_ATTRS:
        if not hasattr(module, attr):
            msg = f"Migration {filename} is missing required attribute: {attr}"
            raise MigrationError(msg)

    if not isinstance(module.SCHEMA_VERSION_BEFORE, int):
        msg = f"Migration {filename}: SCHEMA_VERSION_BEFORE must be int, got {type(module.SCHEMA_VERSION_BEFORE).__name__}"
        raise MigrationError(msg)

    if not isinstance(module.SCHEMA_VERSION_AFTER, int):
        msg = f"Migration {filename}: SCHEMA_VERSION_AFTER must be int, got {type(module.SCHEMA_VERSION_AFTER).__name__}"
        raise MigrationError(msg)

    if not isinstance(module.DESCRIPTION, str):
        msg = f"Migration {filename}: DESCRIPTION must be str, got {type(module.DESCRIPTION).__name__}"
        raise MigrationError(msg)

    if not callable(module.upgrade):
        msg = f"Migration {filename}: upgrade must be callable"
        raise MigrationError(msg)


def discover_migrations() -> list[tuple[str, ModuleType]]:
    """Discover and load all migration files from nomarr/migrations/.

    Returns:
        List of (name, module) tuples sorted by filename (lexical order).
        Name is the filename stem (e.g., "V006_example").

    Raises:
        MigrationError: If any migration module is invalid.

    """
    if not MIGRATIONS_DIR.exists():
        logger.debug("No migrations directory found at %s", MIGRATIONS_DIR)
        return []

    migration_files = sorted(MIGRATIONS_DIR.glob("V*.py"))
    if not migration_files:
        logger.debug("No migration files found in %s", MIGRATIONS_DIR)
        return []

    migrations: list[tuple[str, ModuleType]] = []
    for path in migration_files:
        name = path.stem
        module_path = f"{MIGRATIONS_PACKAGE}.{name}"
        logger.debug("Loading migration: %s", module_path)
        module = importlib.import_module(module_path)
        _validate_migration_module(module, path.name)
        migrations.append((name, module))

    logger.info("Discovered %d migration(s)", len(migrations))
    return migrations


def get_pending_migrations(
    all_migrations: list[tuple[str, ModuleType]],
    applied_names: set[str],
) -> list[tuple[str, ModuleType]]:
    """Filter to only migrations that have not been applied.

    Args:
        all_migrations: All discovered migrations (name, module) pairs.
        applied_names: Set of migration names already applied.

    Returns:
        List of (name, module) pairs for pending migrations, in order.

    """
    pending = [(name, mod) for name, mod in all_migrations if name not in applied_names]
    if pending:
        logger.info(
            "Found %d pending migration(s): %s",
            len(pending),
            ", ".join(name for name, _ in pending),
        )
    else:
        logger.debug("No pending migrations")
    return pending


def validate_version_chain(
    pending: list[tuple[str, ModuleType]],
    current_db_version: int,
) -> None:
    """Validate that the pending migration version chain is contiguous.

    Args:
        pending: Pending migrations in execution order.
        current_db_version: Current schema version in the database.

    Raises:
        MigrationChainError: If the version chain has gaps.

    """
    expected_version = current_db_version
    for name, module in pending:
        if expected_version != module.SCHEMA_VERSION_BEFORE:
            msg = (
                f"Migration version chain broken at {name}: "
                f"expects version {module.SCHEMA_VERSION_BEFORE} "
                f"but current version is {expected_version}"
            )
            raise MigrationChainError(msg)
        expected_version = module.SCHEMA_VERSION_AFTER


def apply_migration(
    name: str,
    module: ModuleType,
    db: DatabaseLike,
    migration_ops: MigrationOperations,
) -> None:
    """Apply a single migration with timing and recording.

    Args:
        name: Migration identifier.
        module: Migration module with upgrade() function.
        db: ArangoDB database handle.
        migration_ops: Operations for recording applied migrations.

    Raises:
        MigrationError: If the migration's upgrade() function fails.

    """
    logger.info(
        "Applying migration %s: %s (v%d -> v%d)",
        name,
        module.DESCRIPTION,
        module.SCHEMA_VERSION_BEFORE,
        module.SCHEMA_VERSION_AFTER,
    )

    start_time = internal_ms()
    try:
        module.upgrade(db)
    except Exception as exc:
        msg = f"Migration {name} failed: {exc}"
        raise MigrationError(msg) from exc

    duration_ms = internal_ms().value - start_time.value
    applied_at = format_wall_timestamp(now_ms(), fmt="%Y-%m-%dT%H:%M:%SZ")

    migration_ops.record_migration(
        name=name,
        schema_version_before=module.SCHEMA_VERSION_BEFORE,
        schema_version_after=module.SCHEMA_VERSION_AFTER,
        duration_ms=duration_ms,
        applied_at=applied_at,
    )

    logger.info(
        "Migration %s completed in %dms",
        name,
        duration_ms,
    )


def check_schema_version_mismatch(
    current_db_version: int,
    code_schema_version: int,
) -> None:
    """Check if the database schema is ahead of the running code.

    Should be called before running migrations to fail fast on
    forward-version mismatches.

    Args:
        current_db_version: Current schema version stored in the database.
        code_schema_version: Schema version expected by the running code.

    Raises:
        SchemaVersionMismatchError: If database is newer than code.

    """
    if current_db_version > code_schema_version:
        msg = (
            f"Database schema version ({current_db_version}) is newer than "
            f"code ({code_schema_version}). Upgrade the application to match "
            f"the database, or restore the database from backup."
        )
        raise SchemaVersionMismatchError(msg)



