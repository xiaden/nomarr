# Persistence Layer

The **persistence layer** handles all database access for Nomarr. It is a thin wrapper around ArangoDB providing type-safe, domain-organized operations via AQL queries.

Persistence is:

- **Pure data access** (no business logic)
- **AQL-based** (ArangoDB Query Language)
- **Injected** (received as `Database` parameter, never imported directly by higher layers)

> **⚠️ Access Rule:** Only **components** may call persistence directly. Services, workflows, and interfaces must go through components for any database access.

---

## 1. Position in the Architecture

```
interfaces → services → workflows → components → (persistence / helpers)
```

Persistence sits at the **bottom** alongside helpers:

- **Components** call persistence (the only layer that may do so)
- **Persistence** may import helpers (time utilities, DTOs, exceptions)
- **Persistence never imports** components, services, workflows, or interfaces

---

## 2. Directory Structure

```text
persistence/
├── arango_client.py                # Factory for ArangoDB connections
├── db.py                           # Database class (wires all operations)
└── database/                       # Operations package
    ├── calibration_history_aql.py
    ├── calibration_state_aql.py
    ├── file_states_aql.py
    ├── health_aql.py
    ├── libraries_aql.py
    ├── library_folders_aql.py
    ├── meta_aql.py
    ├── migrations_aql.py
    ├── ml_capacity_aql.py
    ├── ml_model_outputs_aql.py
    ├── ml_models_aql.py
    ├── navidrome_playcounts_aql.py
    ├── navidrome_tracks_aql.py
    ├── segment_scores_stats_aql.py
    ├── sessions_aql.py
    ├── tag_model_output_aql.py
    ├── vector_promotion_lock_aql.py
    ├── vectors_track_aql.py
    ├── vram_promises_aql.py
    ├── worker_claims_aql.py
    ├── worker_restart_policy_aql.py
    │
    ├── library_files_aql/            # Multi-file subpackage
    │   ├── calibration.py
    │   ├── chromaprint.py
    │   ├── crud.py
    │   ├── queries.py
    │   ├── reconciliation.py
    │   ├── stats.py
    │   ├── status.py
    │   └── tracks.py
    │
    └── tags_aql/                     # Multi-file subpackage
        ├── analytics.py
        ├── cleanup.py
        ├── crud.py
        ├── mood.py
        ├── queries.py
        └── stats.py
```

**Naming rules:**

- **Operations files:** `<collection_name>_aql.py`
- **Operations class:** `<CollectionName>Operations`
- **Methods:** Verb-noun describing the operation (`create_library`, `get_file_by_id`)

**Subpackage pattern:** When an operations class exceeds ~500 lines, split into a subpackage directory (e.g., `library_files_aql/`) with logical module groupings (`crud.py`, `queries.py`, `stats.py`). The import path stays the same: `from nomarr.persistence.database import LibraryFilesOperations`.

---

## 3. Core Components

### 3.1 Database Class (`db.py`)

Single entry point for all database operations. Wires all `*Operations` classes as named attributes.

```python
# Components receive db as parameter
db = Database(hosts=config.arango_host, password=config.arango_password)

# Access operations via attributes
library_id = db.libraries.create_library(name="My Library", root_path="/music")
files = db.library_files.get_files_for_library(library_id)
tags = db.tags.get_library_tags(library_id)
```

**Key properties:**
- Connection pooling handled automatically by python-arango
- Thread-safe within a single process
- Hardcoded username and db_name: `"nomarr"`
- Schema versioned via migrations (see `nomarr/migrations/`)

### 3.2 ArangoDB Client Factory (`arango_client.py`)

Creates ArangoDB connections. Typically called by `Database`, not by application code directly.

### 3.3 Operations Classes (`database/*_aql.py`)

Collection-oriented data access — one class per collection:

```python
class LibrariesOperations:
    def __init__(self, db: StandardDatabase) -> None:
        self.db = db
        self.collection = db.collection("libraries")
    
    def create_library(self, name: str, root_path: str) -> str:
        result = self.collection.insert({"name": name, "root_path": root_path})
        return result["_id"]
    
    def get_library_by_id(self, library_id: str) -> dict[str, Any] | None:
        cursor = self.db.aql.execute(
            "FOR lib IN libraries FILTER lib._id == @id RETURN lib",
            bind_vars={"id": library_id}
        )
        return cursor.next() if cursor.count() > 0 else None
```

---

## 4. What Belongs in Persistence

