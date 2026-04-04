# Task: Schema Refactor v1 — Part E File Artifacts

## Problem Statement
Populate `file_has_vectors` and `file_has_segment_stats` edge collections from existing FK properties, update persistence queries to use graph traversal, then drop FK columns. The key complexity is **polymorphic edges** — vector collections are dynamically created per backbone per library (`vectors_track_{hot|cold}__{backbone}__{library_key}`), requiring dynamic collection discovery in migration.

## Phases

### Phase 1: Data Migration — file_has_segment_stats
- [x] Add AQL to V021: `FOR doc IN segment_score_stats FILTER doc.file_id != null INSERT { _from: doc.file_id, _to: doc._id } INTO file_has_segment_stats OPTIONS { ignoreErrors: true }`
- [x] Run `lint_project_backend(path="nomarr/migrations")`

### Phase 2: Data Migration — file_has_vectors (Polymorphic)
- [x] Add V021 helper to discover all `vectors_track_*` collections via `db.collections()` — log each collection
- [x] AQL loop per collection: `FOR doc IN {coll} FILTER doc.file_id != null INSERT { _from: doc.file_id, _to: doc._id } INTO file_has_vectors`
- [x] Run `lint_project_backend(path="nomarr/migrations")`

### Phase 3: Update segment_scores_stats_aql.py
- [x] `upsert_stats()` — UPSERT edge after doc
- [x] `upsert_stats_batch()` — batch UPSERT edges
- [x] `get_stats_for_file()` — `FOR stats IN OUTBOUND @file_id file_has_segment_stats`
- [x] `get_stats_for_files_bulk()` — same traversal pattern
- [x] `delete_by_file_id()` — cascade-delete edges after doc removal
- [x] `delete_by_file_ids()` — batch cascade
- [x] Run `lint_project_backend(path="nomarr/persistence/database")`

### Phase 4: Update vectors_track_aql.py — Hot
- [x] `upsert_vector()` — UPSERT edge after doc
- [x] `get_vector()` — `FOR vec IN OUTBOUND @file_id file_has_vectors FILTER IS_SAME_COLLECTION(@coll, vec)`
- [x] `get_vectors_by_file_ids()` — same traversal
- [x] `delete_by_file_id()` — cascade-delete edge
- [x] `delete_by_file_ids()` — batch cascade
- [x] Run `lint_project_backend(path="nomarr/persistence/database")`

### Phase 5: Update vectors_track_aql.py — Cold
- [x] `get_vector()` — OUTBOUND traversal with `IS_SAME_COLLECTION`
- [x] `get_vectors_by_file_ids()` — same pattern
- [x] Add `delete_by_file_id()` / `delete_by_file_ids()` (currently missing)
- [x] Run `lint_project_backend(path="nomarr/persistence/database")`

### Phase 6: Update db.py orchestration
- [x] `delete_vectors_by_file_id()` — add edge cleanup: `FOR e IN file_has_vectors FILTER e._from == @file_id REMOVE e`
- [x] `delete_vectors_by_file_ids()` — batch edge cleanup
- [x] Run `lint_project_backend(path="nomarr/persistence")`

### Phase 7: Caller verification — Components
- [x] Review `ml_vector_persist_comp.py`, `ml_vector_retrieve_comp.py`, `ml_vector_maintenance_comp.py` — verify no changes needed
    **Changes:** Updated `drain_hot_to_cold` to migrate edges from hot→cold. Updated `backfill_genres` to use `INBOUND file_has_vectors` traversal instead of FK.
- [x] Run `lint_project_backend(path="nomarr/components")`

### Phase 8: Caller verification — Workflows
- [x] Review `write_calibrated_tags_wf.py`, `apply_calibration_wf.py` — consumers of segment_stats
    **Notes:** No changes needed. Workflows use updated persistence layer methods correctly.
- [x] Run `lint_project_backend(path="nomarr/workflows")`

### Phase 9: Caller verification — Workers
- [x] Review `discovery_worker.py` — upsert_stats_batch caller
    **Notes:** No changes needed. Worker sends entries with `file_id`; persistence extracts it for edge creation and doesn't store it in the document.
- [x] Run `lint_project_backend(path="nomarr")`

### Phase 10: Drop FK columns
- [x] V021: `UPDATE doc WITH { file_id: null } OPTIONS { keepNull: false }` for `segment_score_stats`
- [x] V021: Same for each `vectors_track_*` collection (dynamic iteration)
- [x] V021: Drop index `segment_score_stats["file_id"]`
- [x] Run `lint_project_backend(path="nomarr/migrations")`

### Phase 11: Tests & Final Verification
- [x] Update pytest mocks for edge-based queries
    **Changes:** Updated `search_similar` and `search_similar_by_genre` to resolve `file_id` via `INBOUND file_has_vectors` edge traversal. Test mocks return `file_id` which now matches expected format.
- [x] Full `lint_project_backend()` — zero errors
- [x] Verify migration imports
    **Notes:** Migration uses only stdlib + TYPE_CHECKING-guarded imports. No runtime imports from nomarr.

## Completion Criteria
1. `lint_project_backend()` passes with zero errors
2. After migration: `file_has_segment_stats` edge count == `segment_score_stats` doc count
3. After migration: `file_has_vectors` edge count == Σ `vectors_track_*` doc counts
4. `FOR s IN segment_score_stats FILTER s.file_id != null RETURN 1` → empty
5. Calibration workflows still retrieve stats; similarity search still works

## Decisions Made
| Decision | Rationale |
|----------|----------|
| Use `IS_SAME_COLLECTION(coll, doc)` for polymorphic edge filtering | Single-collection reads in traversal |
| Edge deletion after doc deletion | Prevents orphan edges |
| Keep vector collection naming as-is (`vectors_track_*`) | Renaming is out of scope |
| Add missing delete methods to `VectorsTrackColdOperations` | Cascade completeness |
| Dynamic collection discovery via `db.collections()` | Vector collections created dynamically |
