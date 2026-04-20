# Task: Explicit Scan Endpoints — Split Dispatch by URL

## Problem Statement

`POST /library/{id}/scan?scan_type=quick|full` forces the dispatch decision into a query param handled by a
dispatcher workflow (`start_library_scan_wf.py`). The dispatcher's only job is routing — it picks a workflow
based on `scan_type`, validates the library, and sets scan status. This structure adds a layer of indirection
that obscures the actual call graph.

The fix is to make scan type a structural fact: two explicit URLs (`/scan/quick`, `/scan/full`), two service
methods. Each service method calls `scan_setup_workflow` synchronously (so errors surface at the HTTP layer
as typed exceptions), then dispatches the appropriate scan workflow as a background task. The scan workflows
themselves remain pure synchronous functions — no infra dependencies, no dispatch logic.

Currently the codebase raises plain `ValueError` for both "library not found" and "already scanning", and
`library_if.py` distinguishes them by string-matching the error message. This plan also replaces that
pattern with typed exceptions.

## Phases

### Phase 1: Add typed scan exceptions to helpers

- [x] Add `LibraryNotFoundError(ValueError)` and `LibraryAlreadyScanningError(ValueError)` to `nomarr/helpers/exceptions.py` with docstrings.
    **Notes:** Added LibraryNotFoundError(ValueError) and LibraryAlreadyScanningError(ValueError) to nomarr/helpers/exceptions.py lines 17–22. lint_project_backend — 0 errors.
- [x] Update `resolve_library_for_scan` in `scan_lifecycle_comp.py` to raise `LibraryNotFoundError` instead of plain `ValueError`.
    **Notes:** Added `from nomarr.helpers.exceptions import LibraryNotFoundError` import and changed raise to `raise LibraryNotFoundError(msg)` in scan_lifecycle_comp.py line 43. lint_project_backend on the component reports 0 errors in scan_lifecycle_comp.py; 1 pre-existing mypy error in metadata_extraction_comp.py line 411 (unrelated return type mismatch).
