# Schema-Driven Persistence Constructor — Design Document

**Status:** Completed (Amended)  
**Author:** RnD-DDAuthor  
**Created:** 2026-04-10  
**Amended:** 2026-04-10  
**Amendment source:** `agent#L4` (round 1), `rnd-manager#L63` (Improver), PatternEnforcer, `agent#L5` (round 2), `agent#L6` (round 3 — range modifiers, lock cleanup, upsert simplification, order_by, unique enforcement, cascade registry), `agent#L7` + `rnd-manager#L72` (round 4 — range operators as .in() overload, Op enum)  

**Related Documents:**
- [ADR-003](../decisions/ADR-003-pure-boolean-state-graph-for-file-processing-pipeline.md) — State graph constraint
- [ADR-004](../decisions/ADR-004-schema-refactor-v1-graph-normalization.md) — Graph normalization
- [DD-discovery-worker-err1579-fix](../designs/archive/DD-discovery-worker-err1579-fix.md) — ERR 1579 pattern
- [ADR-016](../decisions/ADR-016-migrations-only-schema-changes.md) — Migrations only
- [ADR-024](../decisions/ADR-024-naming-convention.md) — Naming convention (superseded for persistence)

---

## Scope

nomarr/persistence/database/ — complete replacement of hand-written AQL persistence layer with a runtime schema-driven persistence constructor

---

## Problem Statement

The persistence layer in `nomarr/persistence/database/` has grown to **287 public methods** across **46 classes** in **52 files** totaling **~11,300 LOC**. The `Database` facade exposes **24 static properties** (one per operation class) plus **3 dynamic vector entrypoints** (`register_vectors_track_backbone`, `get_vectors_track_cold`, `get_vectors_track_maintenance`) and **4 facade-level methods** (`delete_vectors_by_file_id`, `delete_vectors_by_file_ids`, `get_version`, `set_version`). Every collection's CRUD, query, stats, and batch operations are hand-written AQL, producing massive duplication:

- **GET patterns** repeat identically across collections (lookup by `_key`, `_id`, field value with edge traversal)
- **UPSERT/UPDATE/DELETE** patterns are structurally identical with only collection names and field lists varying
- **Count/aggregate** queries differ only in collection name and filter fields
- **Batch variants** repeat the single-doc pattern with `FOR item IN @items` wrappers
- **Edge traversal** patterns (OUTBOUND/INBOUND for library filtering, tag enrichment) are copy-pasted across query modules

This creates three problems:
1. **Maintenance cost:** Adding a field to a collection requires updating every query that touches it. Adding a new collection requires writing 5-15 methods from scratch.
2. **Inconsistency:** Identical operations have different error handling, different return shapes, and different AQL patterns across collections (some use `DOCUMENT()`, some use `FOR ... FILTER`, some use `FIRST()`).
3. **Scale:** The 287-method surface makes API completion (ASR-0013) impractical by hand — the persistence layer would grow to 400+ methods.

The hand-written approach made sense when the schema was evolving rapidly. Now that ADR-003 (state graph), ADR-004 (graph normalization), and the edge-first schema are stable, the patterns are predictable enough to derive from schema.

---

## Architecture

## 1. System Overview

A **schema definition** (Python dict in `persistence/schema.py`) declares all collections, fields, edges, and verb configurations. A **runtime constructor** reads this schema at import time and dynamically builds nested namespace objects — one per collection — using descriptors and `__call__`-based chaining. The `Database` facade wires to these constructed namespaces exactly as it does today. **All existing method names will break** — no in-code shims or compatibility wrappers. A separate migration mapping document (old method → new verb equivalent) will be created for developers.

```
persistence/schema.py (source of truth — Python dict)
    ↓ import time
persistence/constructor/ (runtime constructor library)
    ↓ builds dynamically
Namespace objects (in-memory, one CollectionNamespace per collection)
    ↓ wired by
persistence/db.py (Database facade)
```

### Design Principles

1. **Schema declares 100% of the persistence surface.** Every operation the DB can do is visible in the schema. No escape hatches, no hand-written side channels.
2. **100% schema-driven.** All operations are derived from verb declarations + nested accessor chain. The persistence layer IS the schema file + the constructor library.
3. **Runtime construction, not build-time generation.** No generated files, no build step, no committed artifacts. The constructor reads the schema at import time and dynamically builds Operations classes.
4. **Type stubs for tooling.** Protocol classes or `.pyi` stub files provide mypy checking and IDE autocomplete for the dynamically-constructed API.
5. **All callers migrate.** Every existing persistence method name changes to the nested accessor API. No compatibility wrappers. A migration mapping document is provided separately.

---

## 2. Schema Format Specification

### 2.1 Top-Level Structure

```python
SCHEMA: dict[str, CollectionSchema] = {
    "library_files": { ... },
    "tags": { ... },
    "file_states": { ... },
    "vectors_track": { ... },
    "libraries": { ... },
    # ... all collections
}
```

### 2.2 Collection Types

```python
class CollectionType(str, Enum):
    DOCUMENT = "document"          # Standard document collection
    EDGE = "edge"                  # Edge collection (has _from, _to)
    STATE_GRAPH = "state_graph"    # ADR-003 boolean state vertices + edges
    TEMPLATE = "template"          # Dynamic collection naming (vectors_track_*)
    INFRASTRUCTURE = "infrastructure"  # meta, migrations — low-ceremony, few ops
```

**State graph** collections get the `transition` verb and axis-parametric validation. **Template** collections get a factory pattern with dynamic naming. **Infrastructure** collections get minimal key-value operations.

### 2.3 Collection Schema Shape

The schema IS the API shape. Collection-level capabilities become `db.collection.verb`, field-level capabilities become `db.collection.field.verb`.

```python
SCHEMA = {
    "library_files": {
        "type": "document",
        "capabilities": ["insert", "delete", "cascade", "count", "transition"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get"]},
            "_id": {"type": "str", "capabilities": ["get"]},
            "path": {"type": "str", "capabilities": ["get", "update", "delete"], "unique": True},
            "library_key": {"type": "str", "capabilities": ["get", "count", "delete"]},
            "status": {"type": "str", "capabilities": ["get", "update"]},
            "modified_time": {"type": "int", "capabilities": ["update"]},
            "duration_seconds": {"type": "float", "capabilities": ["get"]},
        },
        "operators": {
            "get": ["in", "like"],  # Modifiers on field-level get; .in() accepts list[str] (IN) or dict[Op, FilterValue] (range/comparison)
        },
        "edges": {
            "song_has_tags": {"target": "tags", "direction": "OUTBOUND"},
            "file_has_state": {"target": "file_states", "direction": "OUTBOUND"},
            "file_has_vectors": {"target": "vectors_track", "direction": "OUTBOUND"},
            "file_has_segment_stats": {"target": "segment_scores_stats", "direction": "OUTBOUND"},
            "library_contains_file": {"target": "libraries", "direction": "INBOUND"},
        },
        "cascade": ["file_has_state", "song_has_tags", "file_has_vectors", "library_contains_file", "file_has_segment_stats"],
    },
    "tags": {
        "type": "document",
        "capabilities": ["insert", "delete", "cascade", "count"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get"]},
            "_id": {"type": "str", "capabilities": ["get"]},
            "rel": {"type": "str", "capabilities": ["get", "count", "collect", "aggregate"]},
            "value": {"type": "TagValue", "capabilities": ["get"]},
        },
        "edges": {
            "song_has_tags": {"target": "library_files", "direction": "INBOUND"},
            "tag_model_output": {"target": "ml_model_outputs", "direction": "OUTBOUND"},
        },
        "cascade": ["tag_model_output", "song_has_tags"],
    },
}
```

**Schema-to-API mapping:**
- Collection `"capabilities": ["insert", ...]` → `db.library_files.insert(doc)`
- Field `"capabilities": ["get", "update"]` → `db.library_files.status.get(value)`, `db.library_files.status.update(value, fields)`
- Field `"capabilities": ["delete"]` → `db.library_files.path.delete(value)` — bulk delete all docs where field matches
- Edge declaration → `db.library_files.traversal(start, edge="song_has_tags")`
- Cascade list → what `db.library_files.cascade(ids)` walks

**Field properties:**
- `type`: Python type annotation string (used in type stubs)
- `capabilities`: List of verbs this field supports — maps directly to methods on the field namespace
- `unique`: Whether the field has a unique index (affects return cardinality: unique → `dict | None`, non-unique → `list[dict]`). Also controls whether `.get.one()` is generated — see §3.6.
- `nullable`: Whether the field can be None (affects type annotations)
- `operators`: Dict of verb → list of modifiers. For `get`: `["in", "like"]`. The `.in()` modifier is overloaded: when passed `list[str]` it emits `FILTER field IN @values` (standard IN operator); when passed `dict[Op, FilterValue]` it emits comparison operators per `Op` key (e.g., `{Op.LT: 100}` → `FILTER field < 100`). See §2.8 for the `Op` enum definition. String-oriented operators (`like`) work on string fields.

