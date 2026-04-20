# Task: Collapse Calibration Generation → DB Tag-Writing Pipeline

## Problem Statement

Currently calibration requires two separate manually-triggered steps:

1. `POST /calibration/start-histogram` triggers `CalibrationService.start_histogram_calibration_background()`, which runs `generate_histogram_calibration()` → `generate_calibration_wf`. This saves per-label p5/p95 values to `calibration_state` and writes a new `calibration_version` hash to `meta`.

2. `POST /calibration/start-apply` triggers `TaggingService.start_apply_calibration_background()`, which reads the stored calibration, reconstructs head outputs from `segment_scores_stats`, re-aggregates mood tier tags, and writes updated tags back to the DB for every stale file.

The gap between these steps means the DB can sit indefinitely in a state where calibration data has been regenerated but mood tags have not yet been updated. Users must remember to trigger step 2 manually each time.

**Invariants that must be preserved:**

- Calibration can only run after ML inference is complete (not changed — the trigger is still user-initiated).
- Writing tags to audio FILES on disk remains a separate manual step (reconcile / `write_file_tags_wf`). This task only collapses the DB-side pipeline.
- `POST /calibration/start-apply` must remain functional as a standalone endpoint for re-runs and recovery scenarios.

**Root cause:** `CalibrationService` and `TaggingService` are independent services with no link. `app.py` registers Calibration before Tagging, so there is no reference available at construction time.

**Solution:** Add a post-generation hook to `CalibrationService` that is wired by `Application.start()` after both services are constructed. When generation completes successfully, the hook automatically calls `TaggingService.start_apply_calibration_background()`.

## Phases

### Phase 1: Extend CalibrationService with a post-generation hook

- [x] Add `from collections.abc import Callable` to the imports in `calibration_svc.py`
    **Notes:** Added `from collections.abc import Callable` after `import threading` at line 12.
- [x] Add `_post_generation_hook: Callable[[], None] | None = None` as an instance field in `CalibrationService.__init__()`
    **Notes:** Added `self._post_generation_hook: Callable[[], None] | None = None` at line 70 in `__init__`.
- [x] Add `set_post_generation_hook(self, hook: Callable[[], None]) -> None` method to `CalibrationService` that stores the callable
    **Notes:** Added `set_post_generation_hook` method at lines 72–82 with docstring.
- [x] In `CalibrationService._run_histogram_generation()`, after `self._generation_result = result` is set, call the hook if set and `result["heads_failed"] == 0`; log: `"[CalibrationService] Generation complete — auto-triggering calibration apply"`
    **Notes:** Inserted hook call at lines 177–179 in `_run_histogram_generation`: checks `self._post_generation_hook is not None and result["heads_failed"] == 0` before calling.
- [x] Run `lint_project_backend` on `nomarr/services/domain/calibration_svc.py` and fix all errors
    **Notes:** `lint_project_backend(path="nomarr/services/domain/calibration_svc.py")` — 0 errors.

### Phase 2: Wire the hook in Application.start() and update docs

- [x] In `nomarr/app.py`, extract the inline `TaggingService(...)` construction into a local variable `tagging_service` in place (do NOT move it — it passes `library_service=self.services.get("library")` which requires `LibraryService` to already be registered, and LibraryService is registered after `calibration_service`)
    **Notes:** Extracted inline TaggingService construction into local variable `tagging_service` at app.py line 336. Registration unchanged — stays after LibraryService so `library_service=self.services.get("library")` resolves correctly.
- [x] Immediately after the `tagging_service` registration line, call `calibration_service.set_post_generation_hook(tagging_service.start_apply_calibration_background)` and add a debug log: `"[Application] Wired calibration post-generation hook → TaggingService.start_apply_calibration_background"` (`calibration_service` remains in scope from ~70 lines earlier)
    **Notes:** Added `calibration_service.set_post_generation_hook(tagging_service.start_apply_calibration_background)` at app.py line 347 and debug log at line 348. `calibration_service` in scope from line 267.
- [x] Update the docstring of the `POST /calibration/start-histogram` endpoint in `nomarr/interfaces/api/web/calibration_if.py` to note that on success, DB tag-writing is triggered automatically (equivalent to calling `POST /calibration/start-apply`)
    **Notes:** Added two lines to the docstring of `start_histogram_calibration_background` at calibration_if.py lines 145–146: notes that on success DB tag-writing is triggered automatically (equivalent to POST /calibration/start-apply), and that file writes remain a separate manual step.
- [x] Run `lint_project_backend` on the full workspace — zero errors is the only acceptable state
    **Notes:** `lint_project_backend()` full workspace — 0 errors, 11 files checked.

## Completion Criteria

- After `POST /calibration/start-histogram` completes successfully, `TaggingService.start_apply_calibration_background()` is called automatically without any manual intervention
- `POST /calibration/start-apply` still works as a standalone endpoint for manual re-runs
- The hook is only called when `heads_failed == 0` — partial calibration failures do NOT auto-trigger a potentially incorrect apply
- No audio files are written to disk as a side effect of this pipeline. The reconcile / `write_file_tags_wf` pathway is untouched
- Full lint passes with zero errors

## References

- `nomarr/services/domain/calibration_svc.py` — `CalibrationService._run_histogram_generation()`
- `nomarr/services/domain/tagging_svc.py` — `TaggingService.start_apply_calibration_background()`
- `nomarr/interfaces/api/web/calibration_if.py` — API surface (docstring update only)
- `nomarr/app.py` — service wiring (Application.start)