- [x] Update `nomarr/helpers/__init__.py` (or wherever exceptions are re-exported) to export both new types if other modules import from the helpers package top-level.
    **Notes:** Inspected nomarr/helpers/**init**.py — only re-exports sanitize_exception_message, no exception classes. New types will be imported directly from nomarr.helpers.exceptions. No changes needed.

### Phase 2: Create scan_setup_wf.py

- [x] Create `nomarr/workflows/library/scan_setup_wf.py` with `scan_setup_workflow(db, library_id, scan_type)` that calls `resolve_library_for_scan` (propagates `LibraryNotFoundError`), raises `LibraryAlreadyScanningError` if `library['scan_status'] == 'scanning'`, calls `check_interrupted_scan` and logs a warning if interrupted, calls `update_scan_progress(db, library_id, status='scanning', progress=0, total=0)`, and returns the library dict.
    **Notes:** Created nomarr/workflows/library/scan_setup_wf.py (75 lines). Calls resolve_library_for_scan (propagates LibraryNotFoundError), raises LibraryAlreadyScanningError if already scanning, logs interrupted scan warning, calls update_scan_progress, returns library dict. lint_project_backend — 0 new errors (1 pre-existing in metadata_extraction_comp.py).
- [x] Export `scan_setup_workflow` from `nomarr/workflows/library/__init__.py` (import line and `__all__` entry).
    **Notes:** Added `from .scan_setup_wf import scan_setup_workflow` and `"scan_setup_workflow"` to **all** in nomarr/workflows/library/**init**.py. lint_project_backend on library workflows — 0 new errors.

### Phase 3: Update LibraryScanMixin with two explicit methods

- [x] In `nomarr/services/domain/library_svc/scan.py`, add `start_quick_scan(self, library_id: str) -> StartScanResult` that calls `scan_setup_workflow(self.db, library_id, scan_type='quick')` synchronously, then calls `self.background_tasks.start_task(task_id=f'scan_library_{library_id}', task_fn=scan_library_quick_workflow, db=self.db, library_id=library_id, tagger_version=self.cfg.tagger_version, min_duration_s=INTERNAL_MIN_DURATION_S)`, and returns `StartScanResult(files_discovered=0, files_queued=0, files_skipped=0, files_removed=0, job_ids=[task_id])`.
    **Notes:** Added start_quick_scan to scan.py lines 75–112. Calls scan_setup_workflow then background_tasks.start_task(scan_library_quick_workflow). Added RuntimeError guard for background_tasks is None. Returns StartScanResult with task_id. lint — 0 errors in scan.py.
- [x] Add `start_full_scan(self, library_id: str) -> StartScanResult` following the same pattern with `scan_type='full'`, dispatching `scan_library_full_workflow` with the additional `models_dir=self.cfg.models_dir` and `namespace=self.cfg.namespace` kwargs.
    **Notes:** Added start_full_scan to scan.py lines 114–152. Same pattern — scan_setup_workflow then start_task(scan_library_full_workflow, ..., models_dir=self.cfg.models_dir, namespace=self.cfg.namespace). RuntimeError guard included. Returns StartScanResult.
- [x] Add imports for `scan_setup_workflow`, `scan_library_quick_workflow`, and `scan_library_full_workflow` to `scan.py`.
    **Notes:** Imports at scan.py lines 17–20: scan_library_full_workflow, scan_library_quick_workflow, scan_setup_workflow. All three resolve correctly — lint clean.
- [x] Remove the `start_scan_for_library` method and its import of `start_library_scan_workflow`.
    **Notes:** start_scan_for_library and its start_library_scan_workflow import removed. Literal also removed from typing import. Lint after removal shows 0 new errors in scan.py.

### Phase 4: Update the interface with two explicit endpoints

- [x] In `nomarr/interfaces/api/web/library_if.py`, replace the single `POST /{library_id}/scan` handler (with `scan_type` query param) with two handlers: `POST /{library_id}/scan/quick` calling `library_service.start_quick_scan(library_id)` and `POST /{library_id}/scan/full` calling `library_service.start_full_scan(library_id)`.
    **Notes:** Replaced POST /{library_id}/scan with POST /{library_id}/scan/quick (scan_library_quick) and POST /{library_id}/scan/full (scan_library_full). Also updated file_watcher_svc.py both call sites to use start_quick_scan. Removed Literal import, added LibraryAlreadyScanningError/LibraryNotFoundError imports.
- [x] In both new handlers, replace the string-sniffing `ValueError` catch with explicit `except LibraryNotFoundError` → 404 and `except LibraryAlreadyScanningError` → 409 (plus a generic `except Exception` → 500). Both handlers return `StartScanWithStatusResponse`.
    **Notes:** Both handlers use except LibraryNotFoundError: raise HTTPException(404) and except LibraryAlreadyScanningError: raise HTTPException(409). No string-sniffing remains. file_watcher_svc.py also updated with typed catches for the poll path.

### Phase 5: Delete dispatcher workflow and clean up exports

- [x] Delete `nomarr/workflows/library/start_library_scan_wf.py`.
    **Notes:** File deleted: nomarr/workflows/library/start_library_scan_wf.py. Lint on workflows/ shows only pre-existing metadata_extraction_comp error.
- [x] Remove `start_library_scan_workflow` from `nomarr/workflows/library/__init__.py` (import line and `__all__` entry).
    **Notes:** Removed from .start_library_scan_wf import start_library_scan_workflow and "start_library_scan_workflow" from **all** in nomarr/workflows/library/**init**.py.
- [x] Remove `start_library_scan_workflow` from `nomarr/workflows/__init__.py` (import line and `__all__` entry).
    **Notes:** Removed from .library.start_library_scan_wf import start_library_scan_workflow and "start_library_scan_workflow" from **all** in nomarr/workflows/**init**.py.

### Phase 6: Update frontend API client

- [x] In `frontend/src/shared/api/library.ts`, replace the `scan(id, scanType)` function with two explicit functions: `scanQuick(id)` posting to `/api/web/libraries/${id}/scan/quick` and `scanFull(id)` posting to `/api/web/libraries/${id}/scan/full`.
    **Notes:** Replaced scan(id, scanType) with scanQuick(id) and scanFull(id) posting to /scan/quick and /scan/full respectively. Both return Promise&lt;ScanResult&gt;.
- [x] Update all callers of `scan(id, scanType)` in the frontend (e.g., `LibraryManagement.tsx`) to call `scanQuick` or `scanFull` explicitly.
    **Notes:** LibraryManagement.tsx: replaced scan as scanLibrary import with scanFull and scanQuick. handleScan now calls (scanType === "quick" ? scanQuick(id) : scanFull(id)). No other callers found.

### Phase 7: Verify correctness

- [x] Run `lint_project_backend` and confirm zero errors.
    **Notes:** Full workspace lint: 5 errors, all pre-existing no-any-return in metadata_extraction_comp.py, ml_svc.py, calibration_svc.py. Zero new errors introduced by this plan. attr-defined errors from file_watcher_svc.py are gone.
- [x] Run `lint_project_frontend` and confirm zero errors.
    **Notes:** Frontend lint clean. ESLint and TypeScript both pass after replacing scan with scanQuick/scanFull in library.ts, LibraryManagement.tsx, and index.ts.
- [x] Confirm no remaining references to `start_library_scan_workflow`, `start_scan_for_library`, `scan_type` query param, or string-sniffing exception handling for scan errors in the codebase.
    **Notes:** start_library_scan_workflow - 0 matches. start_scan_for_library - 0 matches. Remaining "already being scanned" strings are all in typed exception handlers or log messages — no string-sniffing. scan_type query param removed from library_if.py. All clean.

## Completion Criteria

- `LibraryNotFoundError` and `LibraryAlreadyScanningError` exist in `helpers/exceptions.py`; no scan-related code raises plain `ValueError` for these cases.
- `start_library_scan_wf.py` no longer exists; no exports of `start_library_scan_workflow` remain.
- Two URL paths exist: `POST /api/web/libraries/{id}/scan/quick` and `POST /api/web/libraries/{id}/scan/full`.
- `scan_setup_workflow` runs synchronously before dispatch; typed exceptions propagate cleanly to the interface.
- `scan_library_quick_workflow` and `scan_library_full_workflow` are unchanged as pure synchronous functions.
- `LibraryScanMixin` has `start_quick_scan` and `start_full_scan`; `start_scan_for_library` is gone.
- Frontend calls explicit endpoint functions with no `scan_type` param.
- `lint_project_backend` and `lint_project_frontend` report zero errors.

## References

- `nomarr/helpers/exceptions.py` — receives `LibraryNotFoundError`, `LibraryAlreadyScanningError`
- `nomarr/components/library/scan_lifecycle_comp.py` — `resolve_library_for_scan` updated to raise `LibraryNotFoundError`
- `nomarr/workflows/library/start_library_scan_wf.py` — dispatcher being deleted
- `nomarr/workflows/library/scan_setup_wf.py` — new workflow (to create): synchronous pre-scan validation using typed exceptions
- `nomarr/workflows/library/scan_library_quick_wf.py` — unchanged; pure sync work function
- `nomarr/workflows/library/scan_library_full_wf.py` — unchanged; pure sync work function
- `nomarr/services/domain/library_svc/scan.py` — receives two explicit methods: call scan_setup then start_task
- `nomarr/interfaces/api/web/library_if.py` — receives two explicit endpoints with typed exception handling
- `frontend/src/shared/api/library.ts` — API client receiving `scanQuick` / `scanFull`
