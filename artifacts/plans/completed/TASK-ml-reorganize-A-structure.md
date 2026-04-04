# Task: Reorganize nomarr/components/ml/ — Part A: Structure

## Problem Statement

The ML component directory (`nomarr/components/ml/`) has 29 files in a flat layout. Three compounding problems exist:

1. **Subdomain confusion** — files from ONNX session management, audio preprocessing, inference pipeline, calibration, vector storage, and resource management all appear as equal peers.
2. **Naming violations** — four files break the `*_comp.py` contract: `chromaprint_comp.py`, `segment_stats_comp.py`, `calibration_state_comp.py` (all missing the `ml_` prefix) and `ml_known_models.py` (missing the `_comp` suffix). Five `ml_onnx_*.py` class-based files carry misleading `_comp`-style names. One file (`ml_onnx_types.py`) is named "types" but contains a single constant.
3. **Empty/misplaced file** — `ml_inference_comp.py` contains only one private function (`_run_in_batches`) and one private constant (`_BACKBONE_BATCH_SIZE = 32`). It has no public API; its two symbols (`_run_in_batches`, `_BACKBONE_BATCH_SIZE`) are imported only by `ml_onnx_backbone.py` and `ml_onnx_head.py`, both of which belong in `onnx/`. The symbols should be consolidated into `onnx/ml_session_comp.py` — not `inference/` — so the dependency flows correctly: `inference/` → `onnx/`, not the reverse.

**This plan covers Part A: creating the subdirectory skeleton, moving and renaming files, and fixing all imports WITHIN `nomarr/components/ml/` itself (intra-ml wiring). It does NOT update any import sites outside of `ml/`.**

See `TASK-ml-reorganize-B-wiring.md` for external import updates, `__init__.py` re-export surface, and `pyproject.toml` changes.

---

## Proposed Subdirectory Layout

```bash
nomarr/components/ml/
  __init__.py                          (existing — updated in Part B)

  onnx/                                ONNX model definitions, discovery, session lifecycle
    __init__.py
    ml_base.py                         ← ml_onnx_base.py  (BaseONNXModel, VramFitError, DevicePlacement)
    ml_backbone.py                     ← ml_onnx_backbone.py  (ONNXBackboneModel)
    ml_head.py                         ← ml_onnx_head.py  (ONNXHeadModel)
    ml_cache.py                        ← ml_onnx_cache.py  (ONNXModelCache)
    ml_constants.py                    ← ml_onnx_types.py  (MODEL_SUITE_VERSION)
    ml_session_comp.py                 ← ml_backend_onnx_comp.py  (create_session, is_available, …)
    ml_discovery_comp.py               ← ml_discovery_comp.py  (discover_heads, HeadInfo, …)
    ml_known_models_comp.py            ← ml_known_models.py  (RENAMED: missing _comp suffix)

  audio/                               Audio loading and spectral preprocessing (Essentia-backed)
    __init__.py
    ml_audio_comp.py                   ← ml_audio_comp.py
    ml_preprocess_comp.py              ← ml_preprocess_comp.py
    ml_chromaprint_comp.py             ← chromaprint_comp.py  (RENAMED: missing ml_ prefix)

  inference/                           Execution pipeline: embedding, pooling, head decisions
    __init__.py
    ml_backbone_embed_comp.py          ← ml_backbone_embed_comp.py (plain move, no absorption)
    ml_embed_comp.py                   ← ml_embed_comp.py  (segment_waveform, score_segments, …)
    ml_heads_comp.py                   ← ml_heads_comp.py  (run_head_decision, HeadSpec, …)
    ml_head_pipeline_comp.py           ← ml_head_pipeline_comp.py  (run_heads, shutdown_head_pool)
    ml_segment_stats_comp.py           ← segment_stats_comp.py  (RENAMED: missing ml_ prefix)

  calibration/                         Calibration computation and DB persistence
    __init__.py
    ml_calibration_comp.py             ← ml_calibration_comp.py
    ml_calibration_state_comp.py       ← calibration_state_comp.py  (RENAMED: missing ml_ prefix)

  vectors/                             Embedding pooling, storage, and vector index
    __init__.py
    ml_vector_pool_comp.py             ← ml_vector_pool_comp.py
    ml_vector_persist_comp.py          ← ml_vector_persist_comp.py
    ml_vector_maintenance_comp.py      ← ml_vector_maintenance_comp.py

  resources/                           VRAM coordination, capacity probing, timing, tier selection
    __init__.py
    ml_vram_coordinator_comp.py        ← ml_vram_coordinator_comp.py
    ml_vram_probe_comp.py              ← ml_vram_probe_comp.py
    ml_capacity_probe_comp.py          ← ml_capacity_probe_comp.py
    ml_timing_comp.py                  ← ml_timing_comp.py
    ml_worker_context_comp.py          ← ml_worker_context_comp.py
    ml_tier_selection_comp.py          ← ml_tier_selection_comp.py

  # DELETED: ml_inference_comp.py   (consolidated into onnx/ml_session_comp.py)
```

