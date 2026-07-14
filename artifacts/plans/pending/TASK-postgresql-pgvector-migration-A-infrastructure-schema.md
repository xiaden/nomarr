# Task: Infrastructure & Schema — PostgreSQL + pgvector Foundation

## Problem Statement

Nomarr's persistence layer currently uses ArangoDB 3.12 (multi-model graph database). The design document `DD-postgresql-pgvector-migration.md` mandates a hard-cut replacement with PostgreSQL 17 + pgvector 0.8.x. This plan (Part A) establishes the foundational infrastructure: Docker service, Python dependencies, SQLAlchemy 2.x ORM models mapping all 37 ArangoDB collections to PostgreSQL tables, the async engine factory, and the Alembic V1 baseline migration.

This plan has **no dependencies** — it is the root of the dependency graph. All subsequent parts (B through G) depend on the contracts established here.

**Scope:**
- Replace `arangodb:3.12` Docker service with `pgvector/pgvector:pg17`
- Add PostgreSQL Python dependencies (asyncpg, psycopg2-binary, sqlalchemy[asyncio], pgvector, alembic, testcontainers-python)
- Create SQLAlchemy declarative Base and ~20 ORM model files in `nomarr/persistence/models/`
- Create `nomarr/persistence/pg_engine.py` with async engine factory, session factory, and session generator
- Initialize Alembic with async template and generate V1 baseline migration
- Verify all models import cleanly and can create tables in ephemeral PostgreSQL

**NOT in scope:**
- Repository layer (Part B/C/D)
- Intent facade re-wiring (Part E)
- Deleting old ArangoDB code (Part F)
- Tests beyond model validation (Part G)

**Prerequisite:** None (root plan)

## Phases

### Phase 1: Docker & Dependencies

- [ ] Replace the `nomarr-arangodb` service in `docker/compose.yaml` with a `nomarr-postgres` service using image `pgvector/pgvector:pg17`, environment variables `POSTGRES_USER=nomarr`, `POSTGRES_PASSWORD=nomarr`, `POSTGRES_DB=nomarr`, port `5432:5432`, volume `pg_data:/var/lib/postgresql/data`, and healthcheck via `pg_isready -U nomarr`. Update the `nomarr` service's `depends_on` to reference `nomarr-postgres` instead of `nomarr-arangodb`. Remove the `command: ["--vector-index", "--query.memory-limit=1073741824"]` line (ArangoDB-specific).
- [ ] Create `docker/nomarr-postgres.env` with `POSTGRES_USER=nomarr`, `POSTGRES_PASSWORD=nomarr`, `POSTGRES_DB=nomarr`. Update `docker/nomarr.env` to replace `ARANGO_HOST=http://nomarr-arangodb:8529` with `DATABASE_URL=postgresql+asyncpg://nomarr:nomarr@nomarr-postgres:5432/nomarr` and `DATABASE_URL_SYNC=postgresql+psycopg2://nomarr:nomarr@nomarr-postgres:5432/nomarr`. Remove `ARANGO_ROOT_PASSWORD` lines.
- [ ] Add the following dependencies to `pyproject.toml` `[project.dependencies]`: `asyncpg>=0.30.0`, `psycopg2-binary>=2.9.10`, `sqlalchemy[asyncio]>=2.0.37`, `pgvector>=0.3.6`, `alembic>=1.14.0`. Add `testcontainers[postgres]>=4.9.0` to `[project.optional-dependencies]` `dev` group. Do NOT remove `python-arango` yet — that is Part F's responsibility.

### Phase 2: SQLAlchemy Models, Engine & Alembic

- [ ] Replace `nomarr/persistence/models/base.py` with a SQLAlchemy 2.x declarative base. Define `Base = declarative_base()` (or use `DeclarativeBase` subclass pattern). Remove the old `ArangoDocument` and `ArangoEdge` Pydantic classes. Import `HalfVector` from `pgvector.sqlalchemy` for use by the Embedding model.
  **Notes:** The old Pydantic base is removed. Any code importing `ArangoDocument` or `ArangoEdge` will break — this is expected and resolved in Part F when all ArangoDB code is deleted. The `__init__.py` lazy-import of `Database` and `DuplicateKeyError` from `nomarr.persistence` remains functional since those come from `db.py` and `exceptions.py`, not from models.

