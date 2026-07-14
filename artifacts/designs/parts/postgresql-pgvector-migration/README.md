# PostgreSQL + pgvector Migration — Implementation Parts

## Parts

| Part | Title | Depends On | Layers | Step Est. |
| --- | --- | --- | --- | --- |
| A | Infrastructure & Schema | None | persistence, docker | ~12 |
| B | SQL Core Primitives | A | persistence | ~8 |
| C | Domain Repositories — Core | A, B | persistence | ~12 |
| D | Domain Repositories — ML & Navidrome | A, B | persistence | ~10 |
| E | Intent Facade Adaptation | C, D | persistence (api/) | ~10 |
| F | Upstream Layers & ArangoDB Removal | E | persistence, services, workflows, interfaces, components | 15 |
| G | Testing & CI | C, D | tests, ci, docker | ~10 |

## Dependency Graph

```
A ──→ B ──┬──→ C ──┬──→ E ──→ F
           │         │
           └──→ D ───┤
                      │
                      └──→ G
```

## Execution Rounds

| Round | Parts | Rationale |
| --- | --- | --- |
| 1 | A | No deps — models and engine must exist first |
| 2 | B | Depends on A (engine, models) |
| 3 | C, D | Both depend on B (primitives). Parallel OK — C and D touch disjoint repo files |
| 4 | E, G | E depends on C,D (repos); G depends on C,D (tests against repos). Parallel OK |
| 5 | F | Depends on E (facades must be in place before upstream layers can switch) |

## Per-Part Scope

### Part A: Infrastructure & Schema

Establish PostgreSQL as the database engine. Replace `arangodb:3.12` Docker service with `pgvector/pgvector:pg17`. Create the SQLAlchemy 2.x declarative Base and all ORM models mapping ArangoDB collections → PostgreSQL tables (libraries, library_files, library_folders, tags, file_tags, file_states, pipeline_states, library_scans, embeddings, ml_output_streams, ml_embedding_streams, ml_models, ml_model_outputs, calibration_state, calibration_history, navidrome_tracks, navidrome_plays, navidrome_track_maps, navidrome_play_maps, plus KV tables: meta, sessions, health, worker_claims, locks, worker_restart_policy, applied_migrations, vram_promises). Write Alembic V1 baseline migration. Create `pg_engine.py` with `create_async_engine()` configured for asyncpg, sessionmaker factory, timeouts, and `pool_pre_ping=True`. Add `psycopg2` (sync, for Alembic) and `asyncpg` + `sqlalchemy[asyncio]` to Python dependencies.

**Files created/modified**: `docker/docker-compose.yml`, `nomarr/persistence/models/__init__.py`, `nomarr/persistence/models/*.py` (~15-20 model files), `alembic/` directory, `nomarr/persistence/pg_engine.py`, `pyproject.toml`

**Contracts exposed downstream**: `Base` declarative base, all SQLAlchemy model classes, `AsyncSession` factory, `create_pg_engine()`

### Part B: SQL Core Primitives

Replace `aql/primitives.py` with `sql/primitives.py`. Implement SQLAlchemy Core equivalents for: `select_by_key()`, `insert_one()`, `upsert_by_field()`, `delete_by_key()`, `get_many_by_keys()`, `batch_upsert()`. Map PostgreSQL exceptions to engine-agnostic `PersistenceError` and `DuplicateKeyError` (preserve existing exception classes). These primitives operate on model-agnostic keys/fields — same pattern as AQL primitives but expressing queries as SQLAlchemy Core expressions rather than AQL strings.

**Files created/modified**: `nomarr/persistence/sql/__init__.py`, `nomarr/persistence/sql/primitives.py`, `nomarr/persistence/sql/exceptions.py` (exception mapping)

**Contracts exposed downstream**: `select_by_key(table, key_val)`, `insert_one(table, data)`, `upsert_by_field(table, field, match_val, data)`, `delete_by_key(table, key_val)`, `get_many_by_keys(table, keys)`, `batch_upsert(table, data_list, conflict_fields)` — all taking SQLAlchemy `Table` objects and returning `Row | None` or `list[Row]`

### Part C: Domain Repositories — Core

Replace the core AQL operations packages with SQLAlchemy repository classes. Create: `LibraryRepository`, `FileRepository`, `FolderRepository`, `TagRepository` (handles tag CRUD, tag interactions, file-tag assignments), `ScanRepository`, `AppRepository` (config, sessions, worker_health, locks), `PipelineRepository`. Each repository receives an `AsyncSession` and uses Part B primitives for basic CRUD plus direct SQLAlchemy queries for domain-specific operations. The `TagRepository` must handle `file_has_tag` junction table insertions with confidence/source metadata. `FileRepository` must support `normalized_path` lookup. `FolderRepository` replaces `folder_has_folder` edges with `parent_id` self-reference.

**Target packages replaced**: `nomarr/persistence/database/libraries_aql.py`, `libraryfiles_aql.py`, `folders_aql.py`, `tags_aql/`, `app_aql.py`, `pipeline_aql.py`

