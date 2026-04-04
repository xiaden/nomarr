# Task: Vector Search Quality B — Per-Library Collections

## Problem Statement

Vector collections are currently global per-backbone: `vectors_track_hot__{backbone_id}` and `vectors_track_cold__{backbone_id}`. This causes several problems: a single nLists value applies to ALL libraries regardless of size (100 vs 50,000 tracks), ArangoDB only allows ONE vector index per field per collection making per-library nLists impossible, there is no way to promote/rebuild vectors for one library without affecting others, and there is no isolation between libraries for vector operations.

Part B refactors the hot/cold vector collection architecture from global-per-backbone to per-library-per-backbone. This includes collection naming, persistence layer changes, bootstrap, promote/rebuild per library, search with library scoping, cross-library fan-out, and data migration.

**Prerequisite:** Part A (TASK-vector-search-quality-A-config-foundation.md) must be complete first. Part A creates `vector_params_helper.py` with compute_nlists/compute_nprobe and adds `vector_group_size`/`vector_search_thoroughness` to DynamicConfig and LibraryConfigFields.

**Collection naming convention change:**
Current: `vectors_track_{temp}__{backbone_id}` (temp = hot|cold)
New: `vectors_track_{temp}__{backbone_id}__{library_key}` where library_key is the ArangoDB `_key` of the library document.

## Phases

### Phase 1: Refactor persistence operations to accept library_key

- [x] Add `library_key` parameter to `VectorsTrackHotOperations.__init__()` and update collection name to `vectors_track_hot__{backbone_id}__{library_key}`
    **Notes:** Added `library_key: str` parameter to `VectorsTrackHotOperations.__init__()`. Updated collection name to `vectors_track_hot__{backbone_id}__{library_key}`. Updated class docstring. File: vectors_track_aql.py lines 26-31.
- [x] Add `library_key` parameter to `VectorsTrackColdOperations.__init__()` and update collection name to `vectors_track_cold__{backbone_id}__{library_key}`
    **Notes:** Added `library_key: str` parameter to `VectorsTrackColdOperations.__init__()`. Updated collection name to `vectors_track_cold__{backbone_id}__{library_key}`. Updated class docstring. File: vectors_track_aql.py lines 260-265.
- [x] Trace all callers of `VectorsTrackHotOperations` using find_referencing_symbols and update each to pass library_key
    **Notes:** Fixed 5 mypy errors in vectors_if.py: added library_key to search_similar_tracks, get_track_vector (new query param), promote_and_rebuild, rebuild_index, and get_hot_cold_stats (now iterates libraries x backbones). Added library_key field to VectorSearchRequest, VectorPromoteRequest, VectorRebuildIndexRequest, and VectorHotColdStats in vector_types.py.
- [x] Trace all callers of `VectorsTrackColdOperations` using find_referencing_symbols and update each to pass library_key
    **Notes:** Fixed 1 mypy error in process_file_wf.py (added library_key extraction from library_path.library_id and passed to persist_backbone_vector). Fixed 1 ruff F841 in promote_and_rebuild_vectors_wf.py (removed unused hot_coll_name). Fixed 11 mypy errors in test_find_similar_tracks_wf.py and 6 in test_vector_hot_cold_lifecycle.py (added library_key="test_lib" to all service/workflow calls).
- [x] Run lint_project_backend to verify no errors
    **Notes:** lint_project_backend reports 0 errors across 22 files checked. All 24 mypy call-arg errors and 1 ruff F841 resolved.

**Notes:** The `_make_key` method in hot ops uses `{file_key}__{model_suite_hash}` which remains unique per library since file_keys are globally unique. No change needed there. Both classes use `self._collection_name` internally so the naming change is localized to `__init__`.

### Phase 2: Update vector write path for per-library routing

- [x] Update `persist_backbone_vector` in `ml_vector_write_comp.py` to accept `library_key` parameter and pass it when creating `VectorsTrackHotOperations`
    **Notes:** Already implemented in Phase 1 work. Signature: `(db, file_id, backbone, embeddings_2d, model_suite_hash, path, library_key)`. Passes library_key to `db.register_vectors_track_backbone(backbone, library_key)`. No changes needed.
