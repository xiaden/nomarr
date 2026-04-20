# Schema Refactor v1 — Design Document

**Status:** Draft  
**Author:** Discussion synthesis  
**Created:** 2026-03-27

**Related Documents:**

- [design-cascade-delete.md](design-cascade-delete.md) — Graph-based cascade patterns (separate refactor)
- [design-db-issues-investigation.md](design-db-issues-investigation.md) — TTL bugs, empty collections, data issues

---

## Scope

This document covers:

1. Converting FK-as-property patterns to proper edges
2. Field cleanup and renaming
3. Collection restructuring (vertex vs edge)
4. Graph and edge collection definitions
5. Making persistence layer return more generic types

**Out of scope:** Cascade delete implementation (see related DD), troubleshooting DB issues.

---

## Problem Statement

The ArangoDB schema has accumulated technical debt through organic growth:

1. **Foreign keys as document properties** — `library_id`, `file_id`, `model_id` stored as strings instead of edges. Defeats graph traversal, loses referential integrity.

2. **Lock collection overhead** — `ml_capacity_probe_locks` and `vector_promotion_locks` implement identical lock semantics in separate collections. Note: `worker_claims` is fundamentally different (work distribution, not locking) and should remain separate.

3. **Redundant timestamps** — `created_at`, `updated_at`, `last_computation_at`, `processed_at` proliferate without clear business purpose.

4. **Incomplete state model** — `file_states` vocabulary incomplete (`calibrated`, `ml_tagged`, `reconciled` only).

5. **Scan conflation in libraries** — Libraries collection contains transient scan state that should be separate.

6. **Manual denormalization** — Tags stored on documents and as edges, creating consistency maintenance burden.

7. **Suboptimal key strategies** — `meta` collection uses property lookup (`FILTER meta.key == @key`) instead of `_key` for O(1) access.

8. **Missing graph definitions** — Edge collections exist but no named graphs defined in ArangoDB, limiting traversal capabilities.

---

## Design Goals

 | Goal | Rationale |
 | ------ | ---------- |
 | Edge-first relationships | Leverage ArangoDB graph capabilities |
 | Named graph definitions | Enable `GRAPH 'name'` traversal syntax |
 | Single source of truth | No manual denormalization; use views for query optimization |
 | Consolidated lock semantics | One `locks` collection for actual locks |
 | Separate work distribution | `worker_claims` remains distinct |
 | Complete state vocabulary | Workers discover work via missing state edges |
 | Generic persistence returns | Reduce coupling between persistence and business logic |
 | Forward-only migrations | All changes via migration scripts |

---

## Target Schema

### Vertex Collections

 | Collection | Purpose | Key Strategy |
 | ------------ | --------- | ------------- |
 | `libraries` | Library identity (immutable after creation) | Auto |
 | `library_files` | Audio file records | Auto |
 | `library_folders` | Folder hierarchy | Auto |
 | `library_scans` | Scan state (one per library) | `{library_key}` |
 | `tags` | Tag definitions | SHA256(`{rel}:{value}`) |
 | `file_states` | State vertices (fixed set) | `ml_tagged`, `calibrated`, etc. |
 | `ml_models` | ML model definitions | Auto |
 | `ml_model_outputs` | Model output definitions | Auto |
 | `calibration_state` | Calibration data per head/label | `{head_name}:{label_hash}` |
 | `segment_score_stats` | Per-file segment statistics | Auto |
 | `vectors_hot_{backbone}` | Hot vectors per backbone | SHA1(`{file_id} | {hash}`) |
 | `vectors_cold_{backbone}` | Cold vectors per backbone | SHA1(`{file_id} | {hash}`) |
 | `locks` | Resource locks (consolidated) | `{lock_type}:{target_key}` |
 | `worker_claims` | Work distribution (NOT locks) | `claim_{file_key}` |
 | `health` | Worker health/heartbeat | `{component_type}:{worker_id}` |
 | `sessions` | Auth sessions | Auto |
 | `meta` | Key-value metadata | Direct `_key` (e.g., `version`) |

### Edge Collections

 | Collection | From | To | Purpose |
 | ------------ | ------ | ---- | --------- |
 | `library_contains_file` | `libraries` | `library_files` | Library membership |
 | `library_contains_folder` | `libraries` | `library_folders` | Folder membership |
 | `library_has_scan` | `libraries` | `library_scans` | Current scan state |
 | `file_has_state` | `library_files` | `file_states` | Processing state machine |
 | `song_has_tags` | `library_files` | `tags` | Tag associations |
 | `tag_model_output` | `tags` | `ml_model_outputs` | Tag provenance |
 | `model_has_output` | `ml_models` | `ml_model_outputs` | Model → output |
 | `file_has_vectors` | `library_files` | `vectors_*` | Vector associations |
 | `file_has_segment_stats` | `library_files` | `segment_score_stats` | Segment statistics |
 | `model_has_calibration` | `ml_models` | `calibration_state` | Calibration per model |

