# Persistence Layer

The **persistence layer** owns ArangoDB access for Nomarr.

The target shape is:

- `db.py` owns connection setup and exposes the python-arango database handle
- `aql/` contains reusable AQL primitives (`execute`, bind/pagination helpers, bulk verbs)
- `database/` contains explicit app/domain operations with stable return shapes

The legacy collection/accessor framework remains for compatibility while callers migrate to explicit operation modules.
It is **legacy compatibility-only** and is no longer the recommended app-facing persistence style.

> **Access rule:** Higher layers should use the injected `Database` facade. Do not import persistence internals directly unless you are extending the persistence layer itself.

---

## 1. Position in the architecture

```text
interfaces → services → workflows → components → (persistence / helpers)
```

Persistence sits at the bottom of the dependency graph:

- **Components** may call persistence directly
- **Persistence** may use helpers and low-level Arango utilities
- **Persistence never imports** components, workflows, services, or interfaces

Persistence is responsible for data access, not orchestration or business policy.

---

## 2. Current package layout

```text
persistence/
├── arango_client.py             # ArangoDB connection / typed DB protocol helpers
├── aql/                         # Shared AQL primitives
│   ├── __init__.py
│   └── primitives.py
├── database/                    # Explicit app/domain operations
│   ├── __init__.py
│   └── library_files_aql.py
├── collections.py               # Concrete collection declarations
├── collections_base.py          # Shared collection wrapper bases and collection-level verbs
├── accessors.py                 # FieldAccessor plus collection/field get/delete helpers
├── base_types.py                # Field criteria, edge metadata, and constants
├── cascade.py                   # Cascade compilation helpers
├── db.py                        # Database facade and dynamic vector registration
└── constructor/
    ├── __init__.py              # Constructor package exports
    ├── verbs.py                 # Shared AQL verb implementations
    ├── filters.py               # Filter helpers
    └── pagination.py            # Pagination helpers
```

Key points:

- New work should go into explicit `database/*_aql.py` operation modules
- New reusable AQL helpers should go in `aql/primitives.py`
- `db.py` wires operation modules (for example `db.library_files_aql`) and still binds legacy collection wrappers for compatibility
- Collection/accessor/query-spec framework files are legacy compatibility internals, not the preferred extension model

### Migration evidence (current branch)

- Added explicit operation modules:
  - `database/library_files_aql.py`
  - `database/libraries_aql.py`
- Migrated callers:
  - `components/library/library_file_query_comp.py` (selected query paths)
  - `components/library/library_records_comp.py` (library record CRUD/query paths)
- Remaining legacy users are tracked as follow-up migration work; new persistence additions should target `aql/` + `database/` modules.

---

## 3. Descriptor-based collection model

Collection classes are plain Python classes with typed field-accessor attributes.

### Base classes

`collections_base.py` defines the collection families used across the persistence layer:

- `DocumentCollection`
- `EdgeCollection`
- `VectorCollection`
- `StateGraphCollection`

`base_types.py` defines:

- field-criteria helpers used by collection and accessor verbs
- `EdgeDef` for traversal and cascade metadata
- `INBOUND`, `OUTBOUND`, `CASCADE`, and `DETACH` constants

`accessors.py` provides `FieldAccessor` plus the collection/field helpers that expose `get`, `delete`, `count`, `update`, `upsert`, and related operations.

### Concrete collections

`collections.py` contains the concrete declarations, for example:

- document collections like `Libraries`, `LibraryFiles`, `Tags`, and canonical ML stream storage in `MlOutputStreams`
- edge collections like `LibraryContainsFile`, `SongHasTags`, `FileHasOutputStream`, and `OutputHasStream`
- vector collection templates like `VectorsTrackHot` and `VectorsTrackCold`
- state graph collections like `FileStates`

Concrete collection classes declare their physical collection names by passing them to the shared base constructor in `__init__()`.

### What field registration does

When a collection instance is constructed, the collection `__init__()` method calls `self._field(...)` for each exposed field. That registration:

1. creates a `FieldAccessor` bound to the shared `SafeDatabase` handle and physical collection name
2. stores the accessor in the collection's internal field registry
3. makes collection-level helpers like `get(...)` reuse those field-specific accessors when possible

That means a declaration pattern like:

```python
class LibraryFiles(DocumentCollection):
    path: FieldAccessor
    library_key: FieldAccessor

    def __init__(self, db: SafeDatabase) -> None:
        super().__init__(db, "library_files")
        self.path = self._field("path", unique=True)
        self.library_key = self._field("library_key")
```

becomes a runtime API like:

```python
db.library_files.path.get("/music/track.flac")
db.library_files.library_key.get.many("main", limit=100)
```

A field registered with `unique=True` treats bare `get(value)` as a single-document lookup. A non-unique field treats bare `get(value)` as a list-producing query and exposes `many()`, `in_()`, `gte()`, `lte()`, and `like()` helpers as needed.

---

## 4. How binding works

