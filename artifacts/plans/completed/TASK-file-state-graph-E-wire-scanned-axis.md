# Task: Wire Scanned Axis — Persistence Additions and Scan Workflow Integration

## Problem Statement

The `scanned/not_scanned` axis is fully defined in persistence (`set_scanned`, `set_not_scanned` exist, vertices seeded, edges initialized as `not_scanned` for new files) but never called by any workflow. After a successful scan upsert, files should transition to `scanned`. Additionally, there is no `bulk_set_scanned` method — scan workflows process files in batches, so calling `set_scanned` per-file inside the batch would be N individual AQL calls. A batch method is needed.

**Prerequisite:** TASK-file-state-graph-D-caller-migration (Plans A–D establish the persistence layer and migrate callers to the new API)

## Phases

### Phase 1: Add bulk_set_scanned persistence method
- [x] Add `bulk_set_scanned(self, file_ids: list[str]) -> int` to `FileStatesOperations` in `nomarr/persistence/database/file_states_aql.py` — transitions listed files from `not_scanned` to `scanned` using REMOVE+INSERT AQL pattern scoped to the provided file_ids list
    **executor:** Added bulk_set_scanned method after bulk_set_tags_stale, using REMOVE+INSERT AQL pattern scoped to file_ids list with STATE_NOT_SCANNED/STATE_SCANNED constants.
  **Notes:** Follow `bulk_set_not_calibrated` pattern but scoped to a list of file IDs instead of all files. AQL: FOR e IN file_has_state FILTER e._to == @not_scanned AND e._from IN @file_ids LET r = (REMOVE e._key IN file_has_state RETURN 1) INSERT { _from: e._from, _to: @scanned } INTO file_has_state RETURN 1
- [x] Add unit test for `bulk_set_scanned` in `tests/unit/persistence/database/test_file_states_aql.py` — verify it transitions only the specified file IDs from not_scanned to scanned
    **executor:** Added TestBulkSetScanned class with 3 tests: returns_count, filters_by_not_scanned_and_file_ids, empty_file_ids_returns_zero. Follows existing mock-based pattern.
- [x] Verify `nomarr/persistence/database/file_states_aql.py` passes `lint_project_backend`
    **executor:** Both files pass lint_project_backend with zero errors.

### Phase 2: Wire set_scanned in scan workflows
- [x] In `nomarr/workflows/library/scan_library_full_wf.py`, add `db.file_states.bulk_set_scanned(file_ids)` call after each `upsert_scanned_files()` call that returns file_ids — there are 3 call sites (updated entries, new entries without tagged files, truly_new entries after move detection)
    **executor:** Added db.file_states.bulk_set_scanned(file_ids) after all 3 upsert_scanned_files call sites: line 163 (updated_entries), line 194 (new_entries no tagged), line 253 (truly_new).
  **Notes:** The 3 upsert_scanned_files call sites are: (1) updated_entries upsert ~line 143, (2) new_entries upsert when no tagged files ~line 167, (3) truly_new upsert ~line 221. Each already has `file_ids` in scope from the return value.
- [x] In `nomarr/workflows/library/scan_library_quick_wf.py`, add `db.file_states.bulk_set_scanned(file_ids)` call after each `upsert_scanned_files()` call — same 3 call sites as full scan
    **executor:** Added db.file_states.bulk_set_scanned(file_ids) after all 3 upsert_scanned_files call sites: line 170 (updated_entries), line 201 (new_entries no tagged), line 260 (truly_new).
  **Notes:** Quick scan has the same 3 upsert_scanned_files call sites as full scan.
- [x] Verify both scan workflow files pass `lint_project_backend`
    **executor:** Both scan_library_full_wf.py and scan_library_quick_wf.py pass lint_project_backend with zero errors.

## Completion Criteria
- `bulk_set_scanned(file_ids)` method exists on `FileStatesOperations` and transitions only specified files
- All `upsert_scanned_files()` call sites in both scan workflows are followed by `bulk_set_scanned(file_ids)`
- Unit test for `bulk_set_scanned` passes
- All modified files pass `lint_project_backend`

## References
- Design doc: `artifacts/designs/pending/DD-file-state-graph-completion.md`
- Parts breakdown: `artifacts/designs/parts/file-state-graph/README.md`
- Contracts ledger: `artifacts/designs/parts/file-state-graph/CONTRACTS.md`
- Existing bulk pattern: `FileStatesOperations.bulk_set_not_calibrated`
