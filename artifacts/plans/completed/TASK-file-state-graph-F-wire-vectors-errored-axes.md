# Task: Wire Vectors Extracted and Errored Axes

## Problem Statement

Two boolean state axes — `vectors_extracted/not_vectors_extracted` and `errored/not_errored` — are fully defined in persistence but never called. This creates two problems: (1) there is no record of which files have had vectors extracted, so model suite changes cannot selectively reset files, and (2) errored files are rediscovered in an infinite retry loop, wasting GPU cycles.

This plan wires both axes: `vectors_extracted` is set during deferred writes and bulk-reset on model suite change; `errored` is set on processing failures, excluded from discovery, and cleared on file re-scan.

**Prerequisite:** TASK-file-state-graph-E-wire-scanned-axis (Plan E adds bulk persistence patterns used here)

## Phases

### Phase 1: Persistence additions for vectors_extracted and errored
- [x] Add `bulk_set_not_vectors_extracted(self) -> int` to `FileStatesOperations` in `nomarr/persistence/database/file_states_aql.py` — transitions ALL files from `vectors_extracted` to `not_vectors_extracted` using the same pattern as `bulk_set_not_calibrated`
    **executor:** Added bulk_set_not_vectors_extracted() following bulk_set_not_calibrated pattern — global reset, no file_ids filter.
  **Notes:** This is a global reset (no file_ids param) because model suite changes affect all files.
- [x] Add `bulk_set_not_errored(self, file_ids: list[str]) -> int` to `FileStatesOperations` — transitions listed files from `errored` to `not_errored`, scoped to provided file_ids
    **executor:** Added bulk_set_not_errored(file_ids) following bulk_set_scanned pattern — scoped to file list.
  **Notes:** Used when re-scanned files should have their error state cleared. Same AQL pattern as bulk_set_scanned from Plan E but for the errored axis.
- [x] Update `discover_next_untagged_file` in `FileStatesOperations` to exclude errored files — add `errored_ids` set via INBOUND traversal on `STATE_ERRORED` and filter `file._id NOT IN errored_ids`, matching the existing `too_short_ids` pattern
    **executor:** Added errored_ids LET clause and FILTER file._id NOT IN errored_ids, matching the too_short_ids pattern. Updated docstring.
  **Notes:** Without this, errored files create infinite retry loops. The existing too_short exclusion pattern at the top of the query is the template: `LET errored_ids = (FOR f IN INBOUND @errored file_has_state RETURN f._id)` then `FILTER file._id NOT IN errored_ids`.
- [x] Add unit tests for `bulk_set_not_vectors_extracted`, `bulk_set_not_errored`, and updated `discover_next_untagged_file` errored exclusion in `tests/unit/persistence/database/test_file_states_aql.py`
    **executor:** Added TestBulkSetNotVectorsExtracted (2), TestBulkSetNotErrored (3), TestDiscoverNextUntaggedFileErroredExclusion (2) tests.
- [x] Verify `nomarr/persistence/database/file_states_aql.py` passes `lint_project_backend`
    **executor:** Both files pass lint with 0 errors.

### Phase 2: Wire vectors_extracted, errored, and clear-on-rescan
- [x] In `nomarr/services/infrastructure/workers/discovery_worker.py` `_execute_deferred_writes`, add `db.file_states.set_vectors_extracted(file_id)` alongside the existing `db.file_states.set_tagged(file_id)` call (step 5 in the function)
    **executor:** Added db.file_states.set_vectors_extracted(file_id) right after set_tagged in step 5 of _execute_deferred_writes.
  **Notes:** Co-locating with set_tagged keeps all state transitions in one place. The file_id is already in scope.
- [x] In `nomarr/services/infrastructure/workers/discovery_worker.py` `_execute_deferred_writes` except block, add `db.file_states.set_errored(file_id)` before the existing logger.exception call
    **executor:** Added db.file_states.set_errored(file_id) in except block, wrapped in try/except to avoid masking the original error. Placed before logger.exception.
  **Notes:** The except block (line ~125) catches failures during tag persistence. Wrap set_errored in its own try/except to avoid masking the original error.
- [x] In `nomarr/services/infrastructure/workers/discovery_worker.py` `DiscoveryWorker.run` method's main except handler (where files fail process_file_workflow), add `db.file_states.set_errored(file_id)` after the existing `release_claim` call
    **executor:** Added db.file_states.set_errored(file_id) in main except Exception handler, before release_claim, wrapped in try/except. No AudioLoadCrashError handler exists in this worker — only the general Exception handler, which is correct.
  **Notes:** This is the except block at ~line 360 that catches errors from process_file_workflow. file_id is in scope. Wrap in try/except to not break the error counter logic.
- [x] In `nomarr/components/ml/calibration/ml_calibration_state_comp.py` `clear_all_calibration_data`, add `db.file_states.bulk_set_not_vectors_extracted()` call after the existing `bulk_set_not_calibrated()` call
    **executor:** Added db.file_states.bulk_set_not_vectors_extracted() after bulk_set_not_calibrated() in clear_all_calibration_data. Return value discarded (not needed by caller).
  **Notes:** Model suite changes invalidate both calibration and extracted vectors. Both resets belong together.
- [x] In both scan workflows (`scan_library_full_wf.py` and `scan_library_quick_wf.py`), add `db.file_states.bulk_set_not_errored(file_ids)` after each `bulk_set_scanned(file_ids)` call added by Plan E — clears errored state for re-scanned files
    **executor:** Added db.file_states.bulk_set_not_errored(file_ids) after each of the 3 bulk_set_scanned calls in both scan_library_full_wf.py and scan_library_quick_wf.py (6 call sites total).
  **Notes:** Re-scanning a file means it changed on disk, so its previous error state is no longer valid. Same 3 call sites per workflow as Plan E.
- [x] Verify all modified files pass `lint_project_backend`
    **executor:** All 4 modified files pass lint_project_backend with 0 errors.

## Completion Criteria
- `bulk_set_not_vectors_extracted()` and `bulk_set_not_errored(file_ids)` exist on `FileStatesOperations`
- `discover_next_untagged_file` excludes files in the `errored` state
- `set_vectors_extracted` is called in `_execute_deferred_writes` alongside `set_tagged`
- `set_errored` is called in both worker error handlers (deferred writes + main loop)
- `bulk_set_not_vectors_extracted` is called in `clear_all_calibration_data`
- `bulk_set_not_errored` is called after `bulk_set_scanned` in both scan workflows
- Unit tests for new persistence methods and errored exclusion pass
- All modified files pass `lint_project_backend`

## References
- Design doc: `artifacts/designs/pending/DD-file-state-graph-completion.md`
- Parts breakdown: `artifacts/designs/parts/file-state-graph/README.md`
- Contracts ledger: `artifacts/designs/parts/file-state-graph/CONTRACTS.md`
- Errored exclusion template: `discover_next_untagged_file` too_short_ids pattern
- Vectors reset trigger: `clear_all_calibration_data` in `ml_calibration_state_comp.py`
