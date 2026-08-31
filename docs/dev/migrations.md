# Database Migration System

Nomarr uses **Alembic** for PostgreSQL schema migrations. Alembic provides a battle-tested, version-controlled approach to database schema evolution.

## Core Principle: One Baseline Until Stable

Nomarr currently uses one Alembic baseline for fresh PostgreSQL installations. The project has not been stable enough to support installed-database upgrade paths, so the pre-stability revision chain was consolidated into `001_current_schema_baseline.py`.

Existing databases created from an earlier revision are unsupported and must be recreated. Once the application is stable enough to preserve upgrade compatibility, future schema changes may be added as normal Alembic revisions after the baseline.

## Architecture

```
Startup Flow:
  validate_environment()
  → ConfigService
  → Database()
  → alembic upgrade head         # Creates the baseline schema
  → Application.start()          # Services initialize
```

**Fresh install:** `alembic upgrade head` creates the complete current schema from the single baseline.

**Existing pre-baseline install:** Recreate the database before running Nomarr. The consolidated history intentionally does not provide an upgrade path from old revisions.

### Migration Tracking

Alembic tracks applied migrations in the `alembic_version` table:

```sql
SELECT * FROM alembic_version;
--  version_num
-- ------------
--  baseline_20260830
```

Alembic's built-in version table ensures each migration runs exactly once.

### Execution Order

The baseline is the only revision and has no predecessor. Future revisions will execute in chain order following the dependency graph defined by `down_revision`.

The runner:

1. Connects to PostgreSQL
2. Reads `alembic_version` to determine current state
3. Computes the migration path from current to `head`
4. Executes each pending migration in order, within a transaction
5. Records each successful migration in `alembic_version`

### Error Handling

- **Migration failure**: App startup aborts immediately. Alembic rolls back the failed migration's transaction. Previously successful migrations remain recorded.
- **DB newer than code**: If the database revision is not in the migration chain, startup aborts with a clear error message.
- **Partial completion**: Each migration runs in a transaction. If it fails, the transaction is rolled back completely.

## Writing Migrations

### Workflow

1. Before stability, update the single baseline directly.
2. Review the baseline against the SQLAlchemy models and fresh-database behavior.
3. Once upgrade compatibility is explicitly supported, create a new revision with:
   ```bash
   alembic revision --autogenerate -m "add_playlist_table"
   ```
4. **Do NOT edit SQLAlchemy models and skip migrations** — Alembic remains the schema source of truth.
5. Run `lint_project_backend` and test on a fresh database.

### File Location

All Alembic revision files live in `alembic/versions/`.

### Naming Convention for Future Revisions

After upgrade-compatible deployments are explicitly supported, Alembic may generate revision IDs with descriptive slugs:

```
{revision_id}_{description}.py
```

Examples:

- `a1b2c3d4e5f6_add_playlist_table.py`
- `b2c3d4e5f6a7_normalize_tag_values.py`
- `c3d4e5f6a7b8_drop_legacy_table.py`

### Required Interface for Future Revisions

The baseline itself uses the same Alembic interface. Future revisions should follow this shape:

```python
"""Add playlist table.

Revision ID: a1b2c3d4e5f6
Revises: previous_revision_id
Create Date: 2026-03-22T12:00:00

Brief description of what this migration does and why.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "previous_revision_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply this migration."""
    op.create_table(
        "playlists",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("library_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_playlists_library_id", "playlists", ["library_id"])


def downgrade() -> None:
    """Revert this migration."""
    op.drop_index("ix_playlists_library_id", table_name="playlists")
    op.drop_table("playlists")
```

### Migration Responsibilities for Future Revisions

Future revisions must handle ALL DDL for their change:

- **New tables**: create with `op.create_table()`
- **New columns**: add with `op.add_column()`
- **New indexes**: create with `op.create_index()`
- **New constraints**: add with `op.create_unique_constraint()`, `op.create_foreign_key()`, etc.
- **Data transforms**: use `op.execute()` with raw SQL for bulk operations
- **Table drops**: use `op.drop_table()`
- **Column drops**: use `op.drop_column()`

All operations should be guarded for idempotency where possible:
- Check table existence before dropping
- Use `IF NOT EXISTS` / `IF EXISTS` clauses in raw SQL

### Best Practices for Future Revisions

1. **Make migrations idempotent** where possible. If a migration partially completes
   and fails, guard destructive operations:

   ```python
   def upgrade() -> None:
       op.execute("DROP TABLE IF EXISTS old_table")
   ```