- [ ] Create core library domain model files in `nomarr/persistence/models/`: `library.py` (Library table: id int PK autoincrement, name String(255), path Text, library_type String(50), auto_tag Integer default 0, auto_curate Integer default 0, created_at BigInteger, updated_at BigInteger), `library_file.py` (LibraryFile table: id int PK, library_id FK→libraries.id ON DELETE CASCADE indexed, folder_id FK→library_folders.id ON DELETE SET NULL indexed, path Text, normalized_path Text, file_size BigInteger, modified_time BigInteger, duration_seconds Float nullable, chromaprint String(255) indexed nullable, needs_tagging Integer default 0, is_valid Integer default 0, tagged Integer default 0, calibration_hash String(255) indexed nullable, write_claimed_by String(255) indexed nullable, last_tagged_at BigInteger nullable, scanned_at BigInteger nullable, created_at BigInteger; UniqueConstraint(library_id, path), UniqueConstraint(library_id, normalized_path), composite indexes on (needs_tagging, is_valid) and (library_id, tagged)), `library_folder.py` (LibraryFolder table: id int PK, library_id FK→libraries.id ON DELETE CASCADE indexed, parent_id FK→library_folders.id ON DELETE CASCADE indexed nullable, path Text, name String(255) nullable).
  **Notes:** All FK columns must have `index=True`. All timestamps are int epoch milliseconds. Use `Mapped[]` type annotations with `mapped_column()`.

- [ ] Create tag and state model files in `nomarr/persistence/models/`: `tag.py` (Tag table: id int PK, name String(255), value String(255), namespace String(50), parent_tag_id FK→tags.id ON DELETE SET NULL indexed nullable, source String(100), confidence Float nullable, tier Integer nullable, created_at BigInteger; UniqueConstraint(name, value, namespace)), `file_tag.py` (FileTag junction table: id int PK, file_id FK→library_files.id ON DELETE CASCADE indexed, tag_id FK→tags.id ON DELETE CASCADE indexed, confidence Float default 1.0, source String(100), created_at BigInteger; UniqueConstraint(file_id, tag_id)), `file_state.py` (FileState table: id int PK, name String(100) unique, description Text nullable), `file_state_assignment.py` (FileStateAssignment junction table: id int PK, file_id FK→library_files.id ON DELETE CASCADE indexed, state_id FK→file_states.id ON DELETE CASCADE indexed, created_at BigInteger; UniqueConstraint(file_id, state_id)), `pipeline_state.py` (PipelineState table: id int PK, library_id FK→libraries.id ON DELETE CASCADE indexed, state_key String(100), state_data JSONB, updated_at BigInteger; UniqueConstraint(library_id, state_key)), `library_scan.py` (LibraryScan table: id int PK, library_id FK→libraries.id ON DELETE CASCADE indexed, scan_type String(50), status String(50), started_at BigInteger, finished_at BigInteger nullable, files_found Integer default 0, files_processed Integer default 0, error Text nullable).

- [ ] Create `nomarr/persistence/models/embedding.py` with the Embedding model — the most critical model in the schema. Fields: id int PK autoincrement, file_id FK→library_files.id ON DELETE CASCADE indexed, backbone_id String(100) indexed, model_id String(255) indexed nullable (transition field — backbone_id already identifies the model; kept nullable for migration flexibility, to be dropped in a future cleanup), embed_dim Integer nullable=False, model_suite_hash String(255) nullable=False, num_segments Integer nullable, segmentation_hash String(255) nullable, embedding HalfVector (using `pgvector.sqlalchemy.HalfVector`), genres ARRAY(String) nullable, tier String(10) default "hot", created_at BigInteger, updated_at BigInteger. Table args: UniqueConstraint(file_id, backbone_id), Index("ix_embeddings_backbone_tier", "backbone_id", "tier"), and the partial HNSW index: `Index("ix_embeddings_cold_hnsw", "embedding", postgresql_using="hnsw", postgresql_with={"m": "16", "ef_construction": "200"}, postgresql_ops={"embedding": "halfvec_cosine_ops"}, postgresql_where=text("tier = 'cold'"))`. Import `text` from `sqlalchemy`.
  **Warning:** The partial HNSW index requires the pgvector extension to be enabled. The Alembic migration must run `CREATE EXTENSION IF NOT EXISTS vector` before creating this index. The `HalfVector` type from `pgvector.sqlalchemy` must be used (not `VECTOR`) for half-precision storage. Note: `vector_type` was removed from the model — it is not in the DD or the EmbeddingRecord DTO. The `model_id` column is a nullable transition field (backbone_id is the canonical model identifier).

