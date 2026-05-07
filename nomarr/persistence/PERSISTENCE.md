# Persistence Layer

The **persistence layer** owns ArangoDB access for Nomarr.

It now exposes a **descriptor-based, class-bound API**:

- `base.py` defines collection base classes, field declarations, and verb descriptors
- `collections.py` declares concrete collections as typed Python classes
- `constructor/` contains reusable AQL helpers (`verbs.py`, `filters.py`, `pagination.py`)
- `db.py` binds a single `SafeDatabase` to all collection classes at startup via `bind_all_collections()`
- External code uses the injected `Database` facade and accesses collections as `db.<collection>` attributes

The live API is descriptor-based and class-bound rather than wrapper-based or code-generated.

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
├── base.py                      # Collection bases, field declarations, verb descriptors
├── collections.py               # Concrete collection declarations
├── db.py                        # Database facade and dynamic vector registration
└── constructor/
    ├── __init__.py              # Constructor package exports
    ├── verbs.py                 # Shared AQL verb implementations
    ├── filters.py               # Filter helpers
    └── pagination.py            # Pagination helpers
```

Key points:

- `base.py` defines the descriptor model and shared collection behavior
- `collections.py` is the source of truth for physical collection declarations
- `constructor/verbs.py` holds reusable AQL execution helpers instead of per-collection operation classes
- `db.py` binds the database handle once and exposes bound collection classes as `db.<collection>` attributes

---

## 3. Descriptor-based collection model

Collection classes are plain Python classes with typed field annotations.

### Base classes

`base.py` defines the collection families used across the persistence layer:

- `DocumentCollection`
- `EdgeCollection`
- `VectorCollection`
- `StateGraphCollection`

It also defines:

- `Field[T]` and `UniqueField[T]` for field declarations
- `EdgeDef` for traversal and cascade metadata
- `INBOUND`, `OUTBOUND`, `CASCADE`, and `DETACH` constants
- collection verb descriptors such as `BaseGet`, `BaseInsert`, `BaseDelete`, `BaseUpsert`, `BaseUpdate`, `BaseCount`, and `BaseTruncate`

### Concrete collections

`collections.py` contains the concrete declarations, for example:

- document collections like `Libraries`, `LibraryFiles`, and `Tags`
- edge collections like `LibraryContainsFile` and `SongHasTags`
- vector collection templates like `VectorsTrackHot` and `VectorsTrackCold`
- state graph collections like `FileStates`

Collection names default to the class name in `snake_case`, but a class may override `_name` when the physical ArangoDB collection name differs.

### What field declarations do

When a collection subclass is created, `DocumentCollection.__init_subclass__()`:

1. derives `_name` if the subclass does not declare one explicitly
2. scans the class annotations for `Field[...]` and `UniqueField[...]`
3. installs descriptors that lazily bind field accessors on first access

That means this declaration:

```python
class LibraryFiles(DocumentCollection):
    path: UniqueField[str]
    library_key: Field[str]
```

becomes a runtime API like:

```python
db.library_files.path.get("/music/track.flac")
db.library_files.library_key.get.many("main", limit=100)
```

A `UniqueField` accessor treats bare `get(value)` as a single-document lookup. A plain `Field` accessor treats bare `get(value)` as a list-producing query and exposes `many()`, `in_()`, `gte()`, `lte()`, and `like()` helpers as needed.

---

## 4. How binding works

`Database` does **not** instantiate per-collection operation objects.

Instead, `Database.__init__()`:

1. creates the underlying ArangoDB client
2. calls `bind_all_collections(self.db)` once
3. assigns collection classes such as `Libraries`, `LibraryFiles`, and `Tags` onto the `Database` instance

`bind_all_collections()` assigns the shared `SafeDatabase` handle to the base collection classes' `ClassVar _db` and pre-compiles any static cascade delete AQL needed by concrete document collections.

Because the verbs are descriptors, access happens at class lookup time:

- `db.library_files.get` returns a collection-scoped read helper bound to `LibraryFiles`
- `db.library_files.path` returns a field-scoped accessor bound to `LibraryFiles.path`
- both helpers resolve the shared `_db` and `_name` when they execute

### Dynamic vector collections

Template-backed vector collections are still registered at runtime with:

```python
db.register("vectors_track_hot__discogs_effnet__main", "vectors_track_hot")
```

`register()` validates the physical collection name against the template `NAME_PATTERN`, creates a dynamic subclass with `_name` set to the resolved collection name, stores it on the `Database` instance, and recompiles any vector-dependent cascade wiring.

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

These verbs are declared once in `base.py` and resolved against the bound collection class at access time.

---

## 6. Constructor helpers

The `constructor/` package no longer builds collection objects. It now contains reusable query helpers:

- `verbs.py` — shared AQL read/write primitives such as `get_one_by_field()`, `insert()`, `update_by_field()`, and `upsert_by_field()`
- `filters.py` — filter expression helpers used by AQL builders
- `pagination.py` — pagination clause helpers

If you need a new persistence capability that fits the shared model, add or extend a helper here and bind it through the relevant descriptor or collection base in `base.py`.

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
2. Use the correct base type from `base.py`
3. Declare fields with `Field[...]` and `UniqueField[...]`
4. Add `EDGES` metadata if traversal or cascade behavior is needed
5. Expose the collection on `Database` in `db.py` if it should be part of the static facade
6. Add or extend shared AQL helpers in `constructor/` when the descriptor verbs need new lower-level behavior
7. Add a forward-only migration in `nomarr/migrations/` if the schema changes

---

## 9. Mental model

Think of the persistence layer like this:

- **`collections.py` declares what a collection is**
- **`base.py` turns those declarations into a descriptor-backed API**
- **`bind_all_collections()` supplies the shared database handle once at startup**
- **`db.py` exposes the bound collection classes to the rest of the app**
- **`constructor/` provides reusable AQL building blocks, not per-collection wrappers**
- **`db.db` remains available for advanced raw ArangoDB work**

If you encounter docs or examples that describe wrapper-based persistence wiring, they are out of date and should be updated to the descriptor-based API.
