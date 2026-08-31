---
name: embedding-lifecycle
description: Embedding creation and storage lifecycle in Nomarr — the pooled-vector-only production path vs the research-script multi-representation pipeline, the unwired ml_embedding_streams table (ADR-038 gap), per-patch head streams, and the HALFVEC(1280) fixed-dimension constraint. Use when working on embedding persistence, embedding streams, vector pooling, segmentation/re-segmentation, ml_inference_repo, vector_repo, or comparing production with scripts/embedding_research.
---

# Embedding Lifecycle

## Mental Model
Nomarr computes per-patch backbone embeddings once per file during process_file_workflow, pools ALL patches into ONE track-level vector per backbone (trimmed_mean 10%), and persists that single vector to the `embeddings` table (halfvec, tier hot→cold). Per-patch head scores ARE stored (ml_output_streams, float JSONB) but have no production consumer. The full per-patch backbone embedding stream is deliberately NOT stored — it exists in memory for the duration of one file's processing and is discarded. ADR-038 mandates canonical int8 embedding streams to make segmentation post-hoc; the `ml_embedding_streams` table was created for this but has zero production writers (only tests + deadcode allowlist).

## Coverage
**Documented:** production write path (workflow→components→facade→repo→schema); embedding-stream table/repo/facade state; output-stream storage vs consumption; dead segmentation utilities; research-script representation inventory; known dimension risk.
**Not yet documented:** whether musicnn is deployed in a given production models_dir (changes severity of the halfvec(1280) risk); any future stream-writer implementation.
**Last extended:** 2026-08-31

## Key Findings

### Production: one pooled vector per (song, backbone), no stream
- `nomarr/workflows/processing/process_file_wf.py:145` — `compute_backbone_embeddings(cache, heads_by_backbone, shared_audio.waveform)` passes the WHOLE waveform; `ONNXBackboneModel._run` (`nomarr/components/ml/onnx/ml_backbone.py:90`) preprocesses (mel→patches, effnet 128f/93-hop, musicnn 187f/128-hop) and returns `[n_patches, embed_dim]`.
- `ml_vector_persist_comp.py:60` `persist_backbone_vector` → `pool_embedding_for_storage` (trimmed_mean, trim 0.10) → payload `{backbone_id, model_id=model_suite_hash, embedding_vector, embed_dim, num_segments=embeddings_2d.shape[0]}`. num_segments is actually the PATCH count — no segmentation exists in production.
- `ml_inference_repo.py:34` `replace_song_inference_results` atomically deletes (song,backbone) vectors + song streams, re-inserts. `_insert_vector` sets `segmentation_hash=None` always, `model_suite_hash=""` (hash travels in model_id), `tier="hot"`.
- `embeddings` table (alembic 001:388-428, `nomarr/persistence/models/embedding.py`): unique (song_id, backbone_id); `embedding HALFVEC(1280)` FIXED dimension; partial HNSW index on cold tier only.

### ml_embedding_streams is dead weight (ADR-038 gap)
- Table DDL (alembic 001:238-255): `(song_id, backbone_id, patches_emb LargeBinary, created_at)` — NO num_segments / segmentation_hash / model_suite_hash / dtype or int8 metadata that ADR-038 specifies.
- Facade `db.ml.replace_embedding_stream_for_song` / `get_embedding_stream_for_song` / `list_embedding_streams_by_backbone` / `remove_embedding_streams_for_song` (ml.py:395-438): only callers are unit tests; all four are entries in `deadcode_allowlist.py` (lines ~508, 528, 568, 580).
- Repo `embedding_stream_repo.py` upsert is concurrency-safe (ON CONFLICT, commit acde4a45) — but nothing calls it in production.

### Output streams: written, never read
- `run_single_head` (ml_head_pipeline_comp.py:73) stores per-patch scores as `RawOutputStream` per output index; process_file_wf resolves output_ids via `build_model_output_index_map` and persists through the same aggregate into `ml_output_streams` (JSONB float lists — NOT uint8 as ADR-038 proposed).
- `load_output_streams_for_song` (ml_output_stream_store_comp.py:111) is the only reader and has no production caller; calibration reads tags, not streams.

### Dead segmentation utilities
- `segment_waveform` (ml_embed_comp.py:29) and `score_segments` (ml_embed_comp.py:84): zero callers; allowlisted. `compute_segment_stats` (ml_segment_stats_comp.py:22): zero callers (superseded by ffbffce3 raw-stream persistence). `temporal_segment` exists ONLY in scripts/embedding_research/helpers/binning.py — no production PTC/CTP segmentation.

### Research scripts: many representations per song
- `common/embed.py:77` saves raw patch stream as float32 `.npy` sidecar (per song×backbone). 6 global-pool strategies (pooling.py) → flat_vecs cache + `pooled_vecs` DuckDB table (per song×backbone×strategy). PTC: 2 bin_modes × 12 dist_thresholds = 24 configs; CTP: 12 heads × 4 score thresholds = 48 configs; each config yields per-segment vec_raw+vec_norm for rep_types median/medoid (strategy_binned/_constants.py, research_config.toml). Research REUSES production components: `load_audio_mono`, `preprocess_for_backbone`, `_run_in_batches`, `create_session`.

### Risks
- HALFVEC(1280) fixed dim: musicnn embed_dim is 200; if a musicnn backbone is discovered + fully configured in production models_dir, its vector insert into `embeddings` raises a pgvector dimension error → whole aggregate write fails → song marked errored (discovery_worker catches, transition_song_state ERRORED). Severity depends on deployment.
- `num_segments` semantic mismatch: stores patch count, ADR-038 treats it as segment count; consumers of this column cannot distinguish.

## Critical Invariants
- One embeddings row per (song_id, backbone_id) — enforced by unique constraint; the aggregate's delete-then-insert must stay scoped to (song, backbone) or it erases other backbones' vectors.
- Do NOT write embedding streams without first deciding the payload format: ADR-038 wants int8 `[[int8×1280]×N]` + metadata; current column is a bare LargeBinary.
- Any future stream writer must run inside (or after) process_file_wf while `embeddings_2d` is still in memory — it is deleted at process_file_wf.py:176.

## Sources
- alembic/versions/001_current_schema_baseline.py:223-255, 388-428
- nomarr/persistence/models/{embedding,ml_embedding_stream,ml_output_stream}.py
- nomarr/persistence/database/{ml_inference_repo,embedding_stream_repo,vector_repo,output_repo}.py
- nomarr/persistence/api/ml.py:395-438, 444-488
- nomarr/workflows/processing/process_file_wf.py; nomarr/services/infrastructure/workers/discovery_worker.py:109-180
- scripts/embedding_research/{common/embed.py,pooling.py,strategy_*/segment_fn.py,strategy_binned/_constants.py,research_config.toml}
- artifacts/decisions/ADR-038, ADR-040
