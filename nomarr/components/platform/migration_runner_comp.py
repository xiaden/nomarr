"""Migration runner component.

Discovers, validates, and executes database migrations in order.
"""

from __future__ import annotations

import importlib
import logging
from collections import defaultdict
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

from packaging.version import InvalidVersion, Version

from nomarr.__version__ import __version__
from nomarr.helpers.time_helper import format_wall_timestamp, internal_ms, now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

MIGRATIONS_PACKAGE = "nomarr.migrations"
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"

_REQUIRED_ATTRS = ("MIGRATION_VERSION", "DESCRIPTION", "upgrade")


class MigrationError(Exception):
    """Raised when a migration fails during execution."""


class SchemaVersionMismatchError(Exception):
    """Raised when the database schema is newer than the code."""


def _validate_migration_module(module: ModuleType, filename: str) -> None:
    """Validate that a migration module has all required attributes."""
    for attr in _REQUIRED_ATTRS:
        if not hasattr(module, attr):
            msg = f"Migration {filename} is missing required attribute: {attr}"
            raise MigrationError(msg)

    if not isinstance(module.MIGRATION_VERSION, str):
        msg = f"Migration {filename}: MIGRATION_VERSION must be str, got {type(module.MIGRATION_VERSION).__name__}"
        raise MigrationError(msg)

    try:
        Version(module.MIGRATION_VERSION)
    except InvalidVersion as exc:
        msg = (
            f"Migration {filename}: MIGRATION_VERSION {module.MIGRATION_VERSION!r} is not a valid semver string: {exc}"
        )
        raise MigrationError(msg) from exc

    if not isinstance(module.DESCRIPTION, str):
        msg = f"Migration {filename}: DESCRIPTION must be str, got {type(module.DESCRIPTION).__name__}"
        raise MigrationError(msg)

    if not callable(module.upgrade):
        msg = f"Migration {filename}: upgrade must be callable"
        raise MigrationError(msg)


def discover_migrations() -> list[tuple[str, ModuleType]]:
    """Discover and load all migration files from nomarr/migrations/."""
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

    migrations.sort(key=lambda item: Version(item[1].MIGRATION_VERSION))

    logger.info("Discovered %d migration(s)", len(migrations))
    return migrations


def check_duplicate_versions(migrations: list[tuple[str, ModuleType]]) -> None:
    """Check for duplicate MIGRATION_VERSION values across discovered migrations."""
    version_to_names: dict[str, list[str]] = defaultdict(list)
    for name, module in migrations:
        version_to_names[module.MIGRATION_VERSION].append(name)

    conflicts = {ver: names for ver, names in version_to_names.items() if len(names) > 1}
    if conflicts:
        conflict_lines = ", ".join(f"{ver!r} in [{', '.join(names)}]" for ver, names in sorted(conflicts.items()))
        msg = f"Duplicate MIGRATION_VERSION detected: {conflict_lines}"
        raise MigrationError(msg)


def get_pending_migrations(
    all_migrations: list[tuple[str, ModuleType]],
    current_db_version: str | None,
) -> list[tuple[str, ModuleType]]:
    """Filter to only migrations that have not yet been applied."""
    if current_db_version is None:
        # Fresh database — all migrations are pending
        pending = list(all_migrations)
    else:
        current = Version(current_db_version)
        pending = [(name, mod) for name, mod in all_migrations if Version(mod.MIGRATION_VERSION) > current]

    if pending:
        logger.info(
            "Found %d pending migration(s): %s",
            len(pending),
            ", ".join(name for name, _ in pending),
        )
    else:
        logger.debug("No pending migrations")
    return pending


def apply_migration(name: str, module: ModuleType, db: Database) -> None:
    """Apply a single migration with two-phase recording.

    Records 'in_progress' before upgrade(), then 'applied' after success.
    Crashes mid-migration are visible and automatically retried on next startup.
    """
    logger.info(
        "Applying migration %s: %s (version %s)",
        name,
        module.DESCRIPTION,
        module.MIGRATION_VERSION,
    )

    started_at = format_wall_timestamp(now_ms(), fmt="%Y-%m-%dT%H:%M:%SZ")
    db.app.upsert_migration(
        name,
        {
            "status": "in_progress",
            "started_at": started_at,
            "migration_version": module.MIGRATION_VERSION,
        },
    )

    start_time = internal_ms()
    try:
        module.upgrade(db.db)
    except Exception as exc:
        # Broad catch: migrations may raise any exception from user code —
        # wrap all failures uniformly as MigrationError for the caller.
        msg = f"Migration {name} (version {module.MIGRATION_VERSION}) failed: {exc}"
        raise MigrationError(msg) from exc

    duration_ms = internal_ms().value - start_time.value
    applied_at = format_wall_timestamp(now_ms(), fmt="%Y-%m-%dT%H:%M:%SZ")

    db.app.upsert_migration(
        name,
        {
            "status": "applied",
            "applied_at": applied_at,
            "duration_ms": duration_ms,
        },
    )

    # Write the new version only after the migration is fully recorded
    db.set_version(module.MIGRATION_VERSION)

    logger.info(
        "Migration %s (version %s) completed in %dms",
        name,
        module.MIGRATION_VERSION,
        duration_ms,
    )


def run_pending_migrations(db: Database) -> None:
    """Discover and apply all pending migrations, then verify version compatibility."""
    current = db.get_version()
    logger.debug("Current database version: %s", current or "<none>")

    migrations = discover_migrations()
    check_duplicate_versions(migrations)

    pending = get_pending_migrations(migrations, current)
    for name, module in pending:
        apply_migration(name, module, db)

    # After applying all migrations, guard against DB being ahead of the code
    final_version = db.get_version()
    if final_version is not None and Version(final_version) > Version(__version__):
        msg = (
            f"Database schema version ({final_version}) is newer than "
            f"application version ({__version__}). "
            f"Upgrade the application to match the database, or restore the database from backup."
        )
        raise SchemaVersionMismatchError(msg)
