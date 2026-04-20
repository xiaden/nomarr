# Task: Caller Migration to FileStatesOperations API

## Problem Statement

The file state graph refactor (Plans A + C) introduced a new `db.file_states.*` API with pure-boolean axis transitions and removed passthrough methods from `db.library_files.*`. Higher-layer code — components, workflows, services, and interfaces — still calls the old methods (`mark_file_tagged`, `update_calibration_hash`, `get_calibration_status_by_library` via `library_files`, direct AQL INSERTs). These callers must be migrated to use the new `db.file_states.*` API. Additionally, the scanner pipeline still computes and passes `has_nomarr_namespace` and `infer_write_mode_from_tags`, both of which are now dropped from the data model entirely.

**Prerequisite:** TASK-file-state-graph-A-persistence-core, TASK-file-state-graph-C-persistence-cleanup

## Phases

### Phase 1: Calibration caller migration

- [x] In `ml_calibration_state_comp.py`, update `update_file_calibration_hash` to call `db.file_states.set_calibrated(file_id)` — drop the `calibration_hash` parameter from the function signature
    **executor:** Changed signature to (db, file_id) — calls db.file_states.set_calibrated(file_id)
- [x] In `ml_calibration_state_comp.py`, update `update_file_calibration_hashes_batch` to iterate items and call `db.file_states.set_calibrated(file_id)` per item — drop hash from signature, keep batch semantics
    **executor:** Changed signature from items: list[tuple[str,str]] to file_ids: list[str], iterates calling db.file_states.set_calibrated per item. BatchContext.pending_calibration_hashes changed from list[tuple[str,str]] to list[str].
- [x] In `ml_calibration_state_comp.py`, update `clear_all_calibration_data` to call `db.file_states.bulk_set_not_calibrated()` instead of `db.library_files.clear_all_calibration_hashes()`
    **executor:** Replaced db.library_files.clear_all_calibration_hashes() with db.file_states.bulk_set_not_calibrated()
- [x] In `ml_calibration_state_comp.py`, update `compute_reconciliation_info` to call `db.file_states.get_calibration_status_by_library()` (no params — `calibration_hash` param removed per Plan A amendment) instead of `db.library_files.get_calibration_status_by_library(global_version)`
    **executor:** Changed to db.file_states.get_calibration_status_by_library() (no params). Updated field access from outdated_count to not_calibrated_count. Function signature kept global_version param (used for early-return guard).
- [x] In `tagging_svc.py` (`TaggingService.get_calibration_status`), replace `self.db.library_files.get_calibration_status_by_library(global_version)` with `self.db.file_states.get_calibration_status_by_library()` (no params — `calibration_hash` param removed per Plan A amendment)
    **executor:** Changed to self.db.file_states.get_calibration_status_by_library() (no params). Adapted field mapping: calibrated_count + not_calibrated_count for total, calibrated_count for current, not_calibrated_count for outdated.
- [x] Update all callers of `update_file_calibration_hash` and `update_file_calibration_hashes_batch` to pass the new signatures (no hash parameter)
    **executor:** Updated write_calibrated_tags_wf.py: single-file call drops hash arg, batch accumulates str instead of tuple. apply_calibration_wf.py flush call unchanged (passes list to updated batch function).

### Phase 2: Scanner pipeline and tagging caller migration

- [x] In `file_batch_scanner_comp.py` `scan_folder_files`, remove `has_nomarr_namespace` / `last_written_mode` / `infer_write_mode_from_tags` computation, remove the `reconciled` type from `edge_bootstraps`, and remove the `infer_write_mode_from_tags` import
    **executor:** Removed infer_write_mode_from_tags import, has_nomarr_namespace/last_written_mode computation, and reconciled edge_bootstrap block from scan_folder_files.
- [x] In `scan_lifecycle_comp.py` `bootstrap_file_state_edges`, replace `db.file_states.set_ml_tagged(file_id, version=...)` with `db.file_states.set_tagged(file_id)`, remove the `reconciled` branch entirely (no more `set_reconciled` calls with `mode`/`has_namespace`)
    **executor:** Replaced set_ml_tagged(file_id, version=...) with set_tagged(file_id), removed reconciled branch entirely.
- [x] In `file_sync_comp.py`, drop `has_nomarr_namespace` and `last_written_mode` keyword parameters from `upsert_library_file` (remove from signature and from the delegated call to `db.library_files.upsert_library_file`)
    **executor:** Dropped has_nomarr_namespace and last_written_mode from upsert_library_file signature and delegated call.
- [x] In `file_sync_comp.py`, update `mark_file_tagged` to call `db.file_states.set_tagged(file_id)` instead of `db.file_states.set_ml_tagged(file_id, version=tagged_version)` — drop the `tagged_version` parameter from the function signature
    **executor:** Changed mark_file_tagged(db, file_id, tagged_version) to mark_file_tagged(db, file_id), now calls db.file_states.set_tagged(file_id).
