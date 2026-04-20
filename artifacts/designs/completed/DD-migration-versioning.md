# Design: Migration Versioning Overhaul

## Summary

Replace the current integer `SCHEMA_VERSION_BEFORE` / `SCHEMA_VERSION_AFTER` migration chain with a simpler semver-based scheme where each migration declares a single `MIGRATION_VERSION: str` (e.g. `"0.2.0"`). The runner sorts by semver, writes `meta.version` after each migration completes, and enforces that no two migrations share the same version string.

The `meta.schema_version` key (current integer) is renamed to `meta.version` (semver string) via a bridge migration (V020) that also bumps the version to `0.2.0`, matching the new `__version__`.

---

## Motivation

- `SCHEMA_VERSION_BEFORE` is defensive redundancy. With semver ordering the chain invariant is implicit.
- Storing an opaque integer in `meta.schema_version` decouples DB version from program version, making upgrade paths confusing.
- Per-migration version writes give crash recovery at the step boundary, not just at the end.
- Uniqueness enforcement (fail-fast on duplicate `MIGRATION_VERSION`) catches developer errors at startup.
- Consolidating V004–V019 into a baseline removes 16 dead files and replaces them with a single auditable starting point.

---

## New Migration Module Contract

Each migration file (`nomarr/migrations/V*.py`) must expose:

```python
MIGRATION_VERSION: str  # semver, e.g. "0.2.1" — must be unique across all migration files
DESCRIPTION: str

def upgrade(db: DatabaseLike) -> None: ...
```

Old constants `SCHEMA_VERSION_BEFORE` and `SCHEMA_VERSION_AFTER` are removed. `DESCRIPTION` and `upgrade` are unchanged.

---

## Runner Logic (new)

```
1. Discover all V*.py in nomarr/migrations/, import each, validate contract.
2. Fail fast if any two modules share the same MIGRATION_VERSION.
3. Sort modules by semver(MIGRATION_VERSION).
4. Read meta.version from DB → str | None.
5. If None: pending = all migrations (fresh install).
   If present: pending = [m for m in sorted if semver(m.MIGRATION_VERSION) > semver(meta.version)].
6. For each pending migration, in order:
   a. Log start.
   b. Call module.upgrade(db).
   c. Write meta.version = module.MIGRATION_VERSION.
7. If meta.version == __version__ after all migrations: done.
   If meta.version > __version__: fail (DB newer than code).
```

The `applied_migrations` collection is **preserved** for audit history. Recording is simplified: no int fields, just `name`, `migration_version`, `started_at`, `applied_at`, `duration_ms`, `status`.

---

## DB Version Storage

 | Key | Old value | New value |
 | --- | --- | --- |
 | `meta.schema_version` | `"19"` | removed by V020 |
 | `meta.version` | absent | `"0.2.0"` (string) |

`db.py` loses `ensure_schema_version(int)` and `update_schema_version(int)`. Gains `get_version() -> str | None` and `set_version(version: str) -> None`.

---

## Bridge Migration (V020)

```python
MIGRATION_VERSION = "0.2.0"
DESCRIPTION = "Rename meta.schema_version to meta.version (semver)"

def upgrade(db: DatabaseLike) -> None:
    # Idempotent: if meta.version already exists (fresh install from baseline), no-op
    # Otherwise: copy value from schema_version (ignore its integer meaning), write "0.2.0", delete old key
```

V020 doesn't translate the integer; it simply marks the transition boundary. All pre-V020 migrations are collapsed by the consolidation tool, so no DB will ever need to "roll forward" through integers after this point.

---

## Existing Migration Files (V004–V019)

Each file gets `SCHEMA_VERSION_BEFORE` / `SCHEMA_VERSION_AFTER` replaced with:

```python
MIGRATION_VERSION = "0.0.{SCHEMA_VERSION_AFTER}"
```

These files are **short-lived** — they exist only until the consolidation tool runs and replaces them with the baseline. Their new format must satisfy the new runner so the tool's test path works.

---

## Consolidation Tool Updates

`scripts/consolidate_migrations/consolidator.py` currently emits:

```python
SCHEMA_VERSION_BEFORE: int = 0
SCHEMA_VERSION_AFTER: int = 1
```

Must emit instead:

```python
MIGRATION_VERSION = "0.0.0"
```

The generated baseline runs on a fresh DB to create all collections/indexes/graphs and seeds without caring about version history. V020 then bumps the version to `"0.2.0"` on top of it.

---

## prepare_database_wf Changes

- Remove `get_code_schema_version_from_files()` call (filename-based integer scan — obsolete).
- Remove `check_schema_version_mismatch(int, int)` — replaced with semver comparison in runner.
- The workflow calls: `ensure_schema()` → `runner.run_pending_migrations(db)` (new unified entry point).
- Runner raises `SchemaVersionMismatchError` if `meta.version > __version__`.

---

## Version Bump

`nomarr/__version__.py`: `"0.1.4"` → `"0.2.0"`

This is the first version where the DB stores semver. The bump signals the schema era change. ML tagger version is unaffected (remains a content hash, `compute_model_suite_hash()`).

---

## Test Coverage

### New tests

- `tests/unit/components/test_migration_runner_comp.py` — full rewrite for new API
- `tests/unit/migrations/test_migration_uniqueness.py` — `@pytest.mark.code_smell`: asserts no two migration files in `nomarr/migrations/` share the same `MIGRATION_VERSION`

### Updated tests

- Any test that constructs `MigrationOperations.record_migration_started(schema_version_before=..., schema_version_after=...)` → update to new signature
- Any test using `db.ensure_schema_version()` or `db.update_schema_version()` → update to `get_version()` / `set_version()`

---

## Files Touched

 | File | Change |
 | --- | --- |
 | `nomarr/__version__.py` | bump to `0.2.0` |
 | `nomarr/persistence/db.py` | `get_version()`, `set_version()` replace integer methods |
 | `nomarr/persistence/database/migrations_aql.py` | remove int fields from record methods |
 | `nomarr/components/platform/migration_runner_comp.py` | full rewrite |
 | `nomarr/workflows/platform/prepare_database_wf.py` | simplify, use new runner |
 | `nomarr/migrations/V004–V019` | `MIGRATION_VERSION = "0.0.X"` (16 files) |
 | `nomarr/migrations/V020_*.py` | new bridge migration |
 | `scripts/consolidate_migrations/consolidator.py` | emit new format |
 | `tests/unit/components/test_migration_runner_comp.py` | full rewrite |
 | `tests/unit/migrations/test_migration_uniqueness.py` | new |
 | Various test files | update int signatures |
