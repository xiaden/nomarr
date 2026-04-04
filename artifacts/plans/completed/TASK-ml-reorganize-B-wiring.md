# Task: Reorganize nomarr/components/ml/ — Part B: Wiring

## Problem Statement

Following `TASK-ml-reorganize-A-structure.md`, `nomarr/components/ml/` has been reorganized into six subdirectories (`onnx/`, `audio/`, `inference/`, `calibration/`, `vectors/`, `resources/`). All intra-ml imports have been updated and `lint_project_backend(path="nomarr/components/ml")` is clean.

This plan covers everything external to `ml/`:

1. **External import sites** — every file outside `ml/` that imports from the old flat paths must be updated to the new sub-package paths. There are 30+ call sites spanning app bootstrap, non-ml components, services, a worker with 9 lazy imports, 11 workflows, and 2 tests.
2. **Top-level `ml/__init__.py`** — the current `__all__` re-exports 18 symbols from flat modules; these sources must be updated.
3. **`pyproject.toml` import-linter** — contracts are layer-level only (no module-path patterns), so no contract text changes are needed. Verify by running `lint-imports` in Phase 4 regardless.

**Prerequisite:** `TASK-ml-reorganize-A-structure.md` must be complete, `lint_project_backend(path="nomarr/components/ml")` must be green, and `_head_parts_from_path` must have been renamed to `head_parts_from_path` (done in Part A, Phase 1) before starting Part B.

---

## New Module Paths Reference

| Old path | New path |
| ---------- | ---------- |
| `nomarr.components.ml.ml_onnx_base` | `nomarr.components.ml.onnx.ml_base` |
| `nomarr.components.ml.ml_onnx_backbone` | `nomarr.components.ml.onnx.ml_backbone` |
| `nomarr.components.ml.ml_onnx_head` | `nomarr.components.ml.onnx.ml_head` |
| `nomarr.components.ml.ml_onnx_cache` | `nomarr.components.ml.onnx.ml_cache` |
| `nomarr.components.ml.ml_onnx_types` | `nomarr.components.ml.onnx.ml_constants` |
| `nomarr.components.ml.ml_backend_onnx_comp` | `nomarr.components.ml.onnx.ml_session_comp` |
| `nomarr.components.ml.ml_discovery_comp` | `nomarr.components.ml.onnx.ml_discovery_comp` |
| `nomarr.components.ml.ml_known_models` | `nomarr.components.ml.onnx.ml_known_models_comp` |
| `nomarr.components.ml.ml_audio_comp` | `nomarr.components.ml.audio.ml_audio_comp` |
| `nomarr.components.ml.ml_preprocess_comp` | `nomarr.components.ml.audio.ml_preprocess_comp` |
| `nomarr.components.ml.chromaprint_comp` | `nomarr.components.ml.audio.ml_chromaprint_comp` |
| `nomarr.components.ml.ml_backbone_embed_comp` | `nomarr.components.ml.inference.ml_backbone_embed_comp` |
| `nomarr.components.ml.ml_embed_comp` | `nomarr.components.ml.inference.ml_embed_comp` |
| `nomarr.components.ml.ml_heads_comp` | `nomarr.components.ml.inference.ml_heads_comp` |
| `nomarr.components.ml.ml_head_pipeline_comp` | `nomarr.components.ml.inference.ml_head_pipeline_comp` |
| `nomarr.components.ml.segment_stats_comp` | `nomarr.components.ml.inference.ml_segment_stats_comp` |
| `nomarr.components.ml.ml_calibration_comp` | `nomarr.components.ml.calibration.ml_calibration_comp` |
| `nomarr.components.ml.calibration_state_comp` | `nomarr.components.ml.calibration.ml_calibration_state_comp` |
| `nomarr.components.ml.ml_vector_pool_comp` | `nomarr.components.ml.vectors.ml_vector_pool_comp` |
| `nomarr.components.ml.ml_vector_persist_comp` | `nomarr.components.ml.vectors.ml_vector_persist_comp` |
| `nomarr.components.ml.ml_vector_maintenance_comp` | `nomarr.components.ml.vectors.ml_vector_maintenance_comp` |
| `nomarr.components.ml.ml_vram_coordinator_comp` | `nomarr.components.ml.resources.ml_vram_coordinator_comp` |
| `nomarr.components.ml.ml_vram_probe_comp` | `nomarr.components.ml.resources.ml_vram_probe_comp` |
| `nomarr.components.ml.ml_capacity_probe_comp` | `nomarr.components.ml.resources.ml_capacity_probe_comp` |
| `nomarr.components.ml.ml_timing_comp` | `nomarr.components.ml.resources.ml_timing_comp` |
| `nomarr.components.ml.ml_worker_context_comp` | `nomarr.components.ml.resources.ml_worker_context_comp` |
| `nomarr.components.ml.ml_tier_selection_comp` | `nomarr.components.ml.resources.ml_tier_selection_comp` |