- [x] In `sync_file_to_library_wf.py` `sync_file_to_library`, remove `has_nomarr_namespace` / `infer_write_mode_from_tags` computation, drop those params from the `upsert_library_file(...)` call, and remove the `infer_write_mode_from_tags` import
    **executor:** Removed infer_write_mode_from_tags import, has_nomarr_namespace/last_written_mode computation, and those params from upsert_library_file call.
- [x] In `sync_file_to_library_wf.py` `_sync_tags_and_entities`, update the `mark_file_tagged(db, file_id, tagged_version)` call to `mark_file_tagged(db, file_id)` (no version)
    **executor:** Changed mark_file_tagged(db, file_id, tagged_version) to mark_file_tagged(db, file_id) — no version arg.
- [x] In `validate_scan_state_comp.py` `_heal_short_files`, replace the direct AQL INSERT into `file_has_state` with a query-then-loop pattern: query short file IDs missing `too_short` state, then call `db.file_states.set_too_short(file_id)` per file
    **executor:** Replaced direct AQL INSERT with query-then-loop: queries short file IDs missing too_short state, then calls db.file_states.set_too_short(file_id) per file. Removed now_ms import.
- [x] In `discovery_worker.py`, replace both calls to `db.library_files.mark_file_tagged(file_id, ver)` (lines ~125 and ~585) with `db.file_states.set_tagged(file_id)`
    **executor:** Replaced both db.library_files.mark_file_tagged calls with db.file_states.set_tagged(file_id) in _execute_deferred_writes and DiscoveryWorker.run.
  **Notes:** Not listed in DD callers map but discovered during codebase research — `discovery_worker.py` bypasses component layer and calls `db.library_files.mark_file_tagged` directly, which Plan C removes.
- [x] In `library_if.py` `update_write_mode`, add `tagging_service.db.file_states.bulk_set_tags_stale(library_id)` call after `library_service.update_library(...)` and before computing reconcile status
    **executor:** Added tagging_service.db.file_states.bulk_set_tags_stale(library_id) after update_library() and before get_reconcile_status(). Left in interface layer per plan note.
  **Notes:** Layer note — ideally this side effect lives in the service layer (e.g., `library_service.update_library` triggers it). If time allows, move the `bulk_set_tags_stale` call into the service method instead of the interface handler.
- [x] Update `__init__.py` exports in `nomarr/components/library/` to reflect the changed `mark_file_tagged` signature (no `tagged_version`)
    **executor:** No changes needed — **init**.py exports mark_file_tagged by name, signature change is internal to file_sync_comp.py.
- [x] Run `lint_project_backend` and fix any remaining import or type errors across all changed files
    **executor:** All changed files pass lint. Only pre-existing mypy errors (library_has_tagged_files — Phase 4 scope). Zero errors from Phase 2.

### Phase 3: Discovery and work-status caller migration

- [x] In `worker_discovery_comp.py`, update `discover_next_file` to call `db.file_states.discover_next_untagged_file(exclude_claimed=True)` instead of `db.library_files.discover_next_unprocessed_file(min_duration_s=..., allow_short=...)` — drop `min_duration_s` and `allow_short` parameters from both `discover_next_file` and `discover_and_claim_file` signatures (too_short exclusion is now handled internally by the discovery query)
    **executor:** Changed discover_next_file(db) to call db.file_states.discover_next_untagged_file(exclude_claimed=True). Dropped min_duration_s and allow_short from both discover_next_file and discover_and_claim_file signatures.
- [x] In `discovery_worker.py`, update the `discover_and_claim_file(db, self.worker_id, min_duration_s=config.min_duration_s, allow_short=config.allow_short)` call to `discover_and_claim_file(db, self.worker_id)` — drop `min_duration_s` and `allow_short` keyword args (params removed from function signature in previous step)
    **executor:** Dropped min_duration_s and allow_short keyword args from discover_and_claim_file call in discovery_worker.py.
- [x] In `library_svc/query.py` `get_work_status`, replace `self.db.library_files.count_recently_tagged(window_seconds=300)` with `0` — the `count_recently_tagged` method is deleted in Plan C (data source `tagged_at` on edge payload no longer exists; deferred to model versioning)
    **executor:** Replaced self.db.library_files.count_recently_tagged(window_seconds=300) with 0 literal. Data source removed per Plan C.
- [x] In `library_svc/query.py`, rewrite `get_paths_needing_calibration` to iterate all enabled libraries via `self.db.libraries.list_libraries(enabled_only=True)` and collect `self.db.file_states.get_uncalibrated_tagged_file_ids(library_id)` per library, then resolve file IDs to paths — drop `calibration_hash` parameter (boolean axis replaces hash comparison)
    **executor:** Rewrote get_paths_needing_calibration to iterate enabled libraries via list_libraries(enabled_only=True), collect get_uncalibrated_tagged_file_ids per library, then resolve IDs to paths via get_files_by_ids_with_tags. Dropped calibration_hash param. Also updated caller in tagging_svc.py tag_library() to drop calibration_version branching.
  **Notes:** Semantic shift: old method accepted a `calibration_hash` and returned paths globally. New API is library-scoped and boolean (`tagged AND not_calibrated`). The caller `tagging_svc.tag_library()` uses this; verify the path-resolution step works with the workflow.

### Phase 4: library_has_tagged_files caller migration