### 2.4 Schema Validation Rules

The constructor validates the schema at import time:

1. **Collection capabilities must be valid verbs:** Only `insert`, `delete`, `cascade`, `count`, `transition`, `traversal`, `ann_search` at collection level.
2. **Field capabilities must be valid verbs:** Only `get`, `count`, `collect`, `aggregate`, `update`, `upsert`, `delete` at field level.
3. **`ann_search` is restricted to template (vector) collections ONLY.** If any other collection type declares `ann_search` in its capabilities, the constructor raises `SchemaValidationError` at import time. This is a hard constraint — vector search has no meaning on non-vector collections.
4. **`transition` requires `state_graph` type** or a valid `edge_collection` + `axes` declaration.
5. **`cascade` targets must reference declared edge collections.**
6. **`unique` fields** — `get` on a unique field defaults to `.get.one(value)` returning `dict | None`; on non-unique defaults to `.get.many(value)` returning `list[dict]`.
7. **`.get.one` requires `"unique": true`.** The constructor ONLY generates the `.one` modifier on field-level `get` namespaces where the field has `"unique": true` in the schema. Accessing `.one` on a non-unique field is an `AttributeError` at import time, not a runtime check. This prevents cardinality bugs where callers assume at-most-one when the schema allows many.
8. **Lock collection uses standard CRUD.** The `locks` collection declares standard capabilities (`insert`, `get`, `update`, `delete`) with a `"unique": true` constraint on its document reference field. There is NO lock-specific verb, `try_lock`, or TTL-conditional CAS UPSERT. Lock lifecycle = pure CRUD: insert (acquire), get (check), update (complete), delete (release). Expiry checking = component calls `get` + checks timestamp in Python.

### 2.5 Edge Definitions

Edges are declared per-collection with explicit direction:

```python
"edges": {
    "song_has_tags": {"target": "tags", "direction": "OUTBOUND"},
    "file_has_state": {"target": "file_states", "direction": "OUTBOUND"},
    "library_contains_file": {"target": "libraries", "direction": "INBOUND"},
},
```

**Direction is always explicit.** The `direction` field is mandatory on every edge declaration. The constructor reads it directly — no inference from naming conventions or edge collection position.

Edges needing BOTH directions are declared on both collections:
- `song_has_tags` is OUTBOUND on `library_files`, INBOUND on `tags`
- `library_contains_file` is OUTBOUND on `libraries`, INBOUND on `library_files`

### 2.6 Cascade Targets

Each collection declares its cascade targets — edge collections whose connected documents should be cleaned up on delete:

```python
"cascade": ["file_has_state", "song_has_tags", "file_has_vectors", "library_contains_file", "file_has_segment_stats"]
```

When `cascade` is called on a collection's documents, it walks each target edge collection, finds connected documents. If removing the edge creates an island (orphaned document with no remaining edges), cascade recursively calls delete on the target collection, which triggers THAT collection's cascade.

### 2.7 Dynamic Collection Templates

Template collections support parameterized naming for collections that vary by backbone and library:

```python
"vectors_track": {
    "type": "template",
    "name_pattern": "vectors_track_{tier}__{backbone_id}__{library_key}",
    "collection_suffix": True,  # Supports optional __{suffix} for test/staging variants
    "tiers": {
        "hot": {
            "fields": { ... },
            "verbs": { ... },
        },
        "cold": {
            "fields": { ... },
            "verbs": { ... },
        },
    },
    "maintenance": {
        # NOT a separate collection tier — an operations class that
        # orchestrates across hot+cold collections for a given backbone+library.
        # Methods like drain_to_cold, rebuild_index operate on the hot/cold pair.
        "operates_on": ["hot", "cold"],
        "verbs": { ... },
    },
}
```

**Cold collection suffix:** The current codebase supports `vectors_track_cold__{backbone_id}__{library_key}[__{suffix}]` with an optional suffix for test/staging variants. The `collection_suffix` flag in the template enables this.

**Maintenance is NOT a third collection tier.** `VectorsTrackMaintenanceOperations` is an operations class that receives both hot and cold collection references and orchestrates cross-tier operations (drain, rebuild, etc.). The template schema models this as a separate `maintenance` key with `operates_on` declaring which tiers it spans.

**Genre-filtered ANN:** The `ann_search` verb's `filter` parameter (§3.2) covers the `search_similar_by_genre` use case. No separate method is needed — `ann_search(query_vector, limit, nprobe, filter={"genre": "rock"})` applies pre-filtering before the approximate nearest neighbor search.

### 2.8 Op Enum and FilterDict (Range/Comparison via `.in()` Overload)

Range and comparison filtering is NOT a standalone modifier family. It is an **overload of the `.in()` method** on the get modifier namespace.

```python
from enum import Enum

FilterValue = int | float | bool | str
FilterDict = dict["Op", FilterValue]

class Op(str, Enum):
    LT = "lt"
    GT = "gt"
    LTE = "lte"
    GTE = "gte"
    EQ = "eq"
    NEQ = "neq"
    NOT = "not"
```

The `.in()` method's `values` parameter accepts either:
- `list[str]` — standard IN operator: `FILTER field IN @values`
- `FilterDict` (`dict[Op, FilterValue]`) — range/comparison filter: each `Op` key emits the corresponding AQL comparison operator

**Usage examples:**
```python
# Standard IN — list of exact values
db.locks.lock_type.get.in(["capacity_probe", "vector_promote"], limit=10)

# Range filter — dict with operator constants
db.locks.expires_at.get.in({Op.LT: time.time()}, limit=10)

# Compound range — multiple operators in one dict
db.locks.acquired_at.get.in({Op.GTE: start_ts, Op.LT: end_ts})

# Negation
db.locks.status.get.in({Op.NEQ: "completed"})
```

**Constructor behavior:** The `.in()` method checks the type of `values` at runtime:
- If `list` → emit `FOR doc IN @@collection FILTER doc.@field IN @values` AQL
- If `dict` → iterate Op keys, emit appropriate comparison per key (e.g., `Op.LT` → `FILTER doc.@field < @value`, `Op.GTE` → `FILTER doc.@field >= @value`). Multiple Op keys in one dict produce `AND`-combined filters.

**Implementation note:** `in` is a Python reserved word. The actual method is `in_()` internally, exposed as `.in()` via `__getattr__` aliasing on `GetModifierNamespace` (same pattern described in §6.6).

---

## 3. Verb Set & Nested Accessor Pattern

### 3.1 Core API Shape: Nested Accessors

The API uses **nested descriptor/namespace objects**, NOT flat methods. Each level is a descriptor that returns the next namespace. The constructor builds these namespaces from the schema at import time.

**Collection-level** (verb directly on collection namespace):
```python
db.collection.insert(doc)           # collection-level insert
db.collection.delete(ids)           # collection-level delete by ID
db.collection.cascade(ids)          # collection-level cascade
db.collection.count()               # collection-level total count
db.collection.get(id)               # shorthand → get.one.id(id)
db.collection.transition(ids, from, to)  # collection-level transition
db.collection.ann_search(vector, limit, nprobe, filter)  # vector collections only
db.collection.traversal(start, edge, ...)  # traversal
```

**Field-level** (verb on field namespace):
```python
db.collection.field.get(value)        # get by field
db.collection.field.count(value)      # count by field
db.collection.field.collect()         # distinct values of field
db.collection.field.aggregate()       # values + counts
db.collection.field.update(value, fields)  # update by field
db.collection.field.upsert(doc, match)     # upsert matching field
db.collection.field.delete(value)     # bulk delete by field (returns count deleted)
```

**Modifier nesting** (on get verbs):
```python
db.collection.get.one.id(_id)         # explicit: one doc by _id
db.collection.get.many.id([ids])      # explicit: many docs by _id list
db.collection.field.get.one(value)    # one doc by field (unique fields)
db.collection.field.get.many(values)  # many docs by field (non-unique)
db.collection.field.get.in(values)    # IN operator (list[str]) or range/comparison filter (FilterDict) — see §2.8
db.collection.field.get.like(pattern) # LIKE operator
```

**Shorthands** (implicit defaults):
```python
db.collection.get(id)     # = get.one.id(id) — simplest form
db.collection.get.one     # = get.one.id — default accessor is _id
```

