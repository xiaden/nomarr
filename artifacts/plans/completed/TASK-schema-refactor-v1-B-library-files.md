# Task: Schema Refactor v1 — Part B Library Files & Folders FK Migration

## Problem Statement

Migrate `library_id` FK properties on `library_files` and `library_folders` to proper edges. Populate the empty `library_contains_file` and `library_contains_folder` edge collections (created in Plan A) from existing FK values, update all persistence layer queries to use graph traversal, then drop the FK columns.

## Phases

### Phase 1: Data Migration — Populate Edge Collections

- [x] Add AQL to `V021_schema_refactor_v1.py` that populates `library_contains_file` edges from existing `library_files.library_id` values
  **Notes:** Pattern: `FOR file IN library_files FILTER file.library_id != null INSERT { _from: file.library_id, _to: file._id } INTO library_contains_file OPTIONS { ignoreErrors: true }`
      Added AQL to populate library_contains_file edges at lines 241-251
- [x] Add AQL to populate `library_contains_folder` edges from existing `library_folders.library_id` values
    **Notes:** Added AQL to populate library_contains_folder edges at lines 253-263
- [x] Run `lint_project_backend(path="nomarr/migrations")`
    **Notes:** Lint clean — 0 errors, 2 files checked

### Phase 2: Update library_files Persistence Layer

- [x] Update `upsert_library_file()` in `library_files_aql/crud.py` — remove `library_id` from doc INSERT/UPDATE, UPSERT edge after getting file._id
    **Notes:** Removed library_id from INSERT/UPDATE bodies, kept in UPSERT key for backward compat. Added edge UPSERT to library_contains_file after file upsert.
- [x] Update `get_library_file()` in `library_files_aql/queries.py` — use graph traversal when library_id provided
    **Notes:** Changed to use OUTBOUND traversal via library_contains_file when library_id provided. Also fixed type from int|None to str|None.
- [x] Update `get_library_stats()` in `library_files_aql/stats.py` — use `OUTBOUND` traversal from library
    **Notes:** Changed to use OUTBOUND traversal via library_contains_file when library_id provided. Fixed type from int|None to str|None.
- [x] Update `get_library_counts()` in `library_files_aql/stats.py` — aggregate via `library_contains_file` edges
    **Notes:** Changed to iterate over library_contains_file edges and lookup files via DOCUMENT(edge._to), then COLLECT by edge._from.
- [x] Run `lint_project_backend(path="nomarr/persistence/database/library_files_aql")`
    **Notes:** Lint passes. Added type: ignore with TODO for count_untagged_files call - file_states_aql will be updated to str|None in a later phase.

### Phase 3: Update file_states_aql.py Queries

- [x] Update `get_untagged_file_ids()` in `file_states_aql.py` — replace `FILTER file.library_id == @library_id` with `FOR file IN OUTBOUND @library_id library_contains_file`
- [x] Update `library_has_tagged_files()` in `file_states_aql.py` — use graph traversal
- [x] Update `get_calibration_status_by_library()` in `file_states_aql.py` — aggregate via `INBOUND edge._from` instead of `file.library_id`
- [x] Update `get_files_needing_reconciliation()` in `file_states_aql.py` — use graph traversal
- [x] Run `lint_project_backend(path="nomarr/persistence/database")`

### Phase 4: Update library_folders Persistence Layer

- [x] Refactor `upsert_folder()` in `library_folders_aql.py` — change UPSERT key from `{library_id, path}` to path-hash, create edge for ownership
    **Notes:** Changed UPSERT key from `{library_id, path}` to `{_key: hash(library_id/path)}`. Removed `library_id` from document body. Added edge UPSERT to `library_contains_folder` after folder upsert.
- [x] Update `get_folder()` in `library_folders_aql.py` — use `INBOUND` traversal
    **Notes:** Changed to use key-based DOCUMENT() lookup instead of property filter. Key computation encodes library ownership implicitly.
- [x] Update `get_all_folders_for_library()` in `library_folders_aql.py` — use `OUTBOUND @library_id library_contains_folder`
    **Notes:** Changed from `FOR folder IN library_folders FILTER folder.library_id == @library_id` to `FOR folder IN OUTBOUND @library_id library_contains_folder`.
