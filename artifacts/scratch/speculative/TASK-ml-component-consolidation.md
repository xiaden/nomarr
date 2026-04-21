# Task: ML Component Layer Consolidation

## Problem Statement

The `nomarr/components/ml/` directory contains 27 files (26 listed in the task + `ml_backend_onnx_comp.py`). Most are 80-150 line single-concern modules that are too granular to navigate efficiently. The goal is to reduce the file count to ~13 logically grouped files by merging files that share the same concern boundary, change at the same rate, and have no circular import risk. Files that are volatile or conceptually distinct must remain separate.

Design constraints established by research:

- No circular imports exist within the ML layer today. All intra-layer imports flow one direction.
- External callers (workflows, services, other components) import directly from specific modules, not only through `__init__.py`. Every caller must be updated when a module is renamed or merged.
- `ml_preprocess_comp.py` is Essentia-restricted and has a distinct concern from audio I/O; it stays separate.
- `ml_vector_maintenance_comp.py` (index management/hot-cold drain) has a different change rate from vector persistence; it stays separate.
- `ml_tier_selection_comp.py` is a pure algorithm with no dependencies and can be merged with resource probing into a single planning module.
- The ONNX base classes (`ml_onnx_base`, `ml_onnx_backbone`, `ml_onnx_head`) must not be merged with business-logic inference code.

## Target File Map (27 → 13)

 | New file | Source files merged |
 | --- | --- |
 | `ml_onnx_base.py` (expanded) | absorbs `ml_backend_onnx_comp.py` + `ml_onnx_types.py` |
 | `ml_onnx_models.py` | `ml_onnx_backbone.py` + `ml_onnx_head.py` + `ml_inference_comp.py` |
 | `ml_model_catalog.py` | `ml_onnx_cache.py` + `ml_discovery_comp.py` |
 | `ml_preprocess_comp.py` | unchanged |
 | `ml_audio_io.py` | `ml_audio_comp.py` + `chromaprint_comp.py` |
 | `ml_segment_ops.py` | `ml_embed_comp.py` + `segment_stats_comp.py` |
 | `ml_embedding_pipeline.py` | `ml_backbone_embed_comp.py` + `ml_timing_comp.py` |
 | `ml_head_scoring.py` | `ml_head_pipeline_comp.py` + `ml_heads_comp.py` |
 | `ml_vram_context.py` | `ml_vram_coordinator_comp.py` + `ml_worker_context_comp.py` |
 | `ml_resource_probes.py` | `ml_vram_probe_comp.py` + `ml_capacity_probe_comp.py` + `ml_tier_selection_comp.py` |
 | `ml_vector_ops.py` | `ml_vector_pool_comp.py` + `ml_vector_persist_comp.py` |
 | `ml_vector_maintenance_comp.py` | unchanged |
 | `ml_calibration.py` | `ml_calibration_comp.py` + `calibration_state_comp.py` |

## Phases

### Phase 1: ONNX infrastructure consolidation (stable base layer)

- [ ] Absorb `ml_backend_onnx_comp.py` and `ml_onnx_types.py` into the expanded `ml_onnx_base.py`, then delete the two source files.
  **Rationale:** Session factory (`create_session`, `is_available`, `get_version`) and sidecar types (`Sidecar`, `MODEL_SUITE_VERSION`) are implementation details of the base ONNX session lifecycle. All three files are very stable and change only when ONNX Runtime fundamentals change.
  **Intra-layer callers updated:** `ml_onnx_head.py` and `ml_onnx_backbone.py` import `Sidecar`/`MODEL_SUITE_VERSION` from `ml_onnx_types` — both will be merged in the next step so these imports dissolve automatically.
  **`ml_discovery_comp.py`** imports `MODEL_SUITE_VERSION, Sidecar` from `ml_onnx_types` — update to import from `ml_onnx_base`.
  **External callers updated:** `discovery_worker.py` imports `ml_backend_onnx_comp.is_available` — update to `ml_onnx_base.is_available`.
  **`__init__.py`:** No changes needed; neither source file is currently exported.

