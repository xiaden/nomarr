# Task: Upstream Layers & ArangoDB Removal

## Problem Statement

Parts A–E of the PostgreSQL+pgvector migration created the SQLAlchemy models (A), SQL primitives (B), domain repositories (C, D), and adapted the intent facades `LibraryDb`/`MlDb`/`AppDb` to use those repositories (E). The facades now work entirely on PostgreSQL. However, the rest of the codebase still imports, references, and depends on ArangoDB code.

This plan switches the three upstream layers (services → workflows → interfaces) and the application entry point (`app.py`) to the PostgreSQL stack, then deletes every remaining ArangoDB artifact so that zero `arango` references remain anywhere under `nomarr/`.

**Scope:**
- Rewrite `nomarr/persistence/db.py` (the `Database` class) to use `pg_engine.py` + Part E facades instead of `SafeDatabase` + `*AqlOperations`
- Update 32 service files, 37 workflow files, and the interface layer to remove ArangoDB type references and docstrings
- Update `nomarr/app.py` bootstrap for PostgreSQL
- Delete ArangoDB persistence code (`aql/`, `arango_client.py`, `schema/`, `schema_types.py`, `database/*_aql*`)
  **Note:** `models/base.py` and `models/tag.py` are NOT deleted — Plan A already replaced them with SQLAlchemy 2.x declarative Base and SQLAlchemy Tag model respectively. Only ArangoDB-specific Pydantic files that have not been replaced should be deleted.
- Delete ArangoDB platform components (`arango_bootstrap_comp.py`, `arango_first_run_comp.py`)
- Delete legacy ArangoDB migration scripts (`nomarr/migrations/V*.py`)
- Remove `python-arango` dependency

**Out of scope:**
- Test suite cleanup — Part G covers test infrastructure; legacy ArangoDB test files (`tests/unit/persistence/database/test_*_aql.py`, `tests/unit/persistence/aql/`, `tests/unit/persistence/test_arango_client.py`, `tests/unit/persistence/test_db.py`) should be deleted as part of Part G or as a follow-up.

**Prerequisite:** TASK-postgresql-pgvector-migration-E (Intent Facade Adaptation) must be complete. All Part E facade signatures must be working against PostgreSQL.

## Phases

### Phase 1: PostgreSQL Core & Upstream Layer Adaptation

- [ ] Rewrite `nomarr/persistence/db.py`: replace `create_arango_client()` with `create_pg_engine()` + `async_sessionmaker()` from `pg_engine.py`; remove all 11 `*AqlOperations` instantiations and their `self.*_aql` / `self.libraries` / `self.library_files` / `self.file_states` / `self.tags` alias attributes; construct Part E facades (`LibraryDb`, `MlDb`, `AppDb`) from repository classes (Parts C/D) via `AsyncSession`; keep adapter classes (`_MigrationsAdapter`, `_MlCapacityAdapter`, `_VramPromisesAdapter`) but rebase them on `AppDb` facade methods; replace `get_version()`/`set_version()` with `AppDb.get_meta("version")` / `AppDb.upsert_meta("version", ...)`; remove `CollectionNames` import; update module docstring
  **Notes:** The `Database` class name is preserved to minimize upstream churn. It no longer creates an ArangoDB connection. The `self.library`, `self.ml`, `self.app` facade attributes remain the public API. The `self.db` (SafeDatabase) attribute is REMOVED — any code accessing `db.db` will break.
- [ ] Update `nomarr/persistence/__init__.py`: rewrite module docstring to remove ArangoDB references; keep lazy-exporting `Database` (now PG-backed) and `DuplicateKeyError`; remove references to `aql/`, `database/`, `models/`, `schema/`, `arango_client.py` from docstring
- [ ] Update `nomarr/persistence/database/__init__.py`: replace AQL package docstring with deprecation notice or redirect to repository modules, OR delete the file if all `*_aql` siblings are being removed in Phase 2 and no other modules remain in `database/`
  **Notes:** After Phase 2, `database/` will contain only `*_repo.py` files (from Parts C/D) plus `repo_dto.py`. The `__init__.py` should export repository classes if needed, or be a minimal namespace package.