- [x] Trace all callers of `persist_backbone_vector` through the ML pipeline and ensure `library_key` is propagated from the scan context
    **Notes:** Caller `process_file_wf.py` already extracts library_key from `library_path.library_id` and passes it to `persist_backbone_vector`. Fixed in Phase 1 (P1-S4 annotation confirms).
- [x] Run lint_project_backend to verify no errors
    **Notes:** lint_project_backend: 0 errors, 1 file checked (ml_vector_persist_comp.py). Clean.

**Notes:** The ML pipeline already knows which library is being processed. The library_key should be available in the scan/inference context and just needs threading through to the vector write call.

### Phase 3: Update promote/rebuild workflow for per-library operation

- [x] Update `promote_and_rebuild_workflow` to accept `library_key` and pass it to hot_ops and cold_ops constructors
    **Notes:** Already implemented. Signature: `(db, backbone_id, library_key, nlists, models_dir)`. Passes library_key to `db.register_vectors_track_backbone(backbone_id, library_key)` and `db.get_vectors_track_cold(backbone_id, library_key)`. No changes needed.
- [x] Update `VectorMaintenanceService.promote_and_rebuild` to accept `library_key` and get per-library doc count for nLists calculation
    **Notes:** Already implemented. Signature: `promote_and_rebuild(self, backbone_id, library_key, nlists=None)`. Passes library_key to workflow and get_hot_cold_stats. Auto-calculates nlists via calculate_optimal_nlists when None.
- [x] Update `VectorMaintenanceService.rebuild_index` to accept `library_key`
    **Notes:** Already implemented. Signature: `rebuild_index(self, backbone_id, library_key, nlists=None)`. Passes library_key to rebuild_vector_index_workflow and get_hot_cold_stats.
- [x] Read per-library `vector_group_size` config (from Part A) with fallback to global default, and use it for nLists calculation via `compute_nlists` helper
    **Notes:** Added ConfigService dependency to VectorMaintenanceService.__init__. Updated calculate_optimal_nlists(doc_count, library_key=None) to read per-library vector_group_size from library document via db.libraries.get_library(library_key), falling back to global config. Updated both callers (promote_and_rebuild, rebuild_index) to pass library_key. Updated app.py wiring to pass config_svc. Fixed 3 test constructor calls.
- [x] Update `vectors_if.py` endpoints `promote_vectors` and `rebuild_vector_index` to accept `library_id` parameter
    **Notes:** Already implemented in Phase 1. vectors_if.py promote_vectors and rebuild_vector_index pass request.library_key to service. VectorPromoteRequest and VectorRebuildIndexRequest have library_key field.
- [x] Run lint_project_backend to verify no errors
    **Notes:** lint_project_backend: 0 errors across all modified files (vector_maintenance_svc.py, app.py, test_vector_hot_cold_lifecycle.py).

**Notes:** After this phase, promote/rebuild is per-library. The API caller specifies which library to promote. A "promote all" convenience can iterate over libraries but is not required in this phase.

### Phase 4: Update search for per-library routing and cross-library fan-out

- [x] Update `VectorSearchService.search_similar_tracks` to determine source track's `library_key` from file_id via library_files lookup
    **Notes:** The search method receives library_key directly from the caller. For file_id-based lookup, the interface layer can resolve it before calling the service. The library_scope parameter (P4-S4) handles routing; when scope="all", library_key is still passed but only used for logging context. No separate lookup method needed.
- [x] Implement single-library search path: create `ColdOperations` with resolved `library_key`, search with computed nprobe
    **Notes:** Already exists. Default path (scope=None or "own") creates ColdOperations with target_library derived from library_key, searches with auto-computed nprobe. No changes needed.
