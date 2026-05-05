# Persistence Layer Class-Schema Refactor — Design Document

**Status:** Completed  
**Author:** rnd-dd-author  
**Created:** 2026-05-04  

**Related Documents:**
- [DD-persistence-capability-model](artifacts/designs/DD-persistence-capability-model.md) — 
- [ADR-003: Pure boolean state graph for file processing pipeline](artifacts/decisions/ADR-003-pure-boolean-state-graph-for-file-processing-pipeline.md) — 
- [ADR-004: Schema refactor v1 — graph normalization](artifacts/decisions/ADR-004-schema-refactor-v1-graph-normalization.md) — 

---

## Scope

nomarr/persistence/ — collections.py (new), builder.py refactor, stubs/ regeneration, and callers across nomarr/components/ (~15 files), nomarr/services/ (config_svc.py, metadata_svc.py, vector_maintenance_svc.py), and nomarr/workflows/ (prepare_database_wf.py, idle_promotion_vectors_wf.py)

---

## Problem Statement

The persistence layer is structured around a central SCHEMA dict in schema.py. SchemaConstructor reads the dict at startup and builds a CollectionNamespace per collection, attaching nested FieldNamespace objects for each declared field. This design has accumulated several compounding problems:

1. **Verbose and error-prone schema dict.** Per-field capability lists (e.g. `"capabilities": ["get", "upsert", "delete", "collect"]`) are manual and duplicative. Forgetting a capability silently removes a verb; adding a spurious one adds a verb that may not be safe.

2. **Partial type safety.** Several edge collections are typed as `Any` in db.py, losing type checking at the boundary callers use most.

3. **Field sub-namespace navigational friction.** Callers write `db.library_files.path.get("/music/track.mp3")` — three dots to reach a single-document lookup. The sub-namespace indirection adds no expressiveness and makes callers harder to read.

4. **CascadeEngine operates document-by-document.** The current CascadeEngine (constructor/cascade.py) performs Python-recursive traversal with one AQL query per edge hop and per-document orphan checks. Deleting a library with 10,000 files generates thousands of round-trips.

5. **Traversal API inconsistency.** `db.col.traversal(id, "edge_col")` and `db.col.traversal.by_ids(ids, "edge_col", target_like_starts_with=("name", "nom:"))` take the edge collection as a string, not a typed reference.

6. **limit=None proliferation.** Many callers pass `limit=None` to load entire collections into memory with no safeguard.

7. **Compound equality workaround.** Queries like `db.tags.get.many.by_filter({"name": name, "value": candidate}, limit=db.tags.count())` exist only because there is no clean compound-key lookup.

---

## Architecture

## Proposed Design

### 2.1 Base Collection Types

Four base classes replace the `CollectionType` enum. Each base class defines:
- Which implicit fields exist on instances of that type
- The default verb set attached by the builder

```python
# nomarr/persistence/base.py  (new)

class DocumentCollection:
    """Implicit: _key, _id, _rev. Verbs: get, get.many, insert, delete, count."""

class EdgeCollection:
    """Implicit: _key, _id, _rev, _from, _to. Verbs: insert, delete, count, truncate."""
    FROM_COLLECTION: ClassVar[type[DocumentCollection]]
    TO_COLLECTION: ClassVar[type[DocumentCollection]]

class VectorCollection:
    """Implicit: _key, _id, _rev. Verbs: insert, ann_search (both tiers), upsert_vector (hot only)."""
    VECTOR_TIER: ClassVar[Literal["hot", "cold"]]
    NAME_PATTERN: ClassVar[str]

class StateGraphCollection(DocumentCollection):
    """Inherits DocumentCollection. Adds: transition verb.

    Note: `transition` is a general edge update verb — it moves an edge's `_to` from one
    document to another for a set of source documents. Validity checks (e.g., legal state
    transitions) are domain logic belonging in the component, not the persistence layer.
    Builder attaches `transition` to any edge collection where the owning document
    collection declares it appropriate. `StateGraphCollection` keeps the verb name as a
    convenience marker; the underlying implementation is a typed edge `_to` update that
    any edge collection could use.
    """
```

### 2.2 Field Annotation Types

```python
# Generic markers — resolved by builder at startup
Field = Annotated[T, FieldMarker(unique=False)]
UniqueField = Annotated[T, FieldMarker(unique=True)]
```

Implicit fields (`_key`, `_id`, `_rev`, `_from`, `_to`) are NOT declared in collection classes. The base class registers them automatically — they get their own accessor objects attached by the builder.

