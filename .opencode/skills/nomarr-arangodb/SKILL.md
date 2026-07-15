---
name: nomarr-arangodb
description: **⚠️ DEPRECATED LAYER.** The ArangoDB persistence layer has been migrated to PostgreSQL (ADR-031). This skill documents the LEGACY ArangoDB schema for reference during the final migration cleanup. The ACTIVE persistence uses `database/*_repo.py` files with SQLAlchemy async + pgvector. Use the PostgreSQL-based repository classes (`nomarr/persistence/database/*_repo.py`) for all new work.
---

# Nomarr ArangoDB (Deprecated)

## Mental Model

**This is the LEGACY ArangoDB layer, fully replaced by PostgreSQL (ADR-031).** All schema files (`schema/names.py`, `schema/ddl.py`, `aql/primitives.py`, `database/*_aql.*`) are deleted from the working tree. The information below is preserved from git history for reference during the final migration cleanup.

The legacy system used ArangoDB 3.12 via a `SafeDatabase` wrapper. Domain-specific AQL lived in `nomarr/persistence/database/*_aql.py` modules. Collections were created idempotently via DDL definitions in `schema/ddl.py`. A static AQL test suite caught mixed read-write conflicts, duplicate variables, and f-string injection.

## Migration Status
- **Commit 97c090e7** — "PostgreSQL + pgvector migration — design doc and 7 implementation plans"
- **Commit f37fdf60** — "refactor(persistence): ADR-031 three-tier facade migration complete"
- **Commit 28903b44** — "cleanup tasks, splitting large files, partial docs updates" (deleted remaining AQL files)
- **Active layer:** `nomarr/persistence/database/*_repo.py` with SQLAlchemy async engine + pgvector
- **Git status (current):** All ArangoDB schema files and AQL modules are `deleted` from the working tree

## Coverage
**Documented:** Legacy ArangoDB collection names, edge collections, DDL definitions, AQL primitives, bootstrap procedure (all from git history).
**Not yet documented:** Final migration cleanup tasks, removal of ArangoDB dependencies.
**Last extended:** 2026-07-15

## Key Findings

### ArangoDB Version & Docker Setup
- **Location:** `docker/compose.yaml`, `.github/workflows/e2e.yml`
- **Image:** `arangodb:3.12` with `--vector-index` and `--query.memory-limit=1073741824` flags
- **Python driver:** `python-arango>=8.0.0` (no upper bound)
- **Why it matters:** 3.12 is the stable version with vector index support. The --vector-index flag is required for ML vector operations.

### Minimal Client Configuration
- **Location:** `nomarr/persistence/arango_client.py:L88-L93`
- **What:** `ArangoClient(hosts=hosts)` — no timeout, pool_size, SSL, retry, or verify_certs configured.
- **Why it matters:** No connection timeout means long TCP hangs. No request timeout means long queries block indefinitely. No SSL means plaintext traffic.

### SafeDatabase Wrapper
- **Location:** `nomarr/persistence/arango_client.py:L22-L83`
- **Components:**
  - `_jsonify_for_arango()` — recursively converts sets→lists, custom objects→dicts before bind var binding
  - `SafeAQL` — proxy on `db.aql` that tracks execute calls
  - `has_collection(name)` / `delete_collection(name)` — safe helpers with guards

### Collection Types — 18 Document + 12 Edge
- **Location:** `nomarr/persistence/schema/ddl.py`, `tests/unit/aql_safety/conftest.py:L31-L75`
- **Document:** `tags`, `libraries`, `library_files`, `sessions`, `ml_models`, `ml_model_outputs`, `file_states`, `health`, `meta`, `locks`, `worker_claims`, `worker_restart_policy`, `navidrome_playcounts`, `navidrome_tracks`, `library_folders`, `library_pipeline_states`, `library_scans`, `applied_migrations`, `calibration_history`, `calibration_state`, `ml_output_streams`
- **Edge:** `song_has_tags`, `library_contains_file`, `library_contains_folder`, `file_has_vectors`, `file_has_state`, `file_has_output_stream`, `file_has_segment_stats`, `has_nd_id`, `has_plays`, `library_has_pipeline_state`, `library_has_scan`, `model_has_calibration`, `model_has_output`, `output_has_stream`