### Named Graph Definitions

```python
# To be created in migration
GRAPHS = {
    "library_graph": {
        "edge_definitions": [
            {"collection": "library_contains_file", "from": ["libraries"], "to": ["library_files"]},
            {"collection": "library_contains_folder", "from": ["libraries"], "to": ["library_folders"]},
            {"collection": "library_has_scan", "from": ["libraries"], "to": ["library_scans"]},
        ]
    },
    "file_graph": {
        "edge_definitions": [
            {"collection": "file_has_state", "from": ["library_files"], "to": ["file_states"]},
            {"collection": "song_has_tags", "from": ["library_files"], "to": ["tags"]},
            {"collection": "file_has_vectors", "from": ["library_files"], "to": ["vectors_hot_effnet", "vectors_cold_effnet", ...]},
            {"collection": "file_has_segment_stats", "from": ["library_files"], "to": ["segment_score_stats"]},
        ]
    },
    "ml_graph": {
        "edge_definitions": [
            {"collection": "model_has_output", "from": ["ml_models"], "to": ["ml_model_outputs"]},
            {"collection": "model_has_calibration", "from": ["ml_models"], "to": ["calibration_state"]},
            {"collection": "tag_model_output", "from": ["tags"], "to": ["ml_model_outputs"]},
        ]
    },
}
```

---

## Schema Changes

### 1. Locks Consolidation

**Current:**

- `ml_capacity_probe_locks` — lock collection for GPU/CPU probes
- `vector_promotion_locks` — lock collection for vector promotion  
- `worker_claims` — work distribution (fundamentally different, NOT a lock)

**Target:**

```
locks (document collection) — for actual resource locks only
├── _key: "{lock_type}:{target_key}"
├── lock_type: "capacity_probe" | "vector_promotion" | ...
├── owner_id: string
├── target_key: string
├── acquired_at: int (epoch ms)
└── expires_at: int (epoch ms) → TTL index
```

**Note:** `worker_claims` stays separate — different semantics (work lease, dual cleanup paths).

**Migration:** Create `locks`, migrate data, add TTL index, drop old collections.

---

### 2. Meta Collection Key Strategy

**Current:** `{key: "schema_version", value: "..."}` with filter queries (O(log n) indexed).

**Target:** `{_key: "schema_version", value: "..."}` for O(1) lookup.

**Migration:** Rewrite documents with `_key` = current `key` property. Drop `key` property and index.

---

### 3. File States Vocabulary Expansion

**Current states:** `calibrated`, `ml_tagged`, `reconciled`

**Target vocabulary:**

 | State | Meaning | Created by |
 | ------- | --------- | ------------ |
 | `scanned` | File discovered and metadata extracted | Scan workflow |
 | `too_short` | Duration below processing threshold | Scan workflow |
 | `vectors_extracted` | Embeddings computed | ML worker |
 | `ml_tagged` | ML tags applied | ML worker |
 | `calibrated` | Calibration applied to scores | Calibration workflow |
 | `tags_written` | Tags written to file | Tag write workflow |
 | `reconciled` | Synced with external source | Reconciliation workflow |
 | `errored` | Processing failed, needs retry | Any worker |

**Migration:** Insert new state vertices. No code changes needed for edge-based queries.

---

### 4. Library Files Edge-ification

**Current:** `library_files.library_id` is a string property.

**Target:** Edge collection `library_contains_file` from `libraries` to `library_files`.

**Field cleanup on `library_files`:**

 | Field | Action | Rationale |
 | ------- | -------- | ---------- |
 | `path` | Rename to `absolute_path` | Clarity |
 | `normalized_path` | Rename to `relative_path` | Clarity |
 | `library_id` | Remove | Replaced by edge |
 | `title`, `album`, `artist`, `artists`, `genres`, `year` | Remove | Denormalized from edges |
 | `chromaprint` | Rename to `spectral_hash` | Actually MD5 of quantized FFT |
 | `labels` | Remove | Dead field |

**Migration:** Create edge collection, migrate `library_id` to edges, update queries.

---

### 5. Library Scans Separation

**Current:** `libraries` contains identity + scan state fields.

**Target:**

