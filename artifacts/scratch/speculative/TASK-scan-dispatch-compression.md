# Task: Compress 3-Layer Scan Dispatch

## Problem Statement

Starting a library scan currently passes through an unnecessary intermediate layer:
`library_if.py` → `LibraryScanMixin.start_scan_for_library` → `start_library_scan_workflow` → actual scan workflow.

The dispatcher workflow (`start_library_scan_wf.py`) exists purely to:

- Do a `_SCAN_WORKFLOWS` dict lookup to pick `scan_library_quick_workflow` or `scan_library_full_workflow`
- Validate the library is not already scanning (check also exists inside each scan workflow)
- Check for interrupted scans (log-only)
- Set `scan_status = 'scanning'` before the background launch
- Build `extra_kwargs` based on `scan_type`, then dispatch via `background_tasks.start_task` or call synchronously

All of this can live directly in `LibraryScanMixin.start_scan_for_library`. No external code calls
`start_library_scan_workflow` directly — the only caller is the service mixin (the `__init__.py` re-exports
are just pass-through). Removing the dispatcher shortens the call chain by one layer and eliminates
a file whose only purpose is forwarding.

## Phases

### Phase 1: Inline dispatcher logic into the service mixin

- [ ] In `nomarr/services/domain/library_svc/scan.py`, replace the call to `start_library_scan_workflow` in `start_scan_for_library` with the inlined body: dict lookup (`_SCAN_WORKFLOWS`), `resolve_library_for_scan`, "already scanning" guard, `check_interrupted_scan`, log, `update_scan_progress`, `extra_kwargs` construction, `background_tasks.start_task` / synchronous fallback, return `StartScanResult`.
- [ ] Add the required imports to `scan.py`: `scan_library_full_workflow`, `scan_library_quick_workflow`, `check_interrupted_scan`, `resolve_library_for_scan`, `update_scan_progress` from their respective modules.
- [ ] Remove the now-unused import of `start_library_scan_workflow` from `scan.py`.

### Phase 2: Delete the dispatcher workflow file and clean up exports

- [ ] Delete `nomarr/workflows/library/start_library_scan_wf.py`.
- [ ] Remove `start_library_scan_workflow` from `nomarr/workflows/library/__init__.py` (import line and `__all__` entry).
- [ ] Remove `start_library_scan_workflow` from `nomarr/workflows/__init__.py` (import line and `__all__` entry).

### Phase 3: Verify correctness

- [ ] Run `lint_project_backend` and confirm zero errors.
- [ ] Confirm no remaining references to `start_library_scan_workflow` in the codebase (use `locate_module_symbol` or grep).

## Completion Criteria

- `start_library_scan_wf.py` no longer exists.
- `LibraryScanMixin.start_scan_for_library` directly calls `resolve_library_for_scan`, `check_interrupted_scan`, `update_scan_progress`, and dispatches to `scan_library_quick_workflow` or `scan_library_full_workflow` — no intermediate dispatcher.
- `lint_project_backend` reports zero errors.
- No external reference to `start_library_scan_workflow` remains anywhere in the codebase.

## References

- `nomarr/workflows/library/start_library_scan_wf.py` — dispatcher being removed
- `nomarr/services/domain/library_svc/scan.py` — service mixin receiving the inlined logic
- `nomarr/workflows/library/scan_library_full_wf.py` — signature: `(db, library_id, tagger_version, models_dir=None, namespace="nom", min_duration_s=None)`
- `nomarr/workflows/library/scan_library_quick_wf.py` — signature: `(db, library_id, tagger_version, min_duration_s=None)`
- `nomarr/components/library/scan_lifecycle_comp.py` — source of `resolve_library_for_scan`, `check_interrupted_scan`, `update_scan_progress`