- [ ] Create ML domain model files in `nomarr/persistence/models/`: `ml_model.py` (MlModel table: id String(255) PK — model name as natural key, model_type String(100), backbone_id String(100), enabled Integer default 1, created_at BigInteger, updated_at BigInteger indexed), `ml_output_stream.py` (MlOutputStream table: id int PK, file_id FK→library_files.id ON DELETE CASCADE indexed, model_id FK→ml_models.id ON DELETE CASCADE indexed, status String(50), created_at BigInteger), `ml_embedding_stream.py` (MlEmbeddingStream table: id int PK, file_id FK→library_files.id ON DELETE CASCADE indexed, backbone_id String(100) indexed, patches_emb LargeBinary, created_at BigInteger), `ml_model_output.py` (MlModelOutput table: id int PK, file_id FK→library_files.id ON DELETE CASCADE indexed, model_id FK→ml_models.id ON DELETE CASCADE indexed, output_data JSONB, created_at BigInteger).
  **Notes:** MlModel uses a string PK (model name as natural key). All `model_id` FK columns point to `ml_models.id` (String type). This is intentional — model names are stable identifiers.

- [ ] Create calibration and Navidrome model files in `nomarr/persistence/models/`: `calibration_state.py` (CalibrationState table: id int PK, model_id FK→ml_models.id ON DELETE CASCADE indexed, state_data JSONB, updated_at BigInteger indexed), `calibration_history.py` (CalibrationHistory table: id int PK, model_id FK→ml_models.id ON DELETE CASCADE indexed, event String(255), data JSONB, created_at BigInteger), `navidrome_track.py` (NavidromeTrack table: id Text PK — Navidrome ID, title Text, artist Text, album Text, file_path Text indexed, created_at BigInteger), `navidrome_track_map.py` (NavidromeTrackMap junction table: navidrome_track_id FK→navidrome_tracks.id ON DELETE CASCADE part of composite PK, file_id FK→library_files.id ON DELETE CASCADE indexed, created_at BigInteger), `navidrome_play.py` (NavidromePlay table: id int PK autoincrement, navidrome_track_id FK→navidrome_tracks.id ON DELETE CASCADE indexed, played_at BigInteger indexed, user_id String(255) nullable), `navidrome_play_map.py` (NavidromePlayMap junction table: play_id FK→navidrome_plays.id ON DELETE CASCADE part of composite PK, file_id FK→library_files.id ON DELETE CASCADE indexed).

- [ ] Create KV/infrastructure model files in `nomarr/persistence/models/`: `meta.py` (Meta table: key String(255) PK, value JSONB), `session.py` (Session table: id String(255) PK, data JSONB, expires_at BigInteger indexed), `health.py` (Health table: id int PK autoincrement, worker_id String(255) indexed, status String(50), last_seen BigInteger), `worker_claim.py` (WorkerClaim table: id int PK autoincrement, worker_id String(255) indexed, key String(255), value JSONB, claimed_at BigInteger indexed), `lock.py` (Lock table: key Text PK, value JSONB), `worker_restart_policy.py` (WorkerRestartPolicy table: id int PK autoincrement, component_id String(255) indexed, policy_data JSONB), `applied_migration.py` (AppliedMigration table: name String(255) PK, status String(50), migration_version String(50), started_at BigInteger, applied_at BigInteger nullable, duration_ms BigInteger nullable), `vram_promise.py` (VramPromise table: id int PK autoincrement, worker_id String(255) indexed, pid Integer, model_path Text, promised_mb Float, total_mb Float, used_mb Float).

- [ ] Update `nomarr/persistence/models/__init__.py` to import and export all new SQLAlchemy model classes from the new model files. Remove the old imports of `ArangoDocument`, `ArangoEdge`, `SongHasTagsEdge`, and the old Pydantic `Tag`. Create `nomarr/persistence/pg_engine.py` with three functions: `create_pg_engine(database_url: str) -> AsyncEngine` (pool_size=5, max_overflow=10, pool_pre_ping=True, connect_args with statement_timeout=30000 and command_timeout=30), `async_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]` (expire_on_commit=False), and `get_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]` (async generator yielding sessions with `asyncio.shield()` on close).
  **Notes:** The `get_session` function must use `asyncio.shield()` when closing the session to prevent connection leaks under `CancelledError`. Import `AsyncEngine`, `AsyncSession`, `async_sessionmaker`, `create_async_engine` from `sqlalchemy.ext.asyncio`.