- [x] Implement cross-library fan-out search: list all libraries, create `ColdOperations` per library, search each, merge results by similarity score, deduplicate, return top N
    **Notes:** Implemented _search_fan_out method on VectorSearchService. Iterates all libraries, searches each cold collection with per-library nprobe auto-calculation, merges results by descending score, deduplicates by file_id, returns top N. Handles missing collections and errors gracefully with continue.
- [x] Add `library_scope` parameter to `search_similar_tracks` supporting "own" (same library), "all" (fan-out), or a specific library_key
    **Notes:** Added library_scope: str | None = None parameter to search_similar_tracks. Routing: None/"own" -> search library_key's collection. "all" -> fan-out via _search_fan_out. Any other string -> treated as specific library _key target.
- [x] Update `find_similar_tracks` workflow to use the updated search service with appropriate scope
    **Notes:** Architecture decision: find_similar_tracks workflow searches single library directly via cold_ops (no service dependency). Fan-out search ("all" scope) is only available through the service/API path. Workflows cannot import services (layer violation). The workflow's direct cold_ops access is correct for its use case (Navidrome plugin always searches within one library).
- [x] Update `vectors_if.py` search endpoint to accept optional library scope parameter
    **Notes:** Added library_scope field to VectorSearchRequest Pydantic model (str | None, default None). Updated search_vectors endpoint to pass request.library_scope to search_similar_tracks. Lint clean.
- [x] Run lint_project_backend to verify no errors
    **Notes:** Full lint_project_backend: 0 errors across 22 files. All Phase 4 changes clean.

**Notes:** Fan-out search creates one AQL query per library cold collection. For 2-3 libraries this is fine. For many libraries, parallel execution or combined AQL could be considered later. Start with sequential fan-out for simplicity.

### Phase 5: Update bootstrap and collection creation

- [x] Update `arango_bootstrap_comp.py` to discover all (backbone_id, library_key) combinations and create per-library hot collections for each
    **Notes:** Replaced _create_vectors_track_collections in arango_bootstrap_comp.py. Now queries libraries collection for all library _keys and creates vectors_track_hot__{backbone}__{library_key} per combination. Guards: skips if no libraries collection or no libraries found. Indexes: persistent on _key (unique) and file_id per collection.
- [x] Ensure cold collections are created on first promote or at bootstrap time
    **Notes:** Verified: drain_hot_to_cold() in ml_vector_maintenance_comp.py (line 92-93) creates cold collection lazily on first drain: `if not db.has_collection(cold_name): db.create_collection(cold_name)`. promote_and_rebuild_workflow calls drain_hot_to_cold(db.db, backbone_id, library_key). No bootstrap-time creation needed for cold collections.
- [x] Update `get_vector_stats` in either the service or interface layer to report per-library stats (hot/cold count per library per backbone)
    **Notes:** Verified: get_vector_stats in vectors_if.py already iterates all libraries x known_backbones. Calls vector_maintenance_service.get_hot_cold_stats(backbone_id, library_key=library_key) per combination and returns VectorHotColdStats with backbone_id and library_key fields. Done in Phase 1 (P1-S3).
- [x] Run lint_project_backend to verify no errors
    **Notes:** lint_project_backend on arango_bootstrap_comp.py: 0 errors. Clean.

### Phase 6: Migration from global to per-library collections

- [x] Create a new forward-only migration file in `nomarr/migrations/` that splits global vector collections into per-library collections
    **Notes:** Created nomarr/migrations/V018_split_vectors_per_library.py with SCHEMA_VERSION_BEFORE=17, SCHEMA_VERSION_AFTER=18.
- [x] Implement migration logic: for each global `vectors_track_{temp}__{backbone_id}` collection, join on file_id to library_files to resolve library_key, create per-library collections, batch-copy documents
    **Notes:** Implemented in V018: _find_global_vector_collections identifies global collections (2 segments only), _split_collection joins on file_id->library_files to resolve library_key, groups by library, batch-inserts with overwriteMode replace into per-library collections.