**Naming convention:** The `ml_` prefix is retained uniformly across every subdirectory — including `onnx/`. Class-based files drop `_comp` (e.g., `ml_base.py`, `ml_backbone.py`) because `_comp` signals stateless functions; stateless function files keep `_comp` (`ml_session_comp.py`, `ml_discovery_comp.py`, etc.).

**Placement rationale for `onnx/`:** `ml_discovery_comp` and `ml_known_models_comp` both describe and locate ONNX models — filesystem/registry concerns, not execution. They belong in `onnx/` alongside the model wrappers, not in `inference/` which is reserved for pipeline execution. Evidence: `ml_known_models` is imported by `tagging_aggregation_comp`, which has no connection to the inference pipeline.

---

## Phases

### Phase 1: Pre-move fix — make `_head_parts_from_path` public

- [x] Rename `_head_parts_from_path` to `head_parts_from_path` in `ml_onnx_head.py` (drop leading underscore). It is imported externally by `nomarr/workflows/platform/register_ml_models_wf.py`, so the underscore is a broken convention — not an import-linter violation (contracts are layer-level only) but a misleading API signal. Update the call site in `register_ml_models_wf.py` in the same edit. This must happen before the file is moved so the rename is a single, clean change.
    **Notes:** Renamed `_head_parts_from_path` → `head_parts_from_path` in `ml_onnx_head.py` (function definition line 35, class call site line 127). Updated `register_ml_models_wf.py` import (line 19) and call site (line 62). Pattern search confirms zero remaining references to old name. Both files lint clean (0 errors).

### Phase 2: Create subdirectory skeletons

- [x] Create empty `__init__.py` stubs for `onnx/`, `audio/`, `inference/`, `calibration/`, `vectors/`, `resources/` using `edit_file_create` in one batch
    **Notes:** Created 6 empty `__init__.py` stubs in one batch: `onnx/`, `audio/`, `inference/`, `calibration/`, `vectors/`, `resources/`. All created at 0 bytes via `edit_file_create`.

**Warning:** After Phase 3 moves files and before Phase 4 fixes imports, all intra-ml imports will be broken — every `from nomarr.components.ml.ml_onnx_base import ...` inside the ml/ tree will fail because those paths no longer exist. This is expected and intentional. Do not attempt to fix imports prematurely; wait for Phase 4, which updates all intra-ml imports systematically.

### Phase 3: Move and rename files by subdomain

- [x] Move 8 ONNX files to `onnx/`: `ml_onnx_base.py`→`ml_base.py`, `ml_onnx_backbone.py`→`ml_backbone.py`, `ml_onnx_head.py`→`ml_head.py`, `ml_onnx_cache.py`→`ml_cache.py`, `ml_onnx_types.py`→`ml_constants.py`, `ml_backend_onnx_comp.py`→`ml_session_comp.py`, `ml_discovery_comp.py` (no rename), `ml_known_models.py`→`ml_known_models_comp.py` — using `edit_file_move`
    **Notes:** Moved all 8 ONNX files to `onnx/`: `ml_onnx_base.py`→`ml_base.py`, `ml_onnx_backbone.py`→`ml_backbone.py`, `ml_onnx_head.py`→`ml_head.py`, `ml_onnx_cache.py`→`ml_cache.py`, `ml_onnx_types.py`→`ml_constants.py`, `ml_backend_onnx_comp.py`→`ml_session_comp.py`, `ml_discovery_comp.py` (no rename), `ml_known_models.py`→`ml_known_models_comp.py`. All moves confirmed by tool response.