`Database` instantiates concrete collection wrapper objects and binds each one to the shared `SafeDatabase` handle.

`Database.__init__()`:

1. creates the underlying ArangoDB client
2. instantiates the static collection set (`Libraries`, `LibraryFiles`, `Tags`, and others)
3. stores those instances as attributes on the `Database` facade
4. compiles cascade-delete callables for document collections with outbound `CASCADE` edges

Because the verbs are instance-bound, access happens through the bound collection object:

- `db.library_files.get` returns a collection-scoped read helper bound to the `library_files` collection instance
- `db.library_files.path` returns a field-scoped accessor bound to the `path` field on that instance
- both helpers execute against the shared `SafeDatabase` handle held by the collection object

### Dynamic vector collections

Template-backed vector collections are still registered at runtime with:

```python
db.register("vectors_track_hot__discogs_effnet__main", "vectors_track_hot")
```

`register()` validates the physical collection name against the template `NAME_PATTERN`, creates a runtime-bound vector collection instance for the resolved collection name, stores it on the `Database` instance, and recompiles any vector-dependent cascade wiring.

---

## 5. Calling convention

The public persistence surface is attribute-based and field-first.

### Field-scoped access

Each declared field becomes a bound accessor with field-scoped verbs:

```python
file_doc = db.library_files.path.get("/music/track.flac")
main_files = db.library_files.library_key.get.many("main", limit=100, offset=0)
rock_tags = db.tags.name.get.like("rock%", limit=50)
deleted = db.song_has_tags._from.delete(file_id)
```

Field accessors also expose convenience mutations tied to their field name:

```python
db.tags.name.upsert("genre", {"value": "genre"})
db.worker_claims.file_id.update(file_id, {"worker_id": worker_id})
count = db.library_files.library_key.count("main")
```

### Collection-scoped access

Collection verbs accept either `Field("name", value)` positional filters or keyword criteria:

```python
recent = db.library_files.get.gte("modified_time", 1700000000000, limit=50)
rows = db.library_files.get.many(library_key="main", limit=100, offset=0)

db.library_files.insert([
    {
        "path": "/music/track.flac",
        "normalized_path": "/music/track.flac",
        "library_key": "main",
    }
])

db.library_files.update(path="/music/track.flac", fields={"size_bytes": 12345})
db.tags.upsert(name="genre", fields={"value": "genre"})
total = db.library_files.count(library_key="main")
db.library_files.delete(path="/music/track.flac")
db.library_files.truncate()
```

### Metadata-driven verbs

Additional verbs are attached based on collection type and metadata:

- traversal helpers derived from `EDGES`
- `delete.cascade(ids)` for collections with outbound `CASCADE` edges
- `transition(file_ids, from_state, to_state)` for `StateGraphCollection`
- vector helpers on `VectorCollection` classes where applicable

These verbs are declared once in `collections_base.py` and `accessors.py`, then executed against the bound collection instance at access time.

---

## 6. Constructor helpers

The `constructor/` package no longer builds collection objects. It now contains reusable query helpers:

- `verbs.py` — shared AQL read/write primitives such as `get_one_by_field()`, `insert()`, `update_by_field()`, and `upsert_by_field()`
- `filters.py` — filter expression helpers used by AQL builders
- `pagination.py` — pagination clause helpers

If you need a new persistence capability that fits the shared model, add or extend a helper here and surface it through the relevant collection base or accessor helper in `collections_base.py` or `accessors.py`.

---

## 7. Raw ArangoDB access

For advanced operations that are not yet exposed through the typed collection API, use the raw handle on:

- `db.db`

Examples include:

- `db.db.aql.execute(...)`
- `db.db.has_collection(...)`
- `db.db.create_collection(...)`

This is the escape hatch for specialized DDL or AQL work. Prefer the typed collection API when it already covers the use case.

---

## 8. Extension guidelines

When adding or changing persistence behavior:

1. Add or update the collection declaration in `collections.py`
2. Use the correct base type from `collections_base.py`
3. Register fields in the collection `__init__()` with `self._field(...)`
4. Add `EDGES` metadata if traversal or cascade behavior is needed
5. Expose the collection on `Database` in `db.py` if it should be part of the static facade
6. Add or extend shared AQL helpers in `constructor/` when the collection or accessor verbs need new lower-level behavior
7. Add a forward-only migration in `nomarr/migrations/` if the schema changes

---

## 9. Mental model

Think of the persistence layer like this:

- **`collections.py` declares what a collection is**
- **`collections_base.py` and `accessors.py` provide the reusable descriptor-driven API surface**
- **`db.py` instantiates and exposes the bound collection facade to the rest of the app**
- **`EDGES` metadata drives traversal and cascade behavior from one place**
- **`constructor/` provides reusable AQL building blocks, not per-collection wrappers**
- **`db.db` remains available for advanced raw ArangoDB work**

If you encounter docs or examples that describe wrapper-based persistence wiring, they are out of date and should be updated to the descriptor-based API.
