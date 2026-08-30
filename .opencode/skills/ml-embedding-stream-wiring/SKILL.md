---
name: ml-embedding-stream-wiring
description: The unwired ML embedding stream pipeline in Nomarr — ml_embedding_streams table, EmbeddingStreamRepository, the four MlDb facade methods, the quantization research (R7 reopened; the amended 2026-08-30 research selects uniform fp16 stream storage plus halfvec fp16 derived lookup, with benchmark gates), and the broken direct-pool embeddings write path. Use when restoring the stream→derived-embeddings pipeline, adding DeferredEmbeddingStreamWrite, quantizing backbone embeddings, segmentation (derive-time vs embedding-time), or touching process_file_wf/discovery_worker/ml_inference_repo/embedding_stream_repo/ml_vector_persist_comp.
---

# ML Embedding Stream Wiring

## Mental Model

Nomarr's ML pipeline computes per-patch backbone embeddings for the whole waveform, then pools ALL patches into ONE track vector via trimmed_mean. Per ADR-038 (Accepted, 2026-06-20) + DD-int8-canonical-embedding-stream-storage (Completed, Arango-era), the per-patch stream was DESIGNED (Arango-era ADR-038) to be stored int8-quantized in `ml_embedding_streams` as the SOURCE OF TRUTH — R7 re-opened that choice; the amended research (artifacts/designs/process/RESEARCH-restore-quantized-embedding-streams.md, 2026-08-30) keeps **int8 for the stream** (evidence-backed: external 97.2-100% recall, repo citation rho=0.9996 — with explicit fp16 fallback if pre-ship gates fail) and **halfvec float16 for the derived lookup** (pgvector has no int8 vector type/opclass, so int8 derived rows would be unsearchable; halfvec is the quantized searchable choice); the `embeddings` table was designed to be a DERIVED lookup table (one pooled vector per (song, backbone)) recomputed from the stored stream when segmentation changes; segmentation was designed as a read-time/post-hoc user-configurable operation. **The design was never wired into production in any era** — git history shows zero `embedding_stream` references in workflows/services ever, and `ml_embedding_stream_store_comp` was never created. Today the pipeline pools whole-waveform embeddings inline (non-segmented) and writes the `embeddings` table directly with `segmentation_hash=None` hardcoded — the stream is discarded.

## Coverage

**Documented:** Table/repo/facade contract (all validated, zero prod callers), broken direct-write path (file:line evidence), quantization design + validation **and its R7 amendment** (amended research report: uniform fp16 stream and halfvec derived lookup; int8/PQ/binary/int4/int16 rejected; missing validation script; gate benchmark mandatory), schema gaps vs DD data model, derive-time vs embedding-time segmentation options, hot/cold maintenance alignment, deferred-write DTO pattern.
**Not yet documented:** Whether head models batch internally (config batch_size exists); final window/hop defaults for embedding-time segmentation; gate-benchmark results on current backbone outputs (must be run before defaults ship).
**Last extended:** 2026-08-30

## Key Findings

### 1. Stream infrastructure exists, validated, but completely unwired
- **Table:** `ml_embedding_streams` — alembic/versions/001_current_schema_baseline.py:245-262 — id, song_id, backbone_id, `patches_emb LargeBinary NOT NULL`, created_at; FK→songs CASCADE; `uq_ml_embedding_streams_song_backbone` UNIQUE(song_id, backbone_id).
- **Repo:** `nomarr/persistence/database/embedding_stream_repo.py` — `upsert_stream` (L55-88) atomic `INSERT … ON CONFLICT DO UPDATE` (constraint uq), concurrency-safe (git acde4a45); `get_stream`, `list_by_backbone` (paginated), `delete_for_song`.
- **Facade:** `nomarr/persistence/api/ml.py:356-399` — `replace_embedding_stream_for_song`, `get_embedding_stream_for_song`, `list_embedding_streams_by_backbone`, `remove_embedding_streams_for_song` — return `EmbeddingStream` domain dataclass (`helpers/dataclasses/ml_embedding_stream_dataclass.py`: frozen, fields backbone + patches_emb bytes ONLY).
- **Wiring:** `db.py:101,172-173` wires EmbeddingStreamRepository + MlInferenceRepo into MlDb. **Zero production callers** — only test_ml_db.py:791.