- [ ] Update all 32 service files in `nomarr/services/`: replace `from nomarr.persistence.db import Database` type annotations (`db: Database`) with the appropriate type (keep `Database` import if the service receives the `Database` object from `app.py`; update to `AsyncSession` only if the service directly creates sessions); remove "ArangoDB" from all docstrings (found in `playlist_import_svc.py`, `pipeline_svc.py`, `ml_svc.py`, `cli_bootstrap_svc.py`, `file_watcher_svc.py`); verify no service accesses `db.db`, `db.libraries_aql`, `db.tags_aql`, or other removed AQL attributes directly
  **Warning:** Services pass `db` to components. If components still expect AQL attributes (e.g., `db.libraries_aql`), the service layer cannot be fully clean until components are also migrated. Verify component state before marking this step complete.
- [ ] Update all 37 workflow files in `nomarr/workflows/`: same pattern as services — update type annotations and remove ArangoDB docstring references (found in `convert_playlist_wf.py`, `prepare_database_wf.py`, `idle_promotion_vectors_wf.py`); replace `from nomarr.components.platform.arango_bootstrap_comp import (...)` in `prepare_database_wf.py` with PostgreSQL/Alembic equivalent (e.g., `alembic upgrade head` via subprocess or `run_alembic_upgrade()` helper)
  **Notes:** `idle_promotion_vectors_wf.py` line 11 references "python-arango uses HTTP connection pooling" in a comment — remove this comment.
- [ ] Update interface layer: rewrite `nomarr/interfaces/api/id_codec.py` to handle integer IDs instead of ArangoDB "collection/key" strings — `encode_id()` and `decode_id()` become pass-through or are removed entirely since integer IDs are natively URL-safe; update `EncodedId` type, `decode_path_id()`, and `encode_ids()` accordingly; update `nomarr/interfaces/api/types/library_types.py` (lines 44, 259, 261: `ArangoDB _id` → integer), `navidrome_types.py` (line 273), and `ml_types.py` (lines 30, 53: docstrings)
  **Warning:** This is a breaking API change if external clients use the "collection:key" URL format. Verify with the frontend that all ID handling uses integers. If the frontend already uses integer IDs (likely, since PG uses integers), this is a clean removal.
- [ ] Update `nomarr/app.py`: replace `from nomarr.components.platform.arango_bootstrap_comp import wait_for_arango` and `arango_first_run_comp` imports with PostgreSQL bootstrap (e.g., `wait_for_postgres()` from a new or existing PG bootstrap component, plus `alembic upgrade head`); update `validate_environment()` to check `DATABASE_URL` (or PG-specific env vars) instead of `ARANGO_HOST`; update `Database` instantiation if constructor signature changed in step P1-S1
- [ ] Audit components layer (`nomarr/components/`): `grep` for ArangoDB references across all 65+ component files. For each file, determine whether it accesses AQL attributes (`db.libraries_aql`, `db.tags_aql`, etc.) or only facade methods (`db.library`, `db.ml`, `db.app`). **V1 scope:** patch components to use the new facade API (Part E). Replace `from nomarr.persistence.schema import CollectionNames` with SQLAlchemy model class references or string table names as appropriate. Replace `from nomarr.persistence.arango_client import DatabaseLike` in `ml_vector_maintenance_comp.py` with `AsyncSession`. Remove `from nomarr.persistence.schema_types import Field` in `ml_vector_maintenance_comp.py` (line 391). **V2 follow-up:** for any components with heavy ArangoDB dependency that cannot be trivially patched, log as V2 follow-up items with file paths and specific blockers.
  **Warning:** This is the highest-risk step. Components use AQL attributes extensively. The facade APIs have different signatures (e.g., `db.libraries_aql.get_library(key)` returns dict with `_id`/`_key` vs `db.library.get_library(id)` returns `LibraryRow` DTO). Each component must be updated individually. If this step is too large, split into a separate plan and defer — but Phase 2 CANNOT proceed without completing this step.
  **Notes:** Key files with `CollectionNames` imports: `file_write_comp.py` (lines 18, 43, 47), `library_file_mutation_comp.py` (line 10), `reconciliation_comp.py` (line 16), `ml_output_stream_store_comp.py` (line 14). These construct ArangoDB document IDs like `f"{CollectionNames.LIBRARY_FILES.value}/{key}"` — replace with integer ID handling.

### Phase 2: ArangoDB Code Deletion & Dependency Cleanup

