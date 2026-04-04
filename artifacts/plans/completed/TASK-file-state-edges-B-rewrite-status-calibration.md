# Task: File State Edges B — Rewrite Status & Calibration Queries

## Problem Statement

Part A created the `file_states` vertex collection, `file_has_state` edge collection,
and `FileStateOperations` persistence module. The edge-based state model is now
available alongside the legacy flat fields.

This plan rewrites the **status** and **calibration** persistence mixins plus their
callers to use the new edge-based state queries instead of flat field filters.
Specifically:

- **status.py** (6 methods): `mark_file_tagged`, `mark_file_invalid`, `bulk_mark_invalid`,
  `library_has_tagged_files`, `get_files_needing_tagging`, `discover_next_unprocessed_file`
- **calibration.py** (4 methods): `update_calibration_hash`, `update_calibration_hashes_batch`,
  `clear_all_calibration_hashes`, `get_calibration_status_by_library`
- **queries.py** (1 method): `get_tagged_paths_needing_calibration`
- **stats.py** (3 methods): `get_library_stats` (needs_tagging count), `count_recently_tagged`
  (last_tagged_at), `get_library_counts` (is_valid filter)

Each method is rewritten to use `db.file_states` or direct AQL graph traversals on
`file_has_state` edges, then the old flat-field version is removed.

**Prerequisite:** TASK-file-state-edges-A-schema-and-persistence

## Phases

### Phase 1: Rewrite Status Mixin
- [x] Rewrite `mark_file_tagged` to call `db.file_states.set_ml_tagged(file_id, version, now_ms)` instead of updating flat fields; update all callers (trace from tagging workers/workflows) to not rely on `tagged`/`needs_tagging` fields in returned docs
    **Notes:** Rewrote mark_file_tagged to delegate to parent_db.file_states.set_ml_tagged. Updated file_sync_comp.py caller. Removed unused now_ms import.
- [x] Rewrite `library_has_tagged_files` to query for existence of any `file_has_state` edge to `file_states/ml_tagged` for the library's files, instead of filtering `tagged == true`
    **Notes:** Delegated to parent_db.file_states.library_has_tagged_files. Removed flat field query.
- [x] Rewrite `get_files_needing_tagging` to find files WITHOUT an `ml_tagged` edge (LEFT JOIN / NOT IN pattern), instead of filtering `needs_tagging == true AND is_valid == true`
    **Notes:** Deleted get_files_needing_tagging method (0 callers, dead code). Removed 37 lines from status.py.
- [x] Rewrite `discover_next_unprocessed_file` to find files without `ml_tagged` edge and without active `worker_claims`, instead of `needs_tagging == true AND is_valid == true`
    **Notes:** Rewrote discover_next_unprocessed_file to use edge absence pattern (files without ml_tagged edge in file_has_state). Replaced needs_tagging/is_valid flat field filters with LEFT ANTI JOIN subquery. Preserved diagnostic logging with updated field names (untagged/unclaimed instead of needs_tagging/is_valid). Worker claims check unchanged.
- [x] Remove `mark_file_invalid` and `bulk_mark_invalid` — these are deprecated (docstring says use `bulk_delete_files`); verify no callers remain, delete the methods
    **Notes:** Deleted mark_file_invalid and bulk_mark_invalid methods (0 callers, deprecated). Removed 37 lines from status.py.
- [x] Run `lint_project_backend` on status.py and all modified callers
    **Notes:** Lint clean on status.py and file_sync_comp.py. Only pre-existing navidrome_song_map_aql.py Cursor typing errors (5).

### Phase 2: Rewrite Calibration Mixin & Stats
- [x] Rewrite `update_calibration_hash` and `update_calibration_hashes_batch` to call `db.file_states.set_calibrated(file_id, hash, now_ms)` — upserts edge instead of updating flat field
- [x] Rewrite `clear_all_calibration_hashes` to call `db.file_states.clear_all_calibrated()` — removes all calibrated edges instead of nulling flat fields; also remove the `last_written_calibration_hash` nulling (that field moves to reconciled edge in Part C)
- [x] Rewrite `get_calibration_status_by_library` to count files with/without `calibrated` edge matching expected hash, grouped by library, instead of comparing flat `calibration_hash` field
- [x] Rewrite `get_tagged_paths_needing_calibration` in queries.py to find files with `ml_tagged` edge but no `calibrated` edge (or wrong hash), instead of `calibration_hash != expected AND tagged == true`
- [x] Rewrite `get_library_stats` to count files without `ml_tagged` edge for `needs_tagging_count`, and `count_recently_tagged` to query `ml_tagged` edge `tagged_at` attribute; rewrite `get_library_counts` to count all files (remove `is_valid` filter since invalid files are now hard-deleted)
- [x] Run `lint_project_backend` on all modified files

## Completion Criteria
- All status.py methods use edge-based queries via `db.file_states` or graph AQL
- All calibration.py methods use edge-based queries
- `mark_file_invalid` and `bulk_mark_invalid` are deleted (no callers)
- Stats queries use edge-based counting
- No method in status.py or calibration.py reads or writes `tagged`, `needs_tagging`, `is_valid`, `calibration_hash` flat fields
- `lint_project_backend` passes with zero new errors

## References
- Prerequisite: `plans/TASK-file-state-edges-A-schema-and-persistence.md`
- Status mixin: `nomarr/persistence/database/library_files_aql/status.py`
- Calibration mixin: `nomarr/persistence/database/library_files_aql/calibration.py`
- Stats mixin: `nomarr/persistence/database/library_files_aql/stats.py`
- Queries mixin: `nomarr/persistence/database/library_files_aql/queries.py`
- FileStatesOperations: `nomarr/persistence/database/file_states_aql.py`
- Part A: `plans/TASK-file-state-edges-A-schema-and-persistence.md`
- Part C: `plans/TASK-file-state-edges-C-rewrite-reconciliation-cleanup.md`