- [x] In `scan_lifecycle_comp.py`, change `db.library_files.library_has_tagged_files(library_id)` to `db.file_states.library_has_tagged_files(library_id)`
    **executor:** Changed db.library_files.library_has_tagged_files to db.file_states.library_has_tagged_files in scan_lifecycle_comp.py
- [x] In `scan_library_quick_wf.py`, change `db.library_files.library_has_tagged_files(library_id)` to `db.file_states.library_has_tagged_files(library_id)`
    **executor:** Changed db.library_files.library_has_tagged_files to db.file_states.library_has_tagged_files in scan_library_quick_wf.py
- [x] In `scan_library_full_wf.py`, change `db.library_files.library_has_tagged_files(library_id)` to `db.file_states.library_has_tagged_files(library_id)`
    **executor:** Changed db.library_files.library_has_tagged_files to db.file_states.library_has_tagged_files in scan_library_full_wf.py

### Phase 5: Reconciliation and file-write caller migration

- [x] In `tagging_svc.py` `reconcile_library`, update `claim_files_for_reconciliation` call to drop `target_mode` and `calibration_hash` params — new signature is `(library_id, worker_id, batch_size)`
    **executor:** Dropped target_mode and calibration_hash params from claim_files_for_reconciliation call in reconcile_library. New call: (library_id, worker_id, batch_size).
- [x] In `tagging_svc.py` `reconcile_library`, update `count_files_needing_reconciliation` call to drop `target_mode` and `calibration_hash` params — new signature is `(library_id)` — also remove local `target_mode` and `calibration_hash` variables if no longer needed
    **executor:** Dropped target_mode and calibration_hash from count_files_needing_reconciliation call. Kept target_mode/calibration_hash local vars in reconcile_library as they are still used by write_file_tags_workflow.
- [x] In `tagging_svc.py` `get_reconcile_status`, update `count_files_needing_reconciliation` call to drop `target_mode` and `calibration_hash` params — new signature is `(library_id)` — also remove the `target_mode` and `calibration_hash` variable lookups
    **executor:** Removed target_mode and calibration_hash variable lookups from get_reconcile_status. count_files_needing_reconciliation now called with just library_id.
- [x] In `file_write_comp.py` `mark_file_written`, update `db.library_files.set_file_written(file_key, mode=mode, calibration_hash=calibration_hash)` to `db.library_files.set_file_written(file_key)` — drop `mode` and `calibration_hash` keyword args, and remove them from `mark_file_written` function signature
    **executor:** Simplified mark_file_written signature to (db, file_key) and set_file_written call to (file_key) only, dropping mode and calibration_hash.
- [x] In `write_file_tags_wf.py`, update `mark_file_written(db, file_key, mode=target_mode, calibration_hash=calibration_hash)` call to `mark_file_written(db, file_key)` — drop `mode` and `calibration_hash` keyword args (params removed from function signature in previous step)
    **executor:** Updated mark_file_written call in write_file_tags_wf.py to (db, file_key) — dropped mode and calibration_hash keyword args.
- [x] Run `lint_project_backend` on all files changed in Phases 3-5
    **executor:** lint_project_backend on nomarr/ passes with zero errors. All code-intel/ errors are pre-existing and unrelated.

## Completion Criteria

- Zero calls to removed `db.library_files` methods: `mark_file_tagged`, `update_calibration_hash`, `update_calibration_hashes_batch`, `clear_all_calibration_hashes`, `get_calibration_status_by_library`, `discover_next_unprocessed_file`, `count_recently_tagged`, `get_tagged_paths_needing_calibration`, `library_has_tagged_files`
- Zero references to `set_ml_tagged`, `set_reconciled` in component/workflow/service/interface layers
- Zero computation of `has_nomarr_namespace` or calls to `infer_write_mode_from_tags` in scanner pipeline
- No direct AQL INSERTs into `file_has_state` outside of persistence layer
- `lint_project_backend` passes with zero errors on all changed files
- `update_write_mode` endpoint calls `bulk_set_tags_stale(library_id)` after mode change
- `worker_discovery_comp.py` uses `db.file_states.discover_next_untagged_file` — no `min_duration_s`/`allow_short` params
- `discovery_worker.py` calls `discover_and_claim_file(db, worker_id)` with no `min_duration_s`/`allow_short` args
- `library_has_tagged_files` calls go through `db.file_states` in all 3 callers
- `tagging_svc.py` reconciliation calls use new simplified signatures (no `target_mode`/`calibration_hash`)
- `file_write_comp.py` `set_file_written` call uses new signature (no `mode`/`calibration_hash`)
- `write_file_tags_wf.py` `mark_file_written` call uses new signature (no `mode`/`calibration_hash`)
- `get_calibration_status_by_library` calls pass no arguments (param removed)

## References

- Design doc: `artifacts/designs/pending/DD-file-state-graph-completion.md` (Callers Update Map section)
- Contracts: `artifacts/designs/parts/file-state-graph/CONTRACTS.md` (Plan A API, Plan C removed methods)
- Parts breakdown: `artifacts/designs/parts/file-state-graph/README.md`
