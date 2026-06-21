# ADR-038: Canonical int8 temporal embedding streams for post-hoc segmentation

**Status:** Accepted  
**Date:** 2026-06-20  
**Tags:** vector-storage, int8-stream, segmentation, backbone-embeddings  
**Source Log:** agent#L49  

## Context

Nomarr currently stores only pooled backbone embedding vectors per song (one 1280d float64 vector per backbone per song). The full temporal patch stream is computed during the audio→ONNX pipeline, pooled, and then discarded. This means any change to segmentation strategy (pooling method, thresholds, PTC vs CTP pathway) requires re-running the full pipeline on raw audio — the most expensive operation in the system.

Recent analysis confirmed that int8 quantization of effnet 1280d embeddings preserves ranking virtually perfectly (Spearman ρ=0.9996, Recall@100=0.99) versus float32, and ArangoDB 3.12 accepts integer arrays for APPROX_NEAR_COSINE ANN search. The full patch stream for 40k songs would require ~7.3 GB in int8 vs ~29 GB in float32 — the int8 cost is high but feasible, while float32 is prohibitive.

Independently, DD-canonical-raw-output-stream-persistence already established the pattern of storing per-output head score streams as canonical artifacts, but uses float lists. The same int8 technique applies to head softmax outputs (12 binary heads × 2 scores × 140 patches = ~3.4 KB/song in int8 vs 13 KB in float32).

Together, int8 streams for both backbone embeddings and head outputs would make segmentation a fully post-hoc, user-configurable operation requiring only a vector index rebuild — no audio I/O, no ONNX inference.

## Decision

Adopt canonical int8 temporal stream storage for both backbone embeddings and classifier head outputs:

1. **Backbone embedding streams**: Store the full per-patch effnet/musicnn output as int8 arrays in the DB (`patches_emb` field: `[[int8 × 1280] × N]`). The pooled vector used for ANN search becomes a derived artifact, recomputed from the stored stream when segmentation changes.

2. **Head output streams**: Extend the existing DD-canonical-raw-output-stream-persistence pattern from float lists to int8/uint8 quantization. Map float softmax outputs [0,1] to uint8 [0,255] via `np.clip(activation * 255, 0, 255).astype(np.uint8)`. This loses no meaningful information for threshold-based decisions and reduces per-song head output storage from ~13 KB to ~3.4 KB.

3. **Current pooled vector**: Retained as the active ANN search surface, but marked as derived — recomputed from the stream rather than independently persisted. The stream is canonical.

4. **Segmentation becomes a read-time operation**: When the user changes segmentation parameters, the system reads the int8 stream, converts to float32 in memory, runs the segmentation algorithm, recomputes pooled vectors, and rebuilds the vector index. No audio I/O, no ONNX inference.

5. **The existing redundant fields**: The `vector` field (two consumers exist but both want centroids — they should use AQL aggregation instead) is dropped once those consumers are migrated to the correct approach. The stored pooled vector is renamed/consolidated to avoid confusion once it becomes a derived field.

## Consequences

Positive:
- User-configurable segmentation without re-running ONNX inference (the bottleneck)
- Segmentation strategy experimentation becomes feasible — change params, re-segment 40k songs in minutes, not hours
- Storage cost for full streams (~7.3 GB) is 4× less than float32 alternatives (~29 GB)
- Both embedding and head output streams use the same int8 pattern, keeping the persistence layer uniform
- The existing APPROX_NEAR_COSINE ANN index works with int arrays — no new index technology needed

Negative:
- Storage increases from ~1.8 GB (current pooled-only, with hot/cold duplication) to ~7.3 GB (full int8 streams) — a 4× increase in the embedding store, though still modest in absolute terms
- Existing vectors must be migrated (re-read from raw audio, re-compute full stream, quantize to int8, store) — this is a full reprocessing pass
- The vector index must be rebuilt after every segmentation change (minutes for 40k songs, not a concern but worth noting)
- Int8 reconstruction to float32 at read time adds CPU overhead during segmentation (microseconds per song — negligible)

Neutral:
- This supersedes the simpler "just add int8 vector_q" approach — the stream IS the canonical artifact, not a secondary compression
- Existing DD-canonical-raw-output-stream-persistence needs updating: head streams should be int8, not float lists
- Migration path: process audio once, store full int8 stream + initial pooled vector + initial segment boundaries. Later segmentation changes operate on the stored stream only.

## References

- DD-canonical-raw-output-stream-persistence (design doc for per-output float head streams)
- DD-segment-group-storage (temporal group storage for classification heads)
- pooling-research-findings.md (pooling strategy benchmarks: median/mean winners)
- artifacts/scratch/vector_storage_full.py (int8 quantization validation: ρ=0.9996, Recall@100=0.99)