### Truncation Patterns
- **AQL-based (dominant):** `FOR doc IN @@collection REMOVE doc IN @@collection OPTIONS { ignoreErrors: true }` — used in domain AQL modules (~10+ callers)
- **Native (2 callers):** `collection.truncate()` — used by `VectorNamespace` in `schema_types.py`
- **Why it matters:** AQL-based truncate is O(n) (iterates documents), native is O(1). The AQL pattern is slower for large collections.

### Known ArangoDB Error Workarounds
- **ERR 1579** (read-after-write): Split edge graph modifications into 3 separate queries (read→REMOVE→INSERT). Applied in `schema_types.py`, `vectors_aql.py`, `ml_vector_maintenance_comp.py`, migration V038.
- **ERR 1210** (unique constraint): Bootstrap `_ensure_index()` ignores HTTP 409 + HTTP 400 with errno 1210 for idempotent index creation.
- **ERR 1203** (collection not found): Caught in `application.py` `get_config_option()` / `get_schema_version()`, returns default.

### AQL Safety Test Suite
- **Location:** `tests/unit/aql_safety/`
- **Detects:**
  - Pattern A: LET-read followed by INSERT/UPSERT on same collection (ERR 1579 risk)
  - Pattern B: FOR-loop reading collection with REMOVE+INSERT in loop body
  - Pattern C: REMOVE+UPSERT on same collection
  - Duplicate top-level variable names (ERR 1511)
  - F-string interpolation in AQL strings (injection risk)
  - Validates all collection references against known name set

### Bootstrap — Idempotent Collection Creation
- **Location:** `nomarr/persistence/arango_bootstrap_comp.py`
- **Pattern:** `contextlib.suppress(CollectionCreateError)` around `create_collection()`
- **Index creation:** Ignores `DuplicateKeyError`, passes `safe=True`
- **Edge collections:** Created with `edge=True` parameter

## Critical Invariants
- **All AQL must be in `nomarr/persistence/database/`** — this is where the static safety tests scan. AQL strings in other locations are not checked.
- **Do not merge read+write in a single AQL query on the same collection** — this triggers ERR 1579. Split into separate queries.
- **All collection names must be in CollectionNames enum or tests will fail** — the conftest validates every collection reference.
- **Bind variables must be used for all user data** — f-strings in AQL are detected and rejected by tests.
- **Native collection.truncate() should be used for bulk truncation** — the AQL FOR+REMOVE pattern is O(n) and should not be used for large collections.

## Legacy ArangoDB Collection Names (from `schema/names.py`, git history)

```python
class CollectionNames(StrEnum):
    """All ArangoDB collection names in the legacy schema."""

    # Document collections (22 total)
    META = "meta"
    LOCKS = "locks"
    HEALTH = "health"
    SESSIONS = "sessions"
    WORKER_CLAIMS = "worker_claims"
    WORKER_RESTART_POLICY = "worker_restart_policy"
    VRAM_PROMISES = "vram_promises"
    APPLIED_MIGRATIONS = "applied_migrations"
    LIBRARIES = "libraries"
    LIBRARY_FOLDERS = "library_folders"
    LIBRARY_FILES = "library_files"
    LIBRARY_SCANS = "library_scans"
    LIBRARY_PIPELINE_STATES = "library_pipeline_states"
    FILE_STATES = "file_states"
    TAGS = "tags"
    ML_MODELS = "ml_models"
    ML_MODEL_OUTPUTS = "ml_model_outputs"
    ML_OUTPUT_STREAMS = "ml_output_streams"
    CALIBRATION_STATE = "calibration_state"
    CALIBRATION_HISTORY = "calibration_history"
    NAVIDROME_TRACKS = "navidrome_tracks"
    NAVIDROME_PLAYCOUNTS = "navidrome_playcounts"

    # Edge collections (14 total)
    SONG_HAS_TAGS = "song_has_tags"
    LIBRARY_CONTAINS_FILE = "library_contains_file"
    LIBRARY_CONTAINS_FOLDER = "library_contains_folder"
    FILE_HAS_VECTORS = "file_has_vectors"
    FILE_HAS_STATE = "file_has_state"
    FILE_HAS_OUTPUT_STREAM = "file_has_output_stream"
    FILE_HAS_SEGMENT_STATS = "file_has_segment_stats"
    HAS_ND_ID = "has_nd_id"
    HAS_PLAYS = "has_plays"
    LIBRARY_HAS_PIPELINE_STATE = "library_has_pipeline_state"
    LIBRARY_HAS_SCAN = "library_has_scan"
    MODEL_HAS_CALIBRATION = "model_has_calibration"
    MODEL_HAS_OUTPUT = "model_has_output"
    OUTPUT_HAS_STREAM = "output_has_stream"
```