- [ ] Create `ml_onnx_models.py` by merging `ml_onnx_backbone.py`, `ml_onnx_head.py`, and `ml_inference_comp.py`, then delete the three source files.
  **Rationale:** `ONNXBackboneModel` and `ONNXHeadModel` are symmetrical ONNX model wrappers. `_run_in_batches` is a private batch-runner used only by these two classes — folding it in removes a cross-module private-symbol import. All three files change at the same rate (model architecture changes).
  **No circular risk:** backbone and head do not import from each other; inference_comp has no intra-layer imports.
  **Intra-layer callers updated:** `ml_onnx_cache.py` imports `ONNXBackboneModel` from `ml_onnx_backbone` and `ONNXHeadModel` from `ml_onnx_head` — update both to `ml_onnx_models`. `ml_head_pipeline_comp.py` imports `ONNXHeadModel` from `ml_onnx_head` — update to `ml_onnx_models`.
  **`__init__.py`:** No changes needed; none of the three source modules are currently exported.

- [ ] Create `ml_model_catalog.py` by merging `ml_onnx_cache.py` and `ml_discovery_comp.py`, then delete the two source files.
  **Rationale:** `ONNXModelCache` calls `discover_backbone_models` and `discover_head_models` at construction time; the cache and the discovery logic are tightly coupled and change together when the model directory structure changes. Merging eliminates an intermediate internal import.
  **No circular risk:** discovery only imports from `ml_onnx_base`; neither file imported from the other directly.
  **Intra-layer callers updated:** `ml_vram_probe_comp.py` imports `discover_backbone_models, discover_head_models` from `ml_discovery_comp` — update to `ml_model_catalog`.
  **External callers updated (direct module imports):** `process_file_wf.py` imports `ONNXModelCache` from `ml_onnx_cache` and `compute_model_suite_hash` from `ml_discovery_comp`; `discovery_worker.py` imports `ONNXModelCache`, `DevicePlacement` (the latter stays in `ml_onnx_base`); `ml_svc.py` imports `discover_backbones` and `discover_heads` from `ml_discovery_comp`, and `HeadInfo` from `helpers/dto/ml_head_dto`; `write_calibrated_tags_wf.py`, `generate_calibration_wf.py`, `apply_calibration_wf.py`, `validate_library_tags_wf.py`, `calibration_download_svc.py`, `config_svc.py`, `calibration_svc.py`, `arango_bootstrap_comp.py` all import from `ml_discovery_comp` — all update to `ml_model_catalog`.
  **`__init__.py`:** Update `compute_model_suite_hash` source from `ml_discovery_comp` → `ml_model_catalog`.

### Phase 2: Audio and inference pipeline consolidation

- [ ] Create `ml_audio_io.py` by merging `ml_audio_comp.py` and `chromaprint_comp.py`, then delete the two source files.
  **Rationale:** Both are audio I/O utilities with no ML inference. Both are Essentia-backed and almost never change except when the audio loading pipeline changes. `compute_chromaprint` sits alongside `load_audio_mono` naturally — both are "read audio → produce representation".
  **No circular risk:** neither file imports from the other.
  **External callers updated:** `process_file_wf.py` imports from both modules separately; update to `ml_audio_io`. `metadata_extraction_comp.py` imports `compute_chromaprint` and `load_audio_mono` from their respective modules; update to `ml_audio_io`. `discovery_worker.py` imports `set_stop_event` and `shutdown_audio_loader` from `ml_audio_comp`; update to `ml_audio_io`.
  **`__init__.py`:** Update `AudioLoadCrashError`, `AudioLoadShutdownError`, `load_audio_mono`, `set_stop_event`, `should_skip_short`, `shutdown_audio_loader` source from `ml_audio_comp` → `ml_audio_io`.

- [ ] Create `ml_segment_ops.py` by merging `ml_embed_comp.py` and `segment_stats_comp.py`, then delete the two source files.
  **Rationale:** `segment_waveform`, `score_segments`, and `pool_scores` (in `ml_embed_comp`) and `compute_segment_stats` (in `segment_stats_comp`) all operate on the same data structure: a 2-D `[num_segments, dim]` array. `segment_stats_comp` is a 30-line single-function file that belongs alongside the pooling and scoring operations.
  **No circular risk:** `ml_embed_comp` has no intra-layer imports; `segment_stats_comp` has none either.
  **Intra-layer callers updated:** `ml_head_pipeline_comp.py` imports `pool_scores` from `ml_embed_comp` — update to `ml_segment_ops`. `ml_vector_pool_comp.py` imports `pool_scores` from `ml_embed_comp` — update to `ml_segment_ops`.
  **External callers updated:** `discovery_worker.py` imports `compute_segment_stats` from `segment_stats_comp` — update to `ml_segment_ops`.
  **`__init__.py`:** No changes needed; neither source module is currently exported.

