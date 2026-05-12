# Persistence Layer

The **persistence layer** owns ArangoDB access for Nomarr.

This package is no longer the descriptor-based collection system described in older docs. In the current code, persistence is organized around a top-level `Database` facade in `db.py`, a set of thin AQL operation classes under `database/`, and higher-level intent facades under `api/`.

> **Access rule:** Higher layers should depend on the injected `Database` facade. Reach for `db.library`, `db.app`, and `db.ml` first. Import persistence internals directly only when you are extending the persistence layer itself.

---

## 1. Position in the architecture

```text
interfaces → services → workflows → components → (persistence / helpers)
```

Persistence sits at the bottom of the dependency graph:

- **Components** may call persistence directly
- **Persistence** may use helpers and low-level Arango utilities
- **Persistence never imports** components, workflows, services, or interfaces
- **Persistence returns raw documents and query results**; higher layers decide how to map or interpret them

Persistence is responsible for data access, not orchestration or business policy.

---

## 2. Current package layout

```text
persistence/
├── __init__.py                  # Re-exports Database lazily
├── PERSISTENCE.md               # This guide
├── arango_client.py             # Safe Arango client wrapper and bind-var sanitization
├── db.py                        # Top-level Database facade and sub-facade wiring
├── schema_types.py              # Legacy schema helpers and runtime vector namespaces
├── api/
│   ├── application.py           # AppDb intent facade
│   ├── library.py               # LibraryDb intent facade
│   └── ml.py                    # MlDb intent facade
├── aql/
│   └── primitives.py            # Shared AQL helper functions
├── database/
│   ├── app_aql.py               # App-domain collection/edge operations
│   ├── file_states_aql.py       # File state edge operations
│   ├── libraries_aql.py         # Libraries collection operations
│   ├── library_files_aql.py     # Files, folders, and link operations
│   ├── ml_models_aql.py         # ML model and calibration persistence
│   ├── ml_streams_aql.py        # ML output stream persistence
│   ├── navidrome_aql.py         # Navidrome mapping/playcount persistence
│   ├── scan_aql.py              # Library scan record operations
│   ├── tags_aql.py              # Tag and file↔tag operations
│   └── vectors_aql.py           # Runtime vector collection operations
└── models/
    ├── base.py                  # Shared persistence models
    └── tag.py                   # Tag-specific model helpers
```

### What changed from the old docs

If you see references to `collections.py`, `collections_base.py`, `accessors.py`, or `constructor/` in persistence documentation, those references are stale for this branch. The live implementation uses:

- `api/` for intent-level facades
- `database/` for thin collection and edge bindings
- `aql/primitives.py` for shared reusable AQL helpers
- `schema_types.py` for remaining schema helpers, especially vector namespaces

---

## 3. The `Database` facade

`db.py` defines the top-level `Database` class. It is the main entry point for the rest of the backend.

`Database.__init__()` currently does four things:

1. Resolves Arango connection settings
2. Creates a shared `SafeDatabase` via `create_arango_client(...)`
3. Instantiates the low-level AQL operation objects in `database/`
4. Wires those objects into intent-level sub-facades in `api/`

The facade exposes three layers of access.

### Preferred: intent-level sub-facades

These are the cleanest entry points for higher layers:

- `db.library` → `LibraryDb`
- `db.app` → `AppDb`
- `db.ml` → `MlDb`

These group related persistence actions by domain rather than by physical collection.

### Available: direct operation namespaces

`Database` also exposes the thin operation bindings directly:

- `db.libraries`
- `db.library_files`
- `db.tags`
- `db.scan`
- `db.file_states`
- `db.ml_streams`
- `db.ml_models`

These are aliases of the underlying AQL operation objects and are useful inside persistence-heavy code where collection-oriented access is appropriate.

### Lowest-level compatibility names

The explicit `*_aql` attributes are also still present:

- `db.libraries_aql`
- `db.library_files_aql`
- `db.tags_aql`
- `db.scan_aql`
- `db.file_states_aql`
- `db.ml_streams_aql`
- `db.vectors_aql`
- `db.ml_models_aql`
- `db.app_aql`
- `db.navidrome_aql`

These are implementation-facing names. Prefer the intent facades unless you are working within the persistence layer or need a very collection-specific capability.

---

## 4. The three public sub-facades

### `db.library`

`LibraryDb` in `api/library.py` is the domain facade for library-facing persistence.

It wraps operations such as:

- library CRUD (`add_library`, `get_library`, `list_libraries`, `update_library`, `delete_library`)
- file CRUD and queries (`add_file`, `get_file`, `upsert_file`, `list_files`, `search_files_by_text`)
- file↔library links and folder links
- tag creation, upsert, lookup, aggregation, and cleanup
- library-scoped cleanup helpers like deleting files, folders, or links for a library

Use `db.library` when the caller thinks in terms of libraries, files, folders, and tags rather than specific Arango collections.

### `db.app`

`AppDb` in `api/application.py` groups application-state persistence.

It wraps operations such as:

- file state reads and transitions
- scan records and library↔scan edges
- pipeline state storage
- locks and worker claims
- health records
- sessions
- worker restart policy documents
- meta and migration records
- VRAM promise tracking
- Navidrome track mappings and playcount persistence

Use `db.app` for coordination data and operational state rather than music-library content.

### `db.ml`

`MlDb` in `api/ml.py` groups ML-related persistence.