```
libraries (identity only)
├── _key, name, root_path, watch_mode, file_write_mode, is_enabled, created_at

library_scans (document collection)
├── _key: same as library_key (1:1 relationship)
├── scan_type: "full" | "incremental" | "watch"
├── status: "idle" | "running" | "completed" | "failed"
├── started_at: int | null
├── completed_at: int | null
├── files_processed: int
├── files_total: int
├── error: string | null

library_has_scan (edge collection)
├── _from: libraries/{lib_key}
└── _to: library_scans/{lib_key}
```

**Migration:** Create collections, migrate scan fields, update queries.

---

### 6. Tags as Pure Edges

**Current:** Tags on `library_files` documents AND as `song_has_tags` edges.

**Target:** Edge-only model. Remove tag fields from `library_files`.

**Query optimization:** Use ArangoSearch view if tag-based filtering becomes slow.

**Edge cleanup:** Remove `created_at`/`updated_at` from `tag_model_output` edges (audit theater).

---

### 7. ML Model Outputs Edge-ification

**Current:** `ml_model_outputs.model_id` is a string property.

**Target:** Edge collection `model_has_output` from `ml_models` to `ml_model_outputs`.

**Field cleanup:**

 | Field | Action |
 | ------- | -------- |
 | `model_id` | Remove (edge replaces) |
 | `created_at`, `updated_at` | Remove |
 | `fully_labeled` | Keep | State flag for labeled vs unlabeled outputs — required for inference |

---

### 8. Vector Collections Edge-ification

**Current:** `vectors_track_*` with `file_id` as string property.

**Target:**

- Rename to `vectors_{hot|cold}_{backbone}`
- Single edge collection `file_has_vectors` with polymorphic `_to` (points to any vector collection)

**Complexity note:** Vector collections are created dynamically per backbone. The `file_has_vectors` edge collection's graph definition must list all possible target collections. When a new backbone is added, the graph definition needs updating.

```python
# Graph definition must enumerate all vector collections
"file_has_vectors": {
    "from": ["library_files"],
    "to": ["vectors_hot_effnet", "vectors_cold_effnet", 
           "vectors_hot_musicnn", "vectors_cold_musicnn", ...]
}
```

**Field cleanup:**

 | Field | Action |
 | ------- | -------- |
 | `file_id` | Remove (edge replaces) |
 | `created_at` | Remove |
 | `embed_dim` | Keep |
 | `model_suite_hash` | Keep |

---

### 9. Segment Score Stats Edge-ification

**Current:** `_key = SHA1(file_id|head_name|tagger_version)` — deterministic key encodes uniqueness.

**Target:** Edge `file_has_segment_stats` from `library_files` to `segment_score_stats`.

**Preserved fields:**

 | Field | Action | Rationale |
 | ------- | -------- | ----------- |
 | `file_id` | Remove | Replaced by edge `_from` |
 | `head_name` | Keep | Query filter + part of `_key` hash |
 | `tagger_version` | Keep | Part of `_key` hash, enables multi-version stats |
 | `num_segments` | Keep | Required metadata |
 | `pooling_strategy` | Keep | Required metadata |
 | `label_stats` | Keep | Core payload |
 | `processed_at` | Keep | Audit |

**Uniqueness mechanism:** The deterministic `_key = SHA1(file_id|head_name|tagger_version)` already ensures business uniqueness. At insert time, `file_id` comes from the edge's `_from`. Edge index `(_from, _to)` unique prevents duplicate edges. No additional constraints needed.

---

### 10. Calibration State Edge-ification

**Current:** `model_key` is `{backbone}_unknown` in production—a bug from the TensorFlow→ONNX migration. The backbone name comes from folder structure, but there's no version/date available in ONNX metadata.

**Problem:** String-based model identity (`model_key`) is unreliable. We don't have version info and can't reliably infer it.

**Target:** Edge to `ml_models` instead of string property.

```
calibration_state
├── _key: "{head_name}:{label_hash}"
├── head_name, label
├── calibration_def_hash
├── histogram, histogram_bins, p5, p95, n
├── underflow_count, overflow_count
└── computed_at: int

model_has_calibration (edge collection)
├── _from: ml_models/{model_key}
└── _to: calibration_state/{key}
```

**Benefits:**

- Model identity is the model document, not a constructed string
- Referential integrity via edge
- No need to infer/create version info that doesn't exist
- Graph traversal: "which calibrations belong to this model?"

**Remove:** `model_key`, `version`, `updated_at`, `last_computation_at`.

---

### 11. Library Folders Edge-ification

**Current:** `library_folders.library_id` is a string property.

**Target:** Edge collection `library_contains_folder` from `libraries` to `library_folders`.

---

## Index Strategy

### Current Pattern

Indexes are created in two places:

