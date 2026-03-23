# ML Inference

Embedding computation, head predictions, and score decision logic — the core of the ML tagging pipeline.

## Responsibilities

- Run backbone models to extract embeddings from preprocessed audio
- Run classification and regression head models on embeddings
- Apply cascade-based tier decisions (high/medium/low confidence)
- Compute segment-level statistics for stability gating
- Parallelize backbone and head inference via thread pools

## Key Modules

| Module | Purpose |
|--------|----------|
| `ml_backbone_embed_comp` | Multi-backbone embedding computation with thread-parallel execution when ≥2 backbones |
| `ml_embed_comp` | Waveform segmentation, segment-level scoring, and score pooling (mean/median/trimmed_mean) |
| `ml_head_pipeline_comp` | Head prediction pipeline with reusable thread pool, versioned tag key building |
| `ml_heads_comp` | Core decision logic: multilabel cascade, binary multiclass, regression; tier assignment with stability gating |
| `ml_segment_stats_comp` | Per-label mean/std/min/max statistics across audio segments |

## Patterns

- **GIL-free parallelism:** ONNX C++ kernels release the GIL, so `ThreadPoolExecutor` gives real CPU parallelism for both backbone and head inference.
- **Cascade tier assignment:** Labels pass through confidence threshold → ratio → gap gates to earn high/medium/low tiers. Segment-level standard deviation further gates unstable predictions.
- **Pre-resolved closures:** Predictor closures are built on the main thread to avoid per-thread cache lookup and lock contention inside the pool workers.
- **Stability gating:** High segment variance downgrades or removes tier assignment, preventing unreliable tags from reaching users.

## Dependencies

- **Upstream:** Called by `workflows/` (ML tagging pipeline)
- **Downstream:** Calls `onnx/` (session/cache), `audio/` (preprocessing), `helpers/` for DTOs
