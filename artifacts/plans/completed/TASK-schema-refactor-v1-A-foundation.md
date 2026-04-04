# Task: Schema Refactor v1 — Part A Foundation & Infrastructure

## Problem Statement

Create foundational Pydantic base classes (`ArangoDocument`, `ArangoEdge`), expand file states vocabulary, fix meta collection key strategy, consolidate locks, create all empty edge collections for future parts, and define named graphs. This is the single migration for all schema changes — subsequent parts add to it.

## Phases

### Phase 1: Base Model Infrastructure

- [x] Create `persistence/models/__init__.py` with public exports
- [x] Create `persistence/models/base.py` with `ArangoDocument` (aliased `_id`/`_key`/`_rev`) and `ArangoEdge` (aliased `_from`/`_to`) base classes
- [x] Run `lint_project_backend(path="nomarr/persistence/models")`

### Phase 2: Migration Scaffold

- [x] Create `nomarr/migrations/V021_schema_refactor_v1.py` with idempotent structure following V001 patterns
  **Notes:** This is the ONLY migration file for the entire refactor
- [x] Add required metadata: `MIGRATION_VERSION = "0.2.1"`, `DESCRIPTION`
- [x] Run `lint_project_backend(path="nomarr/migrations")`

### Phase 3: Locks Consolidation

- [x] Create `locks` document collection with schema: `_key: "{lock_type}:{target_key}"`, `lock_type`, `owner_id`, `target_key`, `acquired_at`, `expires_at`
- [x] Add TTL index on `expires_at` for auto-cleanup
- [x] Add unique index on `["lock_type", "target_key"]` for composite key pattern
- [x] Migrate data from `ml_capacity_probe_locks` → `locks` with `lock_type: "capacity_probe"`
- [x] Migrate data from `vector_promotion_locks` → `locks` with `lock_type: "vector_promotion"`
- [x] Drop `ml_capacity_probe_locks` and `vector_promotion_locks` collections
- [x] Run `lint_project_backend(path="nomarr/migrations")`

### Phase 4: Meta Key Fix

- [x] Rewrite all meta documents: copy `key` property to `_key`, drop `key` property
    **Notes:** Added meta document migration in Data Migration section — copies `key` property to `_key` and removes `key` property. Uses two AQL queries: first UPSERT for docs where `_key != key`, then UPDATE to strip remaining `key` properties.
- [x] Drop `meta.key` index (O(log n) → O(1) lookup via `_key`)
    **Notes:** Added index cleanup in Cleanup section — iterates over `meta` indexes and drops any persistent index on `["key"]` field. Guarded with `db.has_collection("meta")` for idempotency.
- [x] Run `lint_project_backend(path="nomarr/migrations")`
    **Notes:** Passed — 0 errors, 1 file checked.

### Phase 5: File States Expansion

- [x] Insert new file state vertices: `scanned`, `too_short`, `vectors_extracted`, `tags_written`, `errored`
  **Notes:** Existing `calibrated`, `ml_tagged`, `reconciled` preserved
- [x] Run `lint_project_backend(path="nomarr/migrations")`

### Phase 6: Edge Collections Creation

- [x] Create all empty edge collections with bidirectional indexes (`["_from", "_to"]` unique, `["_from"]`, `["_to"]`): `library_contains_file`, `library_contains_folder`, `library_has_scan`, `file_has_vectors`, `file_has_segment_stats`, `model_has_output`, `model_has_calibration`
- [x] Run `lint_project_backend(path="nomarr/migrations")`

### Phase 7: Named Graph Definitions

- [x] Create `library_graph` with edge definitions: `library_contains_file`, `library_contains_folder`, `library_has_scan`
- [x] Create `file_graph` with edge definitions: `file_has_state`, `song_has_tags`, `file_has_vectors`, `file_has_segment_stats`
- [x] Create `ml_graph` with edge definitions: `model_has_output`, `model_has_calibration`, `tag_model_output`
- [x] Run `lint_project_backend()`

## Completion Criteria

- `lint_project_backend()` passes with zero errors
- Migration imports cleanly: `python -c "from nomarr.migrations.V021_schema_refactor_v1 import upgrade"`
- `ArangoDocument` and `ArangoEdge` instantiate correctly with `model_construct()` bypass
- All 7 new edge collections have exactly 3 indexes each (unique composite + bidirectional)
- `locks` collection has TTL index on `expires_at`
- `meta` documents use `_key` directly (no `key` property)
- File states collection has 8 vertices: `scanned`, `too_short`, `vectors_extracted`, `ml_tagged`, `calibrated`, `tags_written`, `reconciled`, `errored`
- Graphs `library_graph`, `file_graph`, `ml_graph` exist with correct edge definitions

## Relevant Files

- `nomarr/persistence/models/__init__.py` — Create with `ArangoDocument`, `ArangoEdge` exports
- `nomarr/persistence/models/base.py` — Base classes with `ConfigDict(from_attributes=True, populate_by_name=True, extra="ignore")` and aliased fields per design doc §Type Safety
- `nomarr/migrations/V021_schema_refactor_v1.py` — Single migration for entire refactor; use patterns from V001_baseline.py for idempotent collection/index/graph creation
- Reference: `nomarr/persistence/database/ml_capacity_aql.py` `try_acquire_probe_lock` — current lock schema to migrate
- Reference: `nomarr/persistence/database/vector_promotion_lock_aql.py` `try_acquire_lock` — current lock schema to migrate
- Reference: `nomarr/persistence/database/file_states_aql.py` — edge operation patterns

## Decisions

- Migration version `0.2.1` (patch bump from `0.2.0`)
- Migration file named `V021_*` following standard naming
- Edge collections created empty — data migration happens in Parts B-F
- Existing edge collections (`file_has_state`, `song_has_tags`, `tag_model_output`) included in graph definitions but not recreated
- `worker_claims` explicitly NOT migrated to `locks` (different semantics per design doc)
