# Task: Migration Versioning — Part B: Workflow Update

## Problem Statement

`prepare_database_wf.py` currently drives the entire migration lifecycle itself: it calls
`get_code_schema_version_from_files()`, `db.ensure_schema_version()`, `check_schema_version_mismatch()`,
`discover_migrations()`, `get_pending_migrations()`, `validate_version_chain()`, `apply_migration()`,
and `db.update_schema_version()`. All of those helpers were removed or consolidated in Part A.

After Part A the runner owns the full version read/compare/apply cycle through the single entry point
`run_pending_migrations(db: Database) -> None`, which raises `SchemaVersionMismatchError` if the DB
is newer than the code. The workflow must be rewritten to match: call `ensure_schema()`, call
`run_pending_migrations(db)`, catch errors, then call `register_ml_models_workflow()`.

This plan covers only `nomarr/workflows/platform/prepare_database_wf.py`.

## Phases

### Phase 1: Simplify prepare_database_wf.py

- [x] Confirm the symbols being removed are actually imported in `prepare_database_wf.py`: `get_code_schema_version_from_files`, `check_schema_version_mismatch`, `validate_version_chain`, `get_pending_migrations`, `apply_migration`, `discover_migrations`, `MigrationChainError`; and that `db.ensure_schema_version` and `db.update_schema_version` are called in the body
- [x] Replace the entire file with the simplified implementation: imports only `run_pending_migrations`, `SchemaVersionMismatchError`, `MigrationError` from `migration_runner_comp`; drops `ModuleType` and all removed symbols; body is `ensure_schema()` → `run_pending_migrations(db)` → catch `SchemaVersionMismatchError` (log critical, raise SystemExit(1)) → catch `MigrationError` (log critical, raise SystemExit(1)) → `register_ml_models_workflow()` guard
- [x] Verify the new file has no references to `get_code_schema_version_from_files`, `check_schema_version_mismatch`, `validate_version_chain`, `get_pending_migrations`, `apply_migration`, `discover_migrations`, `MigrationChainError`, `ensure_schema_version`, or `update_schema_version`
- [x] Run `lint_project_backend` on `nomarr/workflows/platform/` and confirm zero errors

## Completion Criteria

- `prepare_database_wf.py` imports only `run_pending_migrations`, `SchemaVersionMismatchError`, and `MigrationError` from `migration_runner_comp`
- The workflow body is: `ensure_schema()` → `run_pending_migrations(db)` → error handling → `register_ml_models_workflow()`
- No integer version plumbing remains (`code_schema_version`, `current_db_version`, `final_version` variables are gone)
- `lint_project_backend` reports zero errors on the workflows layer

## References

- Design doc: `plans/dev/design-migration-versioning.md`
- Prior plan: `plans/TASK-migration-versioning-A-persistence-runner-core.md`
- Contracts ledger: provided in task context
