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
- **Persistence returns raw rows and query results**; higher layers decide how to map or interpret them

Persistence is responsible for data access, not orchestration or business policy.

---

## 2. Current package layout

```text
persistence/
├── __init__.py                  # Re-exports Database lazily
├── PERSISTENCE.md               # This guide
├── db.py                        # Top-level Database facade and sub-facade wiring
├── pg_engine.py                 # PostgreSQL engine, session factory, scoped session
├── exceptions.py                # Deprecated PersistenceError/DuplicateKeyError (use nomarr/helpers/exceptions.py domain exceptions)
├── api/
│   ├── __init__.py
│   ├── application.py           # AppDb intent facade
│   ├── library.py               # LibraryDb intent facade (thin forwarder)
│   ├── library_regions.py       # LibraryRegionsDb sub-facade
│   ├── library_scans.py         # LibraryScansDb sub-facade
│   ├── library_songs.py         # LibrarySongsDb sub-facade
│   ├── library_tags.py          # LibraryTagsDb sub-facade
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
│   ├── embedding_stream_repo.py  # Embedding stream operations
│   ├── song_repo.py             # Library song CRUD
│   ├── song_state_repo.py       # Song state and assignment operations
│   ├── song_tag_repo.py         # Song–tag relationship operations
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
    ├── library_folder.py        # Library folder table
    ├── library_scan.py          # Library scan table
    ├── song.py                  # Song table
    ├── song_state.py            # Song state table
    ├── song_state_assignment.py # Song state assignment table
    ├── song_tag.py              # Song–tag join table
    ├── tag.py                   # Tag table
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
2. Creates a SQLAlchemy engine and thread-local scoped session via `pg_engine.py`
3. Instantiates all repository objects in `database/`
4. Wires those repositories into intent-level sub-facades in `api/`

The facade exposes three layers of access.

### Preferred: intent-level sub-facades

These are the cleanest entry points for higher layers:

- `db.library` → `LibraryDb`
- `db.app` → `AppDb`
- `db.ml` → `MlDb`

These group related persistence actions by domain rather than by physical table.

### Lowest-level implementation names

The repository instances are constructed internally and wired into the sub-facades. Components and higher layers access data through the intent facades, not through raw repository methods unless a maintenance/bootstrap seam requires it.

---

## 4. The three public sub-facades

### `db.library`

`LibraryDb` in `api/library.py` is a thin namespaced forwarder over four sub-facades — `library_songs`, `library_tags`, `library_scans`, and `library_regions` (exposed as `db.library.songs`, `db.library.tags`, `db.library.scans`, `db.library.regions`) — exposing the library-facing persistence surface.

It wraps operations such as:

- library CRUD and library-domain queries
- song and folder queries plus intent-level song lifecycle operations
- tag lookup, replacement, aggregation, and cleanup routed through library-domain methods
- maintenance-only routines (orphan cleanup, destructive resets) are flat on the facade: `db.library.list_orphaned_song_ids()`, `db.library.list_orphaned_tag_ids()`, `db.library.delete_tags_by_ids(...)`, `db.library.truncate_songs()`, `db.library.truncate_song_links()`, `db.library.truncate_folder_links()`, `db.library.truncate_folders()`, `db.library.truncate_tags()`, `db.library.truncate_song_tag_edges()`, `db.library.truncate_scan_records()`

Use `db.library` when the caller thinks in terms of libraries, songs, folders, and tags rather than specific database tables.

### `db.app`

`AppDb` in `api/application.py` groups application-state persistence.

It wraps operations such as:

- song state reads and state-oriented intents
- scan and pipeline-state persistence hidden behind app-domain methods
- locks, claims, health, migration/config, and VRAM promise persistence
- maintenance-only routines on `db.app` (truncation, resets): `db.app.truncate_song_state_edges()`, `db.app.truncate_worker_claims()`, `db.app.truncate_health()`
- legacy Navidrome persistence isolated as compatibility debt, not future public contract

Use `db.app` for coordination data and operational state rather than music-library content.

### `db.ml`

`MlDb` in `api/ml.py` groups ML-related persistence.

It wraps operations such as:

- ML output stream, vector, model, model-output, and calibration intents
- runtime vector-collection registration/query surfaces routed through ML-domain methods
- maintenance-only routines on `db.ml` (truncation, resets): `db.ml.truncate_vectors_in_collection(...)`, `db.ml.truncate_calibration_states()`, `db.ml.truncate_calibration_history()`

Use `db.ml` when the caller works with embeddings, models, output streams, or calibration artifacts.

---

## 5. The lower layer: repository classes

The `database/` package holds the thin repository bindings that actually talk to PostgreSQL.

Examples include:

- `AppRepository`
- `LibraryRepository`
- `SongRepository`
- `FolderRepository`
- `TagRepository`
- `SongTagRepository`
- `SongStateRepository`
- `ScanRepository`
- `PipelineRepository`
- `NavidromeRepo`
- `VectorRepo`
- `ModelRepo`
- `OutputRepo`
- `CalibrationRepo`
- `EmbeddingStreamRepository`

These classes are intentionally narrow. They are not business services; they are focused table/relationship adapters that receive a thread-local `scoped_session` proxy. Each repo's session parameter is a `scoped_session` that resolves to the current thread's `Session` at query time.

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
3. **Error mapping discipline** — SQLAlchemy exceptions raised by Tier 1 primitives are translated at the Tier 2 repository boundary via `map_persistence_exceptions()` in `sql/exceptions.py` into the four domain exceptions in `nomarr/helpers/exceptions.py`: `EntityNotFoundError`, `DuplicateEntityError`, `ReferentialIntegrityError`, and `DatabaseStateError`. Raw SQLAlchemy exceptions propagate out of Tier 1 primitives and are only mapped at the Tier 2 repo boundary.

Use these helpers when several repository classes need the same safe query-building pattern. Keep table-specific and domain-specific intent in the `database/` modules; do not grow `primitives.py` into a generic query framework.

---

## 7. Safe database access

`pg_engine.py` provides the PostgreSQL connection infrastructure:

- `create_pg_engine(database_url)` — creates a SQLAlchemy engine with connection pooling, pre-ping, and statement timeout
- `session_factory(engine)` — creates a `sessionmaker[Session]` bound to the engine
- `get_session(session_factory)` — context manager that yields a `Session` with automatic cleanup (uses `try/finally` for commit/rollback and close)

This means:

- The engine is configured with `pool_pre_ping=True` (validates connections before use), `pool_size=5`, and `max_overflow=10`
- Statement timeouts are enforced at the database level (30 seconds)
- Sessions use `expire_on_commit=False` to avoid detached-instance errors outside of active session scopes
- Callers should work through repository classes and `sql/primitives.py` rather than issuing raw SQL
- `Database.__init__` wraps the session factory in `scoped_session`, giving each thread its own `Session`; `Database.close()` calls `scoped.remove()` to clean up the thread-local session, then `engine.dispose()` to release all pooled connections

### Escape hatch: raw SQL

For advanced queries or DDL work that repositories do not yet wrap, callers can use `Session.execute(text("..."))` directly:

```python
from sqlalchemy import text