- **Bootstrap** (`arango_bootstrap_comp.py`) — idempotent startup, handles most indexes via `_ensure_index()`
- **Migrations** (`nomarr/migrations/`) — new indexes for schema changes

### Edge Collection Indexes

All edge collections require **bidirectional indexing** for traversal and uniqueness:

```python
# Pattern for every edge collection
_ensure_index(db, "edge_name", "persistent", ["_from", "_to"], unique=True)  # Uniqueness
_ensure_index(db, "edge_name", "persistent", ["_from"])  # Forward traversal
_ensure_index(db, "edge_name", "persistent", ["_to"])    # Reverse lookup
```

### New Indexes Required

 | Collection | Index Fields | Type | Rationale |
 | ------------ | -------------- | ------ | ----------- |
 | `library_contains_file` | `["_from", "_to"]` | Unique | Prevent duplicate membership |
 | `library_contains_file` | `["_from"]` | Persistent | Fast "files in library" query |
 | `library_contains_file` | `["_to"]` | Persistent | Fast "which library owns file" |
 | `library_contains_folder` | Same pattern | — | — |
 | `library_has_scan` | `["_from"]` | Unique | 1:1 library→scan |
 | `model_has_output` | Same as edge pattern | — | — |
 | `file_has_vectors` | Same as edge pattern | — | — |
 | `file_has_segment_stats` | Same as edge pattern | — | — |
 | `locks` | `["lock_type", "target_key"]` | Unique | Composite key alternative |
 | `locks` | `["expires_at"]` | TTL | Auto-cleanup |

### Renamed Field Indexes

When renaming fields, indexes must be recreated:

 | Collection | Old Index | New Index |
 | ------------ | ----------- | ----------- |
 | `library_files` | `["library_id"]` | Drop (edge replaces) |
 | `library_files` | `["library_id", "path"]` | `["absolute_path"]` unique per edge |
 | `library_files` | `["chromaprint"]` sparse | `["spectral_hash"]` sparse |

### Migration Order

1. Create new indexes on new collections/fields
2. Migrate data
3. Drop old indexes on deprecated fields
4. Drop deprecated fields

---

## Type Safety: Document Models

### Decision: Pydantic for Database I/O

Pydantic models will be used for database operations. This provides:

- Runtime validation on writes (prevent garbage data entering DB)
- Clear contracts for document shapes
- Easier refactoring (pydantic raises on schema violations)
- Single source of truth for field names, types, and constraints

### Current State

```
Interfaces (FastAPI) ← pydantic BaseModel (request/response validation)
Services             ← TypedDict / @dataclass DTOs
Persistence          ← dict[str, Any] + typed parameters
ArangoDB             ← JSON primitives only
```

### Target State

```
Interfaces (FastAPI) ← pydantic BaseModel (API contracts)
Services             ← pydantic models (domain contracts)
Persistence          ← pydantic models (DB contracts)
ArangoDB             ← JSON primitives only
```

### Pattern: Unified Models with Unvalidated Reads

Single pydantic model per collection. Validation on writes, no validation on reads.

```python
class LibraryFile(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True, extra="ignore")
    
    id: str | None = Field(default=None, alias="_id")
    key: str | None = Field(default=None, alias="_key")
    absolute_path: str
    relative_path: str
    duration_ms: int
    spectral_hash: str | None = None

# Write path: validated (prevents garbage entering DB)
def insert_library_file(db: Database, data: LibraryFile) -> str:
    doc = data.model_dump(by_alias=True, exclude={"id", "key"})
    result = db.collection("library_files").insert(doc)
    return result["_id"]

# Read path: unvalidated (zero overhead, full type hints)
def get_library_file(db: Database, file_id: str) -> LibraryFile | None:
    doc = db.collection("library_files").get(file_id)
    return LibraryFile.model_construct(**doc) if doc else None

def get_library_files_by_library(db: Database, library_id: str) -> list[LibraryFile]:
    docs = db.aql.execute(query, bind_vars={"library_id": library_id})
    return [LibraryFile.model_construct(**doc) for doc in docs]
```

**Why this works:**

- `model_construct()` creates an instance without validation — bypasses all field validators
- All type hints still work (IDE autocomplete, mypy)
- Single model definition per collection (no fragmentation)
- Writes are validated (catches bugs before data enters DB)
- Reads trust the database (data was validated on write)
- No performance penalty on bulk operations

### Model Structure