### 2. Broken direct-pool write path (current behavior)
- `process_file_wf.py:145` — whole waveform → `compute_backbone_embeddings`; L154-176 per backbone: `run_heads(embeddings_2d)` then `persist_backbone_vector(backbone, embeddings_2d, …)` (L173) → `ml_vector_persist_comp.persist_backbone_vector` L85 `pool_embedding_for_storage(embeddings_2d)` = trimmed_mean over ALL patches (ml_vector_pool_comp.py:17-54).
- Carried as `DeferredBackboneVectorWrite` (processing_dto.py:119-131) → `discovery_worker._execute_deferred_writes` L143-149 → `db.ml.replace_song_inference_results` → `MlInferenceRepo.replace_song_inference_results` (ml_inference_repo.py:34-68, atomic begin_nested + one commit, deletes (song_id, backbone) vectors + song_id streams) → `_insert_vector` L96-119 with **`segmentation_hash=None` hardcoded (L112)**, `tier="hot"`.
- Backbone internals: ml_backbone.py `_run` L90-122 → `preprocess_for_backbone(whole waveform)` (ml_preprocess_comp.py:254-284: log-mel + `extract_patches`; effnet patch=128f hop=93, musicnn 187f/128, vggish/yamnet 96f/96 non-overlap) → ONNX `_run_in_batches` batch 32 (ml_session_comp.py:198-230). n_patches scales linearly with track duration → unbounded total work; heads (ml_head_pipeline_comp.run_single_head L93) also pool over ALL patches trimmed_mean.

### 3. Design intent (ADR-038 + DD)
- Quantization: per-document symmetric int8, `embed_scale = max_abs(embeddings_2d)/127.0`, flat int list; reconstruction `np.array(patches, int8).reshape(n,d).astype(float32)*scale`. Validated Spearman ρ=0.9996, Recall@100=0.99 (artifacts/scratch/vector_storage_full.py, Jun 19 2026; uses `np.clip(np.round(v*scale), …)`). **R7 amended (2026-08-30):** int8 is no longer assumed — it is the evidence-backed recommendation for the STREAM (4x storage, external recall 97.2-100%, cosine sim 0.9999) with a gate-gated fp16 fallback; the DERIVED lookup stays halfvec fp16 (HALFVEC(1280) + halfvec_cosine_ops HNSW; pgvector has NO int8 type/opclass → int8 derived is unsearchable). Rejected: PQ (codebook/non-invertible/no pgvector support), binary/bit (recall collapse without rescore), int4, int16. **CAUTION:** artifacts/scratch/vector_storage_full.py is ABSENT from the working tree — the ρ/R@100 figures are citation-only; pre-ship gates G1-G3 (ρ≥0.999, Recall@100≥0.98, cosine≥0.999) must be re-benchmarked on current backbone outputs via scripts/embedding_research (extend vector_types.py with quantization types). Stream metadata needs new baseline columns: embed_dim, num_segments, embed_scale, quant_format (int8/fp16/…), model_suite_hash, segment_s, hop_s, pad_final, updated_at.
- Flow: step 3a persist stream BEFORE pooling; 3b pool FROM stored stream (`dequantize_and_pool`); stream persist SYNCHRONOUS (DD decision 5), head output streams deferred; `segmentation_hash` on derived vector; `resegmentation_wf` = read streams → dequantize → re-pool → update embeddings → REINDEX; no audio/ONNX on resegment.
- **PG-era deltas:** `patches_emb` is packed `bytes` (LargeBinary), not list[int]; `embeddings.embedding` is HALFVEC(1280) (float16) not int8 vector_n; stream table LACKS the DD's metadata columns (embed_dim, num_segments, embed_scale, model_suite_hash) — schema must be extended in 001 baseline (R5) for scale/reshape metadata.