### 2.3 Real Collection Declarations

```python
# nomarr/persistence/collections.py

from nomarr.persistence.base import (
    DocumentCollection, EdgeCollection, VectorCollection, StateGraphCollection,
    Field, UniqueField, EdgeDef, INBOUND, OUTBOUND, CASCADE, DETACH,
)

# --- Document collections ---

class Libraries(DocumentCollection):
    name: UniqueField[str]

    EDGES = [
        EdgeDef(via=LibraryContainsFile, direction=OUTBOUND, target=LibraryFiles,  on_delete=CASCADE),
        EdgeDef(via=LibraryHasScan,      direction=OUTBOUND, target=LibraryScans,  on_delete=CASCADE),
    ]


class LibraryFiles(DocumentCollection):
    path:           UniqueField[str]
    size:           Field[int]
    last_tagged_at: Field[int]
    library_id:     Field[str]

    EDGES = [
        EdgeDef(via=LibraryContainsFile, direction=INBOUND,  target=Libraries,  on_delete=DETACH),
        EdgeDef(via=SongHasTags,         direction=OUTBOUND, target=Tags,        on_delete=DETACH),
        EdgeDef(via=FileHasState,        direction=OUTBOUND, target=FileStates,  on_delete=DETACH),
    ]


class LibraryScans(DocumentCollection):
    started_at:  Field[int]
    finished_at: Field[int]
    status:      Field[str]

    EDGES = [
        EdgeDef(via=LibraryHasScan, direction=INBOUND, target=Libraries, on_delete=DETACH),
    ]


class Tags(DocumentCollection):
    name:  UniqueField[str]
    value: Field[str]

    EDGES = [
        EdgeDef(via=SongHasTags, direction=INBOUND, target=LibraryFiles, on_delete=DETACH),
    ]


class FileStates(StateGraphCollection):
    EDGES = [
        EdgeDef(via=FileHasState, direction=INBOUND, target=LibraryFiles, on_delete=DETACH),
    ]


class Meta(DocumentCollection):
    # Replaces INFRASTRUCTURE type — plain DocumentCollection with unique key field
    key:   UniqueField[str]
    value: Field[str]


# --- Edge collections ---

class LibraryContainsFile(EdgeCollection):
    FROM_COLLECTION = Libraries
    TO_COLLECTION   = LibraryFiles


class LibraryHasScan(EdgeCollection):
    FROM_COLLECTION = Libraries
    TO_COLLECTION   = LibraryScans


class SongHasTags(EdgeCollection):
    FROM_COLLECTION = LibraryFiles
    TO_COLLECTION   = Tags


class FileHasState(EdgeCollection):
    FROM_COLLECTION = LibraryFiles
    TO_COLLECTION   = FileStates


# --- Vector collections ---

class VectorsTrackHot(VectorCollection):
    VECTOR_TIER:  ClassVar[Literal["hot"]] = "hot"
    NAME_PATTERN: ClassVar[str] = "vectors_track_hot__{backbone_id}__{library_key}"

    file_id: Field[str]
    vector:  Field[list[float]]


class VectorsTrackCold(VectorCollection):
    VECTOR_TIER:  ClassVar[Literal["cold"]] = "cold"
    NAME_PATTERN: ClassVar[str] = "vectors_track_cold__{backbone_id}__{library_key}"

    file_id: Field[str]
    vector:  Field[list[float]]
```

**Implicit field summary by base class:**

| Base class | Implicit fields | Default verbs |
|---|---|---|
| DocumentCollection | `_key`, `_id`, `_rev` | `get`, `get.many`, `get.in_`, `insert`, `delete`, `count` |
| EdgeCollection | `_key`, `_id`, `_rev`, `_from`, `_to` | `insert`, `delete`, `count`, `truncate` |
| VectorCollection | `_key`, `_id`, `_rev` | `insert`, `ann_search`, (`upsert_vector` hot only) |
| StateGraphCollection | inherits DocumentCollection | + `transition` |

**Edge collections with payload fields:** Edge collections may declare additional typed fields beyond `_from`/`_to` using the same `Field[T]` syntax. Payload fields are returned in query results alongside `_from`/`_to`:

```python
class TagModelOutput(EdgeCollection):
    FROM_COLLECTION = MlModelOutputs
    TO_COLLECTION   = Tags
    score:      Field[float]
    created_at: Field[int]
    updated_at: Field[int]
```

### 2.4 Complete Collection Inventory

All collections that must be declared in `collections.py`. Base class derived from the current SCHEMA type and capability set.