**Key design decisions:**
- The constructor builds **namespace objects**, not named methods
- Each level is a descriptor that returns the next namespace
- No Django-style double-underscore operators (`__in`, `__like`) — operators are explicit method names in the accessor chain (`.in()`, `.like()`)
- Return cardinality is obvious from `.one` vs `.many` in the call chain

### 3.2 Verb Scope Table

| Scope | Verbs | Accessor Pattern |
|-------|-------|-----------------|
| **Collection-level** | `insert`, `delete`, `cascade`, `count` (no field), `get` (shorthand) | `db.collection.verb(...)` |
| **Field-level** | `get`, `count`, `collect`, `aggregate`, `update`, `upsert`, `delete` | `db.collection.field.verb(...)` |
| **Specialized** | `transition`, `traversal`, `ann_search` | `db.collection.verb(...)` |

### 3.3 Complete Verb Table (12 verbs)

| # | Verb | Scope | Accessor Pattern |
|---|------|-------|-----------------|
| 1 | **get** | Collection + Field | `db.col.get(id)`, `db.col.field.get(value)`, `db.col.field.get.one(v)`, `.many(v)`, `.in([v] or {Op: v})`, `.like(p)` |
| 2 | **insert** | Collection | `db.col.insert(doc)` |
| 3 | **upsert** | Field | `db.col.field.upsert(doc, match_field)` |
| 4 | **update** | Field | `db.col.field.update(match_value, fields)` |
| 5 | **delete** | Collection + Field | `db.col.delete(ids)`, `db.col.field.delete(value)` |
| 6 | **count** | Collection + Field | `db.col.count()`, `db.col.field.count(value)` |
| 7 | **collect** | Field | `db.col.field.collect()` |
| 8 | **aggregate** | Field | `db.col.field.aggregate()` |
| 9 | **traversal** | Collection | `db.col.traversal(start, edge=...)` |
| 10 | **transition** | Collection | `db.col.transition(ids, from_edge, to_edge)` |
| 11 | **cascade** | Collection | `db.col.cascade(ids)` |
| 12 | **ann_search** | Collection | `db.col.ann_search(vector, limit, nprobe, filter?)` |

### 3.4 Implicit Bulk

All verbs that operate on documents accept either a single value or a list. The constructor handles the difference internally:

```python
# Single
db.library_files.insert({"path": "/music/song.flac", ...})
# Bulk — same verb, list input
db.library_files.insert([{"path": "/music/a.flac"}, {"path": "/music/b.flac"}])

# Single transition
db.library_files.transition(["file_id_1"], from_edge, to_edge)
# Bulk transition — same verb, multiple IDs
db.library_files.transition(["file_id_1", "file_id_2", "file_id_3"], from_edge, to_edge)
```

There are no separate `_batch` or `bulk_` variants. The constructor inspects the input type and dispatches to single-doc or batch AQL accordingly.

### 3.5 Mandatory Pagination

All verbs that CAN return unbounded results MUST expose pagination parameters:

```python
db.library_files.library_key.get.many("abc", limit=50, offset=0)
db.tags.rel.collect(limit=100, offset=0)
db.tags.rel.aggregate(limit=100, offset=0)
db.library_files.traversal("library_files/abc", edge="song_has_tags", limit=50, offset=0)
```

The pagination parameters are:
- `limit: int | None = None` — maximum results to return (None = configured default, NOT unbounded)
- `offset: int = 0` — skip this many results

Verbs requiring pagination: `get.many`, `get.in`, `get.like`, `collect`, `aggregate`, `traversal`, `ann_search`.

Verbs NOT paginated: `get.one`, `insert`, `upsert`, `update`, `delete`, `count`, `cascade`, `transition`.

### 3.6 Complete Verb Signatures

#### Collection-level signatures

```python
# GET (collection shorthand + explicit forms)
collection.get(id: str) -> dict | None
    # Shorthand for get.one.id(id)
collection.get.one.id(id: str) -> dict | None
    # Single document by _id — python-arango direct access, no AQL
collection.get.many.id(ids: list[str]) -> list[dict]
    # Multiple documents by _id list

# INSERT
collection.insert(doc: dict | list[dict]) -> str | list[str]
    # Insert one or many documents, return _id(s)

# DELETE (collection-level: by ID)
collection.delete(ids: str | list[str]) -> None
    # Delete document(s) by _id

# COUNT (collection-level: total count)
collection.count() -> int
    # Total documents in collection

# CASCADE
collection.cascade(ids: str | list[str]) -> int
    # Recursive edge-walk + island detection, returns total deleted count

# TRANSITION (state graph — ADR-003 + ERR 1579)
collection.transition(ids: list[str], from_edge_target: str, to_edge_target: str) -> None
    # Three-phase READ→REMOVE→INSERT per ERR 1579

# TRAVERSAL
collection.traversal(
    start: str | dict,
    edge: str,
    *,
    target_filter: dict | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]
    # Graph traversal — see §4 for modes

# ANN_SEARCH (vector template collections ONLY)
collection.ann_search(
    query_vector: list[float],
    limit: int,
    nprobe: int,
    *,
    filter: dict | None = None,
) -> list[dict]
    # APPROX_NEAR_COSINE with nprobe. SchemaValidationError if declared
    # on any non-template collection type.
```

#### Field-level signatures

```python
# GET (field-level: with modifier chain)
collection.field.get(value: T) -> dict | None
    # Shorthand — resolves to get.one(value) for unique fields,
    # get.many(value) for non-unique fields
collection.field.get.one(value: T) -> dict | None
    # Single document where field == value
collection.field.get.many(value: T, *, limit: int | None = None, offset: int = 0) -> list[dict]
    # All documents where field == value (paginated)
collection.field.get.in(values: list[T], *, limit: int | None = None, offset: int = 0) -> list[dict]
    # Documents where field IN values list (standard IN operator)
collection.field.get.in(values: FilterDict, *, limit: int | None = None, offset: int = 0) -> list[dict]
    # Documents matching range/comparison filter (see §2.8 for Op enum and FilterDict)
collection.field.get.like(pattern: str, *, limit: int | None = None, offset: int = 0) -> list[dict]
    # Documents where field LIKE pattern (AQL LIKE operator)

# UPDATE (field-level: match by field value)
collection.field.update(match_value: T, fields: dict) -> None
    # Update all documents where field == match_value, setting fields

# UPSERT (field-level: match on field)
collection.field.upsert(doc: dict | list[dict], match_field: str) -> str | list[str]
    # UPSERT with match on field, returns _id(s)

# COUNT (field-level: count by field value)
collection.field.count(value: T) -> int
    # Count documents where field == value

# COLLECT (field-level: distinct values)
collection.field.collect(*, limit: int | None = None, offset: int = 0) -> list[T]
    # Distinct values of field across collection

# AGGREGATE (field-level: values + counts)
collection.field.aggregate(*, limit: int | None = None, offset: int = 0) -> list[AggResult]
    # Distinct values with occurrence counts

# DELETE (field-level: bulk delete by field match)
collection.field.delete(value: T) -> int
    # Delete all documents where field == value, returns count deleted
```

### 3.7 Verb Details

#### GET verb

```python
# Collection-level shorthand
db.library_files.get("library_files/abc123")          # → dict | None (= get.one.id)

# Explicit modifier chain — collection level
db.library_files.get.one.id("library_files/abc123")   # → dict | None
db.library_files.get.many.id(["library_files/abc", "library_files/def"])  # → list[dict]

# Field-level — unique field (path)
db.library_files.path.get("/music/song.flac")         # → dict | None (unique → get.one)
db.library_files.path.get.one("/music/song.flac")     # → dict | None (explicit)

# Field-level — non-unique field (library_key)
db.library_files.library_key.get("abc")               # → list[dict] (non-unique → get.many)
db.library_files.library_key.get.many("abc", limit=50)  # → list[dict] (explicit)

# Field-level — operators as methods
db.tags.rel.get.in(["genre", "mood"], limit=100)      # → list[dict] (IN operator — list mode)
db.tags.rel.get.like("genre%", limit=50)              # → list[dict] (LIKE operator)

# Field-level — .in() with range/comparison filter (FilterDict mode — see §2.8)
db.locks.expires_at.get.in({Op.LT: time.time()}, limit=10)        # → list[dict] (range: expires_at < now)
db.locks.acquired_at.get.in({Op.GTE: start_ts, Op.LT: end_ts})    # → list[dict] (compound range)
db.locks.status.get.in({Op.NEQ: "completed"})                      # → list[dict] (negation)
```