---

## Phases

### Phase 1: Update app bootstrap and non-ml components

- [x] Update imports in `nomarr/app.py` (`compute_model_suite_hash` from `onnx.ml_discovery_comp`) and `nomarr/components/platform/arango_bootstrap_comp.py` (`discover_heads_no_db` from `onnx.ml_discovery_comp`)
    **Notes:** Updated app.py line 116: `ml_discovery_comp` → `onnx.ml_discovery_comp`. Updated arango_bootstrap_comp.py line 370: same. Both were lazy imports inside function bodies.
- [x] Update imports in `nomarr/components/library/metadata_extraction_comp.py` (`compute_chromaprint` from `audio.ml_chromaprint_comp`; `load_audio_mono` from `audio.ml_audio_comp`), `nomarr/components/tagging/tagging_aggregation_comp.py` (`OPPONENT_MAP` from `onnx.ml_known_models_comp`), and `nomarr/components/tagging/tagging_reconstruction_comp.py` (`apply_minmax_calibration` from `calibration.ml_calibration_comp`; symbols from `inference.ml_heads_comp`)
    **Notes:** metadata_extraction_comp.py: 2 replacements (chromaprint_comp→audio.ml_chromaprint_comp, ml_audio_comp→audio.ml_audio_comp). tagging_aggregation_comp.py: 1 replacement (ml_known_models→onnx.ml_known_models_comp). tagging_reconstruction_comp.py: 2 replacements (ml_calibration_comp→calibration.ml_calibration_comp, ml_heads_comp→inference.ml_heads_comp).
- [x] Run `lint_project_backend(path="nomarr/components")` — fix any errors before continuing
    **Notes:** lint_project_backend(path="nomarr/components"): 0 errors, 39 files checked.

### Phase 2: Update services

- [x] Update imports in all 7 service files: `nomarr/services/domain/calibration_svc.py` (`calibration.ml_calibration_state_comp`, `onnx.ml_discovery_comp`); `nomarr/services/domain/vector_maintenance_svc.py` and `nomarr/services/domain/vector_search_svc.py` (`vectors.ml_vector_maintenance_comp`); `nomarr/services/infrastructure/calibration_download_svc.py` and `nomarr/services/infrastructure/config_svc.py` (`onnx.ml_discovery_comp`); `nomarr/services/infrastructure/ml_svc.py` (`onnx.ml_discovery_comp`, `resources.ml_vram_probe_comp`); `nomarr/services/infrastructure/worker_system_svc.py` (`resources.ml_capacity_probe_comp`, `resources.ml_tier_selection_comp`, `resources.ml_vram_coordinator_comp`)
    **Notes:** calibration_svc.py: 3 replacements (calibration_state_comp×2→calibration.ml_calibration_state_comp, ml_discovery_comp→onnx.ml_discovery_comp). vector_maintenance_svc.py + vector_search_svc.py: 1 each (ml_vector_maintenance_comp→vectors.ml_vector_maintenance_comp). calibration_download_svc.py + config_svc.py: 1 each (ml_discovery_comp→onnx.ml_discovery_comp). ml_svc.py: 3 (ml_discovery_comp×2→onnx.ml_discovery_comp, ml_vram_probe_comp→resources.ml_vram_probe_comp). worker_system_svc.py: 3 (ml_capacity_probe_comp→resources, ml_tier_selection_comp→resources, ml_vram_coordinator_comp→resources). Total: 12 replacements.