**Document collections:**

| Name | Base Class | Notable fields / notes |
|---|---|---|
| `Libraries` | `DocumentCollection` | `name: UniqueField[str]` |
| `LibraryFiles` | `DocumentCollection` | `path: UniqueField[str]`, `library_key`, `status`, `modified_time` |
| `LibraryFolders` | `DocumentCollection` | `path: UniqueField[str]`, `library_key` |
| `LibraryScans` | `DocumentCollection` | `started_at`, `finished_at`, `status` |
| `LibraryPipelineStates` | `DocumentCollection` | `library_key`, pipeline progress fields |
| `Tags` | `DocumentCollection` | `name: UniqueField[str]`, `value` |
| `FileStates` | `StateGraphCollection` | Fixed vertex set (e.g. `ml_tagged`, `calibrated`) |
| `Meta` | `DocumentCollection` | `key: UniqueField[str]`, `value` |
| `Migrations` | `DocumentCollection` | `_key` = migration ID |
| `Health` | `DocumentCollection` | `component: UniqueField[str]`, `status`, `message` |
| `Sessions` | `DocumentCollection` | `expiry_timestamp` |
| `Locks` | `DocumentCollection` | `document_reference: UniqueField[str]`, `lock_type`, `expires_at` |
| `VramPromises` | `DocumentCollection` | `worker_id`, `model_path`, `promised_mb` |
| `WorkerClaims` | `DocumentCollection` | `file_id: UniqueField[str]`, `worker_id` |
| `CalibrationState` | `DocumentCollection` | `label: UniqueField[str]`, `calibration_def_hash`, histogram fields |
| `CalibrationHistory` | `DocumentCollection` | calibration snapshot fields |
| `MlModels` | `DocumentCollection` | model definition fields |
| `MlModelOutputs` | `DocumentCollection` | output head definition fields |
| `NavidromeTracks` | `DocumentCollection` | `nd_id: UniqueField[str]` |
| `NavidromePlaycounts` | `DocumentCollection` | `nd_id: UniqueField[str]`, `play_count` |
| `SegmentScoresStats` | `DocumentCollection` | `head_name`, `tagger_version`, `label_stats` |

**Edge collections:**

| Name | `FROM_COLLECTION` | `TO_COLLECTION` | Payload fields |
|---|---|---|---|
| `LibraryContainsFile` | `Libraries` | `LibraryFiles` | — |
| `LibraryContainsFolder` | `Libraries` | `LibraryFolders` | — |
| `LibraryHasScan` | `Libraries` | `LibraryScans` | — |
| `LibraryHasPipelineState` | `Libraries` | `LibraryPipelineStates` | — |
| `SongHasTags` | `LibraryFiles` | `Tags` | — |
| `FileHasState` | `LibraryFiles` | `FileStates` | — |
| `FileHasVectors` | `LibraryFiles` | vector collection ref | — |
| `FileHasSegmentStats` | `LibraryFiles` | `SegmentScoresStats` | — |
| `TagModelOutput` | `MlModelOutputs` | `Tags` | `score: Field[float]`, `created_at: Field[int]`, `updated_at: Field[int]` |
| `ModelHasOutput` | `MlModels` | `MlModelOutputs` | — |
| `ModelHasCalibration` | `MlModels` | `CalibrationState` | — |
| `HasNdId` | `LibraryFiles` | `NavidromeTracks` | — |
| `HasPlays` | `NavidromeTracks` | `NavidromePlaycounts` | — |

**Vector collections:**

| Name | Tier | `NAME_PATTERN` |
|---|---|---|
| `VectorsTrackHot` | `hot` | `vectors_track_hot__{backbone_id}__{library_key}` |
| `VectorsTrackCold` | `cold` | `vectors_track_cold__{backbone_id}__{library_key}` |


---

## 3. Builder Design

### 3.1 Overview

`builder.construct(collection)` is called once per collection instance at `Database.__init__` time. It reads `__annotations__` from the class MRO (to pick up base class implicit fields), constructs typed accessor objects, and `setattr`s them onto the instance. No SCHEMA dict. No `SchemaConstructor` as a separate pipeline step.