- [x] Update `delete_folders_for_library()` in `library_folders_aql.py` — delete via traversal, cascade edge deletion
    **Notes:** Changed to use OUTBOUND traversal with cascading deletion of both edge and folder in a single query.
- [x] Update `delete_missing_folders()` in `library_folders_aql.py` — use edge-based library filter
    **Notes:** Changed to use OUTBOUND traversal with cascading deletion of both edge and folder, filtering by path NOT IN existing_paths.
- [x] Update `get_folder_count_for_library()` in `library_folders_aql.py` — count via edge traversal
    **Notes:** Changed from property filter to edge traversal count via `FOR folder IN OUTBOUND @library_id library_contains_folder`.
- [x] Run `lint_project_backend(path="nomarr/persistence/database")`
    **Notes:** Lint clean - 0 errors, 7 files checked. Also fixed pre-existing syntax error in libraries_aql.py (missing return type annotation).

### Phase 5: Drop FK Columns in Migration

- [x] Add AQL to remove `library_id` field from all `library_files` documents (`UPDATE file WITH { library_id: null } OPTIONS { keepNull: false }`)
- [x] Add AQL to remove `library_id` field from all `library_folders` documents
- [x] Add index drop for `["library_id"]` on `library_files`
- [x] Add index drop for `["library_id", "path"]` composite on `library_files`
- [x] Add index drop for `["library_id"]` on `library_folders`
- [x] Run `lint_project_backend(path="nomarr/migrations")`

### Phase 6: Update Tests

- [x] Update `test_file_states_aql.py` tests for `get_untagged_file_ids()` — mock edge queries instead of property filters
    **Notes:** Changed `test_query_filters_by_library` to `test_query_uses_edge_traversal_for_library` — now asserts `OUTBOUND @library_id library_contains_file` instead of property filter. Also renamed `test_query_no_library_filter_when_none` to `test_query_no_edge_traversal_when_library_is_none`.
- [x] Update tests for `library_has_tagged_files()` — edge-based mocking
    **Notes:** Added `test_query_uses_edge_traversal` — verifies query uses `OUTBOUND @library_id library_contains_file` traversal pattern.
- [x] Update tests for `get_calibration_status_by_library()` — verify edge-based aggregation returns same structure
    **Notes:** Added `test_query_uses_edge_traversal_for_aggregation` — verifies query uses `FOR lib IN libraries` + `OUTBOUND lib library_contains_file` pattern instead of property filter.
- [x] Update tests for `get_files_needing_reconciliation()` — edge-based mocking
    **Notes:** Added `test_query_uses_edge_traversal` — verifies query uses `OUTBOUND @library_id library_contains_file` traversal pattern.
- [x] Run `lint_project_backend(path="tests")`
    **Notes:** Lint clean — 0 errors, 2 files checked.

### Phase 7: Integration Verification

- [x] Run full `lint_project_backend()` with no errors
    **Notes:** Lint passed: 0 errors, 15 files checked
- [x] Verify migration imports: `python -c "from nomarr.migrations.V021_schema_refactor_v1 import upgrade"`
    **Notes:** Import verified: V021_schema_refactor_v1.upgrade imports successfully

## Completion Criteria

1. `lint_project_backend()` returns zero errors
2. Migration import succeeds without exceptions
3. Scan workflows (`scan_library_quick_wf.py`, `scan_library_full_wf.py`) still work — they call `library_has_tagged_files()` which now uses edges
4. Calibration status check still works — `get_calibration_status_by_library()` returns same `{library_id, total_files, current_count, outdated_count}` structure
5. Folder cache operations in `scan_lifecycle_comp.py` still work with edge-based queries

## Decisions Made

 | Decision | Rationale |
 | ---------- | ---------- |
 | Keep `library_id` parameter names in method signatures | Callers pass library doc IDs; only internal implementation changes to edges |
 | Use `OUTBOUND/INBOUND collection_name` not `GRAPH 'name'` | Single-hop traversal; explicit collection avoids graph ambiguity |
 | Folder UPSERT key becomes path-hash | Edge defines ownership; `{library_id, path}` composite no longer valid |
 | Handle NULL `library_id` gracefully in migration | Skip orphan documents; log warning but don't fail |
 | FK removal is last phase | Ensures queries updated before column dropped |
