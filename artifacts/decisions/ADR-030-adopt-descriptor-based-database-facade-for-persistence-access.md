# ADR-030: Adopt descriptor-based `Database` facade for persistence access

**Status:** Accepted  
**Date:** 2026-05-08  
**Tags:** persistence, architecture, database, facade, descriptors  
**Source Log:** agent#L1  

## Context

ADR-025 established that Nomarr is leaving the hand-written AQL module model behind in favour of the schema-driven persistence constructor. That decision explained what the new system replaces, but it did not fully lock in the positive architecture that contributors should build on going forward.

The current persistence layer now has a clear shape:

- `Database` in `nomarr/persistence/db.py` owns the ArangoDB connection and exposes collection instances as attributes
- `collections.py` declares one typed wrapper class per collection
- `collections_base.py` defines the shared collection base classes (`DocumentCollection`, `EdgeCollection`, `StateGraphCollection`, `VectorCollection`)
- `accessors.py` provides the instance-bound field and collection accessors that form the public persistence API
- `constructor/verbs.py` contains reusable AQL verb implementations rather than collection-specific query modules
- `EDGES` metadata on document collections defines graph relationships once and drives both traversal helpers and cascade compilation
- Dynamic vector collections are the only runtime-registered extension point, via `Database.register()`

Without an ADR for this target architecture, the codebase risks drifting back toward ad hoc persistence patterns: direct imports of collection internals, custom collection-specific AQL methods, separate cascade registries, or higher layers bypassing the `Database` facade.

## Decision

Nomarr standardises on a descriptor-based persistence architecture with `Database` as the only public entry point for higher layers.

### 1. Higher layers access persistence only through `Database`

Services, workflows, and components receive an injected `Database` instance and call persistence through its bound collection attributes:

```python
file_doc = db.library_files.path.get("/music/track.flac")
matching_tags = db.tags.rel.get.many("genre", limit=100, offset=0)
db.library_files.insert([{"path": "/music/track.flac"}])
```

Higher layers do **not** import `FieldAccessor`, collection wrapper classes, or constructor helpers directly.

### 2. Collections are declared as typed wrappers, then bound on the facade

Every concrete collection lives as a class in `nomarr/persistence/collections.py` and inherits from one of the shared bases in `collections_base.py`:

- `DocumentCollection` for standard vertex/document collections
- `EdgeCollection` for edge collections with `_from` / `_to`
- `StateGraphCollection` for document collections that own an atomic state-transition operation through a companion edge collection
- `VectorCollection` for vector template families that are instantiated dynamically at runtime

`Database.__init__()` is responsible for instantiating the static collection set and exposing each instance as a stable attribute.

### 3. Persistence methods are expressed through collection and field descriptors

The persistence API is built from reusable verbs instead of per-collection method classes.

Collection-level operations live on the collection instance itself, including the standard verbs such as:

- `get`
- `insert`
- `update`
- `upsert`
- `upsert_batch`
- `delete`
- `count`
- `aggregate`
- `truncate`
- `update_many` where applicable

Field-specific operations live under instance-bound `FieldAccessor`s:

```python
db.tags.rel.get("genre")
db.tags.rel.get.many("genre", limit=50)
db.tags.value.delete("rock")
db.library_files.path.upsert("/music/track.flac", {"size_bytes": 12345})
```

This keeps the persistence surface uniform across collections while still allowing field-scoped ergonomics.

### 4. `EDGES` metadata is the single relationship declaration

Graph relationships are declared once on document collection classes with `EdgeDef` metadata.

That metadata is authoritative for two behaviours:

1. `DocumentCollection` auto-attaches traversal helpers during construction
2. `Database._compile_all_cascades()` compiles outbound cascade deletes from the same declarations

Nomarr does not maintain a second hand-written traversal registry or a separate cascade map for these relationships.

### 5. Dynamic runtime registration is limited to vector collections

Runtime registration is supported only for vector-template collection families.

`Database.register(collection_name, template_name)` validates that:

- the concrete ArangoDB collection exists
- the requested template is supported
- the collection name matches the template class `NAME_PATTERN`

Once registered, the vector collection becomes a bound attribute on the `Database` instance and vector-aware cascades are recompiled.

No other collection family uses runtime registration.

### 6. Persistence stays single-step; orchestration belongs above it

Persistence owns data access primitives. Multi-step business operations remain compositions in components or workflows.

Examples:

- deleting and recreating several edge sets is component logic
- combining multiple persistence reads/writes into a use-case transaction surrogate is workflow or component logic
- persistence helper code may build one AQL statement, but it does not become a collection-specific orchestration layer

### 7. Persistence returns storage-shaped results

Persistence methods return raw document dictionaries, primitive counts, keys, or aggregated query results. Translation into DTOs or service-facing response models happens in higher layers.

## Consequences

**Positive:**

- Higher layers have one predictable persistence entry point: `Database`
- Collection wrappers stay thin and consistent because the verb system does the heavy lifting
- Traversal and cascade behaviour cannot drift apart because both are derived from `EDGES`
- Static collection attributes keep autocomplete and discoverability strong
- Dynamic vector collections remain supported without weakening the rest of the API surface
- The architecture matches the current implementation and existing persistence instructions

**Negative:**

- Returning storage-shaped dictionaries means higher layers must continue mapping results into domain or API DTOs where needed
- Some former “single persistence operation” behaviours are now explicit multi-call compositions in components, which can mean more than one database round trip
- Collection declarations are intentionally repetitive because explicit field registration is what enables the descriptor-based API

## Rejected alternatives

### Reintroduce collection-specific AQL operation classes

Rejected because this recreates the inconsistency and naming churn that ADR-025 intentionally removed.

### Allow higher layers to import collection wrapper classes directly

Rejected because it bypasses the injected `Database` facade, weakens discoverability, and makes runtime registration/cascade setup easier to bypass.

### Keep separate traversal and cascade registries

Rejected because it duplicates graph relationship knowledge and invites drift between read and delete semantics.

## References

- `nomarr/persistence/db.py`
- `nomarr/persistence/collections.py`
- `nomarr/persistence/collections_base.py`
- `nomarr/persistence/accessors.py`
- `nomarr/persistence/constructor/verbs.py`
- `.github/instructions/persistence.instructions.md`
- `docs/dev/architecture.md`
- ADR-025: `artifacts/decisions/ADR-025-schema-driven-persistence-constructor-supersedes-hand-written-aql-conventions.md`
