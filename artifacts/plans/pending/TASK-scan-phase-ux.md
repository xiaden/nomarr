# Task: Add UX for Move Detection During File Scanning

## Problem Statement

When a library scan runs, the frontend shows "Scanning... X / Y files (Z%)" via `scan_progress` / `scan_total` fields on the library document. Once folder scanning (Step 4) completes and progress reaches 100%, the scan enters several post-scan phases — move detection (computing chromaprints for every new file), entity cleanup, and finalization. During these phases, the UI still shows "Scanning..." at 100% with no indication of what's holding up completion. For large libraries with many moved files, chromaprint computation is CPU-intensive and this wait is noticeable.

The fix: add a `scan_phase` field to library scan status so the backend reports which phase is active, and the frontend displays a contextual label instead of a static "Scanning...".

## Phases

### Phase 1: Backend — Add scan_phase to library status

- [ ] Add `scan_phase` field to `update_scan_status` in `nomarr/persistence/database/libraries_aql.py` (new optional string param, persisted alongside `scan_status`)
- [ ] Add `scan_phase` parameter to `update_scan_progress` in `nomarr/components/library/scan_lifecycle_comp.py` (pass through to persistence)
- [ ] Add `scan_phase` field to `LibraryScanStatusResult` in `nomarr/helpers/dto/library_dto.py`
- [ ] Add `scan_phase` field to `ScanningLibraryInfo` in `nomarr/helpers/dto/info_dto.py`
- [ ] Update `compute_work_status` in `nomarr/components/library/work_status_comp.py` to propagate `scan_phase` from library doc into `ScanningLibraryInfo`
- [ ] Run `lint_project_backend` on modified paths and fix all errors

### Phase 2: Backend — Emit scan_phase from workflows

- [ ] Add `update_scan_progress(db, library_id, scan_phase="scanning")` call at start of folder loop (Step 4) in `scan_library_quick_wf.py`
- [ ] Add `update_scan_progress(db, library_id, scan_phase="move_detection")` before move detection (Step 6) in `scan_library_quick_wf.py`
- [ ] Add `update_scan_progress(db, library_id, scan_phase="finalizing")` before entity cleanup / finalize (Step 7+) in `scan_library_quick_wf.py`
- [ ] Mirror the same phase updates in `scan_library_full_wf.py` (Steps 4, 6, 7+)
- [ ] Ensure `mark_scan_completed` or the final `update_scan_progress(status="complete")` clears `scan_phase` to `None`
- [ ] Run `lint_project_backend` on both workflow files and fix all errors

### Phase 3: Backend — Expose scan_phase in API responses

- [ ] Ensure `get_status` endpoint response includes `scan_phase` (via `LibraryScanStatusResult`)
- [ ] Ensure library list endpoint response includes `scan_phase` per library (via `LibraryDict` or list response mapper)
- [ ] Run `lint_project_backend` on interface files and fix all errors

### Phase 4: Frontend — Display scan phase in UI

- [ ] Add `scan_phase` to `LibraryResponse` interface and `mapLibraryResponse` in `frontend/src/shared/api/library.ts`
- [ ] Add `scanPhase` to `Library` type in `frontend/src/shared/types.ts`
- [ ] Add `scan_phase` to `ScanningLibrary` interface in `frontend/src/shared/api/processing.ts`
- [ ] Update `LibraryManagement.tsx` scan progress display: replace static "Scanning..." chip label with phase-aware label (e.g. "Scanning files...", "Detecting moves...", "Finalizing...")
- [ ] Update `DashboardPage.tsx` `ProgressBar` for scanning libraries to show phase label when available
- [ ] Run `lint_project_frontend` and fix all errors

## Completion Criteria

- `scan_phase` is written to library document during scan workflows (both quick and full)
- `scan_phase` is exposed in library list, library status, and work-status API responses
- Frontend displays a contextual phase label during scanning instead of static "Scanning..."
- Move detection phase is clearly indicated to the user so they know what's holding up the scan
- `scan_phase` is cleared to null when scan completes or errors
- All lint checks pass (backend and frontend)

## References

- Backend scan workflows: `nomarr/workflows/library/scan_library_quick_wf.py`, `scan_library_full_wf.py`
- Scan lifecycle component: `nomarr/components/library/scan_lifecycle_comp.py`
- Move detection component: `nomarr/components/library/move_detection_comp.py`
- Persistence: `nomarr/persistence/database/libraries_aql.py` (`update_scan_status`)
- DTOs: `nomarr/helpers/dto/library_dto.py`, `nomarr/helpers/dto/info_dto.py`
- Frontend types: `frontend/src/shared/types.ts`, `frontend/src/shared/api/library.ts`, `processing.ts`
- Frontend UI: `frontend/src/features/library/components/LibraryManagement.tsx`, `features/dashboard/DashboardPage.tsx`