```python
class Builder:
    def __init__(self, db: SafeDatabase) -> None:
        self._db = db

    def construct(self, collection: BaseCollection) -> None:
        # 1. Collect all annotations from MRO (base implicit + declared explicit)
        annotations: dict[str, Any] = {}
        for cls in reversed(type(collection).__mro__):
            annotations.update(getattr(cls, "__annotations__", {}))

        # 2. Build a FieldAccessor for each annotation
        for field_name, field_type in annotations.items():
            if field_name.startswith("EDGES") or field_name in _CLASS_VAR_NAMES:
                continue  # skip EDGES, FROM_COLLECTION, VECTOR_TIER, NAME_PATTERN etc.
            origin = get_origin(field_type)   # Field or UniqueField marker
            inner  = get_args(field_type)[0]  # e.g. str, int, list[float]
            is_unique = origin is UniqueField or field_name in _ALWAYS_UNIQUE  # _key is unique
            accessor = FieldAccessor(
                db=self._db,
                collection_name=collection._name,
                field_name=field_name,
                python_type=inner,
                unique=is_unique,
            )
            setattr(collection, field_name, accessor)

        # 3. Attach base verb set for this collection type
        self._attach_base_verbs(collection)

        # 4. Attach typed traversal verbs from EDGES
        for edge_def in getattr(type(collection), "EDGES", []):
            self._attach_traversal(collection, edge_def)

        # 5. Pre-compile cascade AQL if any CASCADE edge exists
        cascade_defs = [e for e in getattr(type(collection), "EDGES", []) if e.on_delete is CASCADE]
        if cascade_defs:
            self._attach_cascade(collection, cascade_defs)
```

### 3.2 Field Accessor API (flat — no sub-namespaces)

The `FieldAccessor` exposes all verbs directly on the collection. For named fields, callers pass the field name as a keyword argument. For `_`-prefixed implicit fields other than `_key` and `_id`, callers use `Field(name, value)` as a positional argument — Python does not allow keyword arguments starting with `_`:

```python
# --- Unique field lookups (→ dict | None) ---
db.library_files.get(path="/music/track.mp3")
db.libraries.get(name="My Library")
db.library_files.get(_key="abc123")          # _key remains a kwarg (exception to Field rule)
db.meta.get(key="schema_version")

# --- Non-unique field lookups (→ list[dict]) ---
db.library_files.get.many(library_id="abc123")
db.library_files.get.many(library_id="abc123", limit=100)
db.song_has_tags.get.many(Field("_from", "libraries/lib-abc"))   # _from uses Field positional arg

# --- Bulk / list-IN lookups ---
db.library_files.get.in_(path=["/a.mp3", "/b.mp3"])
db.song_has_tags.get.in_(Field("_to", [tag["_id"] for tag in tags]))  # _to uses Field positional arg

# --- Filter comparisons (explicit methods — no Op-keyed dicts) ---
db.library_files.get.gte(last_tagged_at, cutoff_ms)    # ≥ comparison
db.library_files.get.lte(last_tagged_at, cutoff_ms)    # ≤ comparison
db.library_files.get.like(path, "/music/%")            # LIKE pattern

# --- Collection-level get (by _id list) ---
db.library_files.get([id1, id2])

# --- Compound equality (multi-field, using Field positional args) ---
db.tags.get.many(Field("name", name), Field("value", candidate))

# --- Mutations ---
db.library_files.update(path="/old.mp3", fields={"size": 1234})
db.meta.upsert(key="schema_version", fields={"value": "28"})

# --- Delete ---
db.library_files.delete(path="/music/track.mp3")          # unique field → single doc
db.library_files.delete.in_(path=["/a.mp3", "/b.mp3"])    # bulk
db.song_has_tags.delete(Field("_from", "/libraries/lib-abc"))  # _from uses Field positional arg

# --- Aggregate (on document collection, keyed by edge collection name) ---
db.library_files.aggregate("song_has_tags")  # count/distinct values for that relationship

# --- Count ---
db.library_files.count()
db.song_has_tags.count(Field("_from", "libraries/lib-abc"))  # _from uses Field positional arg
```

**Before/after comparison for real callers:**

