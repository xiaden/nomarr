# Task: Migration File Updates — Replace SCHEMA_VERSION constants with MIGRATION_VERSION

## Problem Statement
The 16 existing migration files (V004–V019) declare two integer constants — `SCHEMA_VERSION_BEFORE` and `SCHEMA_VERSION_AFTER` — that are incompatible with the new semver-based runner introduced in Plan A. Each file must instead expose a single `MIGRATION_VERSION: str` in the form `"0.0.{SCHEMA_VERSION_AFTER}"`. A new bridge migration V020 must also be written to rename the `meta.schema_version` ArangoDB key to `meta.version`, completing the transition from integer versioning to semver.

This plan covers **only** `nomarr/migrations/`. Runner (Plan A), workflow (Plan B), consolidation (Plan D), and tests (Plan E) are out of scope.

## Phases

### Phase 1: Batch-update V004–V019 to use MIGRATION_VERSION
- [x] In each of V004–V019, remove both `SCHEMA_VERSION_BEFORE: int = N` and `SCHEMA_VERSION_AFTER: int = M` lines and insert `MIGRATION_VERSION: str = "0.0.{M}"` in their place. Leave `DESCRIPTION` and `upgrade` untouched. Exact mappings: V004→"0.0.4", V005→"0.0.5", V006→"0.0.6", V007→"0.0.7", V008→"0.0.8", V009→"0.0.9", V010→"0.0.10", V011→"0.0.11", V012→"0.0.12", V013→"0.0.13", V014→"0.0.14", V015→"0.0.15", V016→"0.0.16", V017→"0.0.17", V018→"0.0.18", V019→"0.0.19".
- [x] Run `lint_project_backend(path="nomarr/migrations")` and confirm zero errors before proceeding.

### Phase 2: Write V020 bridge migration
- [x] Create `nomarr/migrations/V020_rename_schema_version_key.py` with `MIGRATION_VERSION = "0.2.0"`, a `DESCRIPTION` string, and an `upgrade(db: DatabaseLike) -> None` that uses AQL directly (no `db.meta.*` helpers). The `upgrade` function must be idempotent: first check whether a document with `_key == "version"` already exists in the `meta` collection; if it does, return immediately (no-op). Otherwise, insert `{_key: "version", value: "0.2.0"}` into `meta`, then delete the document with `_key == "schema_version"` (if it exists). Use two separate AQL statements — one `UPSERT`/`INSERT` for the new key, one `REMOVE` for the old key — wrapped in a `try/except` that logs and ignores `DocumentDeleteError` on the remove so the function remains idempotent even if the old key is already absent.
- [x] Run `lint_project_backend(path="nomarr/migrations")` and confirm zero errors.

## Completion Criteria
- All 16 files V004–V019 expose `MIGRATION_VERSION: str` and no longer contain `SCHEMA_VERSION_BEFORE` or `SCHEMA_VERSION_AFTER`.
- `nomarr/migrations/V020_rename_schema_version_key.py` exists, exposes `MIGRATION_VERSION = "0.2.0"`, and its `upgrade()` is idempotent (safe to run on a DB that already has `meta.version`).
- `lint_project_backend` reports zero errors across `nomarr/migrations/`.

## References
- Design doc: `plans/dev/design-migration-versioning.md`
- Plan A (runner): `plans/TASK-migration-versioning-A-persistence-runner-core.md`
- Plan B (workflow): `plans/TASK-migration-versioning-B-*.md`
- Contracts ledger: see task description