- [x] Run `lint_project_backend(path="nomarr/services")` — fix any errors before continuing
    **Notes:** lint_project_backend(path="nomarr/services"): 0 errors, 10 files checked.

### Phase 3: Update worker

- [x] Update all 9 lazy imports inside `nomarr/services/infrastructure/workers/discovery_worker.py`. All are inside function bodies — use `search_file_text` to locate each one before replacing. Affected old paths: `ml_onnx_cache` → `onnx.ml_cache`; `segment_stats_comp` → `inference.ml_segment_stats_comp`; `ml_audio_comp` → `audio.ml_audio_comp`; `ml_backend_onnx_comp` → `onnx.ml_session_comp`; `ml_worker_context_comp` → `resources.ml_worker_context_comp`; `ml_vram_coordinator_comp` → `resources.ml_vram_coordinator_comp`; `ml_onnx_base` → `onnx.ml_base`; `ml_vram_probe_comp` → `resources.ml_vram_probe_comp`; `ml_head_pipeline_comp` → `inference.ml_head_pipeline_comp`
    **Notes:** 13 occurrences across 12 unique patterns updated: ml_onnx_cache→onnx.ml_cache (×2, lines 27+442), segment_stats_comp→inference.ml_segment_stats_comp (line 76), ml_audio_comp→audio.ml_audio_comp (×2, lines 275+615), ml_backend_onnx_comp→onnx.ml_session_comp (line 280), ml_worker_context_comp→resources.ml_worker_context_comp (line 312), ml_vram_coordinator_comp import release_worker_promises→resources (×2, lines 318+609), ml_onnx_base→onnx.ml_base (line 441), ml_vram_probe_comp→resources.ml_vram_probe_comp (line 445), ml import ml_vram_coordinator_comp→resources.ml_vram_coordinator_comp (line 461), ml_head_pipeline_comp→inference (line 620).
- [x] Run `lint_project_backend(path="nomarr/services/infrastructure/workers")` — fix any errors before continuing
    **Notes:** lint_project_backend(path="nomarr/services/infrastructure/workers"): 0 errors, 1 file checked.

### Phase 4: Update workflows

- [x] Update imports in all 6 workflow files under `nomarr/workflows/calibration/`: each imports from `calibration_state_comp` (now `calibration.ml_calibration_state_comp`) and several additionally from `ml_calibration_comp` (now `calibration.ml_calibration_comp`) and `ml_discovery_comp` (now `onnx.ml_discovery_comp`)
    **Notes:** apply_calibration_wf.py: 2 replacements. calibration_loader_wf.py: 2 occurrences of calibration_state_comp→calibration.ml_calibration_state_comp. export_calibration_bundle_wf.py: 1 replacement. generate_calibration_wf.py: 3 replacements (calibration_state_comp, ml_calibration_comp, ml_discovery_comp). import_calibration_bundle_wf.py: 1+2 replacements (calibration_state_comp×1, ml_calibration_comp×2). write_calibrated_tags_wf.py: 2 replacements. Total: 12 replacements across 6 files.
