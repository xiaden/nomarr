# Task: Schema Refactor v1 — Part D ML Domain

## Problem Statement
Populate `model_has_output` and `model_has_calibration` edge collections created in Plan A, update all ML persistence queries to use graph traversal instead of FK property filters, and drop the obsolete `model_id`/`model_key` fields. The key challenge is resolving `calibration_state.model_key` (e.g., `"effnet-20220825"`) to actual `ml_models` documents, which can be done via backbone + embedder_release_date matching. `HeadInfo.model_path` provides direct model_id resolution in workflows.

## Phases

### Phase 1: Data Migration — ml_model_outputs
- [x] Add AQL to V021 migration: INSERT `model_has_output` edges from existing `model_id` property
    **Done:** Added migration block after Plan C P2-S1, following same pattern as library edge migrations
- [x] Run `lint_project_backend(path="nomarr/migrations")`
    **Done:** Zero errors, 2 files checked

### Phase 2: Data Migration — calibration_state
- [x] Add AQL to V021: resolve model by parsing `model_key` into (backbone, date), query `ml_models` for match, INSERT `model_has_calibration` edge
    **Done:** Added migration that parses model_key (backbone-YYYYMMDD) → ISO date, matches against ml_models, creates model_has_calibration edges. Orphaned calibrations logged with warning.
  **Notes:** Orphans (no matching model) are logged but skipped
- [x] Run `lint_project_backend(path="nomarr/migrations")`
    **Done:** Zero errors, 2 files checked

### Phase 3: Update ml_model_outputs_aql.py
- [x] Update `upsert_outputs()`: UPSERT edge after insert, remove `model_id` from doc
    **Done:** Removed `model_id` from doc, UPSERT edge via `model_has_output` after insert using `contextlib.suppress` for idempotency
- [x] Update `get_outputs_for_model()`: use `OUTBOUND` traversal
    **Done:** Changed to `FOR o IN OUTBOUND @model_id model_has_output`
- [x] Update `get_fully_labeled_outputs()`: use `OUTBOUND` traversal
    **Done:** Changed to `FOR o IN OUTBOUND @model_id model_has_output` with `fully_labeled` filter
- [x] Update `get_output_id_map()`: join via edge instead of property filter
    **Done:** Changed to `FOR o IN OUTBOUND m model_has_output` instead of property filter join
- [x] Update `delete_outputs_for_model()`: cascade-delete edges
    **Done:** Now collects outputs via OUTBOUND traversal, deletes edges via `_from` filter, deletes outputs via PARSE_IDENTIFIER
- [x] Run `lint_project_backend(path="nomarr/persistence/database")`
    **Done:** Zero errors, 8 files checked

### Phase 4: Update calibration_state_aql.py
- [x] Update `upsert_calibration_state()`: add `model_id` param, remove `model_key`/`version`, UPSERT edge
    **Done:** Changed signature: `model_key: str, version: int` → `model_id: str`. Removed `model_key`/`version` from doc. UPSERT edge via `model_has_calibration` using `contextlib.suppress` for idempotency.
- [x] Update `_make_key()`: change to `"{head_name}:{label}"` (model in edge)
    **Done:** Changed from `(model_key, head_name, label) → "{model_key}:{head_name}:{label}"` to `(head_name, label) → "{head_name}:{label}"`
- [x] Update `get_calibration_state()`: remove `model_key` param
    **Done:** Changed from `(model_key, head_name, label)` to `(head_name, label)`
- [x] Update `get_all_calibration_states()`: join model info via INBOUND edge
    **Done:** Now uses `FOR model IN INBOUND cs model_has_calibration` to join model info (backbone, embedder_release_date). Sorted by head_name, label.
- [x] Update `get_sparse_histogram()`: derive backbone from edge lookup
    **Done:** Changed from `model_key: str` to `model_id: str`. Now derives backbone/date via `DOCUMENT(@model_id)` inside the AQL query.
- [x] Run `lint_project_backend(path="nomarr/persistence/database")`
    **Done:** Zero errors, 9 files checked