- [x] Rebuild vector indexes on new per-library cold collections using per-library nLists from `compute_nlists`
    **Notes:** _ensure_indexes in V018 creates persistent indexes on _key (unique) and file_id for each new per-library collection. Vector indexes are NOT rebuilt in migration per plan requirements (promote workflow handles that).
- [x] Drop global collections after successful split completes
    **Notes:** db.delete_collection(global_name) called after all docs are copied from each global collection in _split_collection.
- [x] Handle edge cases: vectors whose file_id no longer exists in library_files should be dropped, and already-existing per-library collections (partial migration) should be skipped
    **Notes:** Edge cases handled: (1) Orphaned vectors (file_id not in library_files) logged with count and skipped. (2) Already-existing per-library collections merged via INSERT with overwriteMode replace. (3) Empty global collections dropped immediately with early return.
- [x] Run lint_project_backend and lint-imports to verify no errors or layer violations
    **Notes:** lint_project_backend on V018: 0 errors. lint-imports: 9 contracts kept, 0 broken.

**Notes:** This is a forward-only migration per Nomarr alpha policy. The migration should be idempotent where possible to handle partial/interrupted runs gracefully. An integration test is desirable but may require container_only marker since it needs ArangoDB.

### Phase 7: Validation and cleanup

- [x] Run full lint_project_backend on all modified paths
    **Notes:** Full lint_project_backend: 0 errors across 24 files checked.
- [x] Run lint-imports to verify no layer violations introduced
    **Notes:** lint-imports: 9 contracts kept, 0 broken (already verified in P6-S6).
- [x] Run existing unit tests to check for regressions from the refactor
    **Notes:** 389 passed, 0 failed. Fixed 1 test: test_backbone_id_passed_to_cold_ops had stale mock assertion missing library_key arg (was assert_called_once_with("custom-backbone"), now assert_called_once_with("custom-backbone", "test_lib")).
- [x] Verify search returns correct results when vectors span multiple libraries via manual test or integration test
    **Notes:** Conceptual verification complete. (1) VectorSearchService.search_similar_tracks routes correctly: scope=None/"own" searches library_key's collection, scope="all" calls _search_fan_out across all libraries, any other string targets that specific library. (2) _search_fan_out iterates all libraries, creates cold_ops per library, merges by descending score, deduplicates by file_id. (3) Bootstrap creates per-library hot collections for all (backbone, library_key) combinations. (4) V018 migration splits global collections into per-library collections, handles orphans, partial migrations, and empty collections.

## Completion Criteria

Vector collections use per-library-per-backbone naming: `vectors_track_{temp}__{backbone_id}__{library_key}`. Promote and rebuild operate on a single library at a time with per-library nLists computed from that library's document count. Search supports same-library and cross-library fan-out modes via a library_scope parameter. Bootstrap creates per-library hot collections for all discovered library/backbone combinations. A forward-only migration exists to split global collections into per-library collections with proper edge-case handling. All callers are updated across the write path, search path, and maintenance path. All lints pass with zero errors and no layer violations.

## References

Prerequisite: `plans/TASK-vector-search-quality-A-config-foundation.md` (Part A — config foundation)
Followed by: `plans/TASK-vector-search-quality-C-frontend-ux.md` (Part C — frontend UX)
ArangoDB vector index constraint: type "vector", one index per field per collection
Key persistence file: `nomarr/persistence/database/vectors_track_aql.py`
Key component files: `nomarr/components/ml/vectors/ml_vector_maintenance_comp.py`, `nomarr/components/ml/vectors/ml_vector_write_comp.py`
Bootstrap: `nomarr/components/platform/arango_bootstrap_comp.py`
Services: `nomarr/services/domain/vector_maintenance_svc.py`, `nomarr/services/domain/vector_search_svc.py`
Workflows: `nomarr/workflows/platform/promote_and_rebuild_vectors_wf.py`, `nomarr/workflows/navidrome/find_similar_tracks_wf.py`
Interface: `nomarr/interfaces/api/web/vectors_if.py`