```python
# tag_query_comp.py — CURRENT
db.tags.name.get.many(name, limit=total)
db.song_has_tags._to.aggregate()
db.song_has_tags._to.get.in_([tag["_id"] for tag in tags], limit=None)
db.library_files.traversal(song_id, "song_has_tags")
db.library_files.traversal.by_ids(list(file_ids), "song_has_tags", target_like_starts_with=("name", "nom:"))

# tag_query_comp.py — PROPOSED
db.tags.get.many(name=name, limit=total)
db.library_files.aggregate("song_has_tags")    # aggregate on document collection, keyed by edge name
db.song_has_tags.get.in_(Field("_to", [tag["_id"] for tag in tags]))  # _to uses Field positional arg
db.library_files.song_has_tags(song_id)        # traversal verb = edge collection name
db.library_files.song_has_tags.by_ids(list(file_ids), name_starts_with="nom:")

# library_file_state_comp.py — CURRENT
db.file_states.transition(file_ids, from_state, to_state)
db.file_has_state._to.get.many(STATE_NOT_TAGGED, limit=None)
db.file_has_state._from.delete(file_id)
db.file_has_state.count_by_filter({"_from": file_id, "_to": STATE_TAGGED})
db.file_states.traversal(state_id, "file_has_state", limit=None)
db.libraries.traversal(library_id, "library_contains_file", limit=None)

# library_file_state_comp.py — PROPOSED
db.file_states.transition(file_ids, from_state, to_state)          # unchanged
db.file_has_state.get.many(Field("_to", STATE_NOT_TAGGED))
db.file_has_state.delete(Field("_from", file_id))
db.file_has_state.count(Field("_from", file_id), Field("_to", STATE_TAGGED))
db.file_states.file_has_state(state_id)            # traversal verb = edge collection name
db.libraries.library_contains_file(library_id)    # traversal verb = edge collection name

# library_file_query_comp.py — CURRENT
db.library_files.get(file_id)
db.library_files.last_tagged_at.get.in_({Op.GTE: cutoff_ms})
db.library_files.path.get.in_(paths)

# library_file_query_comp.py — PROPOSED
db.library_files.get(_id=file_id)
db.library_files.get.gte(last_tagged_at, cutoff_ms)  # explicit filter method, not Op-keyed dict
db.library_files.get.in_(path=paths)

# tag_stats_comp.py — CURRENT (compound equality + count-with-filter)
db.tags.get.many.by_filter({"name": name, "value": candidate})  # compound equality filter dict
db.song_has_tags.count_by_filter({"_to": tag_id})               # count with filter dict

# tag_stats_comp.py — PROPOSED
db.tags.get.many(Field("name", name), Field("value", candidate))  # multi-Field compound equality
db.song_has_tags.count(Field("_to", tag_id))                      # Field positional arg

# Callers affected by get.in_() explicit-verb split (was Op-keyed get.in_):
# - library_file_query_comp.py: last_tagged_at.get.in_({Op.GTE: cutoff_ms})  →  get.gte(last_tagged_at, cutoff_ms)
# - library_file_query_comp.py: path.get.in_(paths)                          →  get.in_(path=paths)
# - tag_query_comp.py: song_has_tags._to.get.in_([...])                      →  song_has_tags.get.in_(Field("_to", [...]))
```


---

## 4. EdgeDef and Traversal

### 4.1 EdgeDef dataclass

```python
@dataclass(frozen=True)
class EdgeDef:
    via:       type[EdgeCollection]
    direction: Literal["INBOUND", "OUTBOUND"]
    target:    type[DocumentCollection]
    on_delete: Literal["CASCADE", "DETACH"]

INBOUND  = "INBOUND"
OUTBOUND = "OUTBOUND"
CASCADE  = "CASCADE"
DETACH   = "DETACH"
```

### 4.2 Traversal verb generation

The builder attaches one traversal verb per `EdgeDef`. The verb name is the snake_case of the **`via`** edge collection class name. Edge collection names are unique by definition — no disambiguation problem exists.

```python
# Libraries.EDGES has two OUTBOUND entries:
#   EdgeDef(via=LibraryContainsFile, direction=OUTBOUND, target=LibraryFiles, ...)
#   EdgeDef(via=LibraryHasScan, direction=OUTBOUND, target=LibraryScans, ...)
# Builder attaches (verb name = snake_case of edge collection class name):
db.libraries.library_contains_file(library_id, limit=None)    # single-id
db.libraries.library_contains_file.by_ids([id1, id2])         # multi-id
db.libraries.library_has_scan(library_id)

# LibraryFiles.EDGES has one INBOUND entry:
#   EdgeDef(via=LibraryContainsFile, direction=INBOUND, target=Libraries, ...)
# Builder attaches:
db.library_files.library_contains_file(file_id)               # which library owns this file

# FileStates.EDGES has one INBOUND entry via FileHasState → LibraryFiles
db.file_states.file_has_state(state_id)
```

Traversal verb signatures:
```python
# Single-id traversal
db.libraries.library_files(library_id: str, limit: int | None = DEFAULT_LIMIT) -> list[dict]

# Multi-id traversal
db.libraries.library_files.by_ids(
    library_ids: list[str],
    limit: int | None = DEFAULT_LIMIT,
    **field_filters,          # e.g. name_starts_with="nom:", status="active"
) -> list[dict]
```

