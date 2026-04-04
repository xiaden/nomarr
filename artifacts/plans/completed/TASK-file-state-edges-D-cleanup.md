# Task: File State Edges D — Bug Fix, Dead Code & Consolidation Cleanup

## Problem Statement

Plans A–C migrated `library_files` from flat state fields to edge-based state
via `file_has_state` edges and `FileStatesOperations`. The migration is
functionally complete but an audit reveals residual issues:

1. **Logic bug:** `get_files_needing_reconciliation` and
   `count_files_needing_reconciliation` in `FileStatesOperations` do not
   require the `ml_tagged` edge. This means untagged files (which have no ML
   tags to write) are returned as "needing reconciliation." The plan A design
   doc and the `claim_files_for_reconciliation` docstring both specify that
   only files with `ml_tagged` edge should be candidates.

2. **Dead `TODO(plan-c)` code:** `calibration.py` `clear_all_calibration_hashes`
   still runs an AQL query to null `last_written_calibration_hash` on
   `library_files` documents. Plan C completed reconciliation's edge migration,
   so this flat-field write is dead — and conflicts with V017 which strips
   that field entirely.

3. **Stale V017 warning:** The migration docstring warns against running until
   `file_sync_comp`, `tagging_writer_comp`, `write_calibrated_tags_wf`, and
   `sync_file_to_library_wf` are migrated. All four are already migrated.

4. **Inline AQL bypassing `FileStatesOperations`:** Four mixin methods
   (`discover_next_unprocessed_file`, `get_library_stats`,
   `count_recently_tagged`, `get_tagged_paths_needing_calibration`) query
   `file_has_state` edges directly with hardcoded collection/state strings
   instead of delegating to `FileStatesOperations`. This duplicates the
   edge query patterns and constants.

5. **File deletion methods have inline edge cleanup:** `delete_library_file`,
   `bulk_delete_files`, and `delete_files_for_library` each have their own
   inline AQL to remove `file_has_state` edges, duplicating
   `FileStatesOperations.clear_all_states()`.

**Prerequisite:** TASK-file-state-edges-C-rewrite-reconciliation-cleanup

## Phases

### Phase 1: Fix Reconciliation Bug & Dead Code
- [x] Add `ml_tagged` edge presence filter to `get_files_needing_reconciliation` in `file_states_aql.py` — only return files that have an `ml_tagged` edge (subquery check), so untagged files are excluded from reconciliation candidates
    **Notes:** Added ml_tagged edge presence filter (LET has_tagged + FILTER has_tagged > 0) to get_files_needing_reconciliation AQL query. Added ml_tagged_state bind var. Updated docstring to document the precondition.
- [x] Add same `ml_tagged` filter to `count_files_needing_reconciliation` in `file_states_aql.py` to keep query logic consistent
    **Notes:** Added identical ml_tagged edge presence filter to count_files_needing_reconciliation. Added ml_tagged_state bind var. Updated docstring to note ml_tagged precondition.
- [x] Remove the `TODO(plan-c)` flat-field nulling block from `clear_all_calibration_hashes` in `calibration.py` (lines 75–80) — the AQL that nulls `last_written_calibration_hash` on `library_files` is dead code since reconciliation uses edges
    **Notes:** Removed TODO(plan-c) block (lines 73-81): inline AQL that nulled last_written_calibration_hash on library_files. Method now directly returns result from file_states.clear_all_calibrated(). Reduced from 26 to 11 lines.
- [x] Update V017 migration docstring to remove the stale warning about unmigrated components — all referenced files now use edge-based state
    **Notes:** Replaced stale ".. warning::" block (lines 34-39) with factual statement that all 4 referenced code paths have been migrated to edge-based state queries.
- [x] Run `lint_project_backend` on all modified files and verify zero new errors
    **Notes:** Ran lint_project_backend on all 3 modified files (file_states_aql.py, calibration.py, V017_remove_dead_state_fields.py). Zero new errors. Only pre-existing navidrome_song_map_aql.py mypy Cursor typing errors (5).

