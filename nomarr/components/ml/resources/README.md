# ML Resources

GPU/VRAM coordination, capacity probing, and execution tier selection for the ML worker fleet.

## Responsibilities

- Probe per-model VRAM requirements via isolated GPU measurements
- Coordinate fleet-wide VRAM promises (atomic register/release via ArangoDB transactions)
- Select execution tier based on resource budgets (GPU memory, RAM, worker count)
- Provide process-local worker context registry for VRAM coordinator access
- Build timing summaries for per-file processing diagnostics

## Key Modules

| Module | Purpose |
|--------|----------|
| `ml_vram_coordinator_comp` | Fleet-wide VRAM promise management — atomic register/release via DB, live GPU telemetry |
| `ml_vram_probe_comp` | Per-model VRAM measurement (load + inference on GPU), OOM correction, CUDA context warmup |
| `ml_capacity_probe_comp` | One-time capacity estimation (backbone VRAM + worker RAM), DB-locked to prevent duplicate probes |
| `ml_tier_selection_comp` | Deterministic tier selection (Tier 0–4) based on VRAM/RAM budgets and worker count |
| `ml_timing_comp` | Compact per-file timing summary strings for logging |
| `ml_worker_context_comp` | Process-local registry mapping worker identity to DB handle for VRAM coordinator access |

## Patterns

- **VRAM coordination:** Workers register promises before loading GPU models; the coordinator rejects if headroom is exhausted. Promises are released on unload and on worker death.
- **Tiered execution:** 5 tiers from fast-path (cached, multi-worker, GPU) to refuse (insufficient resources). Selection is deterministic and owned by the service layer.
- **Probe-once architecture:** Capacity probe runs once per model set hash, protected by a DB lock. Other workers poll for completion (5s interval, 120s timeout).
- **OOM correction:** When a BFC arena OOM occurs at runtime, the stored VRAM measurement is bumped by 25% and persisted so future loads use accurate limits.

## Dependencies

- **Upstream:** Called by `onnx/` (VRAM checks during load), `services/` (tier selection, capacity probe)
- **Downstream:** Calls `persistence/` for meta keys, vram_promises collection, and GPU telemetry