### 4.3 Edge collection class vars for cascade resolution

`FROM_COLLECTION` and `TO_COLLECTION` on edge collection classes tell the builder which vertex collections to check during cascade orphan analysis:

```python
class LibraryContainsFile(EdgeCollection):
    FROM_COLLECTION = Libraries    # _from vertex is a Libraries doc
    TO_COLLECTION   = LibraryFiles # _to vertex is a LibraryFiles doc
```

Edge collections have NO traversal verbs. They have only: `insert`, `delete`, `count`, `truncate`. This is intentional — traversal always starts from a document collection.


---

## 5. delete vs delete.cascade

### 5.1 `delete(key)` — local cleanup only

Removes the document by `_key` and cleans up its own edge records across all declared edge collections. Does NOT recurse into connected documents. Always available on `DocumentCollection`.

```python
db.library_files.delete(_key="file-abc")
# Equivalent AQL (two statements, single transaction):
# REMOVE "file-abc" IN library_files
# FOR e IN UNION(
#     (FOR e IN song_has_tags   FILTER e._from == "library_files/file-abc" RETURN e),
#     (FOR e IN file_has_state  FILTER e._from == "library_files/file-abc" RETURN e),
#     (FOR e IN library_contains_file FILTER e._to == "library_files/file-abc" RETURN e)
# ) REMOVE e._key IN e._id  -- dispatched per-collection
```

The builder knows which edge collections to clean up by inspecting `EDGES` on the collection class (both INBOUND and OUTBOUND dirs).

### 5.2 `delete.cascade(key)` — full orphan subgraph removal

Only attached by the builder when at least one `EdgeDef` has `on_delete=CASCADE`. Builder **pre-compiles** a static AQL template at startup — the ownership graph does not change at runtime, so the template is constant. Runtime binds only `@start`.

Pre-compiled AQL logic (conceptual):
```
LET subgraph = (
    FOR v, e, p IN 1.. OUTBOUND @start
        @cascade_edge_collections
        OPTIONS {uniqueVertices: "global", bfsUnique: true}
    RETURN v
)
LET orphans = (
    FOR candidate IN subgraph
        LET external_inbound = (
            FOR parent IN 1..1 INBOUND candidate
                @all_edge_collections
                FILTER parent NOT IN subgraph AND parent._id != @start
                LIMIT 1 RETURN 1
        )
        FILTER LENGTH(external_inbound) == 0
        RETURN candidate
)
// Bulk remove orphan vertices + their edge records
FOR orphan IN orphans
    REMOVE orphan._key IN @@collection_of_orphan
// Remove edge records connecting orphans and start doc
FOR e IN @cascade_edge_collections
    FILTER e._from IN UNION([@start], orphan_ids) OR e._to IN orphan_ids
    REMOVE e._key IN @@edge_collection
```

The builder resolves `@cascade_edge_collections` from the `EDGES` list (OUTBOUND + on_delete=CASCADE only), and `@all_edge_collections` from the full edge registry. No `@max_depth` is needed: the builder validates at startup that CASCADE edges form a DAG, so traversal naturally terminates without a depth limit.

**Contrast with current `CascadeEngine`:**

| | Current CascadeEngine | Proposed `delete.cascade` |
|---|---|---|
| Traversal | Python recursion, one AQL per hop | Single pre-compiled AQL |
| Orphan check | Per-document Python loop | Subquery inside AQL |
| Round-trips (library with 10k files) | Thousands | 1 |
| Schema dependency | Reads SCHEMA dict at runtime | Pre-compiled at startup |
| Error surface | Python RecursionError on deep graphs | None — builder validates CASCADE edges form a DAG at startup |


---

## 6. VectorCollection

### 6.1 Class declaration

```python
class VectorsTrackHot(VectorCollection):
    VECTOR_TIER:  ClassVar[Literal["hot"]]  = "hot"
    NAME_PATTERN: ClassVar[str] = "vectors_track_hot__{backbone_id}__{library_key}"

    file_id: Field[str]
    vector:  Field[list[float]]


class VectorsTrackCold(VectorCollection):
    VECTOR_TIER:  ClassVar[Literal["cold"]] = "cold"
    NAME_PATTERN: ClassVar[str] = "vectors_track_cold__{backbone_id}__{library_key}"

    file_id: Field[str]
    vector:  Field[list[float]]
```

### 6.2 Verb availability by tier

