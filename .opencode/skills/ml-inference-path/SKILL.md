---
name: ml-inference-path
description: ONNX model lifecycle, inference hot path, VRAM coordination, and async PostgreSQL audit for the Nomarr ML pipeline. Covers BaseONNXModel, ONNXModelCache, VRAM promises, OOM recovery, head pipeline parallelism, and the asyncio.run() bridges in the inference hot path. Load when working on ML inference, ONNX session management, VRAM coordination, the process_file workflow, or the sync-PostgreSQL migration.
---

# ML Inference Path

## Mental Model

Nomarr's ML pipeline uses ONNX Runtime for audio classification. Models (backbones + heads) are loaded into an `ONNXModelCache` at worker startup via the `warm = True` setter. During inference, audio files are processed by `process_file_workflow`, which computes backbone embeddings (sync ONNX C++) and runs head predictions in parallel via a `ThreadPoolExecutor`. The ONNX C++ kernels release the GIL, giving real CPU parallelism.

The key architectural tension: `BaseONNXModel.run()` is `async def` **solely** for the OOM recovery path (a rare BFC arena error that writes corrected VRAM limits to DB). The hot path — successful ONNX inference — is 100% sync C++. Two `asyncio.run()` bridges exist in the inference pipeline only because `run()` is async.

**Known bugs:** Several coroutine-discard bugs exist where `async` functions are called without `await` in sync contexts (marked with `# type: ignore[unused-coroutine]`). The VRAM coordinator's primary gating function is effectively non-functional due to a missing `await` in `load()`.

## Coverage

**Documented:** BaseONNXModel lifecycle (load/unload/device/run), ONNXModelCache warm/device management, VRAM coordinator functions and their async nature, OOM recovery path, head pipeline concurrency model, process_file_workflow async call inventory, all asyncio.run() bridges in the ML path, known coroutine-discard bugs

**Not yet documented:** Subclass-specific _run() implementations (backbone preprocessing, head batching), VRAM probe subsystem, audio preprocessing pipeline, calibration workflow integration

**Last extended:** 2026-07-18

## Key Files

| Area | Canonical File |
|------|---------------|
| ONNX model lifecycle (load/unload/device/run) | `nomarr/components/ml/onnx/ml_base.py` |
| Model cache (warm/device/discovery) | `nomarr/components/ml/onnx/ml_cache.py` |
| Head model subclass | `nomarr/components/ml/onnx/ml_head.py` |
| Backbone model subclass | `nomarr/components/ml/onnx/ml_backbone.py` |
| Head pipeline concurrency | `nomarr/components/ml/inference/ml_head_pipeline_comp.py` |
| Backbone embedding computation | `nomarr/components/ml/inference/ml_backbone_embed_comp.py` |
| VRAM promise coordinator | `nomarr/components/ml/resources/ml_vram_coordinator_comp.py` |
| OOM recovery helpers | `nomarr/components/ml/resources/ml_vram_oom_helper_comp.py` |
| Worker context registry | `nomarr/components/ml/resources/ml_worker_context_comp.py` |
| File processing workflow | `nomarr/workflows/processing/process_file_wf.py` |
| Discovery worker (caller) | `nomarr/services/infrastructure/workers/discovery_worker.py` |
| Tag extraction worker (caller) | `nomarr/services/infrastructure/workers/tag_extraction_worker.py` |

## Critical Invariants

1. **`BaseONNXModel._run()` is sync and must remain sync.** It calls ONNX Runtime C++ which releases the GIL. Never make it async.
2. **`BaseONNXModel.run()` wraps `_run()` with OOM recovery.** The recovery path writes to DB (currently async). Any change to the recovery path must not add latency to the hot path.
3. **ONNX inference happens inside `ThreadPoolExecutor` workers.** The `asyncio.run(m.run(e))` bridges on L73 of `ml_head_pipeline_comp.py` and L77 of `ml_backbone_embed_comp.py` create a new event loop per call. This is the hot path — any added overhead here is multiplied by every head × every file.
4. **VRAM coordinator functions (`register_vram_promise`, `release_vram_promise`) are called from `BaseONNXModel.load()` and `unload()`. They must not be called per-inference — only per model load/unload.
5. **`ONNXModelCache.warm = True` must be called before any inference.** The `process_file_workflow` does this defensively on L94-95. If the cache is not warm, inference will crash.
6. **Worker context (`ml_worker_context_comp`) must be registered before model loading.** `load()` reads it on L103 of `ml_base.py`. Without it, VRAM coordination and OOM recovery are skipped (graceful degradation).

## Known Bugs (2026-07-18)

### BUG 1: `register_vram_promise` not awaited in `load()`
- **File:** `ml_base.py:120`
- **Impact:** VRAM promises are never written to DB. `registered` is a coroutine (always truthy), so `VramFitError` is never raised. Fleet VRAM coordination is non-functional.
- **Fix:** Add `await` before the call.

### BUG 2: `device` setter calls `self.load(value)` without `await`
- **File:** `ml_base.py:178, 184`
- **Impact:** Setting `model.device = "gpu"` discards the `load()` coroutine. Model session is never created. `_device` remains `None`.
- **Fix:** Either make `load()` sync (preferred, for sync migration) or restructure the setter to be async-capable.

### BUG 3: `unload()` calls `release_vram_promise` without `await`
- **File:** `ml_base.py:150`
- **Impact:** Coroutine discarded, VRAM promises never released on unload. (Moot while BUG 1 also prevents promise creation.)
- **Fix:** Add `await` or make `release_vram_promise` sync.

### BUG 4: `warm` setter cascades into BUG 2
- **File:** `ml_cache.py:153`
- **Impact:** `cache.warm = True` calls `m.device = self._device`, which triggers BUG 2. No models are loaded.
- **Fix:** Same as BUG 2 — once `device` setter is fixed, this is resolved.

## Sources

- Log entry: L84 (2026-07-18) — ML inference path async audit
- Source code audit of all files listed in Key Files above
