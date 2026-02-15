# Database Migration System

Nomarr uses a forward-only migration system to handle schema changes that require data transformation.

## Overview

**Key concepts:**

- `ensure_schema()` handles DDL (creating collections, indexes, graphs) — idempotent, runs every startup
- **Migrations** handle DML and destructive DDL (data transformation, field renames, collection drops)
- Migrations run **after** `ensure_schema()` and **before** service initialization
- Each migration is a Python module with a standardized interface
- Migrations are forward-only — no rollback/down functions (alpha policy)

## Architecture

```
Startup Flow:
  validate_environment()
  → ConfigService
  → Database()
  → prepare_database_workflow()   # Single workflow call from Application.__init__
      → ensure_schema()           # Creates missing collections/indexes (idempotent)
      → ensure_schema_version()   # Reads/initializes schema version
      → check_version_mismatch()  # Fails fast if DB is ahead of code
      → discover_migrations()     # Finds migration files
      → get_pending_migrations()  # Filters to unapplied
      → validate_version_chain()  # Ensures contiguous chain
      → apply_migration() loop    # Applies each pending migration
      → update_schema_version()   # Records final version
  → Application.start()           # Services initialize
```

### Migration Tracking

Applied migrations are tracked in the `applied_migrations` collection:

```json
{
  "_key": "V006_example_migration",
  "name": "V006_example_migration",
  "applied_at": "2026-02-15T12:00:00Z",
  "schema_version_before": 5,
  "schema_version_after": 6,
  "duration_ms": 142
}
```

Duplicate prevention is automatic via ArangoDB's `_key` uniqueness constraint.

### Execution Order

Migrations execute in **lexical sort order** of their filenames. The version prefix
(`V006_`, `V007_`) guarantees correct ordering.

The runner:

1. Scans `nomarr/migrations/` for `V*.py` files
2. Queries `applied_migrations` for already-applied migration keys
3. Filters to pending migrations (not yet applied)
4. Validates the version chain is contiguous
5. Executes each pending migration in order
6. Records each successful migration in `applied_migrations`
7. Updates `schema_version` in meta collection after all migrations complete

### Error Handling

- **Migration failure**: App startup aborts immediately. The failed migration is NOT
  recorded, so it retries on next startup. Previously successful migrations remain recorded.
- **DB newer than code**: If the database `schema_version` exceeds the code's
  `SCHEMA_VERSION`, startup aborts with a clear error message.
- **Partial completion**: Each migration is responsible for its own idempotency.
  If a migration partially completes before failing, it must handle re-execution gracefully.

## Writing Migrations

### File Location

All migration files live in `nomarr/migrations/`.

### Naming Convention

```
V{NNN}_{description}.py
```

Where:
- `NNN` is a zero-padded 3-digit **target** schema version
- `description` is snake_case describing what the migration does

Examples:
- `V006_add_applied_migrations.py`
- `V007_normalize_tag_values.py`
- `V008_drop_legacy_calibration_collections.py`

### Required Interface

Every migration module must define:

```python
"""V006: Add applied_migrations collection.

Brief description of what this migration does and why.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.types import DatabaseLike

# Required metadata
SCHEMA_VERSION_BEFORE: int = 5
SCHEMA_VERSION_AFTER: int = 6
DESCRIPTION: str = "Add applied_migrations collection"


def upgrade(db: DatabaseLike) -> None:
    """Apply this migration.

    Args:
        db: ArangoDB database handle. Use db.aql.execute() for AQL queries,
            db.has_collection() / db.create_collection() for DDL, etc.

    Raises:
        Any exception aborts the migration and prevents startup.
    """
    # Migration logic here
    ...
```

### Metadata Fields

| Field | Type | Description |
|-------|------|-------------|
| `SCHEMA_VERSION_BEFORE` | `int` | Schema version this migration expects to find |
| `SCHEMA_VERSION_AFTER` | `int` | Schema version after this migration completes |
| `DESCRIPTION` | `str` | Human-readable description for logs |
| `upgrade(db)` | function | The migration logic |

The runner validates the version chain: each migration's `SCHEMA_VERSION_BEFORE` must
match the previous migration's `SCHEMA_VERSION_AFTER` (or the current DB version for
the first pending migration).

### Migration Best Practices