| Verb | Hot | Cold | Notes |
|---|---|---|---|
| `ann_search` | Yes | Yes | ArangoDB vector index query |
| `upsert_vector` | Yes | No | Builder skips attachment when `VECTOR_TIER == "cold"` |
| `insert` | Yes | Yes | Standard document insert |
| `delete` | Yes | Yes | By `_key` or `file_id` |
| `get_vector` | Yes | Yes | Retrieve stored vector by `file_id` — used by `ml_vector_retrieve_comp.py` |
| `update_many` | Yes | Yes | Bulk-update documents by list of dicts — used by `ml_vector_maintenance_comp.py` |
| `move_collection` | Yes | No | Drain all vectors to a `dest` VectorCollection (hot→cold) — used by `ml_vector_maintenance_comp.py`; not applicable on cold tier |

The builder checks `collection.VECTOR_TIER` at `construct` time — no string parsing of the collection name.

### 6.3 Dynamic registration

`db.register(resolved_name, template_name: str)` continues to work as today. Callers pass a **template name string** (e.g. `"vectors_track_cold"`), not a class object. The registry maps that string to the originating class (`VectorsTrackCold`) for type resolution and stub lookup. The `NAME_PATTERN` class var is used to match a resolved collection name (e.g. `"vectors_track_hot__resnet__lib-abc"`) back to the originating class. No change to the external `db.register` API.

---

## Design Goals

- Replace the SCHEMA dict with Python classes — one class per collection — where fields are typed annotations using `Field[T]` or `UniqueField[T]`
- Eliminate per-field capability lists; collection base class determines the default verb set
- Eliminate field sub-namespaces; callers use keyword arguments: `db.library_files.get(path=...)`
- Pre-compile cascade AQL at startup so runtime just binds `@start` — no Python recursion
- Express edge relationships as `EDGES = [EdgeDef(...)]` on document collections; builder generates typed traversal verbs
- Preserve all existing AQL-layer logic in constructor/verbs.py — only the builder and schema declaration change
- Simplify stubs — generated per-collection .pyi files reduce from ~50 to ~10 lines each

---

## Constraints

- **No SCHEMA dict at runtime.** The SCHEMA dict in schema.py is retired. All schema information lives in collection class annotations and class vars.
- **AQL layer preserved.** Existing AQL-issuing functions in constructor/verbs.py are reused — only the builder dispatch changes, not the SQL strings.
- **Forward-only migration.** No ArangoDB schema migration is needed — the collection structure in ArangoDB does not change. Only the Python representation changes. The bootstrap workflow (`prepare_database_wf.py`) continues to call `ensure_schema(db.db, ...)` on startup; that call operates on the live Arango schema, which is unaffected by this refactor. No V029+ migration file is needed.
- **No breaking change to db.register().** External callers (services, workflows) that call `db.register(name, template)` must continue to work without modification.
- **CascadeEngine must remain available** until all callers of `db.col.cascade(ids)` are migrated to `db.col.delete.cascade(key)`. The two can coexist during the migration window.
- **Protected stubs must not be regenerated.** stubs/_base.pyi and stubs/_base.py are hand-authored and must never be touched by gen_stubs.py.
- **Raw `db.db` handle preserved.** `prepare_database_wf.py` uses `db.db.collections()` and `ensure_schema(db.db, ...)`. `vector_maintenance_svc.py` uses `db.db.has_collection(...)`. These direct ArangoDB driver calls via `db.db` are out of scope for this refactor and are preserved unchanged.
- **`limit=None` with `offset > 0`:** When `limit=None` is combined with `offset > 0`, the constructor injects `DEFAULT_LIMIT = 1000` to prevent unbounded full-collection scans with skipping. This behavior is preserved as-is.

---

## Open Questions

1. **`_from`/`_to` as Python keyword arguments.** ~~Python keyword argument names cannot begin with `_`. `db.song_has_tags.delete(from_=file_id)` is one option; `db.song_has_tags.delete_by_from(file_id)` is another. The verb API for edge-collection implicit fields needs an explicit decision before caller migration begins.~~

   **Resolved:** Wrap `_`-prefixed non-key fields in a `Field` dataclass with `name` and `value` properties. Callers use `Field("_from", file_id)` as a positional argument. `_key` and `_id` remain as kwargs. All other `_`-prefixed implicit fields (`_from`, `_to`, `_rev`) use the `Field(name, value)` form. See §3.2 for updated examples.