- [x] Move 3 audio files to `audio/`: `ml_audio_comp.py`, `ml_preprocess_comp.py` (no rename); `chromaprint_comp.py`→`ml_chromaprint_comp.py`
    **Notes:** Moved 3 audio files to `audio/`: `ml_audio_comp.py` (no rename), `ml_preprocess_comp.py` (no rename), `chromaprint_comp.py`→`ml_chromaprint_comp.py`. All confirmed by tool response.
- [x] Move 5 inference files to `inference/`: `ml_backbone_embed_comp.py`, `ml_embed_comp.py`, `ml_heads_comp.py`, `ml_head_pipeline_comp.py` (no rename); `segment_stats_comp.py`→`ml_segment_stats_comp.py`
    **Notes:** Moved 5 inference files to `inference/`: `ml_backbone_embed_comp.py`, `ml_embed_comp.py`, `ml_heads_comp.py`, `ml_head_pipeline_comp.py` (no rename); `segment_stats_comp.py`→`ml_segment_stats_comp.py`. All confirmed by tool response.
- [x] Move 2 calibration files to `calibration/`: `ml_calibration_comp.py` (no rename); `calibration_state_comp.py`→`ml_calibration_state_comp.py`
    **Notes:** Moved 2 calibration files to `calibration/`: `ml_calibration_comp.py` (no rename), `calibration_state_comp.py`→`ml_calibration_state_comp.py`. Confirmed by tool response.
- [x] Move 3 vector files to `vectors/`: `ml_vector_pool_comp.py`, `ml_vector_persist_comp.py`, `ml_vector_maintenance_comp.py` (no renames)
    **Notes:** Moved 3 vector files to `vectors/`: `ml_vector_pool_comp.py`, `ml_vector_persist_comp.py`, `ml_vector_maintenance_comp.py` (no renames). All confirmed by tool response.
- [x] Move 6 resource files to `resources/`: `ml_vram_coordinator_comp.py`, `ml_vram_probe_comp.py`, `ml_capacity_probe_comp.py`, `ml_timing_comp.py`, `ml_worker_context_comp.py`, `ml_tier_selection_comp.py` (no renames)
    **Notes:** Moved 6 resource files to `resources/`: `ml_vram_coordinator_comp.py`, `ml_vram_probe_comp.py`, `ml_capacity_probe_comp.py`, `ml_timing_comp.py`, `ml_worker_context_comp.py`, `ml_tier_selection_comp.py` (no renames). All confirmed by tool response.

### Phase 4: Consolidate ml_inference_comp.py
- [x] Move `_run_in_batches` function and `_BACKBONE_BATCH_SIZE = 32` constant from `ml_inference_comp.py` into `onnx/ml_session_comp.py` using `edit_file_insert_at_boundary`. Both symbols are consumed by `onnx/ml_backbone.py` and `onnx/ml_head.py` — ONNX session-level infrastructure that belongs alongside the session factory. Placing them in `inference/` would create a backwards dependency (`onnx/` importing from `inference/`). After inserting, update the import in `onnx/ml_backbone.py` (`_BACKBONE_BATCH_SIZE, _run_in_batches` from `onnx.ml_session_comp`) and in `onnx/ml_head.py` (`_run_in_batches` from `onnx.ml_session_comp`); then delete `ml_inference_comp.py`
    **Notes:** Appended `_BACKBONE_BATCH_SIZE = 32` and `_run_in_batches()` to `onnx/ml_session_comp.py` (lines 207–238). Added `import numpy as np` and `from collections.abc import Callable` (under TYPE_CHECKING) to support the appended code. Updated `onnx/ml_backbone.py` line 19 and `onnx/ml_head.py` line 17 to import from `nomarr.components.ml.onnx.ml_session_comp`. Deleted `ml_inference_comp.py`. Pattern search confirms zero remaining Python import references. `lint_project_backend` on ml_session_comp.py: 0 errors.

