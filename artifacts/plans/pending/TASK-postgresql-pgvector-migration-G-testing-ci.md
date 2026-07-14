# Task: Testing & CI for PostgreSQL Migration

## Problem Statement

Parts C and D created SQLAlchemy repository classes (`LibraryRepository`, `FileRepository`, `TagRepository`, `VectorRepo`, `ModelRepo`, `NavidromeRepo`, etc.) that replace the ArangoDB AQL operations layer. These repositories depend on PostgreSQL-specific types (ARRAY, JSONB, halfvec, HNSW operators, pg_trgm) that cannot be approximated by SQLite or in-memory fakes.

This plan creates the test infrastructure and test suites that verify the repository layer works correctly against a real PostgreSQL instance. It also configures CI to run these tests with adequate resources for HNSW index builds.

**Scope**: Test files only (plus `tests/conftest.py` for the PG fixture and `pyproject.toml` for the new marker), CI Docker configuration, FK index CI enforcement, and legacy ArangoDB test file cleanup. No repository source files are modified.

**Prerequisites**: Parts C and D must be complete — all repository classes and their DTOs must exist.

## Phases

### Phase 1: Test Infrastructure & Repository Unit Tests

- [ ] Add session-scoped PostgreSQL fixture to `tests/conftest.py` using `testcontainers-python` (`PostgresContainer("pgvector/pgvector:pg17")`) that starts an ephemeral PG container, runs `Base.metadata.create_all(engine.sync_engine)` to create all tables, and exposes the async connection URL. Add `testcontainers[postgresql]` to dev dependencies in `pyproject.toml`.
- [ ] Add function-scoped `pg_session` fixture to `tests/conftest.py` that yields a fresh `AsyncSession` per test from the session-scoped engine, begins a transaction, and rolls back after the test completes — ensuring test isolation without re-creating tables. Use `async_sessionmaker` from Part A's `pg_engine.py`.
- [ ] Register `hnsw_build` marker in `pyproject.toml` `[tool.pytest.ini_options]` markers list with description "Heavy HNSW index build tests — skip locally with `-m 'not hnsw_build'`". Also register `requires_pg` marker for tests that need the PostgreSQL fixture.
- [ ] Create `tests/unit/persistence/test_library_repo.py` testing `LibraryRepository`: `add_library` returns int PK, `get_library` returns `LibraryRow`, `list_libraries` with `enabled_only` filter, `update_library` modifies fields, `delete_library` removes row, `remove_library` triggers FK cascade (verify child rows deleted). Test unique constraint on `(library_id, path)` via `LibraryFile` insert.
- [ ] Create `tests/unit/persistence/test_file_repo.py` testing `FileRepository`: `add_file`, `get_file_by_path`, `get_file_by_normalized_path`, `upsert_file` (insert + update paths), `upsert_files_for_library` batch, `list_files` with filters and limit, `count_files`, `remove_files` batch delete, `list_existing_file_paths`. Create `tests/unit/persistence/test_tag_repo.py` testing `TagRepository`: `create_tag`, `get_or_create_tag` idempotency, `assign_tag_to_file` with confidence/source, `get_tags_for_file`, `remove_tag_from_file`, `replace_file_tags`, `cleanup_orphaned_tags`, `get_tags_for_files_batch`.
- [ ] Create `tests/unit/persistence/test_vector_repo.py` testing `VectorRepo`: `insert_embedding` with halfvec vector, `find_nearest` returns `SimilarResult` list ordered by cosine distance, `drain_hot_to_cold` updates tier column and returns count, `get_embeddings_for_file`, `count_cold_embeddings`. Create `tests/unit/persistence/test_model_repo.py` testing `ModelRepo`: `upsert_model` with string PK, `get_enabled_models` filters by `enabled=1`, `get_by_backbone`. Create `tests/unit/persistence/test_navidrome_repo.py` testing `NavidromeRepo`: `upsert_track`, `map_track_to_file`, `get_mapped_file`, `record_play`, `resolve_file_to_nd_track`.

### Phase 2: Integration Tests & CI Configuration