It wraps operations such as:

- ML output stream storage and cleanup
- vector registration and vector search
- file↔vector links
- model CRUD
- model outputs and tag-model-output edges
- calibration state and calibration history persistence

Use `db.ml` when the caller works with embeddings, models, output streams, or calibration artifacts.

---

## 5. The lower layer: thin AQL operation classes

The `database/` package holds the thin bindings that actually talk to ArangoDB.

Examples include:

- `LibrariesAqlOperations`
- `LibraryFilesAqlOperations`
- `TagsAqlOperations`
- `ScanAqlOperations`
- `FileStatesAqlOperations`
- `AppAqlOperations`
- `NavidromeAqlOperations`
- `MlStreamsAqlOperations`
- `VectorsAqlOperations`
- `MlModelsAqlOperations`

These classes are intentionally narrow. They are not business services; they are focused collection/edge/query adapters over `SafeDatabase`.

Several of their docstrings describe them as **thin Tier 2 bindings**, which is a good mental model: they sit below the intent facades and above the generic AQL helper functions.

---

## 6. Shared AQL helpers

The reusable query helpers live in `aql/primitives.py`.

That module currently provides helpers such as:

- `execute(...)`
- `normalize_limit(...)`
- `get_many_by_keys(...)`
- `get_many_by_field(...)`
- `get_filtered_docs(...)`
- `list_field_values(...)`
- `count_distinct_edge_sources_to_filtered_vertices(...)`
- `delete_many_by_keys(...)`
- `upsert_by_field(...)`
- `insert_document(...)`
- `update_document_by_key(...)`

Use these helpers when several operation classes need the same safe query-building pattern. Keep collection-specific intent in the `database/` modules.

---

## 7. Safe database access

`arango_client.py` provides two important wrappers:

- `SafeDatabase`
- `_SafeAQL`

Their job is to sanitize bind variables before AQL execution so persistence code passes JSON-serializable primitives into Arango.

That means:

- `db.db` is a wrapped `SafeDatabase`, not a raw `StandardDatabase`
- `db.db.aql.execute(...)` still works, but bind variables are normalized first
- persistence call sites should convert rich objects to primitives explicitly rather than relying on accidental serialization

This wrapper is the main escape hatch for advanced AQL or DDL work while still preserving the project's safety checks.

---

## 8. Vector collections and `schema_types.py`

`schema_types.py` is still part of the live persistence surface.

It contains:

- `Field` and `UniqueField` helper types used by remaining collection-style APIs
- `CollectionType` and persistence-related error types
- runtime vector collection namespaces such as `VectorCollection`, `VectorsTrackHot`, and `VectorsTrackCold`

### Dynamic vector registration

Vector collections are registered at runtime through the ML layer:

```python
db.ml.register_vector_collection(
    "vectors_track_hot__demo_model__main",
    "vectors_track_hot",
)
```

That registration returns a runtime `VectorCollection` namespace that can then be used for vector persistence and search.

This part of the package is the main place where collection-like runtime objects still exist in the current architecture.

---

## 9. Recommended calling patterns

Prefer intent-level calls from higher layers:

```python
library = db.library.get_library(library_id)
files = db.library.list_library_files(library_id, limit=100)
db.app.transition_file_states(file_ids, "queued", "processing")
streams = db.ml.get_output_streams_for_file(file_id)
```

Drop to direct operation bindings only when you need collection-oriented behavior:

```python
doc = db.library_files.get_file(file_id)
db.tags.upsert_tag(file_id, "genre", {"name": "genre", "value": "rock"})
db.scan.update_scan_record(scan_id, {"status": "complete"})
```

Use raw database access only for capabilities that are not already wrapped:

```python
rows = db.db.aql.execute(query, bind_vars=bind_vars)
exists = db.db.has_collection("example_collection")
```

The rule of thumb is simple:

- **Domain intent first** → `db.library`, `db.app`, `db.ml`
- **Collection-specific persistence second** → `db.<thing>` or `db.<thing>_aql`
- **Raw Arango last** → `db.db`

---

## 10. Extension guidelines

When changing persistence behavior, work from the right layer downward.

### If the caller needs a new domain operation

1. Add or extend a method on `LibraryDb`, `AppDb`, or `MlDb`
2. Delegate to one or more existing `database/` operation classes where possible
3. Keep orchestration light; this layer should still be data access focused

### If the caller needs a new collection or query capability

1. Add or extend the relevant `*AqlOperations` class in `database/`
2. Reuse helpers from `aql/primitives.py` when they fit
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
- hide ArangoDB-native `_id` and `_key` fields behind renamed abstractions
- turn into a workflow layer just because a query touches several collections

If code starts deciding *what should happen* instead of *how data is read or written*, it probably belongs above persistence.

---

## 12. Mental model

Think about the current persistence layer like this:

- **`db.py` wires the world together**
- **`api/` presents intent-level domain facades**
- **`database/` holds thin collection and edge adapters**
- **`aql/primitives.py` provides reusable query building blocks**
- **`arango_client.py` keeps AQL execution safe**
- **`schema_types.py` preserves the runtime vector namespace machinery**
- **`db.db` is the escape hatch for advanced raw Arango work**

If you encounter docs that describe a descriptor-driven collection facade with `collections_base.py` and `FieldAccessor`, those docs are describing an older design, not the implementation that exists in this branch.
