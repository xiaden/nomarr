# Task: Migration Versioning — Part A: Persistence & Runner Core

## Problem Statement

The migration system currently uses integer `SCHEMA_VERSION_BEFORE` / `SCHEMA_VERSION_AFTER` constants on each migration module, stores the version as an integer in `meta.schema_version`, and exposes `db.ensure_schema_version(int)` / `db.update_schema_version(int)` on `Database`. This plan replaces that with a semver-string scheme:

- `Database` gains `get_version() -> str | None` and `set_version(str)` that read/write `meta.version` (new key); the old integer methods are removed.
- `MigrationOperations.record_migration_started` loses `schema_version_before: int` / `schema_version_after: int` and gains `migration_version: str`. The legacy `record_migration` method (unused by the two-phase runner) is removed.
- `migration_runner_comp.py` is fully rewritten: `_REQUIRED_ATTRS` becomes `("MIGRATION_VERSION", "DESCRIPTION", "upgrade")`, validation enforces a parseable semver string, `check_duplicate_versions()` fail-fasts on collisions, migrations are sorted and filtered by `packaging.version.Version`, and a unified entry point `run_pending_migrations(db: Database) -> None` owns the full lifecycle.

Old public helpers (`get_code_schema_version_from_files`, `validate_version_chain`, `check_schema_version_mismatch`, `apply_migration` with the old signature, `get_current_schema_version`) are removed. `prepare_database_wf.py` will have broken imports after this plan — this is expected and resolved by Part B.

**Prerequisite:** None. This is the first plan in the migration-versioning series.

---

## Phases

### Phase 1: Persistence Layer Signatures

- [x] Remove `ensure_schema_version(self, code_schema_version: int) -> int` and `update_schema_version(self, version: int) -> None` from `nomarr/persistence/db.py`; add `get_version(self) -> str | None` that calls `self.meta.get("version")` and returns the result directly (no initialization logic — returns None if absent), and `set_version(self, version: str) -> None` that calls `self.meta.set("version", version)`; update the SCHEMA VERSIONING POLICY comment block to describe the new semver approach
    **Notes:** Replaced ensure_schema_version/update_schema_version with get_version(self) -> str | None and set_version(self, version: str) -> None. Updated SCHEMA VERSIONING POLICY comment block to describe semver approach. meta key changed from "schema_version" to "version".
- [x] Update `record_migration_started` in `nomarr/persistence/database/migrations_aql.py`: remove the `schema_version_before: int` and `schema_version_after: int` keyword parameters, add `migration_version: str` keyword parameter; update the `collection.insert` body to store `"migration_version": migration_version` instead of the removed int fields; update docstring accordingly
    **Notes:** Removed schema_version_before/schema_version_after params; added migration_version: str. collection.insert body updated. Docstring updated.
- [x] Remove the `record_migration` method from `MigrationOperations` (it duplicates the two-phase pattern with now-deleted int fields and is not called by any component after this rewrite); update the `get_applied_migrations` docstring to remove references to `schema_version_before` / `schema_version_after` fields
    **Notes:** Confirmed record_migration had no callers outside its definition. Removed the method entirely. Updated get_applied_migrations docstring to list migration_version instead of schema_version_before/after.
- [x] Verify `lint_project_backend` passes on `nomarr/persistence/` and fix any errors before proceeding
    **Notes:** lint_project_backend(path="nomarr/persistence/") reported 0 errors across 3 files checked. Clean.

### Phase 2: Runner Rewrite

- [x] Update `_REQUIRED_ATTRS` in `nomarr/components/platform/migration_runner_comp.py` to `("MIGRATION_VERSION", "DESCRIPTION", "upgrade")`; rewrite `_validate_migration_module` to check `MIGRATION_VERSION` is a `str` parseable by `packaging.version.Version` (catch `packaging.version.InvalidVersion`), `DESCRIPTION` is `str`, and `upgrade` is callable; remove all `SCHEMA_VERSION_BEFORE` / `SCHEMA_VERSION_AFTER` checks
    **Notes:** Updated _REQUIRED_ATTRS to ("MIGRATION_VERSION", "DESCRIPTION", "upgrade"). Rewrote _validate_migration_module to check MIGRATION_VERSION is a str parseable by packaging.version.Version (catches InvalidVersion), DESCRIPTION is str, upgrade is callable. Removed all SCHEMA_VERSION_BEFORE/SCHEMA_VERSION_AFTER checks.
- [x] Rewrite `discover_migrations` to load modules and return them sorted by `packaging.version.Version(module.MIGRATION_VERSION)` (semver order, not filename lexical order); keep the existing `MIGRATIONS_PACKAGE` / `MIGRATIONS_DIR` constants and filename glob `V*.py`
    **Notes:** discover_migrations now sorts by packaging.version.Version(module.MIGRATION_VERSION) after loading all modules. MIGRATIONS_PACKAGE / MIGRATIONS_DIR constants and V*.py glob kept unchanged.