- [x] Update imports in `nomarr/workflows/library/validate_library_tags_wf.py` (`onnx.ml_discovery_comp`), `nomarr/workflows/platform/promote_and_rebuild_vectors_wf.py` and `nomarr/workflows/platform/rebuild_vector_index_wf.py` (`vectors.ml_vector_maintenance_comp`), `nomarr/workflows/platform/register_ml_models_wf.py` (`onnx.ml_known_models_comp`, `onnx.ml_head` — and note `head_parts_from_path` is now public as of Part A Phase 1), and `nomarr/workflows/processing/process_file_wf.py` (`audio.ml_chromaprint_comp`, `audio.ml_audio_comp`, `inference.ml_backbone_embed_comp`, `onnx.ml_discovery_comp`, `inference.ml_head_pipeline_comp`, `onnx.ml_cache`, `resources.ml_timing_comp`, `vectors.ml_vector_persist_comp`)
    **Notes:** validate_library_tags_wf.py: 1 (ml_discovery_comp→onnx.ml_discovery_comp). promote_and_rebuild_vectors_wf.py: 1 (ml_vector_maintenance_comp→vectors). rebuild_vector_index_wf.py: 1 (same). register_ml_models_wf.py: 2 (ml_known_models→onnx.ml_known_models_comp, ml_onnx_head→onnx.ml_head). process_file_wf.py: 8 (chromaprint_comp→audio.ml_chromaprint_comp, ml_audio_comp→audio, ml_backbone_embed_comp→inference, ml_discovery_comp→onnx, ml_head_pipeline_comp→inference, ml_onnx_cache→onnx.ml_cache, ml_timing_comp→resources, ml_vector_persist_comp→vectors). Total: 13 replacements.
- [x] Run `lint_project_backend(path="nomarr/workflows")` — fix any errors before continuing
    **Notes:** lint_project_backend(path="nomarr/workflows"): 0 errors, 14 files checked.

### Phase 5: Update tests and final validation

- [x] Update imports in `tests/unit/components/ml/test_ml_capacity_probe_comp.py` (`resources.ml_capacity_probe_comp`) and `tests/unit/components/ml/test_ml_tier_selection_comp.py` (`resources.ml_capacity_probe_comp`, `resources.ml_tier_selection_comp`)
    **Notes:** test_ml_capacity_probe_comp.py: 4 occurrences of ml_capacity_probe_comp→resources.ml_capacity_probe_comp (1 import + 3 patch strings). test_ml_tier_selection_comp.py: 2 replacements (ml_capacity_probe_comp→resources, ml_tier_selection_comp→resources).
- [x] Update `nomarr/components/ml/__init__.py`: change all re-export sources from flat paths to new sub-package paths. Current `__all__` includes 18 symbols sourced from flat modules (`ml_audio_comp`, `ml_capacity_probe_comp`, `ml_calibration_comp`, `ml_tier_selection_comp`, `ml_vram_probe_comp`, `ml_discovery_comp`); update each import to the correct sub-package.
    **Notes:** Updated all 6 relative import sources in ml/__init__.py: .ml_audio_comp→.audio.ml_audio_comp, .ml_calibration_comp→.calibration.ml_calibration_comp, .ml_capacity_probe_comp→.resources.ml_capacity_probe_comp, .ml_discovery_comp→.onnx.ml_discovery_comp, .ml_tier_selection_comp→.resources.ml_tier_selection_comp, .ml_vram_probe_comp→.resources.ml_vram_probe_comp. __all__ unchanged (still exports the same 18 symbols).
- [x] Run `lint_project_backend()` (no path filter — full workspace). Zero errors is the only acceptable outcome.
    **Notes:** lint_project_backend() (full workspace): 0 errors, 78 files checked.
- [x] Verify no old flat-path references remain: run `search_for_pattern` for `from nomarr\.components\.ml\.(ml_onnx_|chromaprint_comp|segment_stats_comp|calibration_state_comp|ml_known_models[^_])` and confirm zero matches.

---

## Completion Criteria

- `lint_project_backend()` (full workspace) returns zero errors
- `lint-imports` (import-linter contracts) passes — no contract text changes needed since rules are layer-level only, but run to confirm
- All files outside `nomarr/components/ml/` reference only the new sub-package paths
- `nomarr/components/ml/__init__.py` re-exports the same 18+ public symbols as before, sourced from the new paths
- Pattern search confirms zero remaining old flat-path references

## References

- Prerequisite plan: `TASK-ml-reorganize-A-structure.md`