2. **`StateGraphCollection` transition verb internals.** ~~The `transition` verb is preserved but the spec is silent on where the TRANSITIONS state machine definition lives. Does `StateGraphCollection` own the transition AQL? Or does it remain in a separate module (currently `constructor/verbs.py`)? The answer affects the `FileStates` class declaration.~~

   **Resolved:** `transition` is a general edge update verb — it moves an edge's `_to` from one document to another for a set of source documents. Validity checks (legal state transitions) are domain logic belonging in the component, not the persistence layer. Builder attaches `transition` to any edge collection where the owning document collection declares it appropriate. `StateGraphCollection` keeps the verb name as a convenience; the underlying implementation is a typed edge `_to` update that any edge collection could use.

3. **`INFRASTRUCTURE` type fate.** ~~The `meta` collection is currently typed as `INFRASTRUCTURE`. The proposed design maps it to a plain `DocumentCollection`. Is there any behavior on `INFRASTRUCTURE` that must be preserved, or is plain `DocumentCollection` with `UniqueField[str]` on `key` sufficient?~~

   **Resolved:** Plain `DocumentCollection`. No special behavior required. The existing `Meta` class declaration (plain `DocumentCollection` with `UniqueField[str]` on `key`) is correct as-is.

4. **`limit=None` policy.** ~~Approximately 10 call sites pass `limit=None` to load entire collections. Should the new API: (a) allow `limit=None` as today, (b) require callers to paginate, or (c) introduce a streaming verb? This affects the `FieldAccessor.get.many` signature and all migrated callers.~~

   **Resolved:** `limit=None` is preserved as-is. No policy change. Existing callers continue to work without modification.

5. **Filter / operator API surface.** ~~Current `get.in_({Op.GTE: cutoff_ms})` mixes list-IN and range-filter semantics in a single call. Should range filters have a dedicated verb (`get.range(field, gte=x, lte=y)`) or stay as `Op`-keyed dicts in `get.in_`? The choice affects how `library_file_query_comp.py` is migrated.~~

   **Resolved:** Split into one verb per comparison type. No `Op`-keyed dicts. Explicit methods: `get.gte(field, val)`, `get.lte(field, val)`, `get.like(field, pattern)`, `get.in_(field, [values])`. Each has a clear, unambiguous return type. See §3.2 for updated examples.

6. **`aggregate()` on edge collections.** ~~`db.song_has_tags._to.aggregate()` is called in `tag_query_comp.py` to count distinct tag targets. In the flat API, `_to` is an implicit field with a standard accessor. Does `aggregate` become `db.song_has_tags.aggregate(_to=...)` returning a count/distinct result, and is that the complete `aggregate` API surface?~~

   **Resolved:** `aggregate` moves to the document collection side, keyed by edge collection name (not target class name). `db.library_files.aggregate("song_has_tags")` — returns count and distinct values for that relationship. Not on the edge collection itself. See §3.2 for updated examples.

7. **`count_by_filter` / `delete_by_filter`.** ~~These collection-level verbs exist on several namespaces today. Are they preserved as keyword-argument forms (`db.file_has_state.count(_from=file_id, _to=STATE_TAGGED)`) or kept as filter-dict methods alongside the keyword form?~~

   **Resolved:** `Field` dataclass wins. Multi-field filters expressed as multiple `Field(name, value)` positional args. No filter-dict methods. Example: `db.file_has_state.count(Field("_from", file_id), Field("_to", STATE_TAGGED))`.

8. **Traversal verb name disambiguation.** ~~If two `EDGES` entries on the same source collection point to the same target class via different edge collections, the verb name (`library_files`) conflicts. The required disambiguation rule (e.g., use `via` snake_case prefix: `library_contains_file__library_files`) must be decided before builder implementation.~~

   **Resolved:** Traversal verbs are named after the **edge collection** (`via`), not the target document collection. `db.library_files.song_has_tags(file_id)` not `db.library_files.tags(file_id)`. Edge collection names are unique by definition — no disambiguation problem exists. See §4.2 for updated examples.

9. **Cascade AQL max_depth.** ~~The pre-compiled cascade AQL needs a maximum traversal depth. This can be a constant (e.g., 10) or computed statically from the longest CASCADE chain in the declared graph. The value needs to be decided — too low silently truncates deep ownership trees, too high is wasteful for shallow ones.~~

   **Resolved:** No arbitrary max depth. Traversal is OUTBOUND-only on CASCADE edges. Since the CASCADE ownership graph must be a DAG (builder validates this at startup), there are no cycles and no depth limit is needed. The traversal naturally terminates. See §5.2 for updated AQL.

---