## Legacy DDL Index Definitions (from `schema/ddl.py`, git history)

### Index-heavy document collections:
- **META** — `_key` index
- **LIBRARY_FILES** — 9 indexes: unique(library_id, path), unique(library_id, normalized_path), (library_id, is_deleted), (library_id, added_at), (path), (file_extension), (duration_ms, library_id), (artist, album, title, library_id), (file_extension, library_id, is_deleted)
- **TAGS** — unique(name, value) + (source), (name)
- **LIBRARY_SCANS** — (library_id, started_at), (status)
- **SESSIONS** — TTL expiry index on (expires_at)
- **ML_MODELS** — (name, version)
- **CALIBRATION_STATE** — unique(backbone)
- **LIBRARY_FOLDERS** — (library_id), (parent_id)
- **NAVIDROME_TRACKS** — unique(song_id)

### Edge collections with unique indexes:
- All edge collections except `file_has_vectors` have unique `(_from, _to)` indexes
- `file_has_vectors` has a non-unique `(_from, _to)` index (since `_to` reference is a partitioned collection)

## Legacy AQL Primitives (from `aql/primitives.py`, git history)

### Document Operations
| Function | Operation |
|---|---|
| `execute(query, bind_vars, count, stream, ...)` | Raw AQL execution proxy |
| `get_many_by_keys(collection, keys)` | `FOR key IN @keys FILTER doc._key == key` |
| `get_many_by_field(collection, field, values)` | `FOR val IN @values FILTER doc.field == val` |
| `get_filtered_docs(collection, filters, ...)` | Multi-field filter with sorting/pagination |
| `count_distinct_edge_sources_*(coll, edge_coll, ...)` | Edge traversal count |
| `delete_many_by_keys(collection, keys)` | `FOR key IN @keys REMOVE key` |
| `delete_many_by_field(collection, field, values)` | Filter-based bulk delete |
| `upsert_by_field(collection, field, value, doc)` | `UPSERT {field: value} INSERT doc UPDATE doc` |
| `insert_document(collection, doc)` | `INSERT doc INTO collection` |
| `update_document_by_key(collection, key, doc)` | `UPDATE key WITH doc` |

### Edge Operations
| Function | Operation |
|---|---|
| `upsert_edge(edge_collection, from_id, to_id, doc)` | `UPSERT {_from: f, _to: t} INSERT ... UPDATE ...` |
| `delete_edges(edge_collection, from_id, to_id_pattern)` | Bulk edge deletion |
| `delete_edges_by_from_list(edge_collection, from_ids)` | Delete all edges from given vertices |
| `delete_edge_by_key(edge_collection, key)` | Single edge removal |
| `insert_edges_batch(edge_collection, edges)` | Batch edge insertion |
| `count_edges(edge_collection)` | `FOR e IN @@ec COLLECT WITH COUNT INTO c RETURN c` |

## Legacy Domain AQL Module Map (deleted, from git history)