### Phase 2: Consolidate Edge Queries into FileStatesOperations
- [x] Add `discover_next_untagged_file(min_duration_s, allow_short)` method to `FileStatesOperations` that encapsulates the edge-absence + worker-claims check currently inline in `status.py` `discover_next_unprocessed_file`, then update `discover_next_unprocessed_file` to delegate to it
    **Notes:** Added discover_next_untagged_file() and _log_tagging_diagnostics() to FileStatesOperations. Uses bind vars for collection/state constants. Rewrote status.py discover_next_unprocessed_file to delegate (3-line body). Removed unused imports (logging, cast, Cursor) from status.py. Both files lint clean.
- [x] Add `count_untagged_files(library_id)` method to `FileStatesOperations` for the `needs_tagging_count` query currently inline in `stats.py` `get_library_stats`, then update `get_library_stats` to use it
    **Notes:** Added count_untagged_files(library_id) to FileStatesOperations. Rewrote get_library_stats to run aggregate AQL without edge subquery, then call file_states.count_untagged_files(library_id) separately. No hardcoded "file_has_state" or "file_states/ml_tagged" strings remain in stats.py. Lint clean.
- [x] Add `count_recently_tagged(window_ms)` method to `FileStatesOperations` for the edge-based tagged_at query currently inline in `stats.py` `count_recently_tagged`, then update the stats mixin to delegate
    **Notes:** Added count_recently_tagged(window_seconds) to FileStatesOperations (queries ml_tagged edges by tagged_at timestamp). Rewrote stats.py count_recently_tagged to a 3-line delegator. Removed inline now_ms import and AQL from stats.py. Lint clean.
- [x] Move the `get_tagged_paths_needing_calibration` inline edge AQL from `queries.py` into a new `FileStatesOperations` method, then update `queries.py` to delegate
    **Notes:** Added get_tagged_paths_needing_calibration(calibration_hash) to FileStatesOperations with bind vars for all collection/state constants. Rewrote queries.py method to 3-line delegator (14 lines with docstring). Removed hardcoded "file_has_state" and "file_states/ml_tagged" from queries.py.
- [x] Replace inline `file_has_state` edge deletion AQL in `delete_library_file`, `bulk_delete_files`, and `delete_files_for_library` with calls to `FileStatesOperations` (use `clear_all_states` for single-file, add `clear_all_states_batch(file_ids)` for bulk)
    **Notes:** Added clear_all_states_batch(file_ids) to FileStatesOperations. Replaced 3 inline file_has_state edge deletion blocks in crud.py: delete_library_file delegates to clear_all_states(file_id), bulk_delete_files and delete_files_for_library delegate to clear_all_states_batch(file_ids). No hardcoded "file_has_state" strings remain in crud.py.
- [x] Run `lint_project_backend` on all modified files and verify zero new errors
    **Notes:** Ran lint_project_backend on nomarr/persistence/database (covers file_states_aql.py + all mixin files + crud.py) and V017 migration. Zero new errors. Only 5 pre-existing mypy errors in navidrome_song_map_aql.py (Cursor type assignments, unrelated to plan changes).

## Completion Criteria
- Reconciliation queries only return files with `ml_tagged` edge (bug fixed)
- No flat-field writes remain in any mixin method (calibration.py dead code removed)
- V017 migration has accurate documentation (stale warning removed)
- All `file_has_state` edge queries go through `FileStatesOperations` — no hardcoded collection names in mixin files
- File deletion cascade uses `FileStatesOperations` for edge cleanup
- `lint_project_backend` passes with zero new errors

## References
- Prerequisite: `plans/completed/TASK-file-state-edges-C-rewrite-reconciliation-cleanup.md`
- FileStatesOperations: `nomarr/persistence/database/file_states_aql.py`
- Status mixin: `nomarr/persistence/database/library_files_aql/status.py`
- Calibration mixin: `nomarr/persistence/database/library_files_aql/calibration.py`
- Stats mixin: `nomarr/persistence/database/library_files_aql/stats.py`
- Queries mixin: `nomarr/persistence/database/library_files_aql/queries.py`
- CRUD mixin: `nomarr/persistence/database/library_files_aql/crud.py`
- V017 migration: `nomarr/migrations/V017_remove_dead_state_fields.py`
