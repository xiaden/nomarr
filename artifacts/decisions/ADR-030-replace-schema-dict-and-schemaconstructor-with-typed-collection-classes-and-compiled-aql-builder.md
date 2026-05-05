# ADR-030: Replace SCHEMA dict and SchemaConstructor with typed collection classes and compiled-AQL builder

**Status:** Proposed  
**Date:** 2026-05-04  
**Tags:** persistence, schema, builder, collections, refactor, cascade, traversal  
**Source Log:** support-patternenforcer#L40  
**Supersedes:** ADR-025, ADR-004, ADR-030  

## Context

The persistence layer is structured around a central SCHEMA dict in `schema.py` and a `SchemaConstructor` that reads it at startup to build `CollectionNamespace` objects with nested `FieldNamespace` sub-objects. This design has five compounding problems:

1. **Verbose and drift-prone schema dict.** Per-field capability lists are manual and duplicative. Forgetting a capability silently removes a verb; the `tags` collection was missing `traversal` and the error was only caught at runtime.

2. **Field sub-namespace navigational friction.** Callers write `db.library_files.path.get(val)` — three dots for a single-document lookup. The sub-namespace layer adds no expressiveness.

3. **CascadeEngine N+1 pattern.** The current `CascadeEngine` performs Python-recursive traversal with one AQL query per edge hop and per-document orphan checks. Deleting a library with 10,000 files generates thousands of round-trips.

4. **Traversal API inconsistency.** `db.col.traversal(id, "edge_col")` takes the edge collection as a string. No typed relationship graph exists.

5. **Partial type safety.** Several edge collections are typed as `Any` in `db.py`. Generated `.pyi` stubs must be manually kept in sync with the SCHEMA dict.

ADR-025 established the schema-driven constructor. ADR-004 introduced `TEMPLATE` for vector collections. ADR-030 proposed a 3-cap simplification (now superseded by this fuller redesign).

## Decision

Replace the SCHEMA dict and SchemaConstructor pipeline with typed Python collection classes and a `builder.construct()` function that reads annotations directly.

**1. One class per collection in `nomarr/persistence/collections.py`**

Each collection is a Python class. Fields are typed annotations using `Field[T]` (non-unique) or `UniqueField[T]` (unique). Implicit fields (`_key`, `_id`, `_rev`, `_from`, `_to`) are NOT declared — base classes add them automatically.

**2. Four base classes replace `CollectionType` enum**

- `DocumentCollection` — implicit `_key`, `_id`, `_rev`; verbs: `get`, `get.many`, `get.in_`, `get.gte`, `get.lte`, `get.like`, `insert`, `update`, `upsert`, `delete`, `count`
- `EdgeCollection` — implicit `_key`, `_id`, `_rev`, `_from`, `_to`; verbs: `insert`, `delete`, `count`, `truncate`
- `VectorCollection` — implicit `_key`, `_id`, `_rev`; verbs: `insert`, `ann_search` (both tiers), `upsert_vector` (hot only), `get_vector`, `update_many`, `move_collection`
- `StateGraphCollection(DocumentCollection)` — adds `transition` verb

**3. Capabilities eliminated**

Collection type determines the default verb set. No per-collection or per-field capability lists.

**4. `builder.construct(self)` reads `__annotations__` from the MRO**

Called once per collection instance at `Database.__init__` time. Attaches typed field accessor objects via `setattr`. No SCHEMA dict. No SchemaConstructor as a separate pipeline step.

**5. Flat field accessor API — no sub-namespaces**

All verbs are on the collection directly. Field is identified by keyword argument or by `Field(name, value)` positional dataclass for `_`-prefixed implicit fields:

```python
db.library_files.get(path="/music/track.mp3")        # unique → dict | None
db.library_files.get.many(library_id="lib-abc")      # non-unique → list[dict]
db.library_files.get.gte(size, 1_000_000)            # range filter
db.song_has_tags.get.many(Field("_from", file_id))   # _-prefixed field
db.library_files.delete(path="/music/track.mp3")
db.library_files.count()
```

**6. Edge relationships declared on document collections via `EDGES`**

```python
class LibraryFiles(DocumentCollection):
    path: UniqueField[str]
    size: Field[int]

    EDGES = [
        EdgeDef(via=LibraryContainsFile, direction=INBOUND,  target=Libraries, on_delete=DETACH),
        EdgeDef(via=SongHasTags,         direction=OUTBOUND, target=Tags,       on_delete=DETACH),
    ]
```

Edge collections keep `FROM_COLLECTION`/`TO_COLLECTION` class vars for cascade resolution and edge cleanup. Traversal verbs are named after the **edge collection**: `db.library_files.song_has_tags(file_id)`.

**7. Two delete verbs**

- `delete(key)` — removes doc and cleans up its own edge records across all declared edge collections. Always available.
- `delete.cascade(key)` — only attached when at least one `CASCADE` EdgeDef exists. Builder pre-compiles a static AQL template at startup: OUTBOUND traversal of all CASCADE edges, isolation check (no external inbound → orphan), bulk removal of orphan docs + all associated edge records in one AQL operation. No Python recursion. No N+1. CASCADE graph must be a DAG; builder validates this at startup.

**8. `db.register(resolved_name, template_name: str)` unchanged**

Dynamic vector collections continue to register via template name string. `db.db.*` raw handle access is out of scope and preserved unchanged.

**9. Stubs simplified**

With field sub-namespaces gone, `.pyi` stubs shrink to traversal verb signatures and `delete.cascade`. `gen_stubs.py` is updated accordingly.

Design document: `artifacts/designs/pending/DD-persistence-class-schema.md`

## Consequences

**Positive:**
- New collections require only a class with typed field annotations — no capability list, no SCHEMA dict entry
- Traversal relationships are typed and navigable; edge collection name is the verb — no string magic
- Cascade delete is a single pre-compiled AQL operation — eliminates N+1 round-trips for library deletion
- `delete` and `delete.cascade` are explicitly separated — callers opt into expensive operations knowingly
- Field accessor API is flat — callers use `db.col.get(field=val)` not `db.col.field.get(val)`
- Type safety improves — collection classes are real Python types, not dict entries
- Stub drift eliminated — stubs derived from class annotations, much smaller surface

**Negative / Trade-offs:**
- One-time migration effort: ~37 collections, ~15 component callers, ~5 service/workflow callers
- `setattr` in `builder.construct` is still invisible to mypy — stubs remain necessary for full type checking
- Payload edge collections (e.g., `TagModelOutput` with `score`, `created_at`) must declare their payload fields alongside `FROM_COLLECTION`/`TO_COLLECTION` — slightly more verbose than bare edges
- `transition` verb is generalized (any edge collection can express it) — domain validity enforcement moves fully to component layer

**No ArangoDB schema migration required** — the ArangoDB collection structure does not change. `ensure_schema` and all existing migrations are unaffected. This is a pure Python representation change.

## References

- Design document: `artifacts/designs/pending/DD-persistence-class-schema.md`
- ADR-025: Schema-driven constructor and capability-gated namespaces (superseded)
- ADR-004: TEMPLATE type for vector collections (superseded)
- ADR-003: Pure boolean state graph for file processing pipeline (transition verb semantics unchanged)
- ADR-030: Simplify persistence capability model to read/write/delete (superseded by this fuller redesign)