- [x] Add `check_duplicate_versions(migrations: list[tuple[str, ModuleType]]) -> None` that collects all `MIGRATION_VERSION` values, identifies any that appear more than once, and raises `MigrationError` naming the colliding version and the conflicting migration file names; call this immediately after `discover_migrations` in the new entry point
    **Notes:** check_duplicate_versions uses collections.defaultdict to group names by MIGRATION_VERSION, raises MigrationError naming the version and all conflicting file stems. Called immediately after discover_migrations in run_pending_migrations.
- [x] Rewrite `get_pending_migrations` with signature `(all_migrations: list[tuple[str, ModuleType]], current_db_version: str | None) -> list[tuple[str, ModuleType]]`: if `current_db_version` is None return all migrations; otherwise return those where `packaging.version.Version(module.MIGRATION_VERSION) > packaging.version.Version(current_db_version)`; remove the `applied_names` parameter (applied-name tracking is gone; version comparison is the gate)
    **Notes:** get_pending_migrations now takes (all_migrations, current_db_version: str | None). Returns all migrations if current_db_version is None (fresh DB). Otherwise filters where Version(module.MIGRATION_VERSION) > Version(current_db_version). applied_names parameter removed entirely.
- [x] Rewrite `apply_migration` with signature `(name: str, module: ModuleType, db: Database) -> None`: calls `db.migrations.record_migration_started(name=name, migration_version=module.MIGRATION_VERSION, started_at=started_at)`, calls `module.upgrade(db.db)`, calls `db.migrations.mark_migration_applied(...)`, then calls `db.set_version(module.MIGRATION_VERSION)`; update log messages to use `module.MIGRATION_VERSION` string in place of int version references; remove the `migration_ops` parameter
    **Notes:** apply_migration rewritten to accept (name, module, db: Database). Calls db.migrations.record_migration_started with migration_version kwarg, module.upgrade(db.db), db.migrations.mark_migration_applied, then db.set_version(module.MIGRATION_VERSION) last. migration_ops parameter removed. Log messages use MIGRATION_VERSION string.
- [x] Add `run_pending_migrations(db: Database) -> None` as the new unified public entry point: (1) reads `current = db.get_version()`, (2) calls `discover_migrations()`, (3) calls `check_duplicate_versions(migrations)`, (4) calls `get_pending_migrations(migrations, current)`, (5) applies each pending migration via `apply_migration(name, module, db)`, (6) after all applied reads `db.get_version()` and raises `SchemaVersionMismatchError` if it is greater than `__version__` (using `packaging.version.Version` comparison); import `__version__` from `nomarr.__version__`
    **Notes:** run_pending_migrations added as unified public entry point. Reads current version, discovers migrations, checks duplicates, gets pending, applies each, then reads final_version and raises SchemaVersionMismatchError if Version(final_version) > Version(__version__). __version__ imported from nomarr.__version__. No error if final_version is None (fresh DB with no migrations).
- [x] Delete the old public functions that are no longer used: `get_current_schema_version`, `get_code_schema_version_from_files`, `validate_version_chain`, and `check_schema_version_mismatch`; note in a comment that `prepare_database_wf.py` currently imports these and will break — resolved by Part B
    **Notes:** Deleted get_current_schema_version, get_code_schema_version_from_files, validate_version_chain, and check_schema_version_mismatch. A comment block at the bottom of the file notes that prepare_database_wf.py currently imports these and will have broken imports until Part B resolves them.
- [x] Verify `lint_project_backend` passes on `nomarr/components/platform/migration_runner_comp.py` and fix any errors before completing this plan
    **Notes:** lint_project_backend(path="nomarr/components/platform/migration_runner_comp.py") reported 0 errors. Clean.

---

## Completion Criteria

- `Database.get_version()` and `Database.set_version(str)` exist; `ensure_schema_version` and `update_schema_version` are gone
- `MigrationOperations.record_migration_started` accepts `migration_version: str`; the deprecated int params are absent
- `migration_runner_comp.py` exports `run_pending_migrations(db: Database) -> None`, `discover_migrations`, `get_pending_migrations`, `apply_migration`, `check_duplicate_versions`, `MigrationError`, `MigrationChainError`, `SchemaVersionMismatchError`
- `packaging.version.Version` is used for all semver comparisons (no hand-rolled parsing)
- `lint_project_backend` reports zero errors on `nomarr/persistence/` and `nomarr/components/platform/migration_runner_comp.py`
- `prepare_database_wf.py` has broken imports (expected — resolved by Part B)

## References

- Design doc: `plans/dev/design-migration-versioning.md`
- Contracts ledger: supplied with task spec (describes all decisions)
- Part B (workflow): `TASK-migration-versioning-B-workflow.md` (not yet created)
- Part C (migration files): `TASK-migration-versioning-C-migration-files.md` (not yet created)