- [ ] Create `ml_embedding_pipeline.py` by merging `ml_backbone_embed_comp.py` and `ml_timing_comp.py`, then delete the two source files.
  **Rationale:** `compute_backbone_embeddings` is the entry point that triggers backbone inference across all backbones, and `build_timing_summary` is a formatting utility called immediately after in the same workflow. They are always used together, change together, and `ml_timing_comp.py` is a ~35-line single-function file.
  **No circular risk:** neither file imports from the other.
  **External callers updated:** `process_file_wf.py` imports `compute_backbone_embeddings` from `ml_backbone_embed_comp` and `build_timing_summary` from `ml_timing_comp` — both update to `ml_embedding_pipeline`.
  **`__init__.py`:** No changes needed; neither source module is currently exported.

- [ ] Create `ml_head_scoring.py` by merging `ml_head_pipeline_comp.py` and `ml_heads_comp.py`, then delete the two source files.
  **Rationale:** `ml_heads_comp.py` contains the decision logic (`Cascade`, `HeadSpec`, `HeadDecision`, `run_head_decision`) and `ml_head_pipeline_comp.py` contains the execution mechanics (`run_heads`, `run_single_head`, `shutdown_head_pool`). The pipeline directly calls `run_head_decision`; the two files form a single responsibility: turning raw ONNX head outputs into tagged decisions. They always change together when the scoring system evolves.
  **No circular risk:** `ml_head_pipeline_comp` imports from `ml_heads_comp`, but not vice-versa; merging dissolves this dependency.
  **External callers updated:** `process_file_wf.py` imports `run_heads` from `ml_head_pipeline_comp` — update to `ml_head_scoring`. `discovery_worker.py` imports `shutdown_head_pool` from `ml_head_pipeline_comp` — update to `ml_head_scoring`. `tagging_reconstruction_comp.py` imports from both `ml_heads_comp` and `ml_calibration_comp` — update `ml_heads_comp` import to `ml_head_scoring`.
  **`__init__.py`:** No changes needed; neither source module is currently exported.

### Phase 3: Resource management consolidation

- [ ] Create `ml_vram_context.py` by merging `ml_vram_coordinator_comp.py` and `ml_worker_context_comp.py`, then delete the two source files.
  **Rationale:** `ml_worker_context_comp.py` is the process-local registry that stores `(db, worker_id)` for each worker process. `ml_vram_coordinator_comp.py` provides the fleet-wide VRAM promise tracking functions that read from that registry (via `BaseONNXModel`). Together they form the VRAM coordination infrastructure — a unit that changes when the GPU management strategy changes.
  **No circular risk:** neither file imports from the other; `ml_onnx_base` imports from `ml_worker_context_comp`, not the other way around.
  **External callers updated:** `discovery_worker.py` imports `register_worker_context` from `ml_worker_context_comp` and `release_worker_promises` from `ml_vram_coordinator_comp` (multiple call sites) — all update to `ml_vram_context`. `worker_system_svc.py` imports `release_worker_promises` from `ml_vram_coordinator_comp` — update to `ml_vram_context`.
  **`__init__.py`:** No changes needed; neither source module is currently exported.