| Category | Example | Returns |
|---|---|---|
| **CRUD** | `create_library()`, `delete_library()` | `str` (_id), `None` |
| **Queries** | `get_unprocessed_files()`, `find_similar_songs()` | `list[dict]`, `dict \| None` |
| **Batch ops** | `bulk_insert_files()`, `bulk_update_tags()` | `None` |
| **Existence checks** | `library_exists()`, `file_exists_in_library()` | `bool` |
| **Aggregations** | `count_files_in_library()`, `get_library_stats()` | `int`, `dict` |

**Does NOT belong:** business logic, validation, orchestration, DTO transformation. Persistence returns raw dicts; services transform to DTOs.

---

## 5. ArangoDB Patterns

### Document Keys vs IDs

**Critical rule:** Never rename `_id` or `_key`.

- `_id`: Full identifier (`"libraries/12345"`)
- `_key`: Collection-local identifier (`"12345"`)

When mutating by `_id`, extract the key:

```python
self.db.aql.execute(
    "UPDATE PARSE_IDENTIFIER(@id).key WITH @updates IN libraries",
    bind_vars={"id": library_id, "updates": updates}
)
```

### Bind Variables

**Always** use bind variables for user input — never string interpolation:

```python
# ✅ Correct
cursor = self.db.aql.execute(
    "FOR lib IN libraries FILTER lib.name == @name RETURN lib",
    bind_vars={"name": library_name}
)
```

### Return Values

- Single document: `dict[str, Any] | None`
- Multiple documents: `list[dict[str, Any]]`
- Scalar: `int`, `bool`, `str`

### Timestamps

Use `now_ms()` from `nomarr.helpers.time_helper` for wall-clock timestamps. Never use monotonic timers (`internal_ms()`) or raw `time.time()`.

### Error Handling

Let ArangoDB exceptions propagate. Services/workflows handle error mapping.

---

## 6. Vector Store Architecture (Hot/Cold)

Nomarr uses a **hot/cold architecture** for vector embeddings to prevent OOM during active ML processing.

### Collection Naming

```
vectors_track_hot__{backbone}   # Write-only, no vector index
vectors_track_cold__{backbone}  # Read/search, vector index via maintenance
```

Examples: `vectors_track_hot__discogs_effnet`, `vectors_track_cold__discogs_effnet`

### Field Schema

| Field | Type | Description |
|---|---|---|
| `_key` | string | SHA-1 of `file_id\|model_suite_hash` |
| `file_id` | string | Library file document ID |
| `model_suite_hash` | string | 12-char hex hash |
| `embed_dim` | int | Embedding dimensions |
| `vector` | array[float] | Pooled embedding |
| `num_segments` | int | Backbone patches pooled |
| `created_at` | int | Unix timestamp (ms) |

### Lifecycle

1. **Active processing:** Embeddings written to hot collection (no vector index, fast writes)
2. **Maintenance:** Hot drained to cold via convergent UPSERT (unique `_key` ensures idempotence)
3. **Search:** Cold collection only, "as of last rebuild" semantics
4. **Cascade delete:** Vectors removed from both hot and cold via `Database.delete_vectors_by_file_id()`

### Constraints

- **NEVER** create vector indexes in bootstrap (owned by maintenance workflow)
- **NEVER** write to cold directly (hot is the only write path)
- **NEVER** search hot (search is cold-only)
- **ALWAYS** use convergent drain with unique `_key`
- **ALWAYS** drop old cold vector index before rebuilding

---

## 7. Method Naming Conventions

| Prefix | Meaning | Returns |
|---|---|---|
| `get_*` | Fetch single document | `dict \| None` |
| `get_all_*` | Fetch multiple documents | `list[dict]` |
| `find_*` | Query/search | `list[dict]` |
| `create_*` | Insert new document | `str` (_id) |
| `update_*` | Modify existing | `None` |
| `delete_*` | Remove document | `None` |
| `count_*` | Aggregation | `int` |
| `exists_*` | Boolean check | `bool` |

---

## 8. Import Rules

**Allowed:**
- ✅ `arango` (python-arango client)
- ✅ `nomarr.helpers.*` (time utilities, DTOs, exceptions)
- ✅ Standard library

**Forbidden:**
- ❌ `nomarr.services.*`
- ❌ `nomarr.workflows.*`
- ❌ `nomarr.components.*`
- ❌ `nomarr.interfaces.*`

---

## 9. Connection Management

- **Pooling:** Automatic via python-arango, thread-safe within a process
- **Multi-process:** Each process creates its own `Database()` instance. Don't share across process boundaries.
- **First run:** App connects as root to provision `nomarr` user/database, generates app password, stores in config

---

## 10. Performance

- **Indexes:** Ensure proper indexes during schema bootstrap
- **Limits:** Always provide limits for unbounded queries
- **Batch ops:** Use `insert_many()` over loops
- **Cursors:** Iterate cursors for large result sets instead of materializing to lists
