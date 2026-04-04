# Task: Vector Search Quality Part A — Config Foundation

## Problem Statement

Vector search quality degrades silently as library size grows because:
1. `nLists` uses N/15 formula but creates fewer, coarser clusters than optimal
2. `nProbe` is hardcoded at 20 everywhere — doesn't scale with nLists, so search thoroughness drops from 100% at 300 tracks to ~1% at 25k tracks
3. No user-facing controls for search quality/speed tradeoff
4. Settings are exposed as raw technical parameters (nLists, nProbe) rather than user-friendly concepts

Part A covers backend foundation: helper functions that convert user-friendly settings to nLists/nProbe, config schema additions (global + per-library), and fixing the immediate nProbe auto-scaling bug in existing search paths. Does NOT cover per-library collections (Part B) or frontend UI (Part C).

**User-facing concepts:**
- `vector_group_size` (int, default 15, range 5–100): "Each similarity neighborhood contains ~N songs." Backend converts: `nLists = doc_count // group_size`.
- `vector_search_thoroughness` (int, default 10, range 1–100): "Check N% of neighborhoods when searching." Backend converts: `nProbe = max(1, nLists * thoroughness // 100)`.

**Where settings live:** Global `DynamicConfig` holds defaults. Per-library `LibraryConfigFields` holds optional overrides. Per-library values are used when present; global is the fallback.

## Phases

### Phase 1: Add percentage-based vector helpers

- [x] Create `nomarr/helpers/vector_params_helper.py` with `compute_nlists(doc_count: int, group_size: int = 15) -> int` returning `max(10, min(4000, doc_count // group_size))`
    **Notes:** Created nomarr/helpers/vector_params_helper.py with compute_nlists(doc_count, group_size=15) -> int, clamped to [10, 4000]. Lint clean.