### Phase 5: Fix intra-ml imports and write sub-package **init**.py files

- [x] Update all `from nomarr.components.ml.*` and relative imports WITHIN the moved files to point at the new paths. Key cross-subpackage dependencies: `onnx/ml_backbone.py` imports from `audio/ml_preprocess_comp.py`, `onnx/ml_base.py`, `onnx/ml_constants.py`, `onnx/ml_session_comp.py` (`_run_in_batches`, `_BACKBONE_BATCH_SIZE`); `onnx/ml_head.py` from `onnx/ml_base.py`, `onnx/ml_session_comp.py` (`_run_in_batches`); `onnx/ml_cache.py` from `onnx/ml_backbone.py`, `onnx/ml_head.py`, `onnx/ml_base.py`; `inference/ml_backbone_embed_comp.py` from `onnx/ml_cache.py`, `onnx/ml_head.py`; `inference/ml_head_pipeline_comp.py` from `onnx/ml_head.py`, `inference/ml_heads_comp.py`, `onnx/ml_discovery_comp.py`; `onnx/ml_discovery_comp.py` from `onnx/ml_backbone.py`, `onnx/ml_head.py`, `onnx/ml_constants.py`; `resources/ml_vram_probe_comp.py` from `onnx/ml_base.py`, `onnx/ml_session_comp.py`, `onnx/ml_discovery_comp.py`; `vectors/ml_vector_persist_comp.py` from `vectors/ml_vector_pool_comp.py`. Use `lint_project_backend(path="nomarr/components/ml")` after each subpackage to catch missed references.
    **Notes:** Fixed all stale `nomarr.components.ml.*` imports across 15 files in all 6 subpackages: `onnx/` (ml_base.py: 4 imports, ml_backbone.py: 3, ml_head.py: 3, ml_cache.py: 4, ml_discovery_comp.py: 4), `inference/` (ml_head_pipeline_comp.py: 3, ml_backbone_embed_comp.py: 2, ml_heads_comp.py: 2), `calibration/` (ml_calibration_comp.py: 1), `resources/` (ml_vram_probe_comp.py: 2, ml_tier_selection_comp.py: 1, ml_capacity_probe_comp.py: 2), `vectors/` (ml_vector_persist_comp.py: 1, ml_vector_pool_comp.py: 1, ml_vector_maintenance_comp.py: 1). `lint_project_backend(path="nomarr/components/ml")`: 0 errors across 33 files.
- [x] Write `__init__.py` for each of the 6 subdirectories, re-exporting the complete public surface needed by the top-level `ml/__init__.py` and by intra-ml sibling packages. Run `lint_project_backend(path="nomarr/components/ml")` to confirm zero errors within ml/ before handing off to Part B.
    **Notes:** Wrote content for all 6 subpackage __init__.py files: audio/ (6 re-exports from ml_audio_comp), calibration/ (2 re-exports from ml_calibration_comp), resources/ (10 re-exports across ml_capacity_probe_comp, ml_tier_selection_comp, ml_vram_probe_comp), onnx/ (1 re-export from ml_discovery_comp), inference/ and vectors/ (docstring only — no public surface consumed by top-level __init__.py). Top-level ml/__init__.py left broken (Part B owns it per plan design: __init__.py is listed as updated in Part B). lint_project_backend(path=nomarr/components/ml): 0 errors, 33 files checked (all subpackage files including the 6 new __init__.py files).

---

## Completion Criteria

- All 29 original flat files are either relocated into a subdirectory or deleted (`ml_inference_comp.py`)
- `nomarr/components/ml/` root contains only `__init__.py` plus 6 named subdirectories
- `_head_parts_from_path` renamed to `head_parts_from_path` and call site in `register_ml_models_wf.py` updated
- `lint_project_backend(path="nomarr/components/ml")` returns zero errors
- No import statements outside `nomarr/components/ml/` have been touched yet (those are Part B)

## References

- Sibling plan: `TASK-ml-reorganize-B-wiring.md` (external import sites, top-level `__init__.py`, `pyproject.toml`)
