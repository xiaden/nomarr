# Persistence Layer

The **persistence layer** owns ArangoDB access for Nomarr.

It is now a **class-based, builder-wired API**:

- Collection shapes are declared as Python classes in `collections.py`
- Base collection types live in `base.py`
- `Builder` in `constructor/builder.py` reads class annotations and attaches runtime verbs/accessors
- `Database` in `db.py` exposes wired collection instances as `db.<collection>` attributes
- Type stubs in `stubs/` are auto-generated from the collection classes by `scripts/tools/gen_stubs.py`

There is **no `SCHEMA` dict** and no constructor-era namespace layer.

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
├── base.py                      # Field markers + base collection classes
├── collections.py               # Concrete collection declarations
├── db.py                        # Database facade and dynamic registration
├── constructor/
│   ├── builder.py               # Builder that wires collection instances
│   ├── verbs.py                 # Shared AQL verb implementations
│   ├── filters.py               # Filter helpers
│   └── pagination.py            # Pagination helpers
├── stubs/
│   ├── _base.pyi                # Shared protocol definitions
│   └── *.pyi                    # Generated per-collection stubs
└── database/
    └── __init__.py              # Legacy empty compatibility stub
```

Key points:

- `base.py` defines the persistence type system
- `collections.py` is the source of truth for collection declarations
- `Builder` attaches verbs to collection instances at runtime
- `stubs/` are generated artifacts, not hand-maintained APIs
- `database/` is retained only as a compatibility stub and is not where the live API lives

---

## 3. Collection declarations

Collection classes are plain Python classes with typed field annotations.

### Base classes

`base.py` defines four collection families:

- `DocumentCollection`
- `EdgeCollection`
- `VectorCollection`
- `StateGraphCollection`

It also defines:

- `Field[T]` and `UniqueField[T]` for field declarations
- `EdgeDef` for traversal / cascade metadata
- `INBOUND`, `OUTBOUND`, `CASCADE`, and `DETACH` constants

### Concrete collections

`collections.py` contains the concrete declarations, for example:

- document collections like `Libraries`, `LibraryFiles`, `Tags`
- edge collections like `LibraryContainsFile`, `SongHasTags`
- vector templates like `VectorsTrackHot`, `VectorsTrackCold`
- state graph collections like `FileStates`

Collection names are usually derived from the class name in `snake_case`, but a class may override this with `_name` when the physical ArangoDB collection name differs.

The builder reads:

- field annotations to create field accessors
- `EDGES` metadata to attach traversal helpers
- base class type to attach state-graph or vector-specific verbs

---

## 4. How collections get wired

`Database` creates collection instances and `Builder` wires them.

### Static collections

Most collections are wired during `Database` initialization:

- `Database` instantiates the collection class
- sets the resolved collection name
- calls `Builder(self.db).construct(instance)`
- exposes the result as `db.<collection_name>`

That means application code works with already-wired collection instances like:

- `db.library_files`
- `db.tags`
- `db.ml_models`
- `db.file_states`

### Dynamic vector collections

Dynamic vector collections are registered at runtime through:

`db.register(resolved_name, template_name)`

This method:

1. checks whether the physical collection exists in ArangoDB
2. looks up the template class by `template_name`
3. validates that `resolved_name` matches the template `NAME_PATTERN`
4. instantiates the template class
5. wires it through `Builder`
6. caches and returns the runtime instance

This is used for template-backed vector collections whose physical names are resolved at runtime.

---

## 5. Flat runtime API

The public persistence surface is intentionally **flat and attribute-based**.

### Collection-level reads

Common read entry points include:

- `db.col.get()`
- `db.col.get.many()`
- `db.col.get.in_()`
- `db.col.get.gte()`
- `db.col.get.lte()`
- `db.col.get.like()`

Examples:

```python
doc = db.library_files.get(path="/music/track.flac")
rows = db.library_files.get.many(library_key="main", limit=100, offset=0)
recent = db.library_files.get.gte("modified_time", 1700000000000, limit=50)
matching = db.library_files.get.like("normalized_path", "/music/")
```

### Field-scoped reads

Each declared field becomes a field accessor with the same read helpers.

Examples:

```python
tag = db.tags.name.get("genre")
tags = db.tags.name.get.many("genre", limit=100)
files = db.library_files.library_key.get.in_(["main", "secondary"], limit=500)
```

### Collection-level writes and utilities

Common write and utility entry points include:

- `db.col.insert()`
- `db.col.update()`
- `db.col.update_many()`
- `db.col.upsert()`
- `db.col.delete()`
- `db.col.delete.cascade()`
- `db.col.count()`
- `db.col.aggregate()`

Examples:

```python
db.library_files.insert([
    {
        "path": "/music/track.flac",
        "normalized_path": "/music/track.flac",
        "library_key": "main",
    }
])

db.tags.upsert(name="genre", value="rock", fields={"value": "rock"})
db.libraries.delete.cascade(name="Main Library")
```

### Traversal, state-graph, and vector verbs

Additional verbs are attached based on collection type and metadata:

- traversal helpers derived from `EDGES`
- `delete.cascade()` for collections with outbound `CASCADE` edges
- `transition()` for `StateGraphCollection`
- vector helpers such as `ann_search()`, `get_vector()`, `upsert_vector()`, and `move_collection()` on `VectorCollection` instances where applicable

These verbs are not hand-written per collection; they are attached by `Builder` based on the class declaration.

---

## 6. Generated type stubs

`nomarr/persistence/stubs/` contains IDE and type-checker stubs for the runtime-wired API.

They are **auto-generated** by:

- `scripts/tools/gen_stubs.py`

The generator reads the collection classes and their annotations / metadata to emit per-collection `.pyi` files.

It derives stub content from:

- field annotations on collection classes
- `EDGES` traversal metadata
- `StateGraphCollection` membership
- `VectorCollection` membership
- whether a collection gets `delete.cascade`

Do not hand-edit generated stubs unless you are also updating the generator.

---

## 7. Raw ArangoDB access

For advanced queries or operations that are not yet exposed through the flat API, use the raw handle on:

- `db.db`

Examples include:

- `db.db.aql.execute(...)`
- `db.db.has_collection(...)`
- `db.db.create_collection(...)`

This is the escape hatch for specialized DDL or AQL work. Prefer the typed collection API when it already covers the use case.

---

## 8. Extension guidelines

When adding or changing persistence behavior:

1. Update or add the collection declaration in `collections.py`
2. Use the correct base type from `base.py`
3. Add field annotations with `Field[...]` / `UniqueField[...]`
4. Add `EDGES` metadata if traversal or cascade behavior is needed
5. Let `Builder` wire the runtime API
6. Regenerate stubs with `scripts/tools/gen_stubs.py` if the public surface changed

If a change requires DB structure updates, add a forward-only migration in `nomarr/migrations/`.

---

## 9. Mental model

Think of the persistence layer like this:

- **`collections.py` declares what a collection is**
- **`Builder` turns that declaration into a callable runtime API**
- **`Database` exposes those wired instances to the rest of the app**
- **`stubs/` make the dynamic API visible to IDEs and static tooling**
- **`db.db` remains available for advanced raw ArangoDB work**

That is the current persistence architecture. If you see references to a `SCHEMA` dict, schema constructor, or constructor-era namespaces, they are historical and should be updated.