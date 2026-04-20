# Database Migrations

Forward-only migration system using baseline + delta approach. Migrations run automatically on startup.

## Responsibilities

- Apply incremental schema changes on top of the frozen `ensure_schema()` baseline
- Track applied migrations in the `applied_migrations` collection
- Support crash recovery (in-progress migrations are retried on restart)

## Current Migrations

 | File | Purpose |
 | ------ | -------- |
 | `V001_baseline.py` | Consolidated baseline — creates all collections, indexes, graphs, and seed documents (idempotent) |
 | `V020_rename_schema_version_key.py` | Rename `meta.schema_version` to `meta.version` |

## How to Add a New Migration

See [docs/dev/migrations.md](../../docs/dev/migrations.md) for the full guide. Summary:

1. Create `V{NNN}_{description}.py` with a single `upgrade(db: DatabaseLike) -> None` function
2. Version number must be the next integer after the highest existing migration
3. Make `upgrade()` idempotent (safe to re-run after crash)
4. **Never edit `ensure_schema()`** — it is a frozen baseline updated only during consolidation
5. Test by running the app against a fresh database

## Architecture

```
Startup: ensure_schema() → discover_migrations() → get_pending() → apply_migration() loop
```

- **Fresh install**: Baseline creates everything, then all migrations run sequentially
- **Existing install**: Baseline is a no-op, only pending migrations execute
- **Crash recovery**: Migrations with `status='in_progress'` (no completion record) are retried

## Patterns

- **Single function**: Each migration exports `upgrade(db)` — no rollback (forward-only)
- **Idempotent guards**: Use `has_collection()`, `try/except` to be safe on re-run
- **Consolidation**: Periodically squash all migrations into a new baseline via `scripts/consolidate_migrations.py`

## Dependencies

- **Called by**: `components/platform/migration_runner_comp.py` during startup
- **Imports**: `persistence.db.DatabaseLike` for the database handle
