# ML ONNX

ONNX Runtime session management, model discovery, and caching — the execution substrate for all ML inference.

## Responsibilities

- Discover backbone and head `.onnx` models from filesystem and database
- Create and manage ONNX Runtime InferenceSessions (CPU and GPU)
- Cache loaded sessions via `ONNXModelCache` (warm/cold lifecycle)
- Handle BFC arena OOM recovery with automatic CPU fallback
- Provide base class for all model wrappers with device transition logic

## Key Modules

 | Module | Purpose |
 | -------- | ---------- |
 | `ml_base` | Abstract `BaseONNXModel` — session lifecycle, load/unload, VRAM coordinator integration, BFC OOM self-healing |
 | `ml_backbone` | `ONNXBackboneModel` — waveform → embedding extraction with per-backbone preprocessing |
 | `ml_head` | `ONNXHeadModel` — embedding → classification/regression scores with tensor metadata resolution at load time |
 | `ml_cache` | `ONNXModelCache` — grouped container, warm/cold switching loads/unloads all sessions at once |
 | `ml_discovery_comp` | Filesystem + DB model discovery, `HeadInfo` metadata, model suite hashing, versioned tag keys |
 | `ml_known_models_comp` | Known model output defaults and semantic opponent map derivation for conflict suppression |
 | `ml_session_comp` | Low-level session creation (`create_session`), CUDA provider options, batched inference runner |
 | `ml_constants` | Shared constants |

## Patterns

- **Session caching:** `ONNXModelCache` discovers all models at construction but loads no sessions until `warm = True`. Setting `warm = False` unloads everything (idle eviction).
- **BFC OOM self-healing:** `BaseONNXModel.run()` catches CUDA BFC arena OOM errors, falls back to CPU, and logs the transition — no manual intervention needed.
- **VRAM coordinator integration:** `load()` checks with the fleet-wide VRAM coordinator before allocating GPU memory; raises `VramFitError` if headroom is exhausted.
- **DB-sourced metadata:** Labels, release dates, and configuration come from `ml_models`/`ml_model_outputs` collections — filesystem-only discovery is limited to probing.

## Dependencies

- **Upstream:** Called by `inference/` (embedding + head pipeline), `resources/` (probing)
- **Downstream:** Calls `persistence/` for model metadata, `resources/` for VRAM coordination
- **External:** `onnxruntime`
