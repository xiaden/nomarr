# Database Migration System

Nomarr uses a **baseline + delta** migration system. The baseline schema is created by `ensure_schema()` on every startup, and migrations apply incremental changes on top of it.

## Core Principle: Single Source of Truth

**`ensure_schema()` is a frozen baseline.** It represents the schema state at the last consolidation point. It is NOT edited when writing new migrations.

**Migrations are the ONLY place for schema changes.** When you need a new collection, index, graph, or data transformation, you write a migration file. You do NOT touch `ensure_schema()`.

This eliminates the drift problem: there is exactly one place that defines each schema change.

### When ensure_schema Gets Updated

`ensure_schema()` is updated **only during consolidation** — when all existing migrations are squashed into a new baseline (typically at a major release boundary). The consolidation process:

1. Captures the current DB state (all migrations applied) as the new `ensure_schema()`
2. Deletes all historical migration files
3. Resets the schema version
4. Creates a single baseline verification migration (V001)

Use `scripts/consolidate_migrations.py` for this. It is an alpha-only operation.

## Architecture

```
Startup Flow:
  validate_environment()
  → ConfigService
  → Database()
  → prepare_database_workflow()
      → ensure_schema()           # Creates baseline collections/indexes (frozen)
      → ensure_schema_version()   # Reads/initializes schema version
      → check_version_mismatch()  # Fails fast if DB is ahead of code
      → discover_migrations()     # Finds migration files
      → get_pending_migrations()  # Filters to unapplied
      → validate_version_chain()  # Ensures contiguous chain
      → apply_migration() loop    # Applies each pending migration
      → update_schema_version()   # Records final version
  → Application.start()           # Services initialize
```

**Fresh install:** `ensure_schema()` creates the baseline, then all migrations run sequentially to bring the schema to the current version.

**Existing install:** `ensure_schema()` is a no-op (everything already exists), then only pending migrations run.

### Migration Tracking

Applied migrations are tracked in the `applied_migrations` collection:

```json
{
  "_key": "V020_example_migration",
  "name": "V020_example_migration",
  "applied_at": "2026-03-22T12:00:00Z",
  "schema_version_before": 19,
  "schema_version_after": 20,
  "duration_ms": 142
}
```

Duplicate prevention is automatic via ArangoDB's `_key` uniqueness constraint.

### Execution Order

Migrations execute in **lexical sort order** of their filenames. The version prefix (`V019_`, `V020_`) guarantees correct ordering.

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

### Workflow

1. **Create a migration file** in `nomarr/migrations/`
2. **Define the schema change** in the migration's `upgrade()` function
3. **Do NOT edit `ensure_schema()`** — the migration is the single source of truth
4. **Run `lint_project_backend`** to verify
5. Test on a fresh database (ensure_schema + all migrations must produce correct state)

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

- `V020_add_playlist_collection.py`
- `V021_normalize_tag_values.py`
- `V022_drop_legacy_collection.py`

### Required Interface

```python
"""V020: Add playlist collection.

Brief description of what this migration does and why.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

# Required metadata
SCHEMA_VERSION_BEFORE: int = 19
SCHEMA_VERSION_AFTER: int = 20
DESCRIPTION: str = "Add playlist collection"


def upgrade(db: DatabaseLike) -> None:
    """Apply this migration.

    Args:
        db: ArangoDB database handle. Use db.aql.execute() for AQL queries,
            db.has_collection() / db.create_collection() for DDL, etc.

    Raises:
        Any exception aborts the migration and prevents startup.
    """
    # Create the collection, index, graph, or transform data here.
    # This is the ONLY place for this schema change.
    ...
```

### Metadata Fields

 | Field | Type | Description |
 | ------- | ------ | ------------- |
 | `SCHEMA_VERSION_BEFORE` | `int` | Schema version this migration expects to find |
 | `SCHEMA_VERSION_AFTER` | `int` | Schema version after this migration completes |
 | `DESCRIPTION` | `str` | Human-readable description for logs |
 | `upgrade(db)` | function | The migration logic |

The runner validates the version chain: each migration's `SCHEMA_VERSION_BEFORE` must
match the previous migration's `SCHEMA_VERSION_AFTER` (or the current DB version for
the first pending migration).

### Migration Responsibilities