| Domain | Module | Key Operations |
|---|---|---|
| **App** | `database/app_aql/` (subpackage) | Meta (config options, schema version), Locks (acquire/release), Worker Claims, Pipeline States, Sessions, Migrations, VRAM Promises, Health |
| **Libraries** | `database/libraries_aql.py` | CRUD, get_by_name, list |
| **Library Files** | `database/library_files_aql/` (subpackage) | File CRUD, folder CRUD, file-link ops, folder tree queries |
| **Tags** | `database/tags_aql/` (subpackage) | Tag CRUD, file-tag graph traversal, tag search, analytics/coverage, curation (rename/merge), mood ops |
| **File States** | `database/file_states_aql.py` | State edge operations, transitions |
| **Scans** | `database/scan_aql.py` | Scan CRUD, last scan query |
| **ML Models** | `database/ml_models_aql.py` | Model CRUD, calibration persistence |
| **ML Streams** | `database/ml_streams_aql.py` | Output stream insert+edge wire, batch ops |
| **ML Embeddings** | `database/ml_embedding_streams_aql.py` | Embedding stream CRUD |
| **Vectors** | `database/vectors_aql.py` | Vector INSERT/kNN/ANN search, ERR 1579 workaround |
| **Navidrome** | `database/navidrome_aql.py` | Track mapping, playcount sync |
| **Calibration** | `database/calibration_state_aql.py` | Calibration state CRUD |
| **Calibration History** | `database/calibration_history_aql.py` | Calibration history CRUD |
| **Calibration Queue** | `database/calibration_queue_aql.py` | Queue operations |
| **Calibration Runs** | `database/calibration_runs_aql.py` | Run tracking |
| **MRU/Entities** | `database/entities_aql.py` | MRU entity operations |
| **GPU Claims** | `database/gpu_claims_aql.py` | GPU claim operations |
| **ML Capacity** | `database/ml_capacity_aql.py` | ML capacity tracking |
| **Pipeline States** | `database/library_pipeline_states_aql.py` | Pipeline state per library |
| **Library Tags** | `database/library_tags_aql.py` | Tag-by-library queries |
| **Segments** | `database/segment_scores_stats_aql.py` | Segment score statistics |
| **Tag Queue** | `database/tag_queue_aql.py` | Tag queue operations |
| **Tag Model Output** | `database/tag_model_output_aql.py` | Tag→model output mapping |
| **Vector Promotion** | `database/vector_promotion_lock_aql.py` | Vector promotion lock |
| **Vectors Track** | `database/vectors_track_aql/` (subpackage) | Hot/cold vector collection maintenance |
| **Vectors Track Vel** | `database/vectors_track_aql.py` | Vector track operations |
| **Navidrome Maps** | `database/navidrome_song_map_aql.py` | Song mapping |
| **Navidrome Tracks** | `database/navidrome_tracks_aql.py` | Track operations (distinct from mapping) |
| **Worker Restarts** | `database/worker_restart_policy_aql.py` | Restart policy operations |

## Sources
- `docker/compose.yaml`, `.github/workflows/e2e.yml` — Docker/CI version pinning
- `nomarr/persistence/arango_client.py` — SafeDatabase, SafeAQL, client init
- `nomarr/persistence/schema/ddl.py` — Collection definitions
- `nomarr/persistence/schema/__init__.py` — CollectionNames enum
- `nomarr/persistence/arango_bootstrap_comp.py` — Bootstrap procedure
- `nomarr/persistence/database/ml_models_aql.py` — AQL truncate pattern
- `nomarr/persistence/schema_types.py` — Native truncate pattern (VectorNamespace)
- `nomarr/persistence/database/primitives.py` — Common AQL helpers
- `nomarr/persistence/api/application.py` — ERR 1203 handling
- `tests/unit/aql_safety/` — Static AQL safety tests
- `requirements/requirements.txt`, `pyproject.toml` — python-arango version
- `nomarr/persistence/database/vectors_aql.py` — ERR 1579 workaround
- `nomarr/persistence/arango_client.py` — Client config