### 4. Segmentation options (Q2)
- **Derive-time (ADR-038 canonical):** segmentation = pooling recipe (mode/trim; research strategies temporal_segment in scripts/embedding_research/helpers/binning.py:90-171, strategy_binned/_pool.py `_pool_segment`, strategy_ctp/segment_fn.py) applied to the STORED stream. Preserves R1-R3 exactly; minimal churn.
- **Embedding-time (segment_waveform):** `ml_embed_comp.py:29-80` survives with zero production callers (deadcode_allowlist.py:600-601); `SegmentWaveformParams` in ml_dto.py:94-102 (waveform/sr/segment_s/hop_s/pad_final). Bounds per-window work (R4 literal) but changes stream content at window boundaries vs whole-waveform; needs window/hop config storage.
- Research strategies operate on the patch stream, so they are derive-time by nature.

### 5. Derivation timing (Q3)
- Maintenance chain: `idle_promotion_vectors_wf` (idle worker, distributed lock "vector_promotion" 30-min TTL, reap stale >10 min) → `promote_and_rebuild_workflow` → `db.ml.index_backbone_embeddings` (drain hot→cold) → `VectorRepo.rebuild_cold_hnsw_index` REINDEX CONCURRENTLY (vector_repo.py:246-251). `rebuild_vector_index_wf` = cold-only rebuild.
- Derived embeddings rows are inserted `tier='hot'`, promoted to cold later; HNSW index only covers cold. Derivation can be synchronous at worker time (insert hot row with segmentation_hash) — resegmentation then only rewrites embeddings + rebuilds.

### 6. Schema/API/deferred-write implications (Q5)
- New DTO: `DeferredEmbeddingStreamWrite` (pattern: processing_dto.py DeferredOutputStreamWrite L110-116 / DeferredBackboneVectorWrite L119-131); add field to `DeferredFileWrites` (L134-159); new branch in `_execute_deferred_writes` L117-158 calling `replace_embedding_stream_for_song`.
- Extend: EmbeddingStream dataclass, `upsert_stream` signature, facade methods, repo DTO `EmbeddingStreamRecord` (embedding_stream_repo_dto.py:13-21); add 001-baseline columns.
- Transactions: stream upsert = single atomic statement (own tx, repo-owned); embeddings aggregate = own tx (MlInferenceRepo). Two transactions — partial failure tolerable BECAUSE embeddings is derived (repair = re-derive from stream; this is the design's idempotency story).
- Test contracts to update: test_ml_db.py:787-856 (facade stream mocks use 3-arg signature), test_process_file_wf.py (deferred writes assertions), test_embedding_stream_repo.py (real SQLite, song_id-keyed — correct pattern).

## Critical Invariants
1. Stream is canonical; embeddings is derived — never write embeddings directly from raw `embeddings_2d` again; always derive from the stored (dequantized) stream.
2. `segmentation_hash` must be populated with a real hash of segmentation params — never hardcode None (ml_inference_repo.py:112 is the bug site).
3. One canonical embeddings writer: `MlInferenceRepo.replace_song_inference_results` (aggregate owns the tx; AR-SDR-4 — no facade-level transactions).
4. Reuse the validated repo/facade (R6): do NOT rewrite upsert_stream's ON CONFLICT logic or the four facade methods.
5. No migration (R5): alter `001_current_schema_baseline.py` directly (NOTE: filename differs from user's stated `001_initial_v1_baseline_schema.py`).
6. `model_id` in vector payload = model_suite_hash (ml_vector_persist_comp.py:53) — stream metadata must carry the same suite hash for provenance.

## Sources
- ADR-038 (artifacts/decisions/), DD-int8-canonical-embedding-stream-storage (artifacts/designs/completed/), ADR-040/041
- Files listed above; git commits c69029b9 (deleted analyze_with_segments), ffbffce3 (segment stats → raw streams), a5e773dd (design commit: ml_embedding_streams_aql.py + vectors_aql segmentation_hash), 37060108/f0885a7d (PG port), c6196fab (atomic aggregate)
- Log L120 (support-researcher full research report); amended research: artifacts/designs/process/RESEARCH-restore-quantized-embedding-streams.md (2026-08-30) + support-researcher log entry (same date, tag quantization)