Since migrations are now the single source of truth for schema changes, they must handle ALL DDL for the change:

- **New collections**: create with `db.create_collection(name, edge=bool)`
- **New indexes**: create with `collection.add_persistent_index(fields=..., unique=...)`
- **New graphs**: create with `db.create_graph(name=..., edge_definitions=[...])`
- **Data transforms**: use AQL for bulk operations
- **Collection drops**: guard with `db.has_collection()` for idempotency

All operations should be idempotent — guard creation with existence checks and use `contextlib.suppress` for race conditions.

### Best Practices

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

### AQL Safety Rules

These rules were learned from production migration failures (V021/V022 fix cycles). Violating them produces errors that only manifest on databases with existing data — they pass on fresh installs.

1. **Never read and write the same collection in a single AQL statement** (beyond the document being modified). ArangoDB raises `ERR 1579` ("access after data-modification") when a query reads a collection that was already modified by an earlier operation in the same statement. The simple `FOR doc IN X UPDATE doc IN X` pattern is safe, but any cross-operation read (subqueries, LET lookups after INSERT/REMOVE) is not.

   Split into sequential Python calls — first a read-only query to collect data into a Python variable, then a write-only query using bind vars:

   ```python
   # WRONG — reads library_files after INSERT into library_files
   db.aql.execute("""
       FOR doc IN source_collection
           INSERT { ... } INTO library_files
           LET existing = (FOR f IN library_files FILTER f.path == doc.path RETURN f)
           ...
   """)

   # RIGHT — separate read and write phases
   cursor = db.aql.execute("FOR doc IN source_collection RETURN doc")
   rows = [doc for doc in cursor]
   for batch in chunked(rows, 1000):
       db.aql.execute("FOR item IN @batch INSERT item INTO library_files", bind_vars={"batch": batch})
   ```

2. **Drop conflicting indexes BEFORE any UPDATE/UPSERT that changes indexed fields.** If a unique index exists on fields being nullified or modified, the UPDATE will hit `ERR 1210` (unique constraint violated) when two documents collapse to the same indexed values (e.g., multiple documents with `field: null`).

   Use a broad match — drop any index where the modified field appears in the fields array, not just exact field-list matches. This future-proofs against compound indexes you don't know about:

   ```python
   for idx in coll.indexes():
       if idx.get("type") == "persistent" and "field_name" in (idx.get("fields") or []):
           coll.delete_index(idx["id"])
   ```

3. **`ensure_schema` does NOT run on existing databases (ADR-016).** The frozen baseline is a no-op when collections already exist. Migrations cannot rely on `ensure_schema` to repair partial failures or create missing indexes. Each migration must be self-contained and handle its own collection/index creation if needed.

4. **Guard against empty collections on fresh databases.** Migrations run on both existing databases (with data) and fresh databases (empty collections after `ensure_schema`). Every AQL query should handle empty result sets gracefully — don't assume documents exist. Use `FILTER != null` guards and test both paths.

5. **Never UPSERT with user-generated or external data as `_key`.** ArangoDB `_key` has strict character restrictions (no `/`, `?`, `#`, etc.). If source data may contain these characters, use a different field for lookup and let ArangoDB auto-generate `_key`:

   ```python
   # WRONG — path may contain forbidden characters
   db.aql.execute('UPSERT { _key: @path } INSERT { ... } UPDATE { ... } IN files', bind_vars={"path": path})

   # RIGHT — use a non-key field for matching
   db.aql.execute('UPSERT { path: @path } INSERT { ... } UPDATE { ... } IN files', bind_vars={"path": path})
   ```

6. **Test migrations against both fresh and populated databases.** The same migration can succeed on one and fail on the other — `ERR 1579` only fires when the collection has data, unique constraint violations only fire when duplicates exist. Always test both paths before merging.

## Schema Consolidation

When the migration chain grows long, consolidate:

1. Run `scripts/consolidate_migrations.py` — this captures the current cumulative schema state into `ensure_schema()`, deletes all migration files, and creates a V001 baseline verification migration
2. Reset existing databases' schema version (the script provides AQL commands)
3. Future migrations start at V002

This is an alpha-only operation. After 1.0, migration history is preserved.

## Testing Migrations

### Requirements

Every migration must:

1. **Pass lint**: `lint_project_backend(path="nomarr/migrations")` reports zero errors
2. **Have correct metadata**: All four required fields present with correct types
3. **Have contiguous versions**: `SCHEMA_VERSION_BEFORE` of migration N+1 equals
   `SCHEMA_VERSION_AFTER` of migration N
4. **Be idempotent**: Running the migration twice on the same database must not fail
   or corrupt data
5. **Work on fresh install**: `ensure_schema()` (baseline) + all migrations must produce the correct final state

### Manual Testing

Use the Docker test environment to validate migrations:

```powershell
# Start fresh environment
cd docker; docker compose down -v; docker compose up -d

# Check migration ran in startup logs
docker compose logs nomarr | Select-String "migration"

# Verify applied_migrations collection
$auth = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("root:nomarr_dev_password"))
$body = @{query="FOR m IN applied_migrations RETURN m"} | ConvertTo-Json
Invoke-RestMethod -Uri "http://127.0.0.1:8529/_db/nomarr/_api/cursor" -Method Post `
  -Body $body -ContentType "application/json" -Headers @{Authorization="Basic $auth"}
```

## Expected Startup Logs

### Fresh database (first startup)

```
INFO  ensure_schema: Created collections, indexes, graphs (baseline)
INFO  Database schema version: 0, code schema version: 19
INFO  Running 16 pending migration(s) (v0 -> v19)
INFO  Applying migration V004_add_segment_scores_stats...
...
INFO  All migrations completed. Schema version: 19
```

### Existing database (all migrations applied)

```
INFO  Database schema version: 19, code schema version: 19
INFO  All migrations already applied
```

### New migration pending

```
INFO  Database schema version: 19, code schema version: 20
INFO  Running 1 pending migration(s) (v19 -> v20)
INFO  Applying migration V020_add_playlist_collection...
INFO  All migrations completed. Schema version: 20
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

### Fresh install schema doesn't match migrated install

This means `ensure_schema()` is out of date relative to the migrations. If you're
post-consolidation, this shouldn't happen. If it does, run the consolidation script
to re-sync the baseline.

## Migration History

### V023_library_pipeline_states — Library Pipeline Automation Graph

Adds the persistence graph that backs end-to-end library pipeline automation.

**Schema changes:**

- Creates `library_pipeline_states` with the singleton states `idle`, `scanning`, `ml_running`, `too_small`, `awaiting_calibration`, `calibrating`, `applying`, `write_ready`, `writing`, and `done`
- Creates `library_has_pipeline_state` so each library points to exactly one current pipeline state vertex
- Adds `library_auto_write: false` to existing library documents

**Data migration:**

- Derives an initial pipeline state for each existing library from file-state counts
- Seeds one `library_has_pipeline_state` edge per library during migration

**Operational impact:**

- Enables idle-path transitions out of `ml_running`
- Supports startup recovery of `scanning`, `calibrating`, `applying`, and `writing`
- Makes auto-write a per-library setting instead of a global calibration loop switch

### V021_schema_refactor_v1 — FK-to-Edge Schema Refactor

Major schema refactor converting foreign key properties to edge collections for graph-native traversal.

**Edge collections created:**

- `library_contains_file` — library → file relationship
- `library_has_scan` — library → scan state (separated from libraries)
- `model_has_output` — ML model → output relationship
- `model_has_calibration` — ML model → calibration state relationship
- `file_has_vectors` — file → vector storage relationship
- `file_has_segment_stats` — file → segment statistics relationship

**Data migrations:**

- Populates all edge collections from existing FK properties
- Uses `OPTIONS { ignoreErrors: true }` for idempotent edge creation

**FK fields dropped after edge migration:**

- `library_id` (from library_files, library_scans)
- `model_key` (from ml_model_outputs, calibration_states)
- `file_id` (from vectors_track_hot, vectors_track_cold, segment_scores_stats)

**Additional changes:**

- Creates unified `locks` collection (consolidates ml_capacity_probe_locks + vector_promotion_locks)
- Updates graphs: `LibraryGraph`, `MLGraph`, `FileArtifactsGraph`

**Idempotency:** Fully idempotent via `IF NOT EXISTS`, `FILTER != null` guards, and `ignoreErrors` options.
