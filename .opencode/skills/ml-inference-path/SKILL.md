---
name: ml-inference-path
description: ONNX model lifecycle, inference hot path, and VRAM coordination for the Nomarr ML pipeline. Covers BaseONNXModel, ONNXModelCache, VRAM promises, OOM recovery, and head/backbone parallelism. Load when working on ML inference, ONNX session management, VRAM coordination, or the process_file workflow.
---

# ML Inference Path

## Mental Model

Nomarr's ML pipeline uses ONNX Runtime for audio classification. Models (backbones + heads) are loaded into an `ONNXModelCache` at worker startup via the `warm = True` setter. During inference (`process_file_workflow`), audio files are processed by computing backbone embeddings and running head predictions in parallel via `ThreadPoolExecutor`s. The ONNX C++ kernels release the GIL, giving real CPU parallelism.

**The entire inference path is synchronous.** `BaseONNXModel.load`/`unload`/`device`/`run` are sync; VRAM coordination, worker-context lookup, and the OOM self-heal DB write are sync. There are **no** `async def`/`await`/`asyncio.run()` bridges anywhere in `nomarr/components/ml/{onnx,inference,resources}` (verified). A prior "async PostgreSQL migration" is complete — this is sync-first code and must stay sync.

## Coverage

**Documented:** BaseONNXModel lifecycle (load/unload/device/run), ONNXModelCache warm/device management, VRAM coordinator sync functions, sync OOM self-heal path, head/backbone parallelism via `ThreadPoolExecutor`, process_file_workflow hot path.
**Not yet documented:** Subclass-specific `_run()` implementations (backbone preprocessing, head batching), VRAM probe subsystem, audio preprocessing pipeline, calibration workflow integration.
**Last extended:** 2026-09-04

## Key Files

| Area | Canonical File |
|------|---------------|
| ONNX model lifecycle (load/unload/device/run) | `nomarr/components/ml/onnx/ml_base.py` |
| Model cache (warm/device/discovery) | `nomarr/components/ml/onnx/ml_cache.py` |
| Head model subclass | `nomarr/components/ml/onnx/ml_head.py` |
| Backbone model subclass | `nomarr/components/ml/onnx/ml_backbone.py` |
| ONNX session creation (create_session) | `nomarr/components/ml/onnx/ml_session_comp.py` |
| Model discovery (filesystem + DB) | `nomarr/components/ml/onnx/ml_discovery_comp.py` |
| Head pipeline parallelism | `nomarr/components/ml/inference/ml_head_pipeline_comp.py` |
| Backbone embedding computation | `nomarr/components/ml/inference/ml_backbone_embed_comp.py` |
| VRAM promise coordinator | `nomarr/components/ml/resources/ml_vram_coordinator_comp.py` |
| OOM recovery helpers | `nomarr/components/ml/resources/ml_vram_oom_helper_comp.py` |
| Worker context registry | `nomarr/components/ml/resources/ml_worker_context_comp.py` |
| File processing workflow | `nomarr/workflows/processing/process_file_wf.py` |
| Discovery worker (caller) | `nomarr/services/infrastructure/workers/discovery_worker.py` |
| Tag extraction worker (caller) | `nomarr/services/infrastructure/workers/tag_extraction_worker.py` |

## Critical Invariants

1. **The ML inference path is synchronous** — `load`/`unload`/`device` setter/`run` and all VRAM/coordinator/OOM helpers are `def`, not `async def`. Do not reintroduce async here; there is no event loop in the hot path.
2. **`BaseONNXModel._run()` is sync and must remain sync.** It calls ONNX Runtime C++ which releases the GIL. External callers use `run()`.
3. **`run()` wraps `_run()` with a sync BFC-arena OOM self-heal loop.** On a GPU BFC OOM it parses the requested bytes, updates the DB VRAM limit (`update_model_vram_from_oom`), unloads, and reloads on GPU (falling back to CPU via `VramFitError` if the fleet has no headroom). Non-BFC errors and CPU-device errors propagate immediately.
4. **ONNX inference happens inside `ThreadPoolExecutor` workers** (`_HEAD_POOL` in `ml_head_pipeline_comp.py`; per-call pool in `ml_backbone_embed_comp.py`). The hot path is real threads, not `asyncio.run`.
5. **VRAM coordinator functions (`register_vram_promise`, `release_vram_promise`) are called from `BaseONNXModel.load()` / `unload()`** — never per-inference, only per model load/unload. They are synchronous.
6. **`ONNXModelCache.warm = True` must be set before any inference.** `process_file_workflow` does this defensively (`if not cache.warm: cache.warm = True`). If no worker context is registered (probe processes, tests), the coordinator check is skipped and models load directly.
7. **Worker context (`ml_worker_context_comp`) must be registered before model loading.** `load()` reads it on the GPU path; without it, VRAM coordination and OOM self-heal are skipped (graceful degradation). `unload()` also reads it to release GPU promises.
8. **`BaseONNXModel.device` setter** unloads then reloads on the new device, re-fetching the VRAM limit from DB so OOM-updated values are respected; same-device set is a no-op; GPU rejection falls back to CPU and re-raises `VramFitError`.

## Resolved bugs (2026-07-18 async audit) — DO NOT reintroduce

A prior audit reported coroutine-discard bugs where `async` functions were called without `await` in sync contexts: `register_vram_promise` not awaited in `load()`, the `device` setter calling `load()` without await, `unload()` calling `release_vram_promise` without await, and the cache `warm` setter cascading into those. **These are all resolved by the sync migration** — every one of those functions is now synchronous (`ml_base.py` `load`/`unload`/`device.setter`, `ml_cache.py` `warm.setter`), so no `await` is possible or needed, and VRAM promises are registered/released correctly. Treat any code that makes these async again as a regression.

## Sources

- `nomarr/components/ml/onnx/ml_base.py`, `ml_cache.py`, `ml_head.py`, `ml_backbone.py`, `ml_session_comp.py`, `ml_discovery_comp.py`
- `nomarr/components/ml/inference/ml_head_pipeline_comp.py`, `ml_backbone_embed_comp.py`
- `nomarr/components/ml/resources/ml_vram_coordinator_comp.py`, `ml_vram_oom_helper_comp.py`, `ml_worker_context_comp.py`
- `nomarr/workflows/processing/process_file_wf.py`
- `nomarr/services/infrastructure/workers/discovery_worker.py`, `tag_extraction_worker.py`
- Related skills: `ml-output-identity`, `ml-embedding-stream-wiring`, `per-song-embedding-cardinality`