- [ ] Delete ArangoDB persistence files: remove entire directory `nomarr/persistence/aql/` (2 files: `__init__.py`, `primitives.py`); remove `nomarr/persistence/arango_client.py`; remove entire directory `nomarr/persistence/schema/` (3 files: `__init__.py`, `names.py`, `ddl.py`); remove `nomarr/persistence/schema_types.py`; remove all AQL operation files from `nomarr/persistence/database/`: `vectors_aql.py`, `scan_aql.py`, `navidrome_aql.py`, `ml_streams_aql.py`, `ml_models_aql.py`, `ml_embedding_streams_aql.py`, `libraries_aql.py`, `file_states_aql.py`, and entire sub-packages `library_files_aql/` (5 files), `tags_aql/` (6 files), `app_aql/` (5 files) including all `__pycache__` directories
- [ ] Verify SQLAlchemy models (DO NOT delete): confirm `nomarr/persistence/models/base.py` contains the SQLAlchemy 2.x declarative `Base` class (replaced by Plan A — do NOT delete); confirm `nomarr/persistence/models/tag.py` contains the SQLAlchemy `Tag` model (replaced by Plan A — do NOT delete); update `nomarr/persistence/models/__init__.py` to remove any remaining ArangoDB Pydantic exports (e.g., `ArangoDocument`, `ArangoEdge`, `SongHasTagsEdge`) — keep only SQLAlchemy model exports from Part A
  **Notes:** Plan A already replaced these files with SQLAlchemy equivalents. The original plan text listed them for deletion, but that was based on stale assumptions. Exec-worker must verify the files contain SQLAlchemy classes before proceeding.
- [ ] Delete ArangoDB platform components: remove `nomarr/components/platform/arango_bootstrap_comp.py` (278+ lines: `ensure_schema()`, `wait_for_arango()`, `_create_collections()`, etc.); remove `nomarr/components/platform/arango_first_run_comp.py` (provisioning: `create_database()`, `is_first_run()`, `write_db_config()`); update `nomarr/components/platform/__init__.py` to remove lazy exports for `ensure_schema`, `DB_NAME`, `USERNAME`, `create_database`, `is_first_run`, `write_db_config`
- [ ] Delete legacy ArangoDB migration scripts: remove all `nomarr/migrations/V*.py` files (V001 through V038); remove `nomarr/migrations/__init__.py` or replace with a stub; Alembic migrations (created in Part A) replace this system entirely
- [ ] Remove `python-arango` from `pyproject.toml` (line 36: `"python-arango>=8.0.0"`); run `uv lock` to update lockfile; remove any other ArangoDB-related dependencies if present (search for `arango` in `pyproject.toml`)
- [ ] Run verification suite: execute `ruff check nomarr/` and fix any remaining import errors; execute `mypy nomarr/` and fix type errors from removed modules; execute `import-linter` to verify no imports from deleted modules (`nomarr.persistence.aql`, `nomarr.persistence.arango_client`, `nomarr.persistence.schema`, `nomarr.persistence.schema_types`); run `aft_search` for `(?i)arango` across `nomarr/` — must return ZERO matches in production code (test files are Part G scope)
  **Notes:** If any imports from deleted modules are found, they must be fixed before this step can be marked complete. Common stragglers: `CollectionNames` references in components, `DatabaseLike` type in `ml_vector_maintenance_comp.py`, `schema_types` imports.

## Completion Criteria
- `nomarr/persistence/db.py` creates a PostgreSQL-backed `Database` using `pg_engine.py` + Part E facades — zero ArangoDB imports
- All 32 service files have no ArangoDB references in code or docstrings
- All 37 workflow files have no ArangoDB references in code or docstrings
- `nomarr/interfaces/api/id_codec.py` handles integer IDs (no "collection/key" format)
- `nomarr/app.py` bootstraps PostgreSQL (no ArangoDB first-run or wait-for logic)
- All files listed for deletion in Phase 2 are removed from disk
- `python-arango` is not in `pyproject.toml` or `uv.lock`
- `ruff check nomarr/` passes with zero errors
- `mypy nomarr/` passes with zero errors (or only pre-existing errors unrelated to this migration)
- `import-linter` passes — no banned imports from deleted ArangoDB modules
- `aft_search("(?i)arango")` across `nomarr/` returns zero matches in production code (`.py` files excluding `tests/`)

## References
- Design doc: `artifacts/designs/pending/DD-postgresql-pgvector-migration.md`
- Parts overview: `artifacts/designs/parts/postgresql-pgvector-migration/README.md`
- Contracts: `artifacts/designs/parts/postgresql-pgvector-migration/CONTRACTS.md`
- Prerequisite plan: TASK-postgresql-pgvector-migration-E (Intent Facade Adaptation)
- Related plan: TASK-postgresql-pgvector-migration-G (Testing & CI) — covers test file cleanup