2. **Use raw SQL for bulk data operations** — it's faster than row-by-row:

   ```python
   def upgrade() -> None:
       op.execute("""
           UPDATE songs
           SET new_field = old_field, old_field = NULL
           WHERE old_field IS NOT NULL
       """)
   ```

3. **Keep migrations focused** — one logical change per migration. Don't combine
   unrelated schema changes.

4. **Log progress** for long-running migrations:

   ```python
   import logging

   logger = logging.getLogger(__name__)
   logger.info("Migrating %d rows...", count)
   ```

5. **Always provide a `downgrade()` function** so migrations can be rolled back.
   For destructive operations, the downgrade should recreate what was lost or raise
   an informative error if rollback is not feasible.

6. **Test migrations against both fresh and populated databases.** The same migration
   can succeed on one and fail on the other — unique constraint violations only fire
   when duplicates exist. Always test both paths before merging.

7. **Never import from `nomarr.services` or `nomarr.interfaces`** — migrations run
   before services are initialized. Only import from SQLAlchemy and Alembic.

### SQL Safety Rules

These rules were learned from production migration experience:

1. **Use transactions.** Alembic wraps each migration in a transaction by default.
   If a migration needs to run outside a transaction (e.g., creating indexes concurrently),
   set `transaction_per_migration = False` or use `op.execute("COMMIT; ...")` carefully.

2. **Drop conflicting indexes BEFORE any UPDATE that changes indexed columns.**
   If a unique index exists on fields being nullified or modified, the UPDATE will hit
   a unique constraint violation when two rows collapse to the same indexed values.

3. **Guard against empty tables on fresh databases.** Migrations run on both existing
   databases (with data) and fresh databases (empty tables). Every query should handle
   empty result sets gracefully.

4. **Never assume auto-generated IDs match external identifiers.** Use explicit
   natural keys (like `path`, `name`) for lookups in data migrations, not surrogate
   IDs that differ between environments.

## Testing the Baseline and Future Migrations

### Baseline Requirements

The baseline must:

1. **Pass lint**: `lint_project_backend(path="alembic/versions")` reports zero errors
2. **Have correct metadata**: Valid `revision`, `down_revision=None`, and docstring
3. **Work on fresh install**: `alembic upgrade head` must produce the complete current schema
4. **Have a working downgrade**: `alembic downgrade base` must cleanly remove the baseline schema

### Manual Testing

Use the Docker test environment to validate migrations:

```powershell
# Start fresh environment
cd docker; docker compose down -v; docker compose up -d

# Check migration ran in startup logs
docker compose logs nomarr | Select-String "alembic"

# Verify schema
docker exec -it nomarr-postgres psql -U nomarr -d nomarr -c "\dt"
```

## Expected Startup Logs

### Fresh database (first startup)

```
INFO  Running alembic upgrade head
INFO  Running upgrade  -> baseline_20260830, current schema baseline
INFO  Migrations complete
```

### Existing database (baseline applied)

```
INFO  Running alembic upgrade head
INFO  Database already at head revision
```

A database stamped with one of the removed pre-baseline revisions is not supported; recreate it instead.

### Future migration pending

Once upgrade-compatible deployments are supported, a future revision may follow the baseline:

```
INFO  Running alembic upgrade head
INFO  Running upgrade baseline_20260830 -> c3d4e5f6a7b8, add_playlist_table
INFO  Migrations complete
```

## Troubleshooting

### "Database revision is newer than code"

The database was migrated by a newer version of Nomarr. Update the application code
to match or restore the database from backup.

### "Migration chain broken"

A migration's `down_revision` doesn't match any known revision. Check for
missing migration files or incorrect revision IDs.

### Migration fails on startup

The app will not start until the migration succeeds. Check logs for the specific error.
Alembic rolls back the failed migration's transaction automatically.
Fix the migration code and restart.

### Fresh install schema doesn't match the models

This means the baseline and SQLAlchemy models are out of sync. Before the project
supports upgrade-compatible deployments, update the single baseline and review it
carefully against the models. After that point, add a new revision with
`--autogenerate` and review the generated operations.

## Alembic Commands

```bash
# Generate a new migration from model changes
alembic revision --autogenerate -m "description_of_change"

# Create an empty migration for manual edits
alembic revision -m "description_of_change"

# Apply all pending migrations
alembic upgrade head

# Remove the baseline schema
alembic downgrade base

# Show current revision
alembic current

# Show migration history
alembic history

# Generate SQL for a migration (dry-run)
alembic upgrade head --sql
```