**Files created**: `nomarr/persistence/database/library_repo.py`, `file_repo.py`, `folder_repo.py`, `tag_repo.py`, `scan_repo.py`, `app_repo.py`, `pipeline_repo.py`

**Contracts exposed downstream**: Repository method signatures (e.g., `FileRepository.get_by_normalized_path()`, `TagRepository.assign_tag_to_file()`, `LibraryRepository.remove_library()`)

### Part D: Domain Repositories — ML & Navidrome

Replace ML and Navidrome AQL operations packages with repository classes. Create: `VectorRepository` (embeddings table: hot/cold tier, HNSW ANN search via `<=>` operator, drain operation as `UPDATE SET tier = 'cold'`), `ModelRepository` (ML model CRUD), `OutputRepository` (model output storage), `CalibrationRepository` (calibration state/history), `NavidromeRepository` (track/play mappings). `VectorRepository` is the highest-complexity repo: handles `file_has_vectors` → FK column, per-backbone filtering via `backbone_id`, hot→cold drain, and ANN queries using pgvector's `<=>` operator with `ORDER BY` + `LIMIT`.

**Target packages replaced**: `nomarr/persistence/database/vectors_aql.py`, `ml_models_aql.py`, `ml_outputs_aql.py`, `calibration_aql.py`, `navidrome_aql.py`

**Files created**: `nomarr/persistence/database/vector_repo.py`, `model_repo.py`, `output_repo.py`, `calibration_repo.py`, `navidrome_repo.py`

**Contracts exposed downstream**: `VectorRepository.find_nearest(embedding, backbone_id, limit)`, `VectorRepository.drain_hot_to_cold(backbone_id)`, `ModelRepository.get_enabled_models()`, `NavidromeRepository.map_track_to_file()`

### Part E: Intent Facade Adaptation

Adapt the three intent facades (`LibraryDb`, `MlDb`, `AppDb`) and their `MaintenanceDb` companions to use PostgreSQL repositories instead of ArangoDB AQL operations. Internal delegation changes only — public method signatures unchanged. Each facade's `__init__` receives an `AsyncSession` and instantiates relevant repository classes. Remove all `SafeDatabase`/`SafeAQL` references. The `remove_library()` method in `LibraryMaintenanceDb` collapses from ~147 lines of AQL to `await session.execute(delete(Library).where(Library.id == lib_id))` — FK CASCADE handles the rest.

**Files modified**: `nomarr/persistence/api/library.py`, `ml.py`, `application.py`

**Contracts exposed downstream**: Unchanged public API surface. Internal: facade classes now accept `AsyncSession` instead of `SafeDatabase`.

### Part F: Upstream Layers & ArangoDB Removal

Update service, workflow, and interface layers to work with the new PostgreSQL persistence stack. Any reference to ArangoDB types (`SafeDatabase`, `ArangoClient`, `Database`) must be replaced with `AsyncSession` or SQLAlchemy types. Delete all ArangoDB code: `aql/` directory (11 files), `arango_client.py`, `schema/ddl.py`, `schema/names.py`, `schema_types.py`, Pydantic models in `models/` that are ArangoDB-specific. Remove `python-arango` from `pyproject.toml` and `uv.lock`. Remove ArangoDB Docker service. Run import-linter to verify no banned cross-layer imports.

**Files deleted**: `nomarr/persistence/aql/`, `nomarr/persistence/arango_client.py`, `nomarr/persistence/schema/`, `nomarr/persistence/schema_types.py`, select `nomarr/persistence/models/*` files, `nomarr/components/platform/arango_bootstrap_comp.py`, `nomarr/components/platform/arango_first_run_comp.py`, `nomarr/migrations/V*.py`

**Files modified**: `nomarr/persistence/db.py`, `nomarr/persistence/__init__.py`, `nomarr/persistence/database/__init__.py`, `nomarr/services/*.py`, `nomarr/workflows/*.py`, `nomarr/interfaces/api/id_codec.py`, `nomarr/interfaces/api/types/*.py`, `nomarr/app.py`, `nomarr/components/**/*.py` (65+ files), `pyproject.toml`, `docker/compose.yaml`

**Plan file:** `artifacts/plans/pending/TASK-postgresql-pgvector-migration-F-upstream-cleanup.md`

### Part G: Testing & CI

Create test infrastructure for PostgreSQL-backed repositories. Add `testcontainers-python` or Docker fixture for ephemeral PostgreSQL containers in tests. Write repository tests for all Part C/D repos: CRUD operations, cascade deletion, ANN search recall, hot/cold drain correctness, pg_trgm fuzzy search. Write integration tests: 50K-file cascade deletion, 10K-vector HNSW recall benchmark, concurrent write safety. Add `@pytest.mark.hnsw_build` marker for heavy HNSW integration tests. Update CI configuration (`docker-compose.ci.yml`, GitHub Actions) for 6 GB RAM PostgreSQL container. Update `scripts/` if `docker-compose` health checks change.

**Files created**: `tests/conftest.py` (PG fixture), `tests/persistence/*.py`, `tests/integration/*.py`, `docker/docker-compose.ci.yml`

**CI updates**: increase Docker RAM to 6 GB for integration tests, add `pgvector/pgvector:pg17` service