- **Return type:** Determined by `.one` vs `.many` in the chain, NOT by field uniqueness (though shorthands use uniqueness to pick the default).
- **`_key`/`_id` lookups** use python-arango direct access (no AQL). All others use AQL `FOR ... FILTER`.

#### INSERT verb
```python
db.library_files.insert({"path": "/music/song.flac", "library_key": "abc", ...})
# → "library_files/abc123"

db.library_files.insert([{"path": "/music/a.flac"}, {"path": "/music/b.flac"}])
# → ["library_files/abc", "library_files/def"]
```

#### UPSERT verb
```python
db.library_files.path.upsert(
    {"path": "/music/song.flac", "library_key": "abc", ...},
    match_field="path",
)
# AQL: UPSERT { path: @key_value } INSERT @doc UPDATE @doc IN library_files RETURN NEW._id
```

#### UPDATE verb
```python
db.library_files.status.update("pending", {"status": "processed"})
# Updates all docs where status == "pending", setting status to "processed"
```

#### DELETE verb (collection-level and field-level)
```python
# Collection-level: delete by ID
db.library_files.delete("library_files/abc123")
db.library_files.delete(["library_files/abc", "library_files/def"])

# Field-level: bulk delete by field value
db.library_files.library_key.delete("old_library")
# → int (count of documents deleted where library_key == "old_library")
```

#### COUNT verb
```python
# Collection-level: total count
db.library_files.count()  # → int

# Field-level: count by field value
db.library_files.library_key.count("abc")  # → int
```

#### COLLECT verb
```python
db.tags.rel.collect(limit=100, offset=0)  # → ["genre", "mood", "era", ...]
```

#### AGGREGATE verb
```python
db.tags.rel.aggregate(limit=100)  # → [{"value": "genre", "count": 42}, ...]
```

#### TRANSITION verb (state graph — ADR-003 + ERR 1579)

**Constraint:** ArangoDB ERR 1579 forbids reading and writing the same collection in a single AQL statement.

```python
# Generic signature — persistence does NOT know what "tagged" means
db.library_files.transition(
    ["library_files/abc", "library_files/def"],  # List of IDs (bulk implicit)
    from_edge_target="file_states/not_tagged",     # Current state vertex
    to_edge_target="file_states/tagged",           # Target state vertex
)
```

Internally emits three separate AQL calls per ERR 1579:

```python
def transition(self, ids: list[str], from_edge_target: str, to_edge_target: str) -> None:
    for file_id in ids:  # Or batched variant
        # Phase 1: READ — find existing edge key
        cursor = self.db.aql.execute(
            "FOR e IN file_has_state FILTER e._from == @file_id AND e._to == @from RETURN e._key",
            bind_vars={"file_id": file_id, "from": from_edge_target},
        )
        old_key = next(cursor, None)

        # Phase 2: REMOVE — separate execution
        if old_key is not None:
            self.db.aql.execute(
                "REMOVE @key IN file_has_state",
                bind_vars={"key": old_key},
            )

        # Phase 3: INSERT — separate execution
        self.db.aql.execute(
            "INSERT { _from: @file_id, _to: @to } INTO file_has_state",
            bind_vars={"file_id": file_id, "to": to_edge_target},
        )
```

**Design decisions:**
- **Three separate `aql.execute()` calls** (read, remove, insert) — never combine read+write on the same edge collection in one statement. This is the ERR 1579 rule.
- **REMOVE+INSERT, not REMOVE+UPSERT.** ADR-003 requires singleton edge per axis. INSERT after REMOVE makes the singleton guarantee explicit.
- **Generic signature:** `transition(ids, from_edge_target, to_edge_target)` — persistence does not encode domain concepts like "tagged" or "calibrated". The component layer maps domain terms to edge targets.
- **Accepts list of IDs:** Bulk is implicit. Single ID = list of one.

**Axis definitions in schema (for validation, not for method naming):**
```python
"file_states": {
    "type": "state_graph",
    "edge_collection": "file_has_state",
    "axes": {
        "tagged": ("file_states/tagged", "file_states/not_tagged"),
        "too_short": ("file_states/too_short", "file_states/not_too_short"),
        "calibrated": ("file_states/calibrated", "file_states/not_calibrated"),
        "tags_written": ("file_states/tags_written", "file_states/tags_not_written"),
        "tags_current": ("file_states/tags_current", "file_states/tags_stale"),
        "scanned": ("file_states/scanned", "file_states/not_scanned"),
        "vectors_extracted": ("file_states/vectors_extracted", "file_states/not_vectors_extracted"),
        "errored": ("file_states/errored", "file_states/not_errored"),
    },
}
```

The constructor validates that `from_edge_target` and `to_edge_target` arguments match declared axis pairs, but does NOT generate named methods like `set_tagged()`. State semantics belong to the component layer.

#### CASCADE verb

```python
db.library_files.cascade(["library_files/abc", "library_files/def"])
# → int (total documents deleted across all cascade targets)
```

Cascade walks the declared cascade targets for the collection:
1. For each target edge collection, find edges connected to the document(s)
2. Remove those edges
3. Check if removing the edge creates an island (orphaned document with no remaining edges to ANY collection)
4. If island detected, recursively call `delete` on the target collection — which triggers THAT collection's cascade

Cascade targets are schema-declared (§2.6), making the cascade graph auditable and predictable.

#### ANN_SEARCH verb

```python
db.vectors_track_hot__discogs__my_library.ann_search(
    query_vector=[0.1, 0.2, ...],
    limit=10,
    nprobe=128,
    filter={"genre": "rock"},  # Optional pre-filter
)
# → list[dict]
```

AQL `APPROX_NEAR_COSINE` with `nprobe` hyperparameter. Not expressible as a filter on `get` — requires its own verb.

**Constraint:** `ann_search` can ONLY be declared on template (vector) collections. If any other collection type includes `ann_search` in its `capabilities` list, the constructor raises `SchemaValidationError` at import time. This prevents nonsensical configurations and makes the restriction explicit in the schema validation layer.

---

## 4. Traversal Design

**Single method on the collection namespace with three modes**, disambiguated by argument type:

```python
collection.traversal(
    start: str | dict,      # Mode 1: str (doc ID) | Mode 2-3: dict (source filters)
    edge: str,              # Edge collection to traverse
    *,
    target_filter: dict | None = None,  # Mode 3: dict of filters on target docs
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]
```

### Mode 1: Start from document ID
```python
# Get all tags for a specific file
db.library_files.traversal("library_files/abc123", edge="song_has_tags")
# AQL: FOR v IN 1..1 OUTBOUND @start_id song_has_tags LIMIT @limit RETURN v
```

### Mode 2: Source collection filter → connected docs
```python
# Get all tags for files in a library
db.library_files.traversal(
    {"library_key": "my_library"},
    edge="song_has_tags",
    limit=100,
)
# AQL: FOR doc IN library_files FILTER doc.library_key == @val
#      FOR v IN 1..1 OUTBOUND doc song_has_tags LIMIT @limit RETURN v
```

### Mode 3: Source filter → connected docs with target filter
```python
# Get genre tags for files in a library
db.library_files.traversal(
    {"library_key": "my_library"},
    edge="song_has_tags",
    target_filter={"rel": "genre"},
    limit=100,
)
# AQL: FOR doc IN library_files FILTER doc.library_key == @val
#      FOR v IN 1..1 OUTBOUND doc song_has_tags
#      FILTER v.rel == @target_val LIMIT @limit RETURN v
```

**Mode disambiguation:** The constructor branches on whether `start` is a string (doc ID → Mode 1) or a dict (filters → Mode 2 or 3). This is straightforward type-based dispatch, not fragile overloading.

All modes support `limit`/`offset` pagination. Direction is read from the edge declaration in the schema — never inferred.

---

## 5. Coverage Analysis

### 5.1 Verb Coverage Progression

The Improver analysis (`rnd-manager#L63`) established that 100% schema-driven coverage is achievable:

| Stage | Coverage | What's added |
|-------|----------|---------------|
| 10 verbs (base: 8 original + transition + cascade) | ~78% | Standard CRUD, queries, state graph, cascade |
| + Modifier chain operators (IN, LIKE on get) | ~91% | Complex queries become expressible via `.get.in()`, `.get.like()` |
| + `ann_search` verb | ~95% | Vector similarity search |
| + Dynamic collection templates | ~98% | Parameterized vector collections |
| + Move 3 orchestration violations out | ~99.5% | Not persistence → not counted |
| + Field-level delete | ~100% | Bulk delete by field value |

### 5.2 Formerly-Custom Operations: Disposition

Every operation that was previously considered "non-generatable" has been re-analyzed:

| Operation | Old Classification | New Disposition |
|-----------|-------------------|----------------|
| State graph transitions (~40 methods) | custom_op | `transition` verb ✓ |
| Cascade orphan cleanup (5 methods) | custom_op | `cascade` verb ✓ |
| Batch variants (~8 methods) | separate verbs | Implicit bulk ✓ |
| `relink_tag_edges` | custom_op | Component-layer composition: get→upsert→delete→cascade |
| `set_song_tags` | custom_op | delete(edges) → upsert(tags) → upsert(edges) — needs IN-operator filter |
| `search_library_files_with_tags` | custom_op | get with LIKE operator + edge expand |
| Lock helpers (8 methods) | custom_op | Standard CRUD on `locks` collection (get/upsert/update/delete) — no lock-specific verb needed |
| `drain_to_cold` | custom_op | **Orchestration violation** → workflow layer |
| `backfill_genres` | custom_op | **Orchestration violation** → workflow layer |
| `claim_files_for_reconciliation` | custom_op | **Orchestration violation** → component layer |
| Vector ANN search | custom_op | `ann_search` verb ✓ |
| Discovery queries | custom_op | get with operator modifiers + traversal |

### 5.3 Operations That Move OUT of Persistence

Three operations are orchestration violations — they don't belong in persistence regardless of verb coverage:

| Method | Why It's Not Persistence | Target Layer |
|--------|--------------------------|-------------|
| `drain_to_cold` | Workflow-level lifecycle management (hot→cold promotion with edge migration) | Workflow |
| `backfill_genres` | Multi-hop traversal data migration | Workflow |
| `claim_files_for_reconciliation` | Cross-module orchestration with claim mechanics | Component |

### 5.4 Component-Layer Compositions

Some operations that appear complex are actually multi-verb compositions that belong at the component layer:

```python
# relink_tag_edges — component layer, not persistence
def relink_tag_edges(db, source_tag_id, target_tag_id, song_ids=None):
    edges = db.song_has_tags._to.get.many(source_tag_id)  # Step 1: get edges to source tag
    db.song_has_tags.insert([{"_from": e["_from"], "_to": target_tag_id} for e in edges])  # Step 2: insert new edges
    db.song_has_tags._to.delete(source_tag_id)  # Step 3: delete old edges by field
    db.tags.cascade([source_tag_id])  # Step 4: cascade if orphaned

# set_song_tags — component layer
def set_song_tags(db, song_id, rel, values):
    db.song_has_tags._from.delete(song_id)  # Delete old tag edges for song
    db.tags.rel.upsert([{"rel": rel, "value": v} for v in values], match_field="value")  # Upsert tag vertices
    db.song_has_tags.insert([{"_from": song_id, "_to": tag_id} for tag_id in new_tag_ids])  # Create edges
```

---

## 6. Constructor Implementation

### 6.1 Namespace Object Architecture

The constructor builds **nested namespace objects**, not flat method dictionaries. Each level in the accessor chain (`db.collection.field.verb.modifier`) is a descriptor or namespace object that returns the next level.

**Three namespace levels:**

1. **Collection namespace** — `db.collection` — has collection-level verbs (`insert`, `delete`, `cascade`, `count`, `transition`, `traversal`, `ann_search`, `get` shorthand) + field sub-namespaces
2. **Field namespace** — `db.collection.field` — has field-level verbs (`get`, `count`, `collect`, `aggregate`, `update`, `upsert`, `delete`) + modifier sub-namespaces on `get`
3. **Modifier namespace** — `db.collection.field.get` — has `.one()`, `.many()`, `.in()`, `.like()` as terminal methods

```
db.library_files                          # CollectionNamespace
├── .insert(doc)                          # collection-level verb (callable)
├── .delete(ids)                          # collection-level verb (callable)
├── .cascade(ids)                         # collection-level verb (callable)
├── .count()                              # collection-level verb (callable)
├── .get(id)                              # shorthand → get.one.id(id) (callable)
│   ├── .one                              # ModifierNamespace
│   │   └── .id(id)                       # terminal method (callable)
│   └── .many                             # ModifierNamespace
│       └── .id(ids)                      # terminal method (callable)
├── .transition(ids, from, to)            # collection-level verb (callable)
├── .traversal(start, edge, ...)          # collection-level verb (callable)
├── .path                                 # FieldNamespace (unique field)
│   ├── .get(value)                       # shorthand → get.one(value) (callable)
│   │   ├── .one(value)                   # terminal (callable)
│   │   ├── .many(value, limit, offset)   # terminal (callable)
│   │   ├── .in(values, limit, offset)    # terminal (callable) — list[T] or FilterDict (§2.8)
│   │   └── .like(pattern, limit, offset) # terminal (callable)
│   ├── .update(match_value, fields)      # field-level verb (callable)
│   ├── .upsert(doc, match_field)         # field-level verb (callable)
│   └── .delete(value)                    # field-level verb (callable)
├── .library_key                          # FieldNamespace (non-unique field)
│   ├── .get(value)                       # shorthand → get.many(value) (callable)
│   │   ├── .one(value)                   # terminal
│   │   ├── .many(value, limit, offset)   # terminal
│   │   ├── .in(values, limit, offset)    # terminal — list[T] or FilterDict (§2.8)
│   │   └── .like(pattern, limit, offset) # terminal
│   ├── .count(value)                     # field-level verb
│   └── .delete(value)                    # field-level verb
└── .status                               # FieldNamespace
    ├── .get(value)                       # shorthand
    │   └── ...modifiers...
    └── .update(match_value, fields)      # field-level verb
```

### 6.2 Descriptor Protocol for Chaining

Each namespace level implements `__getattr__` or uses descriptor protocol to return the next namespace:

```python
class CollectionNamespace:
    """Built per collection from schema. Holds collection-level verbs + field namespaces."""

    def __init__(self, db, collection_name: str, spec: dict):
        self._db = db
        self._collection_name = collection_name
        # Build collection-level verbs as bound methods
        # Build field namespaces as attributes
        for field_name, field_spec in spec.get("fields", {}).items():
            setattr(self, field_name, FieldNamespace(db, collection_name, field_name, field_spec))

class FieldNamespace:
    """Built per field from schema. Holds field-level verbs + get modifier namespace."""

    def __init__(self, db, collection_name: str, field_name: str, field_spec: dict):
        self._db = db
        self._field_name = field_name
        if "get" in field_spec.get("capabilities", []):
            self.get = GetModifierNamespace(db, collection_name, field_name, field_spec)
        # ... other verbs as methods

class GetModifierNamespace:
    """Callable (shorthand) + has .one(), .many(), .in(), .like() modifiers."""

    def __call__(self, value):
        """Shorthand: unique fields → one(), non-unique → many()."""
        if self._unique:
            return self.one(value)
        return self.many(value)

    def one(self, value) -> dict | None: ...
    def many(self, value, *, limit=None, offset=0) -> list[dict]: ...
    def in_(self, values: list | FilterDict, *, limit=None, offset=0) -> list[dict]:
        """Overloaded: list[str] → IN operator; dict[Op, FilterValue] → range/comparison (§2.8)."""
        ...
    def like(self, pattern, *, limit=None, offset=0) -> list[dict]: ...
```

### 6.3 Shorthand Resolution

Shorthands allow ergonomic access for common operations:

| Shorthand Call | Resolves To | Rule |
|---|---|---|
| `db.collection.get(id)` | `db.collection.get.one.id(id)` | Collection-level get defaults to _id lookup |
| `db.collection.get.one` | `db.collection.get.one.id` | Default accessor is _id |
| `db.collection.field.get(value)` | `db.collection.field.get.one(value)` | If field is `unique: True` |
| `db.collection.field.get(value)` | `db.collection.field.get.many(value)` | If field is NOT unique |

The collection-level `get` namespace is simultaneously callable (shorthand) and an attribute container (for `.one`, `.many`). This is implemented via `__call__` on the namespace object.

### 6.4 Runtime Construction (not build-time)

The constructor is a Python library that builds namespace objects dynamically at import time:

```python
# persistence/constructor/builder.py
from persistence.schema import SCHEMA

class SchemaConstructor:
    """Reads SCHEMA and builds namespace objects at import time."""

    def build_collection_namespace(self, collection_name: str, spec: dict) -> CollectionNamespace:
        """Build a typed CollectionNamespace from a collection schema spec."""
        ns = CollectionNamespace(self.db, collection_name, spec)

        # Add collection-level verbs from capabilities
        for verb in spec.get("capabilities", []):
            self._attach_collection_verb(ns, verb, collection_name, spec)

        # Collection-level get shorthand (always present — _id access)
        ns.get = CollectionGetNamespace(self.db, collection_name)

        # Field namespaces built from field declarations
        for field_name, field_spec in spec.get("fields", {}).items():
            field_ns = self._build_field_namespace(collection_name, field_name, field_spec)
            setattr(ns, field_name, field_ns)

        return ns
```
- **Descriptors:** Verb methods as descriptor objects that generate AQL on first access
- **`__getattr__`:** Lazy method construction on first attribute access
- **`type()` with closures:** Direct class construction with closure-captured AQL templates

