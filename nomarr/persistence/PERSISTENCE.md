# Persistence Layer

The **persistence layer** owns PostgreSQL access for Nomarr.

This package is organized around a top-level `Database` facade in `db.py`, a private Tier 2 repository layer under `database/`, a narrow Tier 1 SQL primitive layer under `sql/`, and higher-level intent facades under `api/`.

> **Access rule:** Higher layers should depend on the injected `Database` facade. Reach for `db.library`, `db.app`, and `db.ml`. Tier 2 (`database/`) and Tier 1 (`sql/`) are persistence-internal layers, not caller APIs.

---

## 1. Position in the architecture

```text
interfaces → services → workflows → components → (persistence / helpers)
```

Persistence sits at the bottom of the dependency graph:

- **Components** may call persistence directly
- **Persistence** may use helpers and low-level SQL utilities
- **Persistence never imports** components, workflows, services, or interfaces
- **Persistence returns raw documents and query results**; higher layers decide how to map or interpret them

Persistence is responsible for data access, not orchestration or business policy.

---

## 2. Current package layout

```text
persistence/
├── __init__.py                  # Re-exports Database lazily
├── PERSISTENCE.md               # This guide
├── db.py                        # Top-level Database facade and sub-facade wiring
├── pg_engine.py                 # PostgreSQL async engine, session factory, session generator
├── exceptions.py                # Domain exceptions (DuplicateKeyError, PersistenceError)
├── api/
│   ├── __init__.py
│   ├── application.py           # AppDb intent facade
│   ├── library.py               # LibraryDb intent facade
│   └── ml.py                    # MlDb intent facade
├── sql/
│   ├── __init__.py
│   ├── primitives.py            # Shared SQL Core primitive functions
│   └── exceptions.py            # SQLAlchemy error mapping
├── database/
│   ├── __init__.py
│   ├── repo_helpers.py          # Shared repository utilities
│   ├── app_repo.py              # Application data operations (locks, sessions, worker claims, VRAM)
│   ├── calibration_repo.py      # Calibration state and history
│   ├── embedding_stream_repo.py # Embedding stream operations
│   ├── file_repo.py             # Library file CRUD
│   ├── file_state_repo.py       # File state and assignment operations
│   ├── file_tag_repo.py         # File–tag relationship operations
│   ├── folder_repo.py           # Folder CRUD
│   ├── library_repo.py          # Library record CRUD
│   ├── model_repo.py            # ML model and output labeling
│   ├── navidrome_repo.py        # Navidrome mapping and playcount operations
│   ├── output_repo.py           # ML output stream persistence
│   ├── pipeline_repo.py         # Pipeline state operations
│   ├── scan_repo.py             # Library scan record operations
│   ├── tag_repo.py              # Tag CRUD and search
│   └── vector_repo.py           # Vector/embedding persistence and similarity search
└── models/
    ├── __init__.py
    ├── base.py                  # SQLAlchemy declarative base
    ├── library.py               # Library table
    ├── library_file.py          # Library file table
    ├── library_folder.py        # Library folder table
    ├── file_state.py            # File state table
    ├── file_state_assignment.py # File state assignment table
    ├── file_tag.py              # File–tag join table
    ├── tag.py                   # Tag table
    ├── library_scan.py          # Library scan table
    ├── ...                      # +20 additional ORM models (vectors, ML, Navidrome, health, etc.)
```

### What changed from the old docs

If you see references to `collections.py`, `collections_base.py`, `accessors.py`, or `constructor/` in persistence documentation, those references are stale. The live implementation uses:

- `api/` for intent-level facades
- `database/` for thin table/relationship repository classes
- `sql/primitives.py` for shared reusable SQL Core helpers
- `models/` for SQLAlchemy ORM table definitions

---

## 3. The `Database` facade

`db.py` defines the top-level `Database` class. It is the main entry point for the rest of the backend.

`Database.__init__()` currently does four things:

1. Accepts a PostgreSQL connection URL and pool configuration
2. Creates an async SQLAlchemy engine and session factory via `pg_engine.py`
3. Instantiates all repository objects in `database/`
4. Wires those repositories into intent-level sub-facades in `api/`

The facade exposes three layers of access.

### Preferred: intent-level sub-facades

These are the cleanest entry points for higher layers:

- `db.library` → `LibraryDb`
- `db.app` → `AppDb`
- `db.ml` → `MlDb`

These group related persistence actions by domain rather than by physical table.

### Compatibility-only: adapters

`Database` exposes lightweight adapter wrappers as intentional compatibility debt during the current migration window:

- `db.migrations` → `_MigrationsAdapter` (migration lifecycle tracking)
- `db.ml_capacity` → `_MlCapacityAdapter` (distributed lock management)
- `db.vram_promises` → `_VramPromisesAdapter` (VRAM promise management)

These adapters wrap async `AppDb` methods and provide sync-compatible interfaces for legacy callers. New higher-layer code should not depend on them; use `db.app` or a direct repository reference instead.

### Lowest-level implementation names

The repository instances are constructed internally and wired into the sub-facades. Components and higher layers access data through the intent facades, not through raw repository methods unless a maintenance/bootstrap seam requires it.

---

## 4. The three public sub-facades

### `db.library`

`LibraryDb` in `api/library.py` is the domain facade for library-facing persistence.

It wraps operations such as:

- library CRUD and library-domain queries
- file and folder queries plus intent-level file lifecycle operations
- tag lookup, replacement, aggregation, and cleanup routed through library-domain methods
- maintenance-only routines on `db.library.maintenance` (orphan cleanup, destructive resets, diagnostics)

Use `db.library` when the caller thinks in terms of libraries, files, folders, and tags rather than specific database tables.

### `db.app`

`AppDb` in `api/application.py` groups application-state persistence.

It wraps operations such as:

- file state reads and state-oriented intents
- scan and pipeline-state persistence hidden behind app-domain methods
- locks, claims, health, migration/config, and VRAM promise persistence
- maintenance-only routines on `db.app.maintenance` (truncation, resets, diagnostics)
- legacy Navidrome persistence isolated as compatibility debt, not future public contract

Use `db.app` for coordination data and operational state rather than music-library content.

### `db.ml`

`MlDb` in `api/ml.py` groups ML-related persistence.

It wraps operations such as:

- ML output stream, vector, model, model-output, and calibration intents
- runtime vector-collection registration/query surfaces routed through ML-domain methods
- maintenance-only routines on `db.ml.maintenance` (truncation, resets, diagnostics)

Use `db.ml` when the caller works with embeddings, models, output streams, or calibration artifacts.

---

## 5. The lower layer: repository classes

The `database/` package holds the thin repository bindings that actually talk to PostgreSQL.

Examples include:

- `AppRepository`
- `LibraryRepository`
- `FileRepository`
- `FolderRepository`
- `TagRepository`
- `FileTagRepository`
- `FileStateRepository`
- `ScanRepository`
- `PipelineRepository`
- `NavidromeRepo`
- `VectorRepo`
- `ModelRepo`
- `OutputRepo`
- `CalibrationRepo`
- `EmbeddingStreamRepository`

These classes are intentionally narrow. They are not business services; they are focused table/relationship adapters over SQLAlchemy's `AsyncSession`.

They sit below the intent facades and above the generic SQL Core helper functions. They are private to persistence and should not be imported by higher layers.

---

## 6. Shared SQL helpers

The reusable query helpers live in `sql/primitives.py`.

That module currently provides helpers such as:

- `select_by_key(table, key_val, *, session)` — fetch a single row by key
- `select_many_by_keys(table, keys, *, session)` — fetch multiple rows by key list
- `insert_one(table, data, *, session)` — insert a single row with RETURNING
- `upsert_by_field(table, field, match_val, data, *, session)` — insert-or-update via PostgreSQL ON CONFLICT
- `update_by_field(table, field, match_val, data, *, session)` — update and return the row
- `delete_by_key(table, key_val, *, session)` — delete a single row
- `batch_upsert(table, data_list, conflict_fields, *, session)` — batch insert-or-update
- `is_table_empty(table, *, session)` — check whether a table has zero rows

### Tier 1 safety rules

When adding or modifying helpers in `sql/primitives.py`, contributors must follow these architectural requirements:

1. **All data values flow through SQLAlchemy parameter binding** — never interpolate user-supplied values directly into SQL text.
2. **Use SQLAlchemy Core `Table.c` column references** for structural elements; avoid string-based column interpolation where possible.
3. **Error mapping discipline** — all SQLAlchemy exceptions are mapped through `map_sqlalchemy_error()` in `sql/exceptions.py` so callers see storage-agnostic `PersistenceError` subtypes.

Use these helpers when several repository classes need the same safe query-building pattern. Keep table-specific and domain-specific intent in the `database/` modules; do not grow `primitives.py` into a generic query framework.

---

## 7. Safe database access

`pg_engine.py` provides the PostgreSQL connection infrastructure:

- `create_pg_engine(database_url)` — creates an async SQLAlchemy engine with connection pooling, pre-ping, and statement timeout
- `async_session_factory(engine)` — creates an `async_sessionmaker` bound to the engine
- `get_session(session_factory)` — async generator that yields an `AsyncSession` with automatic cleanup (uses `asyncio.shield` to prevent connection leaks under `CancelledError`)

This means:

- The engine is configured with `pool_pre_ping=True` (validates connections before use), `pool_size=5`, and `max_overflow=10`
- Statement timeouts are enforced at the database level (30 seconds)
- Sessions use `expire_on_commit=False` to avoid detached-instance errors outside of active session scopes
- Callers should work through repository classes and `sql/primitives.py` rather than issuing raw SQL

### Escape hatch: raw SQL

For advanced queries or DDL work that repositories do not yet wrap, callers can use `AsyncSession.execute(text("..."))` directly:

```python
from sqlalchemy import text

result = await session.execute(text("SELECT version()"))
```

This is the escape hatch — prefer intent facades and repository methods for routine work.

---

## 8. ORM models

The `models/` package contains SQLAlchemy ORM models for every database table.

Key points:

- `models/base.py` defines the shared `Base` declarative base
- Each model file corresponds to one database table (e.g., `library.py` → `libraries` table, `tag.py` → `tags` table)
- All models use standard PostgreSQL column types (integer primary keys, `UUID`, `JSONB`, `TEXT`, `TIMESTAMPTZ`, etc.)
- Vector/embedding data is stored in dedicated tables with PostgreSQL-compatible types

### Dynamic vector registration

Vector collections are registered at runtime through the ML layer:

```python
db.ml.add_vector_collection(
    "vectors_track_hot__demo_model__main",
    "vectors_track_hot",
)
```

That registration returns a runtime vector namespace that can then be used for vector persistence and similarity search.

---

## 9. Recommended calling patterns

Prefer intent-level calls from higher layers:

```python
library = db.library.get_library(library_id)
files = db.library.list_library_files(library_id, limit=100)
db.app.transition_file_states(file_ids, "queued", "processing")
streams = db.ml.list_output_streams_for_file(file_id)
```

Within higher layers, do **not** drop to raw SQL just because the session is available:

```python
file_doc = db.library.get_file(file_id)
db.library.replace_file_tags(file_id, [{"name": "genre", "value": "rock"}])
db.app.update_scan(library_id, {"status": "complete"})
```

Use raw SQL access only for capabilities that are not already wrapped:

```python
result = await session.execute(text("SELECT version()"))
```

The rule of thumb is simple:

- **Domain intent first** → `db.library`, `db.app`, `db.ml`
- **Persistence internals second** → repository classes inside `nomarr.persistence`
- **Raw SQL last** → `session.execute(text(...))`

---

## 10. Extension guidelines

When changing persistence behavior, work from the right layer downward.

### If the caller needs a new domain operation

1. Add or extend a method on `LibraryDb`, `AppDb`, or `MlDb`
2. Delegate to one or more existing repository classes where possible
3. Keep orchestration light; this layer should still be data access focused

### If the caller needs a new table or query capability

1. Add or extend the relevant repository class in `database/`
2. Reuse helpers from `sql/primitives.py` when they fit
3. Add a new shared primitive only when the pattern is genuinely reusable

### If the schema changes

1. Add the forward-only migration under `nomarr/migrations/`
2. Do not patch old baselines in place
3. Update any affected persistence APIs and their callers together

---

## 11. What this layer is not

Persistence should **not**:

- make business decisions
- import services, workflows, components, or interfaces
- hide database-native identifier fields behind renamed abstractions
- turn into a workflow layer just because a query touches several tables

If code starts deciding *what should happen* instead of *how data is read or written*, it probably belongs above persistence.

---

## 12. Mental model

Think about the current persistence layer like this:

- **`db.py` wires the world together** — engine, session factory, repos, sub-facades
- **`api/` presents the only supported caller-facing persistence API**
- **`database/` holds private Tier 2 table and relationship repositories**
- **`sql/primitives.py` provides the narrow private Tier 1 SQL Core toolbox**
- **`pg_engine.py` manages the async PostgreSQL connection lifecycle**
- **`models/` defines the SQLAlchemy ORM table schema**
- **`session.execute(text(...))` is the escape hatch for advanced raw SQL work**

If you encounter docs that describe a descriptor-driven collection facade with `collections_base.py` and `FieldAccessor`, those docs are describing an older design, not the implementation that exists in this branch.