- [x] Add `compute_nprobe(nlists: int, thoroughness_pct: int = 10) -> int` returning `max(1, min(nlists, nlists * thoroughness_pct // 100))`
    **Notes:** compute_nprobe added in same file. Returns max(1, min(nlists, nlists * thoroughness_pct // 100)).
- [x] Add `VectorSearchDescription` TypedDict with fields: songs_per_group, num_groups, groups_searched, songs_checked, pct_searched
    **Notes:** VectorSearchDescription TypedDict added with all five fields: songs_per_group (int), num_groups (int), groups_searched (int), songs_checked (int), pct_searched (float).
- [x] Add `describe_search_params(doc_count: int, group_size: int, thoroughness_pct: int) -> VectorSearchDescription` that computes all derived values
    **Notes:** describe_search_params added. Computes nlists, nprobe, songs_per_group, songs_checked (capped at doc_count), and pct_searched (capped at 100%).
- [x] Create `tests/unit/helpers/test_vector_params_helper.py` with unit tests covering edge cases (small libraries, boundary values, min/max clamping)
    **Notes:** Created tests/unit/helpers/test_vector_params_helper.py with 21 tests across 3 classes (TestComputeNlists, TestComputeNprobe, TestDescribeSearchParams). All 21 passed in 0.11s.

**Notes:** This is a pure helpers module with no nomarr imports. All functions are stateless. The describe function is for future UI tooltip display (Part C).

### Phase 2: Add vector config to schema

- [x] Add `vector_group_size: int = 15` and `vector_search_thoroughness: int = 10` fields to `DynamicConfig` in `config_schema.py`
    **Notes:** Added vector_group_size: int = 15 and vector_search_thoroughness: int = 10 to DynamicConfig at lines 58-59 of config_schema.py. Drift guard assertion passes.
- [x] Add corresponding entries to `DYNAMIC_FIELD_META` with label, description, and ui_type (both are `number` type with min/max)
    **Notes:** Added DYNAMIC_FIELD_META entries at lines 127-136: vector_group_size ("Songs per Neighborhood", number) and vector_search_thoroughness ("Search Thoroughness (%)", number). Also added "number" to FieldMeta ui_type Literal.
- [x] Add `vector_group_size` and `vector_search_thoroughness` to `LibraryConfigFields` as `NotRequired[int]` optional overrides
    **Notes:** Added vector_group_size: int and vector_search_thoroughness: int to LibraryConfigFields (total=False TypedDict, so all fields are already NotRequired).
- [x] Update `validate_library_config()` to validate the new fields — int type, group_size range 5–100, thoroughness range 1–100
    **Notes:** Updated validate_library_config() with isinstance(gs, int) + range checks: vector_group_size 5-100, vector_search_thoroughness 1-100. Both raise ValueError with clear messages.
- [x] Add the two new keys to `config.yaml` with descriptive comments
    **Notes:** Added vector_group_size: 15 and vector_search_thoroughness: 10 to build_resources/config/config.yaml under new "Vector Search Quality" section before calibration section.
- [x] Run lint_project_backend on `nomarr/helpers/config_schema.py` to verify
    **Notes:** lint_project_backend on nomarr/helpers/config_schema.py: 0 errors, clean.

**Notes:** The module-level drift assertion in config_schema.py auto-checks that DYNAMIC_FIELD_META keys match DynamicConfig fields, so missing metadata entries will fail at import time.

### Phase 3: Fix nProbe auto-scaling in existing search paths

- [x] Update `VectorMaintenanceService.calculate_optimal_nlists()` to delegate to `compute_nlists` from vector_params_helper
    **Notes:** Replaced inline N/15 formula with delegation to compute_nlists(doc_count). Added import for compute_nlists from vector_params_helper. Lint clean (0 errors).
- [x] Update `VectorSearchService.search_similar_tracks()` to auto-calculate nprobe using `compute_nprobe` when not explicitly provided, reading `vector_search_thoroughness` from global config
    **Notes:** Changed nprobe param from int=20 to int|None=None. Added ConfigService injection to __init__. When nprobe is None, auto-calculates from cold_ops.count(), vector_group_size, and vector_search_thoroughness via compute_nlists/compute_nprobe. Updated app.py wiring and two integration test constructors. Lint clean (0 errors).
- [x] Update `find_similar_tracks` workflow to resolve effective config (per-library override or global default) and pass computed nprobe to `cold_ops.search_similar()`
    **Notes:** Added vector_group_size and vector_search_thoroughness params to find_similar_tracks (defaults 15, 10). Workflow now calls cold_ops.count(), computes nlists/nprobe via helpers, and passes nprobe to cold_ops.search_similar(). Updated NavidromeService.get_similar_tracks to read config and pass values. Updated test _make_db to set cold_ops.count.return_value=300. All 3 files lint clean.
- [x] Verify `cold_ops.search_similar()` signature accepts the nprobe argument correctly (it already has `nprobe=20` default)
    **Notes:** Confirmed: VectorsTrackColdOperations.search_similar(vector, limit, nprobe=20) already accepts nprobe kwarg. Both workflow and service callers pass nprobe=<computed> as keyword argument — fully compatible, no changes needed.
- [x] Run lint_project_backend on changed service and workflow files
    **Notes:** Lint clean: nomarr/services/domain (3 files, 0 errors), nomarr/workflows/navidrome (1 file, 0 errors).

**Notes:** Do NOT wire new config into index building yet — Part B handles that when collections become per-library. This phase only fixes the search-time nProbe scaling.

### Phase 4: Validation

- [x] Run lint_project_backend on full workspace — zero errors required
    **Notes:** lint_project_backend on full workspace: 13 files checked, 0 errors. Clean.
- [x] Run lint-imports to verify no layer violations (vector_params_helper is in helpers, imported by services and workflows)
    **Notes:** lint-imports: 9 contracts kept, 0 broken. No layer violations.
- [x] Run unit tests for the new vector_params_helper
    **Notes:** 21 tests passed in 0.08s across TestComputeNlists, TestComputeNprobe, TestDescribeSearchParams.

## Completion Criteria

- `vector_params_helper.py` exists with `compute_nlists`, `compute_nprobe`, `describe_search_params` — all tested
- `DynamicConfig` has `vector_group_size` and `vector_search_thoroughness` with DYNAMIC_FIELD_META entries
- `LibraryConfigFields` has the same two fields as `NotRequired` optional overrides
- `validate_library_config()` validates the new fields with correct ranges
- `search_similar_tracks` and `find_similar_tracks` auto-scale nProbe based on config instead of hardcoded 20
- `calculate_optimal_nlists` delegates to the new helper
- All lints pass, all unit tests pass, no layer violations

## References

- Prerequisite: None (Part A is standalone foundation)
- Followed by: TASK-vector-search-quality-B-per-library-collections.md (per-library vector collections + index rebuilding)
- Followed by: TASK-vector-search-quality-C-frontend-ux.md (frontend settings UI)
- Key files: `nomarr/helpers/config_schema.py`, `nomarr/services/domain/vector_maintenance_svc.py`, `nomarr/services/domain/vector_search_svc.py`, `nomarr/workflows/navidrome/find_similar_tracks_wf.py`, `nomarr/persistence/database/vectors_track_aql.py`