result = session.execute(text("SELECT version()"))
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

### Vector collections

Vector collections are addressed by name through the ML layer; the name acts
as a ``backbone_id`` over the single PostgreSQL ``embeddings`` table. They are
no longer registered at runtime:

```python
db.ml.list_vector_collection_names()
db.ml.search_vectors("vectors_track_hot__demo_model__main", query_vector, limit=10)
```

``search_vectors`` returns the nearest-neighbour vectors for a query vector
within the named collection.

---

## 9. Recommended calling patterns

Prefer intent-level calls from higher layers:

```python
library = db.library.get_library(library_id)
songs = db.library.list_songs(library_id, limit=100)
streams = db.ml.list_output_streams_for_song(song_id)
```

Within higher layers, do **not** drop to raw SQL just because the session is available, and do **not** open your own transactions for ordinary writes. Facade write methods execute directly; the underlying repositories own their own short internal transactions (AR-SDR-4). Just call the write method:

```python
song = db.library.get_song(song_id)
db.library.replace_song_tags(song_id, [{"name": "genre", "value": "rock"}])
db.library.update_scan(library_id, {"status": "complete"})
db.app.replace_song_states(song_ids, "processing")
```

Use raw SQL access only for capabilities that are not already wrapped:

```python
result = session.execute(text("SELECT version()"))
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

1. Add the forward-only migration under `alembic/versions/`
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

- **`db.py` wires the world together** — engine, scoped session, repos, sub-facades
- **`api/` presents the only supported caller-facing persistence API**
- **`database/` holds private Tier 2 table and relationship repositories**
- **`sql/primitives.py` provides the narrow private Tier 1 SQL Core toolbox**
- **`pg_engine.py` manages the PostgreSQL connection lifecycle**
- **`models/` defines the SQLAlchemy ORM table schema**
- **`session.execute(text(...))` is the escape hatch for advanced raw SQL work**

If you encounter docs that describe a descriptor-driven collection facade with `collections_base.py` and `FieldAccessor`, those docs are describing an older design, not the implementation that exists in this branch.