### 6.5 Why Runtime, Not Build-Time

| Concern | Build-time codegen | Runtime constructor |
|---------|-------------------|--------------------|
| Build step required | Yes — must run generator, commit output | No — schema IS the code |
| Generated files to maintain | ~52 files in output directory | Zero generated files |
| Schema-code drift | Possible if someone forgets to regenerate | Impossible — schema is read every import |
| Pre-commit hooks | Required to catch stale generated code | Not needed |
| IDE/mypy support | Native (real .py files) | Via type stubs or Protocol classes |
| Debugger stepping | Real source files | Step into dynamically-built closures |
| Git diff noise | Every schema change produces large diffs in generated files | Only schema.py changes |
| Single source of truth | Schema + generated files (two copies) | Schema only (one copy) |

The key insight: **the persistence layer IS the schema file + the constructor library.** There is no second copy of the truth. The tradeoff is IDE/mypy support, which is addressed with type stubs.

### 6.6 Type Stubs for IDE/mypy Support

Since namespace objects are built dynamically, mypy and IDEs cannot infer their methods. Two approaches (choose during implementation):

**Option A: Protocol classes** (preferred)
```python
# persistence/stubs/library_files.pyi
class LibraryFilesPathGet(Protocol):
    def __call__(self, value: str) -> dict | None: ...
    def one(self, value: str) -> dict | None: ...
    def many(self, value: str, *, limit: int | None = ..., offset: int = ...) -> list[dict]: ...
    def in(self, values: list[str] | FilterDict, *, limit: int | None = ..., offset: int = ...) -> list[dict]: ...
    def like(self, pattern: str, *, limit: int | None = ..., offset: int = ...) -> list[dict]: ...

class LibraryFilesPath(Protocol):
    get: LibraryFilesPathGet
    def update(self, match_value: str, fields: dict) -> None: ...
    def upsert(self, doc: dict | list[dict], match_field: str) -> str | list[str]: ...
    def delete(self, value: str) -> int: ...

class LibraryFilesNamespace(Protocol):
    path: LibraryFilesPath
    def insert(self, doc: dict | list[dict]) -> str | list[str]: ...
    def delete(self, ids: str | list[str]) -> None: ...
    def cascade(self, ids: str | list[str]) -> int: ...
    def count(self) -> int: ...
    def transition(self, ids: list[str], from_edge_target: str, to_edge_target: str) -> None: ...
    def traversal(self, start: str | dict, edge: str, *, target_filter: dict | None = ...,
                  limit: int | None = ..., offset: int = ...) -> list[dict]: ...
```

**Implementation note on `.in()` naming:** Python reserves `in` as a keyword, so the attribute on the namespace object is stored as `in_` internally. The user-facing API exposes `.in()` via `__getattr__` aliasing on the `GetModifierNamespace`: accessing `.in` returns the `in_` method. Protocol stubs declare `def in(...)` for readability; the runtime uses `in_` as the attribute name. This is a one-time implementation detail — all other DD sections use `.in()` as the canonical API name.

**Option B: Auto-generated stubs** (can be added later)
A script reads `SCHEMA` and writes `.pyi` files. This is a convenience tool, not a build step — stubs are committed but the runtime doesn't depend on them.

---

## 7. Database Facade Wiring

### 7.1 What Changes

- **All method names:** Every method adopts the nested accessor API (e.g., `get_file_by_id(id)` → `library_files.get(id)`, `get_file_by_path(p)` → `library_files.path.get(p)`). Migration mapping document provided separately.
- **Import paths:** `persistence.database.X_aql` → dynamically constructed (no import path for namespace objects)
- **Orchestration methods** that call `parent_db.other_collection` move to components/workflows
- **Dynamic vector collections:** Same `register_vectors_track_backbone`/`get_vectors_track_cold` pattern, but underlying namespace objects built by constructor

### 7.2 What Stays the Same

- **Attribute names:** `db.library_files`, `db.tags`, `db.file_states` — identical
- **Connection management:** Same `create_arango_client`, `close()`, password loading
- **Facade-level methods preserved as-is:**

| Method | Disposition |
|--------|------------|
| `delete_vectors_by_file_id` | Facade method: iterates registered dynamic vector collections, calls `collection._from.delete(file_id)` on each + edge cleanup on `file_has_vectors` |
| `delete_vectors_by_file_ids` | Facade method: bulk variant of above |
| `get_version` | Facade method: delegates to `meta.key.get("version")` — the meta collection uses a `key` field (not `_key`) as the lookup/filter field |
| `set_version` | Facade method: delegates to `meta.key.upsert({key: "version", value: version}, match_field="key")` |

### 7.3 Facade Auto-Wiring

```python
class Database:
    def __init__(self, db):
        self.db = db
        constructor = SchemaConstructor(db)
        for name, spec in SCHEMA.items():
            if spec["type"] != "template":
                ns = constructor.build_collection_namespace(name, spec)
                setattr(self, name, ns)
        # Template collections wired lazily via register_* methods
```

The facade wires dynamically at startup. Callers use `db.library_files.path.get("/music/song.flac")` — the namespace behind the property is constructed from schema, not hand-written.

---

## 8. Migration Strategy

### 8.1 Incremental Transition

The transition is **per-collection, not big-bang:**

**Phase 1 — Schema + Constructor Infrastructure**
- Create `persistence/schema.py` with schema for all collections
- Build the constructor library in `persistence/constructor/`
- Create type stubs in `persistence/stubs/` (if using Protocol approach)
- No caller changes yet

**Phase 2 — Simple Collections First**
- Start with infrastructure collections (meta, migrations, health, sessions, locks, etc.)
- These have simple CRUD patterns
- Replace hand-written modules, verify tests pass
- ~10 collections, building confidence in the constructor

**Phase 3 — Complex Collections**
- library_files, tags, file_states (with transition, cascade, operator modifiers)
- This is where the full verb set is exercised
- Verify all methods are accounted for in the schema

**Phase 4 — Dynamic Collections**
- vectors_track with template collection support
- ann_search verb exercised here
- Factory pattern in schema for dynamic naming

**Phase 5 — Cleanup**
- Delete all hand-written AQL modules in `persistence/database/`
- Remove `persistence/database/` directory entirely
- Final structure: `persistence/schema.py` + `persistence/constructor/` + `persistence/stubs/` + `persistence/db.py`

### 8.2 Caller Migration

ALL existing method names will break. This is accepted and intentional.

- **No in-code shims or compatibility wrappers.**
- A separate **migration mapping document** (old method → new verb equivalent) will be created for developers during migration.
- The mapping document is NOT part of this DD — it will be created as a companion artifact during execution.
- Migration proceeds per-collection alongside Phase 2-4 above.

### 8.3 Orchestration Policy

**Policy:** Orchestration methods (multi-collection coordination via `parent_db.*`) are handled in TWO ways:

- **Cascade side effects** (referential integrity): Expressed via the `cascade` verb with schema-declared targets (§2.6). The constructor handles cascade automatically.
- **Business logic / pure orchestration / delegation wrappers**: Move to the component or workflow layer.

All orchestration violations categorized:

#### Category A: Full Orchestration — Extract to Component/Workflow (7 methods)

| Method | Target |
|--------|--------|
| `claim_files_for_reconciliation` | `components/library/reconciliation_comp.py` |
| `set_file_written` | Same |
| `release_claim` | Same |
| `count_files_needing_reconciliation` | Same |
| `drain_to_cold` | Workflow layer |
| `backfill_genres` | Workflow layer |
| `delete_capacity_estimate` | Component layer (delete estimate → delete lock = delete→delete composition) |

#### Category B: Delegation Wrappers — Remove (9 methods)

| Removed Method | Callers Migrate To |
|---------------|-------------------|
| `db.libraries.update_scan_status(...)` | `db.library_scans.update(...)` |
| `db.libraries.mark_scan_started(...)` | `db.library_scans.update(...)` |
| `db.libraries.mark_scan_completed(...)` | `db.library_scans.update(...)` |
| `db.libraries.get_scan_state(...)` | `db.library_scans.get(...)` |
| `db.libraries.check_interrupted_scan(...)` | `db.library_scans.get(...)` |
| `db.ml_capacity.try_acquire_probe_lock(...)` | `db.locks.lock_type.upsert(...)` |
| `db.ml_capacity.get_probe_lock_status(...)` | `db.locks.lock_type.get(...)` |
| `db.ml_capacity.complete_probe_lock(...)` | `db.locks.lock_type.update(...)` |
| `db.ml_capacity.release_probe_lock(...)` | `db.locks.lock_type.delete(...)` |