### Phase 5: Update Calibration Component
- [x] Update `ml_calibration_state_comp.py` `save_calibration_state()`: accept `model_id`
    **Done:** Changed `model_key: str, version: int` → `model_id: str`. Updated call to `upsert_calibration_state()` accordingly.
- [x] Update `ml_calibration_comp.py` functions: accept `model_id` instead of `model_key`
    **Done:** `generate_calibration_from_histogram()`: removed `version` param, changed `model_key` → `model_id`. `compute_calibration_def_hash()`: changed signature to `(model_id, head_name, label)`.
- [x] Update import/export functions for edge model
    **Done:** Export v2 format: uses `backbone` + `embedder_release_date` from edge-joined model info. Import: builds model lookup cache, resolves model_id from backbone/date, uses new upsert signature.
- [x] Run `lint_project_backend(path="nomarr/components")`
    **Done:** Zero errors, 2 files checked

### Phase 6: Update Calibration Workflows
- [x] Update `generate_calibration_wf.py`: resolve `model_id` via `db.ml_models.get_model_by_path(head_info.model_path)["_id"]`
    **Done:** Updated `generate_histogram_calibration_wf`: resolves model_id via `db.ml_models.get_model_by_path(head_info.model_path)["_id"]`. Removed `model_key` and `version` variables. Updated calls to `generate_calibration_from_histogram()`, `compute_calibration_def_hash()`, and `save_calibration_state()` with new signatures.
- [x] Update `import_calibration_bundle_wf.py`: resolve model via backbone lookup
    **Done:** Updated `import_calibration_bundle_wf`: builds model lookup cache from `db.ml_models.list_models()` keyed by (backbone, embedder_release_date). Parses model_key from bundle (e.g., "effnet-20220825") into backbone+date, resolves model_id via lookup. Skips calibrations with no matching model (logged as `no_model_count`). Updated `save_calibration_state()` call with new signature.
- [x] Run `lint_project_backend(path="nomarr/workflows")`
    **Done:** Zero errors, 2 files checked

### Phase 7: Update Calibration Service
- [x] Update `calibration_svc.py` for new signatures
    **Done:** Updated `get_histogram_for_head` to call `get_calibration_state(head_name, label)` without model_key (matches new persistence signature). Kept model_key param in service method for API backward compatibility.
- [x] Run `lint_project_backend(path="nomarr/services")`
    **Done:** Zero errors, 1 file checked

### Phase 8: Drop FK Fields
- [x] Add V021 step: remove `model_id`, `created_at`, `updated_at` from ml_model_outputs
- [x] Add V021 step: remove `model_key`, `version`, `updated_at`, `last_computation_at` from calibration_state
- [x] Run `lint_project_backend(path="nomarr/migrations")`

### Phase 9: Tests & Verification
- [x] Update test mocks for changed signatures
    **Notes:** No test mocks exist for the changed ML persistence functions (upsert_calibration_state, get_calibration_state, get_sparse_histogram, ml_model_outputs methods). Existing tests in tests/unit/persistence/database/test_file_states_aql.py relate to file state calibration hashes, not the ml_model_outputs or calibration_state persistence.
- [x] Run full `lint_project_backend()` — zero errors required
    **Done:** Ruff: zero errors. Mypy: zero errors. Import-linter: 9 contracts kept, 0 broken (305 files, 874 dependencies).

## Completion Criteria
1. `lint_project_backend()` passes with zero errors
2. After migration: `model_has_output` edges match ml_model_outputs doc count
3. After migration: `model_has_calibration` edges exist (orphans logged)
4. Verify FK fields dropped: `FOR o IN ml_model_outputs FILTER o.model_id != null RETURN 1` returns empty
5. Test: `generate_calibration_wf` produces calibrations with correct edges

## Decisions Made
| Decision | Rationale |
|----------|----------|
| Orphaned calibrations (no matching model) are logged but not migrated to edges | They're stale data |
| `_make_key()` changes to `{head_name}:{label}` | Model identity moves to edge |
| `HeadInfo.model_path` used to resolve model_id in workflows | Already uniquely identifies ml_models docs |
| Keep `fully_labeled` on ml_model_outputs | Actively used for inference gating |
