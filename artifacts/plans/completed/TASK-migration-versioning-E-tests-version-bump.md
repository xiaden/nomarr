# Task: Tests & Version Bump (Migration Versioning Part E)

## Problem Statement
Plans A–D replaced the integer migration chain with a semver-based runner. This final part confirms
everything works: bump `__version__` to `"0.2.0"`, add the `packaging` runtime dependency that the
new runner relies on for semver comparison, delete or fix tests that reference removed APIs
(V016 test file, old integer-based runner signatures), and write the two new test suites — a
`code_smell` uniqueness enforcer and a unit suite for the new runner API. Finally, confirm the
full test suite passes with zero regressions.

## Phases

### Phase 1: Cleanup, Dependencies, and Version Bump
- [x] Delete `tests/unit/persistence/test_migration_v016.py` — V016 was removed by Plan D; this file will fail to import after that plan executes
- [x] Search the entire `tests/` tree for references to `SCHEMA_VERSION_BEFORE`, `SCHEMA_VERSION_AFTER`, `ensure_schema_version`, `update_schema_version`, `schema_version_before=`, `schema_version_after=`, and `record_migration_started(schema_version`; update or delete each file found so no test references the removed APIs
    **Note:** grep search confirmed zero matches for all listed patterns across tests/. No files needed updating.
- [x] Audit `MigrationChainError` usages across `nomarr/` and `tests/` using `locate_module_symbol` and `find_referencing_symbols`; if no caller remains after the runner rewrite, add a `# TODO: remove MigrationChainError — no callers` comment in `migration_runner_comp.py` (do NOT delete it yet; Part F or a follow-up cleans dead code)
    **Note:** Confirmed zero callers via grep, one definition in migration_runner_comp.py. Added TODO comment above the class definition.
- [x] Add `packaging>=24.0` to `[project.dependencies]` in `pyproject.toml` (currently absent; the new runner uses `packaging.version.Version` for semver comparison)
- [x] Bump `__version__` in `nomarr/__version__.py` from `"0.1.4"` to `"0.2.0"` and update `__version_info__` accordingly
- [x] Create `tests/unit/migrations/__init__.py` (empty) so pytest discovers the new directory
- [x] Run `lint_project_backend` with no path argument and confirm zero errors before proceeding to Phase 2
    **Note:** lint_project_backend() reported 0 errors across 20 files checked.

### Phase 2: New Tests and Full Suite Validation
- [x] Create `tests/unit/migrations/test_migration_uniqueness.py`: single test class `TestMigrationVersionUniqueness`, method `test_no_duplicate_migration_versions`, marked `@pytest.mark.code_smell`; scan `nomarr/migrations/` for `V*.py` files via `pathlib.Path.glob`, import each with `importlib.import_module`, collect `MIGRATION_VERSION` values into a list, assert `len(versions) == len(set(versions))` with a message showing which version is duplicated; no fixture needed; file-level `pytestmark = pytest.mark.code_smell`
- [x] Create `tests/unit/components/platform/test_migration_runner_comp.py` covering the new runner API from Plan A: `discover_migrations` (returns sorted list, raises `MigrationError` on invalid module), `check_duplicate_versions` (raises on duplicate `MIGRATION_VERSION`, passes on unique), `get_pending_migrations` (skips applied when `current_db_version` is set, returns all on fresh `None`), `apply_migration` (calls `module.upgrade`, calls `migration_ops.record_migration_started` with `name` and `migration_version` kwargs, calls `migration_ops.mark_migration_applied`), `run_pending_migrations` (calls `db.get_version`, calls `db.set_version` after each migration); each test method carries `@pytest.mark.unit`
- [x] Run `lint_project_backend path="tests/"` and confirm zero ruff/mypy errors on the new test files
    **Note:** lint_project_backend(path="tests/") reported 0 errors across 4 files checked.
- [x] Run `pytest -m "not container_only and not requires_database and not code_smell"` and confirm zero failures
    **Note:** 433 passed, 2 deselected (container_only), 0 failures in 8.22s.
- [x] Run `pytest -m "code_smell"` and confirm `test_no_duplicate_migration_versions` passes and no duplicates are detected in the current two-migration catalogue (`V001_baseline.py`, `V020_rename_schema_version_key.py`)
    **Note:** 2 passed, 433 deselected in 1.74s. test_no_duplicate_migration_versions PASSED — V001_baseline (0.0.0) and V020_rename_schema_version_key (0.2.0) are unique.

## Completion Criteria
- `nomarr/__version__.py` reads `"0.2.0"`
- `pyproject.toml` lists `packaging>=24.0` in `[project.dependencies]`
- `tests/unit/persistence/test_migration_v016.py` is deleted
- No test file anywhere imports or references removed APIs (`SCHEMA_VERSION_BEFORE`, `SCHEMA_VERSION_AFTER`, `ensure_schema_version`, `update_schema_version`)
- `tests/unit/migrations/test_migration_uniqueness.py` exists and passes under `pytest -m "code_smell"`
- `tests/unit/components/platform/test_migration_runner_comp.py` exists and covers the new runner API
- `pytest -m "not container_only and not requires_database and not code_smell"` exits zero
- `lint_project_backend` exits zero

## References
- Design doc: `plans/dev/design-migration-versioning.md`
- Contracts ledger: see prior plans `TASK-migration-versioning-A` through `D`
- New runner API: `nomarr/components/platform/migration_runner_comp.py` (Plan A output)
- New persistence API: `nomarr/persistence/database/migrations_aql.py` (Plan A output)
- Bridge migration: `nomarr/migrations/V020_rename_schema_version_key.py` (Plan D output)