- [ ] Create `ml_resource_probes.py` by merging `ml_vram_probe_comp.py`, `ml_capacity_probe_comp.py`, and `ml_tier_selection_comp.py`, then delete the three source files.
  **Rationale:** These three files form a self-contained planning pipeline: (1) probe measures VRAM per model, (2) capacity probe combines VRAM + RAM measurements into a `CapacityEstimate`, (3) tier selection converts that estimate into an `ExecutionTier` + worker count decision. All three change together when the GPU resource strategy changes. `ml_vram_probe_comp` only uses `ml_model_catalog` and `ml_onnx_base`; `ml_tier_selection_comp` is a pure function with no side effects and no intra-layer imports.
  **No circular risk:** the three files do not import from each other.
  **External callers updated:** `worker_system_svc.py` imports `CapacityEstimate`, `get_or_run_capacity_probe`, `compute_model_set_hash`, `invalidate_capacity_estimate` from `ml_capacity_probe_comp` and `ExecutionTier`, `TierConfig`, `TierSelection`, `select_execution_tier` from `ml_tier_selection_comp` — all update to `ml_resource_probes`. `ml_svc.py` imports `clear_model_vram_measurements` from `ml_vram_probe_comp` — update to `ml_resource_probes`. `discovery_worker.py` imports `has_model_vram_measurements`, `probe_all_models` from `ml_vram_probe_comp` — update to `ml_resource_probes`.
  **`__init__.py`:** Update sources for `CapacityEstimate`, `compute_model_set_hash`, `get_or_run_capacity_probe`, `invalidate_capacity_estimate`, `ExecutionTier`, `TierConfig`, `TierSelection`, `select_execution_tier`, `parse_oom_requested_bytes`, `update_model_vram_from_oom` to `ml_resource_probes`.

### Phase 4: Vector and calibration consolidation

- [ ] Create `ml_vector_ops.py` by merging `ml_vector_pool_comp.py` and `ml_vector_persist_comp.py`, then delete the two source files.
  **Rationale:** `ml_vector_persist_comp.py` imports `pool_embedding_for_storage` and `get_embedding_dimension` directly from `ml_vector_pool_comp.py` — a tight dependency. The full pipeline is: pool segment embeddings → serialize as a track-level vector → persist to ArangoDB. These two steps belong together. Both are low-volatility DB write operations.
  **No circular risk:** `ml_vector_persist_comp` imports from `ml_vector_pool_comp`, not vice-versa; merging dissolves this.
  **External callers updated:** `process_file_wf.py` imports `persist_backbone_vector` from `ml_vector_persist_comp` — update to `ml_vector_ops`.
  **`__init__.py`:** No changes needed; neither source module is currently exported.

- [ ] Create `ml_calibration.py` by merging `ml_calibration_comp.py` and `calibration_state_comp.py`, then delete the two source files.
  **Rationale:** `ml_calibration_comp.py` contains calibration computation (generate, apply, import/export) and `calibration_state_comp.py` contains calibration state persistence (save, load, update, convergence). Both deal exclusively with calibration data and are always imported together by the same workflow and service files.
  **No circular risk:** neither file imports from the other.
  **External callers updated:** All calibration workflows (`import_calibration_bundle_wf.py`, `write_calibrated_tags_wf.py`, `generate_calibration_wf.py`, `calibration_loader_wf.py`, `export_calibration_bundle_wf.py`, `apply_calibration_wf.py`) import from one or both source modules — update all imports to `ml_calibration`. `calibration_svc.py` imports from both — update to `ml_calibration`. `tagging_reconstruction_comp.py` imports `apply_minmax_calibration` — update to `ml_calibration`.
  **`__init__.py`:** Update `apply_minmax_calibration` and `save_calibration_sidecars` source from `ml_calibration_comp` → `ml_calibration`.

### Phase 5: Verification

- [ ] Run `lint_project_backend` on `nomarr/components/ml/` and fix any import errors before proceeding.
- [ ] Run `lint_project_backend` on the full workspace to catch broken imports in workflows, services, and other component packages.
- [ ] Run `lint_project_backend` on `nomarr/` (all layers) and confirm zero errors.

## Completion Criteria

- File count in `nomarr/components/ml/` is reduced from 27 to 13 (the 10 merged destination files + `ml_preprocess_comp.py` + `ml_vector_maintenance_comp.py` + `__init__.py`).
- All 13 destination modules import cleanly with no `ImportError` at runtime.
- `lint_project_backend` reports zero errors across the entire workspace.
- `__init__.py` public API is unchanged: all 18 symbols in `__all__` still resolve correctly from their new source modules.
- All workflows, services, and non-ML components that previously imported directly from the old module names now import from the new module names.
- No two merged files had fundamentally different change rates (verified by rationale in each step).
- Circular import risk was assessed for each merge and confirmed absent.
