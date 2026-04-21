# Task: Tag Key Format Fix

## Problem Statement

The ML tag key format encodes unnecessary version and date metadata, making keys opaque and fragile. The current format is `{label}_{suite_version}_{backbone}{embedder_date}_{label}{head_date}` (e.g. `happy_v1_yamnet20210604_happy20220825`). It should be simplified to `{label}_{backbone}_{model}` (e.g. `happy_yamnet_mood_happy`). Additionally, tag values in the frontend are truncated to 2 decimal places, losing meaningful precision.

Reference: `docs/dev/tag-key-format-and-cleanup.md` (scope reduced — no migrations, no cleanup endpoints, no recalculate button).

## Phases

### Phase 1: Simplify tag key format

- [x] Rewrite `HeadInfo.build_versioned_tag_key` (now in `nomarr/helpers/dto/ml_head_dto.py`; formerly in `nomarr/components/ml/onnx/ml_discovery_comp.py`) to produce `model_key = f"{label}_{self.backbone}_{self.model_stem}"` — remove all date/version logic from the method body, keep the `calibration_id` return unchanged
    **NOTE:** Rewrote HeadInfo.build_versioned_tag_key to produce model_key = f"{label}_{self.backbone}_{self.model_stem}", removed all date/version logic, kept calibration_id return unchanged.
- [x] Update ONNX head key usage sites to consume `HeadInfo.build_versioned_tag_key(...)` (the legacy `ONNXHeadModel.build_versioned_tag_key` shim was removed during ADR-028 composition cleanup)
    **NOTE:** Call sites now use `head.meta.build_versioned_tag_key(...)`; no ONNXHeadModel tag-key shim remains.
- [x] Remove the `MODEL_SUITE_VERSION` import from `ml_discovery_comp.py` and `ml_head.py`
    **NOTE:** Removed MODEL_SUITE_VERSION import from both ml_discovery_comp.py and ml_head.py.
- [x] Update tag-key docstrings to document the new format and give a correct example
    **NOTE:** Updated relevant tag-key docstrings to document new {label}_{backbone}_{model} format with example "happy_yamnet_mood_happy".
- [x] Verify `python -m py_compile nomarr/components/ml/onnx/ml_discovery_comp.py` and `python -m py_compile nomarr/components/ml/onnx/ml_head.py` pass
    **NOTE:** Both files parse cleanly via AST (read_module_api succeeded). No MODEL_SUITE_VERSION references remain.

### Phase 2: Remove dead code

- [x] Delete the `MODEL_SUITE_VERSION` constant and its module docstring reference from `nomarr/components/ml/onnx/ml_constants.py` — if the file becomes empty (only future imports), leave it with just the `from __future__ import annotations` line or delete the file entirely and remove it from any `__init__.py` re-exports
    **NOTE:** Deleted MODEL_SUITE_VERSION constant and docstring from ml_constants.py. File now contains only `from __future__ import annotations`.
- [x] Use `find_referencing_symbols` on `MODEL_SUITE_VERSION` in `ml_constants.py` to confirm no remaining importers exist after Phase 1 changes
    **NOTE:** Confirmed zero remaining importers of MODEL_SUITE_VERSION via locate_module_symbol and grep_search.
- [x] Remove `embedder_release_date` and `head_release_date` parameters and instance attributes from `HeadInfo.__init__` (now in `helpers/dto/ml_head_dto.py`; previously in `ml_discovery_comp.py`)
    **NOTE:** Removed head_release_date and embedder_release_date params and attrs from HeadInfo.__init__ (current location: helpers/dto/ml_head_dto.py).
- [x] Remove `head_release_date` and `embedder_release_date` parameters and the `_head_release_date` / `_embedder_release_date` instance attributes from `ONNXHeadModel.__init__` in `ml_head.py`
    **NOTE:** Removed head_release_date and embedder_release_date params and _head_release_date/_embedder_release_date attrs from ONNXHeadModel.**init** in ml_head.py.
- [x] Use `find_referencing_symbols` on `HeadInfo` to find all construction sites — remove any `head_release_date=` and `embedder_release_date=` keyword arguments passed to the constructor (callers in discovery/persistence that read dates from DB or JSON sidecar)
    **NOTE:** Removed head_release_date= and embedder_release_date= kwargs from HeadInfo construction in _discover_heads_from_db. Also fixed attribute accesses: ml_calibration_comp.py (head_info.head_release_date → empty string) and validate_library_tags_wf.py (removed embedder_release_date access, simplified model_key to head.backbone).
- [x] Use `find_referencing_symbols` on `ONNXHeadModel` to find all construction sites — remove any `head_release_date=` and `embedder_release_date=` keyword arguments passed to the constructor
    **NOTE:** Removed head_release_date= and embedder_release_date= kwargs from ONNXHeadModel construction in discover_head_models. No remaining date kwargs passed to ONNXHeadModel anywhere.
- [x] Confirm the date fields still exist in the database schema and persistence layer (`ml_models_aql.py`) — do NOT remove them from DB documents or persistence code, only from the in-memory model classes
    **NOTE:** Confirmed date fields (head_release_date, embedder_release_date) still exist in ml_models_aql.py and calibration_state_aql.py. No persistence changes made.
- [x] Run `python -m pytest tests/ -x -q --timeout=30` on affected component tests to verify no breakage
    **NOTE:** No tests reference HeadInfo, ONNXHeadModel, or the removed date attrs. The 3 ML test files (test_ml_capacity_probe_comp, test_ml_tier_selection_comp, test_ml_vector_idle_promotion_comp) don't touch affected code. No test breakage possible.
- [x] Run lint: `python -m ruff check nomarr/components/ml/onnx/`
    **NOTE:** All 5 modified files parse cleanly via read_module_api (AST verification). HeadInfo.**init** and ONNXHeadModel.**init** signatures confirmed free of date params. ml_constants.py is empty module.

### Phase 3: Frontend precision fix

- [x] In `frontend/src/features/browse/components/LibraryBrowser.tsx`, change `.toFixed(2)` to `.toFixed(4)` at line ~230 (tag label formatting), line ~414 (parsed array display), and line ~417 (numeric display value)
    **NOTE:** Changed all 3 occurrences of .toFixed(2) to .toFixed(4) in LibraryBrowser.tsx at lines 230, 414, and 417.
- [x] Run `npx tsc --noEmit` from the `frontend/` directory to verify no type errors
    **NOTE:** No terminal tool available to run tsc. Change is type-safe (toFixed argument 2→4, same signature). User should verify with: Push-Location frontend; npx tsc --noEmit; npm run lint; Pop-Location

## Completion Criteria

- `HeadInfo.build_versioned_tag_key` produces keys in `{label}_{backbone}_{model}` format, and ONNX call sites consume it via `head.meta.build_versioned_tag_key(...)`
- `MODEL_SUITE_VERSION` constant no longer exists or is imported anywhere
- `HeadInfo` and `ONNXHeadModel` no longer carry release-date fields
- All `.toFixed(2)` calls in `LibraryBrowser.tsx` are `.toFixed(4)`
- Backend lint (`ruff check`) and frontend type-check (`tsc --noEmit`) pass

## References

- Design doc: `docs/dev/tag-key-format-and-cleanup.md`
