---
name: nomarr-arangodb
description: ArangoDB setup, client configuration, SafeDatabase wrapper, AQL safety measures, error workarounds (ERR 1579/1210/1203), collection types, truncation patterns, and bootstrap procedures. Use when working on persistence layer, AQL queries, database schema changes, debugging ArangoDB errors, or modifying truncation/collection creation logic.
---

# Nomarr ArangoDB

## Mental Model

Nomarr uses ArangoDB 3.12 as its primary datastore. All database access goes through a `SafeDatabase` wrapper that sanitizes bind variables and proxies `aql.execute()`. Domain-specific AQL lives in `nomarr/persistence/database/*_aql.py` modules, each providing typed methods for their domain (library, ML models, tags, etc.). Collections are created idempotently at bootstrap via DDL definitions in `schema/ddl.py`. A static AQL test suite catches mixed read-write conflicts, duplicate variables, and f-string injection at test time.

## Coverage
**Documented:** Docker version, client config, SafeDatabase wrapper, AQL safety tests, truncation patterns, collection types, known ArangoDB error workarounds, bootstrap procedures.
**Not yet documented:** Connection pool behavior, performance characteristics of AQL truncate vs native truncate, migration patterns for schema changes.
**Last extended:** 2026-07-12

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