#### Category C: Cascade Side Effects — Schema-Driven (5 methods)

Methods that previously called `self.parent_db.*` for referential integrity are now expressed as cascade targets in the schema:

| Method | New Expression |
|--------|---------------|
| `delete_library_file` + cascade | `delete` verb + schema cascade targets |
| `bulk_delete_files` + cascade | Same (bulk implicit) |
| `delete_files_for_library` + cascade | Same |
| `upsert_library_file` + state init | `upsert` + `transition` (component orchestrates the pair) |
| `upsert_batch` + state init | Same (bulk implicit) |

#### Category D: Business Logic — Extract to Component (2 methods)

| Method | Target |
|--------|--------|
| `get_mood_coverage` | `components/ml/mood_analysis_comp.py` — multi-collection aggregation with business logic |
| `get_mood_balance` | Same |

#### Category E: Facade Vector Wrappers — Become Dynamic Verb Calls (2 methods)

| Method | Disposition |
|--------|------------|
| `delete_vectors_by_file_id` | Iterates registered dynamic vector collections, calls `collection._from.delete(file_id)` on each + edge cleanup on `file_has_vectors` |
| `delete_vectors_by_file_ids` | Bulk variant of above |

#### Category F: Retained Facade Methods (1 method)

| Method | Disposition |
|--------|------------|
| `get_library_stats` | Keep — single subquery, not multi-step orchestration |

### 8.4 Directory Structure

```
persistence/
├── schema.py              # The schema dict (single source of truth)
├── constructor/           # Runtime constructor library
│   ├── __init__.py
│   ├── builder.py         # SchemaConstructor — builds namespace objects
│   ├── namespaces.py      # CollectionNamespace, FieldNamespace, GetModifierNamespace
│   ├── verbs.py           # Verb templates (AQL generators per verb)
│   ├── filters.py         # Operator handling (IN, LIKE, etc.)
│   ├── pagination.py      # Pagination parameter injection
│   └── cascade.py         # Cascade engine (recursive island detection)
├── stubs/                 # Type stubs for IDE/mypy support
│   ├── library_files.pyi
│   ├── tags.pyi
│   └── ...
└── db.py                  # Database facade (wires constructor output)
```

The existing `persistence/database/` directory (52 hand-written AQL files) is deleted after migration

---

## 9. ADR Interaction

This design interacts with several existing ADRs. Some are compatible; others are contradicted and must be formally superseded before implementation begins.

**ADR-003 (State Graph):** The `transition` verb respects the boolean state graph’s three-phase READ→REMOVE→INSERT pattern per ERR 1579. Compatible — no supersession needed.

**ADR-004 (Graph Normalization):** Edge definitions in the schema match the normalized graph structure from ADR-004. The DD’s approach of using standard CRUD on the `locks` collection (no lock-specific verb) is compatible — ADR-004 addresses graph normalization, not lock API design. No supersession needed.

**ADR-010 (set_song_tags_batch as persistence primitive):** This DD demotes `set_song_tags_batch` from a persistence primitive to a component-layer composition (`delete(edges)` → `upsert(tags)` → `upsert(edges)`). This contradicts ADR-010 which accepted it as a persistence-layer primitive. The new approach is more compositional and aligns with the schema-driven design where every operation is a standard verb. **ADR-010 must be formally superseded BEFORE implementation begins.**

**ADR-014 (relink_tag_edges as persistence primitive):** This DD demotes `relink_tag_edges` from a persistence primitive to a component-layer composition (`get` → `upsert` → `delete` → `cascade`). This contradicts ADR-014 which accepted it as a persistence-layer primitive. **ADR-014 must be formally superseded BEFORE implementation begins.**

**ADR-016 (Migrations only for schema changes):** Compatible — the constructor changes the Python access pattern, not the database schema. No migrations needed.

**ADR-024 (Naming convention):** This DD supersedes the persistence file reorganization aspects of ADR-024. The AQL subpackage naming convention becomes irrelevant when the entire persistence layer is replaced by schema-driven generation — there are no hand-written AQL files to name. The non-persistence aspects of ADR-024 (collection origination principle) remain valid.

### Summary

---

## Appendix A: Surface Count Reconciliation

### Audited Surface

| Metric | Value | Notes |
|--------|-------|-------|
| **Public methods** | **287** | Excluding `__init__`, private (`_`-prefixed), and static helpers |
| **Classes** | **46** | 25 distinct operation classes; composite classes (e.g., `LibraryFilesOperations`) aggregate multiple mixins counted separately |
| **Files** | **52** | Includes `__init__.py` files, `_constants.py`, `_helpers.py` |
| **Lines of code** | **~11,300** | All `.py` files combined |

### Method Categorization

| Category | Count | % of 287 | Schema-Driven Mapping |
|----------|-------|----------|-----------------------|
| **CRUD** | ~65 | ~23% | `get`, `insert`, `upsert`, `update`, `delete` verbs |
| **Query** | ~80 | ~28% | `get` verb with field accessors + `.in()`, `.like()` modifiers + `traversal` |
| **Batch** | ~40 | ~14% | Implicit bulk (same verb, list input) — no separate batch verbs |
| **Stats** | ~30 | ~10% | `count` (collection + field level), `collect`, `aggregate` verbs |
| **Edge/Traversal** | ~20 | ~7% | `traversal` verb (3 modes) + edge declarations in schema |
| **Vector** | ~20 | ~7% | `ann_search` verb + template collection CRUD verbs |
| **Lock** | ~18 | ~6% | Standard CRUD on `locks` collection (`get`/`upsert`/`update`/`delete`) — no lock-specific verb |
| **Meta** | ~10 | ~3% | Infrastructure collection type — minimal key-value operations |
| **Orchestration/Facade** | ~4 | ~1% | Moved to component/workflow layer (not persistence) |
| **TOTAL** | **~287** | **~100%** | |

### Coverage Progression

| Stage | Cumulative Coverage | What's Added |
|-------|---------------------|--------------|
| 12 verbs as-is | ~78% | Standard CRUD, queries, state graph (`transition`), `cascade`, stats (`count`/`collect`/`aggregate`) |
| + operator modifiers (`.in()`, `.like()`) | ~91% | Complex queries become expressible via modifier chain on `get` |
| + `ann_search` verb | ~95% | Vector similarity search on template collections |
| + dynamic collection templates | ~98% | Parameterized vector collections (`vectors_track_{tier}__{backbone}__{library}`) |
| + move orchestration to component layer | 100% | `drain_to_cold`, `backfill_genres`, `claim_files_for_reconciliation`, delegation wrappers — not persistence, not counted |

### Disposition Summary

