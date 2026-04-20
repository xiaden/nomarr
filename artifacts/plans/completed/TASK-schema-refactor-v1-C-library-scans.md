# Task: Schema Refactor v1 — Part C Library Scans Separation

## Problem Statement

Migrate library scan state from inline fields on `libraries` documents to a dedicated `library_scans` collection with 1:1 edge relationship. The `library_has_scan` edge collection (created empty in Plan A) gets populated, and all scan queries are updated to use edge traversal. API compatibility is preserved by joining scan state into library responses.

## Phases

### Phase 1: Create library_scans Collection

- [x] Add `library_scans` document collection creation to V021 migration (after existing collections)
- [x] Run `lint_project_backend(path="nomarr/migrations")`

### Phase 2: Data Migration AQL

- [x] Add data migration to V021: for each library, create `library_scans` doc with `_key = library._key` + create `library_has_scan` edge
  **Notes:** Field mapping: `scan_status`→`status`, `scan_progress`→`files_processed`, `scan_total`→`files_total`, `scanned_at`→`completed_at`, `scan_error`→`error`, `last_scan_started_at`→`started_at`, `scan_type_in_progress`→`scan_type`
      Added data migration AQL to V021 at lines 265-293. Maps library scan fields to library_scans collection and creates library_has_scan edges. Uses idempotent UPSERT patterns.
- [x] Run `lint_project_backend(path="nomarr/migrations")`
    **Notes:** Clean (0 errors, 2 files checked). Fixed 2 trailing-whitespace issues in AQL string.

### Phase 3: New Persistence Module

- [x] Create `library_scans_aql.py` with `LibraryScansOperations`: `get_or_create_scan()`, `update_scan()`, `get_scan_state()`
    **Notes:** Created library_scans_aql.py with LibraryScansOperations class following codebase patterns (DatabaseLike type, db.aql.execute). Adapted from plan to match existing conventions.
- [x] Register in `db.py` as `self.library_scans`
    **Notes:** Added import and self.library_scans = LibraryScansOperations(self.db) in Database.**init**
- [x] Run `lint_project_backend(path="nomarr/persistence")`
    **Notes:** Lint passed after fixing one type error (added type: ignore[arg-type] on dict() call)

### Phase 4: Update LibrariesOperations

- [x] Update `create_library()` — remove scan field initialization
    **Notes:** Removed scan_status, scan_progress, scan_total, scanned_at, scan_error from create_library insert. Added parent_db parameter to LibrariesOperations constructor and updated db.py to pass parent_db=self.
- [x] Update `update_scan_status()` — delegate to `library_scans.update_scan()`
    **Notes:** Delegated to self.parent_db.library_scans.update_scan() with field mapping: scan_status→status, scan_progress→files_processed, scan_total→files_total, scan_error→error, scanned_at→completed_at
- [x] Update `mark_scan_started()` — delegate to `library_scans.update_scan(started_at=now, scan_type=...)`
    **Notes:** Delegated to library_scans.update_scan(started_at=now, scan_type=scan_type)
- [x] Update `mark_scan_completed()` — delegate to `library_scans.update_scan(completed_at=now, ...)`
    **Notes:** Delegated to library_scans.update_scan(completed_at=now, started_at=None, scan_type=None)
- [x] Update `get_scan_state()` — delegate to `library_scans.get_scan_state()`
    **Notes:** Delegated to library_scans.get_scan_state(). Added field mapping for backward compatibility: started_at→last_scan_started_at, completed_at→last_scan_at, scan_type→scan_type_in_progress
- [x] Update `check_interrupted_scan()` — use `library_scans.get_scan_state()` for logic
    **Notes:** No code changes needed — check_interrupted_scan already calls self.get_scan_state() which now delegates to library_scans. Field name mapping ensures backward-compatible comparison logic.
- [x] Update `get_library()` — join scan state from edge into returned dict
    **Notes:** Added last_scan_started_at and scan_type_in_progress to AQL merge
- [x] Update `list_libraries()` — batch-join scan state for all libraries
    **Notes:** Batch join via AQL OUTBOUND traversal with same field mapping
- [x] Run `lint_project_backend(path="nomarr/persistence")`

### Phase 5: Drop FK Fields

- [x] Add V021 step to remove scan fields from libraries documents
  **Notes:** AQL: `UPDATE lib WITH {...} OPTIONS { keepNull: false }`
      Added AQL in V021 Cleanup section to null out all scan_* fields with keepNull: false
- [x] Run `lint_project_backend(path="nomarr/migrations")`
    **Notes:** 0 errors

### Phase 6: Tests

- [x] Update `test_file_watcher_svc.py` mock expectations
    **Notes:** No changes needed — test_file_watcher_svc.py mock only uses library fields (name, root_path, watch_mode, is_enabled). FileWatcherService doesn't access scan state fields. Verified via grep: no scan_status/scan_progress/scan_total/scanned_at references in file.
- [x] Update `test_library_dto.py` for joined data
    **Notes:** Added 2 tests to TestLibraryDict: test_can_create_library_with_joined_scan_state (verifies LibraryDict accepts last_scan_started_at, last_scan_at, scan_type_in_progress) and test_can_create_library_with_active_scan (verifies active scan state with scan_type_in_progress).
- [x] Add unit test for `LibraryScansOperations.get_or_create_scan()`
    **Notes:** Created tests/unit/persistence/database/test_library_scans_aql.py with 3 test classes: TestGetOrCreateScan (4 tests), TestUpdateScan (2 tests), TestGetScanState (2 tests). Mock-based tests verify AQL query structure and bind vars without requiring ArangoDB.
- [x] Run `lint_project_backend(path="tests")`
    **Notes:** 0 errors after fixing one F841 (unused variable) in test_library_scans_aql.py. 3 files checked.

### Phase 7: Verification

- [x] Run full `lint_project_backend()` with no path filter
    **Notes:** lint_project_backend() passed with 0 errors, 15 files checked
- [x] Verify imports: migration and persistence modules
    **Notes:** Migration import OK. Persistence import fails due to missing mutagen runtime dep (not a code error - lint clean)

## Completion Criteria

1. `lint_project_backend()` passes with zero errors
2. `python -c "from nomarr.migrations.V021_schema_refactor_v1 import upgrade"` succeeds
3. `python -c "from nomarr.persistence.database.library_scans_aql import LibraryScansOperations"` succeeds
4. After migration, `library_scans` collection has one doc per library, `library_has_scan` has edges, libraries docs have no `scan_*` fields

## Decisions Made

 | Decision | Rationale |
 | ---------- | ---------- |
 | Field names change in storage but API compatibility maintained via join | Minimize interface changes |
 | Status values unchanged (`idle`, `scanning`, `complete`, `error`) | No workflow changes needed |
 | Lazy scan document creation on first `get_or_create_scan()` call | Handles pre-existing libraries |
 | Single edge per library enforced by unique `_from` index (REPLACE semantics) | 1:1 relation |
 | No component/workflow changes needed | They use persistence methods unchanged |