1. **Make migrations idempotent** where possible. If a migration partially completes
   and fails, it will re-run on next startup. Guard destructive operations:
   ```python
   if db.has_collection("old_collection"):
       db.delete_collection("old_collection")
   ```

2. **Use AQL for bulk data operations** — it's faster than document-by-document:
   ```python
   db.aql.execute("""
       FOR doc IN library_files
           FILTER doc.old_field != null
           UPDATE doc WITH { new_field: doc.old_field, old_field: null } IN library_files
   """)
   ```

3. **Keep migrations focused** — one logical change per migration. Don't combine
   unrelated schema changes.

4. **Log progress** for long-running migrations:
   ```python
   import logging
   logger = logging.getLogger(__name__)
   logger.info("Migrating %d documents...", count)
   ```

5. **Never import from `nomarr.services` or `nomarr.interfaces`** — migrations run
   before services are initialized. Only import from `nomarr.persistence` and
   `nomarr.helpers` if needed.

## Testing Migrations

### Requirements

Every migration must:

1. **Pass lint**: `lint_project_backend(path="nomarr/migrations")` reports zero errors
2. **Have correct metadata**: All four required fields present with correct types
3. **Have contiguous versions**: `SCHEMA_VERSION_BEFORE` of migration N+1 equals
   `SCHEMA_VERSION_AFTER` of migration N
4. **Be idempotent**: Running the migration twice on the same database must not fail
   or corrupt data

### Manual Testing

Use the Docker test environment to validate migrations:

```powershell
# Start fresh environment
cd .docker; docker compose down -v; docker compose up -d

# Check migration ran in startup logs
docker compose logs nomarr | Select-String "migration"

# Verify applied_migrations collection
$auth = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("root:nomarr_dev_password"))
$body = @{query="FOR m IN applied_migrations RETURN m"} | ConvertTo-Json
Invoke-RestMethod -Uri "http://127.0.0.1:8529/_db/nomarr/_api/cursor" -Method Post `
  -Body $body -ContentType "application/json" -Headers @{Authorization="Basic $auth"}
```

## Expected Startup Logs

### Fresh database (first startup with migrations)

```
INFO  [Application] Database schema version: 5, code schema version: 6
INFO  [nomarr.components.platform.migration_runner_comp] Discovered 1 migration(s)
INFO  [nomarr.components.platform.migration_runner_comp] Found 1 pending migration(s): V006_add_applied_migrations
INFO  [nomarr.components.platform.migration_runner_comp] Running 1 pending migration(s) (v5 -> v6)
INFO  [nomarr.components.platform.migration_runner_comp] Applying migration V006_add_applied_migrations: Add applied_migrations collection for migration tracking (v5 -> v6)
INFO  [nomarr.migrations.V006_add_applied_migrations] Migration V006: applied_migrations collection verified.
INFO  [nomarr.persistence.database.migrations_aql] Recorded migration V006_add_applied_migrations (v5 -> v6, 12ms)
INFO  [nomarr.components.platform.migration_runner_comp] Migration V006_add_applied_migrations completed in 12ms
INFO  [nomarr.components.platform.migration_runner_comp] All migrations completed. Schema version: 6
INFO  [Application] Schema version updated: 5 -> 6
```

### Existing database (all migrations already applied)

```
INFO  [Application] Database schema version: 6, code schema version: 6
INFO  [nomarr.components.platform.migration_runner_comp] Discovered 1 migration(s)
INFO  [nomarr.components.platform.migration_runner_comp] All migrations already applied
```

### Migration failure

```
INFO  [Application] Database schema version: 5, code schema version: 6
INFO  [nomarr.components.platform.migration_runner_comp] Running 1 pending migration(s) (v5 -> v6)
CRITICAL [Application] Database migration failed: Migration V006_add_applied_migrations failed: <error details>. Application cannot start.
```

## Troubleshooting

### "Database schema version (X) is newer than code (Y)"

The database was migrated by a newer version of Nomarr. Update the application code
to match or restore the database from backup.

### "Migration version chain broken"

A migration's `SCHEMA_VERSION_BEFORE` doesn't match the expected version. Check for
missing migration files or incorrect version numbers.

### Migration fails on startup

The app will not start until the migration succeeds. Check logs for the specific error.
If the migration partially completed, it must handle re-execution (idempotency).
Fix the migration code and restart.
