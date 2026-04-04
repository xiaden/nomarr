# Task: Migration Versioning D — Consolidation Tool Update + Run

## Problem Statement

The consolidation tool (`scripts/consolidate_migrations/consolidator.py`) generates a baseline migration file. It currently emits the old integer contract (`SCHEMA_VERSION_BEFORE: int = 0` / `SCHEMA_VERSION_AFTER: int = 1`) rather than the new semver contract (`MIGRATION_VERSION: str = "0.0.0"`). This must be fixed before the tool is run, because the output baseline (`nomarr/migrations/V001_baseline.py`) must conform to the contract established in Plans A–C.

Once the tool is patched, it is executed: the `--consolidate` flag generates the new baseline file, deletes V004–V019, and leaves V020 intact (the live bridge migration for existing DBs).

Plans A (runner), B (workflow), and C (migration file format) are complete. This plan covers only the tool patch and its execution.

## Phases

### Phase 1: Patch the Consolidation Tool

- [x] In `scripts/consolidate_migrations/consolidator.py`, locate lines 250–251 which read `SCHEMA_VERSION_BEFORE: int = 0` and `SCHEMA_VERSION_AFTER: int = 1` (inside the generated baseline template string)
- [x] Replace those two lines with the single line `MIGRATION_VERSION: str = "0.0.0"` using `edit_file_replace_string`
- [x] Run `lint_project_backend(path="scripts/consolidate_migrations")` and confirm zero errors

### Phase 2: Execute the Consolidation Tool

- [x] Activate the venv: `& D:/Github/nomarr/.venv/Scripts/Activate.ps1`
- [x] Run dry-run validation: `python -m scripts.consolidate_migrations` (no flags) and confirm the Shape A == Shape B assertion passes with no errors
- [x] Run the consolidation: `python -m scripts.consolidate_migrations --consolidate`
- [x] Confirm `nomarr/migrations/V001_baseline.py` was created and contains `MIGRATION_VERSION: str = "0.0.0"`
- [x] Confirm V004–V019 (`nomarr/migrations/V004_*.py` through `V019_*.py`) have been deleted
- [x] Confirm `nomarr/migrations/V020_rename_schema_version_key.py` still exists and was NOT deleted
- [x] Confirm `nomarr/migrations/` contains exactly `V001_baseline.py` and `V020_rename_schema_version_key.py` (and no other `V*.py` files)
- [x] Run `lint_project_backend(path="nomarr/migrations")` and confirm zero errors

## Completion Criteria

- `consolidator.py` emits `MIGRATION_VERSION: str = "0.0.0"` in the baseline template (no `SCHEMA_VERSION_BEFORE`/`SCHEMA_VERSION_AFTER`)
- `nomarr/migrations/V001_baseline.py` exists and declares `MIGRATION_VERSION: str = "0.0.0"`
- `nomarr/migrations/V020_rename_schema_version_key.py` is present and unchanged
- No `V004_*.py` through `V019_*.py` files remain in `nomarr/migrations/`
- `lint_project_backend` passes with zero errors on both `scripts/consolidate_migrations/` and `nomarr/migrations/`

## References

- Design doc: `plans/dev/design-migration-versioning.md`
- Contracts ledger: Part A plan (`plans/TASK-migration-versioning-A-persistence-runner-core.md`)
- Plan C (migration file format): `plans/TASK-migration-versioning-C-migration-file-updates.md`
- Consolidation tool: `scripts/consolidate_migrations/consolidator.py` (lines 250–251 are the patch target)