| Disposition | Count | % of 287 |
|-------------|-------|----------|
| Schema-driven verbs (CRUD/query/traversal/transition/cascade/ann_search) | ~263 | ~92% |
| Component-layer compositions (`relink_tag_edges`, `set_song_tags`, etc.) | ~8 | ~3% |
| Facade methods (vector cleanup, version, dynamic dispatch) | 4 | ~1% |
| Moved to component/workflow (orchestration violations) | 10 | ~3% |
| Removed delegation wrappers (callers migrate directly) | 9 | ~3% |
| **Total accounted** | **~294** | ≥287 (total exceeds 287 because schema-driven verbs include new methods that don't exist today, e.g., `cascade` for collections that previously had hand-written cascade logic, pagination variants) |

---

## Appendix B: Caller Migration Note

A separate migration mapping document will be created during execution, mapping every existing method name to its new verb equivalent. This document will:

- List all 287 current public methods
- Map each to its verb-based replacement (e.g., `get_file_by_id(id)` → `library_files.get(id)`)
- Flag methods that move to component/workflow layer
- Flag methods that are removed (delegation wrappers)

The mapping document is a companion artifact, NOT part of this design document.

---

## Open Questions

1. **Namespace construction strategy:** Direct attribute assignment in `__init__` — most explicit, best debugger stepping, avoids `__getattr__` magic.

2. **Type stub generation:** Manual Protocol classes vs auto-generated `.pyi` files? Manual stubs are more precise but must be kept in sync. Auto-generated stubs are always current but may be less readable. **Recommendation:** Start with auto-generated stubs from a helper script; refine to manual Protocols if needed.

3. **Pagination defaults:** What should the default `limit` be when callers don't specify? Global config value vs per-collection? **Recommendation:** Global default (e.g., 1000) with per-collection override in schema.

4. **Test migration:** Migrate tests per-collection alongside source, or in a dedicated phase? **Recommendation:** Per-collection alongside source — ensures each phase is fully verified.

---

## Design Goals

1. **Eliminate boilerplate** — Standard persistence operations should be declared, not written
2. **100% schema-driven** — No escape hatches. Every operation derives from verbs + operator modifiers in the nested accessor chain
3. **Single source of truth** — The schema file IS the persistence API definition. No second copy.
4. **Full tooling support** — Type stubs provide mypy, IDE autocomplete for the dynamically-constructed nested accessor API

## Appendix C: Cascade Matrix

Complete cascade relationships verified against the codebase. The matrix has two columns per behavior: **Current** (what the persistence layer actually does today) and **Schema-Driven Target** (what the cascade verb WILL do). Rows marked **NEW** indicate cascade relationships that don't exist in the current persistence code; **EXISTING** rows map behavior already implemented as direct deletes.

| Source Collection | Edge Collections Removed | Current Behavior | Schema-Driven Target | Status |
|---|---|---|---|---|
| `library_files` | `file_has_state`, `song_has_tags`, `file_has_vectors`, `file_has_segment_stats` | `delete_library_file()` directly removes `song_has_tags` edges (AQL FOR/REMOVE), delegates to `parent_db` for vectors, segment_scores_stats, and file_states cleanup. Does NOT remove `library_contains_file` edges — that cleanup only happens in the bulk `delete_files_for_library()` path. No orphan detection — edges are removed unconditionally. | `cascade` verb walks all 5 edge collections (including `library_contains_file`), removes edges, detects orphaned target documents (tags with zero remaining `song_has_tags` AND zero `tag_model_output` edges), recursively cascades into orphaned targets. | EXISTING (direct deletes) → **enhanced** with orphan detection + `library_contains_file` cleanup added to per-file path |
| `tags` | `tag_model_output`, `song_has_tags` (inbound edges TO this tag) | `cleanup_orphaned_tags()` is a **standalone cleanup routine** — not triggered by cascade. It finds tags with zero `song_has_tags` AND zero `tag_model_output` edges, deletes their `tag_model_output` edges, then removes the tag vertices. Runs periodically or after bulk deletions, not on individual tag delete. | `cascade` verb on tag deletion removes `tag_model_output` edges. Under the new schema, orphan detection on `library_files` cascade triggers tag deletion automatically (replacing the standalone `cleanup_orphaned_tags` routine). | **NEW** — `cleanup_orphaned_tags` becomes a cascade triggered by edge removal that creates orphans, rather than a standalone periodic routine |
| `calibration_state` | `model_has_calibration` | Deletes `model_has_calibration` edges before deleting calibration_state documents | `cascade` verb removes `model_has_calibration` edges | EXISTING |
| `ml_model_outputs` | `model_has_output` | `delete_outputs_for_model()` deletes `model_has_output` edges then removes output documents — this IS persistence-layer cascade behavior (not caller-side). | `cascade` verb removes `model_has_output` edges. Caller-side: `tag_model_output` edges referencing this output must also be cleaned (declared on `tags` cascade, not here, because edge direction is tags→ml_model_outputs) | EXISTING (direct deletes) |
| `library_folders` | `library_contains_folder` | Direct REMOVE, no cascade logic | `cascade` verb removes `library_contains_folder` edges | EXISTING |
| `navidrome_tracks` | `has_nd_id`, `has_plays` | `delete_tracks_cascade()` removes `has_plays` edges (filter `edge._to IN full_ids`), removes `has_nd_id` edges, then deletes track documents | `cascade` verb removes edges + detects orphaned `navidrome_playcounts` | EXISTING → **enhanced** with orphan detection |
| vector collections (hot/cold) | `file_has_vectors` | Vectors deleted by `delete_vectors_by_file_id` facade method iterating registered collections | `cascade` verb on vector documents removes `file_has_vectors` edges | EXISTING |
| `segment_scores_stats` | `file_has_segment_stats` | `delete_by_file_id` via graph traversal (OUTBOUND from file, then REMOVE) | `cascade` verb removes `file_has_segment_stats` edges | EXISTING |
| `libraries` | `library_contains_file`, `library_contains_folder`, `library_has_scan`, `library_has_pipeline_state` | `delete_library()` removes ONLY the library document — no cascade. The **component layer** (`library_admin_comp.delete_library()`) orchestrates file deletion first by calling `delete_library_file` per file, then deletes the library. | `cascade` verb recursively deletes: walks `library_contains_file` edges → cascades into `library_files` (which triggers its own cascade), walks `library_contains_folder` → deletes folders, walks `library_has_scan` → deletes scans, walks `library_has_pipeline_state` → deletes pipeline states. | **NEW** — moves orchestration from component layer into schema-driven cascade |

**Notes:**
- `library_files` cascade is the most complex — 5 edge collections. Current code handles this via direct edge removal + `parent_db` delegation. The schema-driven cascade **adds** orphan detection (especially for tags).
- `libraries` cascade is the biggest behavioral change: currently the persistence layer only deletes the library document itself; the component layer orchestrates all related cleanup. Under the new schema, `cascade` on libraries handles the full recursive teardown.
- `cleanup_orphaned_tags` is currently a standalone periodic routine that checks BOTH `song_has_tags` AND `tag_model_output` edges before declaring a tag orphaned. Under the new schema, this becomes automatic: when `library_files` cascade removes `song_has_tags` edges, orphan detection checks remaining edges on the tag; if none remain, the tag is recursively cascade-deleted.
- `ml_model_outputs` deletion requires caller-side cleanup of `tag_model_output` edges. The cascade target is declared on `tags` (not `ml_model_outputs`) because the edge direction is tags→ml_model_outputs.
- Vector collection cascade uses dynanames — the constructor must resolve registered template instances at cascade time.

---

## Appendix D: Edge Collection Inventory

Complete inventory of all edge collections, verified against the codebase.

| Edge Collection | From Collection | To Collection | Direction(s) Used | Applicable Patterns
|---|---|---|---|---|
| `file_has_state` | `library_files` | `file_states` | OUTBOUND, INBOUND | traversal (state lookup), cascade (file deletion), transition (state changes) |
| `song_has_tags` | `library_files` | `tags` | OUTBOUND, INBOUND | traversal (tags for file, files for tag), cascade (file deletion, tag orphan cleanup), filter (tag drill-down) |
| `tag_model_output` | `tags` | `ml_model_outputs` | OUTBOUND | traversal (provenance lookup), cascade (tag deletion) |
| `library_contains_file` | `libraries` | `library_files` | OUTBOUND, INBOUND | traversal (files in library), filter (library-scoped queries), cascade (library deletion) |
| `library_contains_folder` | `libraries` | `library_folders` | OUTBOUND | traversal (folders in library), cascade (library deletion) |
| `library_has_scan` | `libraries` | `library_scans` | OUTBOUND | traversal (scans for library), cascade (library deletion) |
| `file_has_vectors` | `library_files` | vector collections (hot/cold) | OUTBOUND | traversal (vectors for file), cascade (file deletion, vector cleanup) |
| `file_has_segment_stats` | `library_files` | `segment_scores_stats` | OUTBOUND | traversal (stats for file), cascade (file deletion) |
| `model_has_output` | `ml_models` | `ml_model_outputs` | OUTBOUND | traversal (outputs for model), cascade (model deletion) |
| `model_has_calibration` | `ml_models` | `calibration_state` | OUTBOUND | traversal (calibration for model), cascade (model deletion) |
| `library_has_pipeline_state` | `libraries` | `library_pipeline_states` | OUTBOUND | traversal (pipeline state for library), cascade (library deletion) |
| `has_nd_id` | `navidrome_tracks` | `library_files` | OUTBOUND, INBOUND | traversal (Navidrome↔file mapping), cascade (Navidrome track deletion) |
| `has_plays` | `navidrome_tracks` | `navidrome_playcounts` | OUTBOUND | traversal (play counts for track), cascade (Navidrome track deletion) |

**Direction notes:**
- Edges needing BOTH directions are those used in library-scoping (INBOUND from library to file) AND file-centric queries (OUTBOUND from file).
- `has_nd_id` uses BOTH: OUTBOUND to find the library_file for a Navidrome track, INBOUND to find the Navidrome track for a library_file.
- `song_has_tags` uses BOTH: OUTBOUND for "get tags for song", INBOUND for "get songs for tag".