- [ ] Create `tests/integration/test_cascade_delete.py` marked `@pytest.mark.integration`: Insert a library with 50,000 `LibraryFile` rows, 100 `Tag` rows with `FileTag` junction entries, 1,000 `Embedding` rows, and 50 `MlOutputStream` rows. Call `LibraryRepository.remove_library()`. Verify zero orphaned rows in `library_files`, `file_tags`, `embeddings`, `ml_output_streams`, `navidrome_track_maps` via `SELECT COUNT(*)` assertions. Assert the operation completes in a single transaction.
- [ ] Create `tests/integration/test_hnsw_recall.py` marked `@pytest.mark.integration` and `@pytest.mark.hnsw_build`: Generate 10,000 synthetic random 512-dim L2-normalized vectors with deterministic seed. Insert as cold-tier embeddings with a single backbone_id. Set `maintenance_work_mem = '2GB'` via raw SQL. Run `find_nearest` for 100 random query vectors with `ef_search=200`. Compare results against brute-force cosine distance (numpy). Assert recall ≥ 0.95 (at least 95% of brute-force top-10 appear in ANN top-10).
- [ ] Create `tests/integration/test_drain.py` marked `@pytest.mark.integration`: Insert 1,000 hot-tier embeddings for a single backbone. Call `VectorRepo.drain_hot_to_cold(backbone_id)`. Assert all 1,000 rows now have `tier = 'cold'`. Verify `count_cold_embeddings` returns 1,000. Verify `find_nearest` returns results (HNSW partial index now covers these rows). Assert drain completes in under 5 seconds.
- [ ] Create `tests/integration/test_concurrency.py` marked `@pytest.mark.integration`: Spawn 10 concurrent `asyncio.Task` instances, each inserting 100 embeddings with unique `file_id` values into the same backbone. Use `asyncio.gather`. Assert no `DeadlockDetected` errors, no `DuplicateKeyError` (all file_ids unique), and total embedding count = 1,000. Create `tests/integration/test_pg_trgm.py` marked `@pytest.mark.integration`: Insert `LibraryFile` rows with paths containing "Abbey Road", "Dark Side of the Moon", "Led Zeppelin IV". Use raw SQL `SELECT similarity(path, 'Abby Road')` and `SELECT * FROM library_files WHERE path % 'Abby Road'` (pg_trgm `%` operator). Assert similarity ≥ 0.60 for typo queries.
- [ ] Create `tests/integration/test_fk_indexes.py` marked `@pytest.mark.integration`: query PostgreSQL catalog tables (`information_schema.table_constraints` joined with `information_schema.key_column_usage` and `pg_index`) to find every FK column in the schema and verify each has a supporting B-tree index (single-column or leading-column of a composite index). Fail the test with a descriptive message listing any FK columns lacking an index (e.g., "FK column 'embeddings.file_id' has no supporting index"). This enforces the DD §6/§7 requirement that every FK column must have a supporting index to prevent FK CASCADE deadlock during `remove_library()` and other cascade operations.
- [ ] Create `docker/docker-compose.ci.yml` with a PostgreSQL service using `pgvector/pgvector:pg17` image, 6 GB RAM limit (`mem_limit: 6g`), `maintenance_work_mem = 2GB` via command override, health check using `pg_isready -U nomarr`, and environment variables matching the test fixture (`POSTGRES_USER=nomarr`, `POSTGRES_PASSWORD=nomarr`, `POSTGRES_DB=nomarr_test`). Expose port 5432 for testcontainers or CI runners.
- [ ] Run full test suite with `pytest tests/unit/persistence/ tests/integration/ -v` and verify all new tests pass. Run `pytest -m "not hnsw_build"` to verify the fast-path exclusion works. Run `pytest --collect-only` to confirm all markers are registered and no warnings appear. Verify `ruff check` and `mypy` pass on the new test files.

### Phase 3: Legacy ArangoDB Test File Cleanup