- [ ] Initialize Alembic: create `alembic.ini` at project root with `sqlalchemy.url = postgresql+psycopg2://nomarr:nomarr@localhost:5432/nomarr` (sync URL for migrations). Create `alembic/` directory with `env.py` configured for async operation using `run_async_migrations()` pattern — import `Base.metadata` from `nomarr.persistence.models` for `target_metadata`. Create `alembic/versions/` directory. Generate V1 baseline migration via `alembic revision --autogenerate -m "V1 baseline schema"` — this must create ALL tables, all indexes (including the partial HNSW index on embeddings), all FK constraints, and all unique constraints. The migration must include `CREATE EXTENSION IF NOT EXISTS vector` and `CREATE EXTENSION IF NOT EXISTS pg_trgm` at the top (both extensions are required — pgvector for halfvec/HNSW, pg_trgm for trigram GIN indexes on path and tag name per DD §7). Immediately before the HNSW index creation statement, the migration must include `SET maintenance_work_mem = '2GB'` — without this, the index build uses PostgreSQL's 64MB default and silently falls back to disk-based builds that are 10–50× slower (DD §7, risk R-014). After the index build, reset with `RESET maintenance_work_mem`. Verify: run `ruff check nomarr/persistence/models/ nomarr/persistence/pg_engine.py alembic/`, run `mypy nomarr/persistence/models/ nomarr/persistence/pg_engine.py`, then verify all models can be imported (`python -c "from nomarr.persistence.models import Base, Library, LibraryFile, Embedding, MlModel"`) and that `Base.metadata.create_all()` succeeds against an ephemeral PostgreSQL instance (use testcontainers or the Docker PG service).

## Completion Criteria

- Docker Compose starts `pgvector/pgvector:pg17` container with healthcheck passing via `pg_isready`
- `pyproject.toml` includes asyncpg, psycopg2-binary, sqlalchemy[asyncio]>=2.0.37, pgvector, alembic in dependencies and testcontainers[postgres] in dev dependencies
- All ~20 SQLAlchemy model files exist in `nomarr/persistence/models/` and import without errors
- Every FK column has `index=True` and `ondelete="CASCADE"` (or `SET NULL` where specified)
- The Embedding model has fields: embed_dim (int, not null), model_suite_hash (str, not null), num_segments (int, nullable), segmentation_hash (str, nullable), model_id (str, nullable — transition field), and NO vector_type column
- The Embedding model has a partial HNSW index with `postgresql_where=text("tier = 'cold'")` and `postgresql_ops={"embedding": "halfvec_cosine_ops"}`
- MlModel uses String(255) primary key (natural key pattern)
- `nomarr/persistence/pg_engine.py` exports `create_pg_engine`, `async_session_factory`, `get_session` with correct signatures
- Alembic V1 baseline migration exists in `alembic/versions/` and creates all tables, indexes, constraints, the pgvector extension, and the pg_trgm extension; sets `maintenance_work_mem = '2GB'` before HNSW index creation
- `ruff check` passes on all new files with zero errors
- `mypy` passes on all new files with zero errors
- All models can be imported: `from nomarr.persistence.models import Base, Library, LibraryFile, Embedding, MlModel, Tag, FileTag` succeeds
- `Base.metadata.create_all()` succeeds against ephemeral PostgreSQL (verified via testcontainers or Docker PG)

## References

- Design doc: `artifacts/designs/pending/DD-postgresql-pgvector-migration.md`
- Parts breakdown: `artifacts/designs/parts/postgresql-pgvector-migration/README.md`
- Contracts ledger: `artifacts/designs/parts/postgresql-pgvector-migration/CONTRACTS.md`
- Current Docker compose: `docker/compose.yaml`
- Current env files: `docker/nomarr.env`, `docker/nomarr-arangodb.env`
- Current persistence structure: `nomarr/persistence/` (db.py, arango_client.py, exceptions.py, models/, schema/)
- Current models: `nomarr/persistence/models/base.py` (ArangoDocument, ArangoEdge — to be replaced), `nomarr/persistence/models/tag.py` (Pydantic Tag — to be replaced)
- Dependency file: `pyproject.toml` (setuptools-based, python-arango>=8.0.0 in dependencies)
- Existing exceptions: `nomarr/persistence/exceptions.py` (PersistenceError, DuplicateKeyError — preserved as-is)

## Contracts Exposed Downstream

These contracts are created by this plan and consumed by Parts B through G:

| Contract | Module | Details |
| --- | --- | --- |
| `Base` | `nomarr.persistence.models.base` | SQLAlchemy declarative base class |
| All model classes | `nomarr.persistence.models` | Library, LibraryFile, LibraryFolder, Tag, FileTag, FileState, FileStateAssignment, PipelineState, LibraryScan, Embedding, MlModel, MlOutputStream, MlEmbeddingStream, MlModelOutput, CalibrationState, CalibrationHistory, NavidromeTrack, NavidromeTrackMap, NavidromePlay, NavidromePlayMap, Meta, Session, Health, WorkerClaim, Lock, WorkerRestartPolicy, AppliedMigration, VramPromise |
| `create_pg_engine(database_url: str) -> AsyncEngine` | `nomarr.persistence.pg_engine` | pool_size=5, max_overflow=10, pool_pre_ping=True, statement/command timeouts |
| `async_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]` | `nomarr.persistence.pg_engine` | expire_on_commit=False |
| `get_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]` | `nomarr.persistence.pg_engine` | async generator with asyncio.shield on close |