```
persistence/
├── models/
│   ├── __init__.py
│   ├── base.py              # Base model config, common fields
│   ├── library.py           # Library, LibraryScan
│   ├── file.py              # LibraryFile, LibraryFolder
│   ├── tag.py               # Tag, edge models
│   ├── ml.py                # MLModel, MLModelOutput, CalibrationState
│   ├── lock.py              # Lock
│   └── edge.py              # Generic edge model
└── database/
    └── ... (existing AQL modules use models)
```

### Base Model Configuration

```python
from pydantic import BaseModel, ConfigDict, Field

class ArangoDocument(BaseModel):
    """Base for all ArangoDB document models."""
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,  # Allow both alias and field name
        extra="ignore",         # Ignore unknown fields from DB
    )
    
    id: str | None = Field(default=None, alias="_id")
    key: str | None = Field(default=None, alias="_key")
    rev: str | None = Field(default=None, alias="_rev")


class ArangoEdge(ArangoDocument):
    """Base for all ArangoDB edge models."""
    from_id: str = Field(alias="_from")
    to_id: str = Field(alias="_to")
```

### Models Required

 | Collection | Model Name | Inherits |
 | ------------ | ------------ | ---------- |
 | `libraries` | `Library` | `ArangoDocument` |
 | `library_files` | `LibraryFile` | `ArangoDocument` |
 | `library_folders` | `LibraryFolder` | `ArangoDocument` |
 | `library_scans` | `LibraryScan` | `ArangoDocument` |
 | `tags` | `Tag` | `ArangoDocument` |
 | `file_states` | `FileState` | `ArangoDocument` |
 | `ml_models` | `MLModel` | `ArangoDocument` |
 | `ml_model_outputs` | `MLModelOutput` | `ArangoDocument` |
 | `calibration_state` | `CalibrationState` | `ArangoDocument` |
 | `segment_score_stats` | `SegmentScoreStats` | `ArangoDocument` |
 | `vectors_*` | `VectorDoc` | `ArangoDocument` |
 | `locks` | `Lock` | `ArangoDocument` |
 | `worker_claims` | `WorkerClaim` | `ArangoDocument` |
 | `health` | `HealthRecord` | `ArangoDocument` |
 | `sessions` | `Session` | `ArangoDocument` |
 | `meta` | `MetaEntry` | `ArangoDocument` |
 | All edge collections | `*Edge` | `ArangoEdge` |

---

## Persistence Layer Changes

### Generic Return Types

Current persistence functions return tightly-coupled DTOs or raw dicts. Target: return generic types that reduce coupling.

 | Current | Target | Rationale |
 | --------- | -------- | ----------- |
 | `LibraryDict` with scan fields | `LibraryDoc` + separate `ScanStateDoc` | Separation of concerns |
 | Raw ArangoDB cursor results | Typed `*Doc` TypedDicts | Type safety |
 | FK property in return | Edge info or omit | Don't leak FK implementation |

### Query Pattern Standardization

Standardize on graph traversal patterns where edges exist:

```python
# Before: property filter
FOR file IN library_files
    FILTER file.library_id == @library_id
    RETURN file

# After: graph traversal
FOR file IN OUTBOUND @library_id GRAPH 'library_graph'
    RETURN file
```

---

## Migration Strategy

All changes implemented as forward-only migrations in `nomarr/migrations/`.

### Phase 1: Additive (Non-breaking)

1. Create new edge collections
2. Create named graphs
3. Add new state vertices
4. Create `locks` collection

### Phase 2: Data Migration

1. Migrate FK properties to edges
2. Migrate lock data to consolidated collection
3. Migrate scan state to separate collection
4. Rewrite `meta` with `_key`

### Phase 3: Code Updates

1. Update persistence layer queries to use graphs
2. Update return types to generic
3. Remove denormalized tag fields from queries

### Phase 4: Cleanup

1. Remove FK property fields
2. Remove denormalized fields
3. Drop old lock collections
4. Drop unused indexes

---

## Success Criteria

- [ ] All FK-as-property patterns converted to edges
- [ ] Named graphs defined for all edge collections
- [ ] All edge collections have bidirectional indexes (`_from`, `_to`, unique composite)
- [ ] `locks` collection consolidates capacity_probe and vector_promotion
- [ ] `worker_claims` remains separate
- [ ] `file_states` vocabulary complete
- [ ] `meta` uses `_key` for O(1) lookup
- [ ] Libraries contain only identity data
- [ ] Tags are edge-only
- [ ] Unified pydantic models in `persistence/models/` for all collections
- [ ] `ArangoDocument` and `ArangoEdge` base classes implemented
- [ ] Persistence layer returns pydantic models (`model_construct()` for reads, validation on writes)
- [ ] All queries use graph traversal where appropriate
- [ ] Old indexes dropped after field removal
- [ ] Zero lint errors after each migration