- [ ] Delete legacy ArangoDB test files: remove entire directory `tests/unit/persistence/database/` (7 test files: `test_libraries_aql.py`, `test_library_files_aql.py`, `test_library_files_crud_aql.py`, `test_tags_aql.py`, `test_ml_models_aql.py`, `test_file_states_aql.py`, `test_app_aql.py`, plus `conftest.py` with ArangoDB mock fixtures, `schema_aware_mock.py`, and `__init__.py`); remove entire directory `tests/unit/persistence/aql/` (1 test file: `test_primitives.py` plus `__init__.py`); remove `tests/unit/persistence/test_arango_client.py`; remove entire directory `tests/unit/aql_safety/` (conftest.py imports `CollectionNames` from deleted `nomarr.persistence.schema`, plus all AQL static analysis test files that validate AQL strings which no longer exist)
- [ ] Delete remaining ArangoDB-specific test files: remove `tests/unit/components/platform/test_arango_bootstrap_comp.py` (tests deleted `arango_bootstrap_comp.py`); update `tests/unit/persistence/test_db.py` to remove all tests that mock `create_arango_client` or reference `SafeDatabase` — if the file has no remaining tests after ArangoDB removal, delete it entirely (Part F rewrote `db.py` to use PostgreSQL)
- [ ] Clean up ArangoDB imports in surviving test files: remove `from arango.exceptions import DocumentInsertError` in `tests/unit/components/library/test_library_file_state_comp.py` and replace with the PostgreSQL equivalent (`from nomarr.persistence.errors import DuplicateKeyError` or the appropriate engine-agnostic exception); search `tests/` for any remaining `arango`, `ArangoDB`, `aql`, `CollectionNames`, or `SafeDatabase` references and remove or update them; verify `tests/test_architecture_qc.py` no longer references `arango_bootstrap_comp.py` (update or remove those assertions since the file was deleted in Part F)
- [ ] Run `pytest tests/ --collect-only` to verify no import errors from deleted test modules. Run `pytest tests/unit/ -v` to verify all surviving unit tests pass. Run `ruff check tests/` and `mypy tests/` to verify no lint errors from stale imports. Verify `aft_search("(?i)arango")` across `tests/` returns zero matches (or only matches in comments/docstrings that are historical context).

## Completion Criteria

- All 6 repository test files exist under `tests/unit/persistence/` and pass against ephemeral PostgreSQL
- All 6 integration test files exist under `tests/integration/` and pass (including FK index CI check)
- FK index CI check passes: every FK column in the schema has a supporting B-tree index
- `pytest -m "not hnsw_build"` runs all tests except HNSW recall in under 60 seconds locally
- HNSW recall test achieves ≥ 0.95 recall at ef_search=200 on 10K synthetic vectors
- Cascade delete test processes 50K files with zero orphaned rows
- Drain test completes in under 5 seconds for 1K embeddings
- pg_trgm similarity test achieves ≥ 0.60 for typo queries
- `docker/docker-compose.ci.yml` provides a 6 GB RAM PostgreSQL service for CI
- `pyproject.toml` has `hnsw_build` and `requires_pg` markers registered
- All legacy ArangoDB test files deleted: `tests/unit/persistence/database/`, `tests/unit/persistence/aql/`, `tests/unit/persistence/test_arango_client.py`, `tests/unit/aql_safety/`, `tests/unit/components/platform/test_arango_bootstrap_comp.py`
- Zero `arango`, `ArangoDB`, `aql`, `CollectionNames`, or `SafeDatabase` references remain in `tests/` (excluding historical comments)
- `ruff check` and `mypy` pass on all new and surviving test files with zero errors

## References

- Design doc: `artifacts/designs/pending/DD-postgresql-pgvector-migration.md` (Section 8: Testing & Acceptance Criteria)
- Parts README: `artifacts/designs/parts/postgresql-pgvector-migration/README.md`
- Contracts: `artifacts/designs/parts/postgresql-pgvector-migration/CONTRACTS.md`
- Depends on: Part C (core repos), Part D (ML/Navidrome repos)
- Sibling plans: TASK-postgresql-pgvector-migration-A through F
