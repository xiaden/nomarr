---
name: per-song-embedding-cardinality
description: Per-song embedding cardinality and storage semantics in Nomarr — the embeddings table (one pooled vector per song/backbone, tier hot→cold, segmentation_hash always NULL), the unwired ml_embedding_streams table (one int8 patch stream per song/backbone, zero production callers), ml_output_streams (one row per song/output_id, no unique constraint), the broken vector read consumers (doc['embedding']/vector_n/score KeyErrors), and the research-script translation gap (pooled_vecs per strategy, binned_vecs per bin never ported). Use when working on vector persistence, embedding streams, similarity search, taste profiles, playlist building, or the ADR-038 int8-stream restoration.
---

# Per-Song Embedding Cardinality & Storage Semantics

## Mental Model
Nomarr persists exactly ONE pooled embedding vector per song per backbone in the
single `embeddings` table. The raw per-patch embedding stream (the canonical
int8 artifact ADR-038 mandated) has a table, ORM model, repo, and facade methods
but ZERO production writers or readers — it is dead plumbing. Head score streams
(`ml_output_streams`) ARE persisted live. The embedding research scripts store
far richer per-song data (per-strategy pooled vectors, per-bin segmented vectors,
patch sidecars); none of that richness was ported.

## Coverage
**Documented:** row keys/uniqueness for embeddings / ml_embedding_streams / ml_output_streams; the live write path (process_file_wf → persist_backbone_vector → deferred aggregate → MlInferenceRepo); the read/consumer paths and their KeyError bugs; schema vs ORM vs repo contract alignment; research-script comparison.
**Not yet documented:** whether taste_profile/playlist_builder consumers were fixed after this audit; any future stream-wiring work.
**Last extended:** 2026-08-31

## Key Findings

### embeddings = exactly one row per (song_id, backbone_id)
- **Location:** `nomarr/persistence/models/embedding.py:44` (UNIQUE `uq_embeddings_song_backbone`); `alembic/versions/001_current_schema_baseline.py:406`
- **What:** Single-table PG schema. `song_id` FK CASCADE, `backbone_id` str(100), `embed_dim` NOT NULL, `model_suite_hash` NOT NULL ("" placeholder), `num_segments` nullable, `segmentation_hash` nullable, HALFVEC(1280), `genres` array, `tier` hot/cold, partial HNSW index on `tier='cold'` only.
- **Why it matters:** The unique constraint means ONE pooled vector per song/backbone — the system cannot store multiple embeddings per song in this table (segmentation variants, strategies, or bins would each need their own backbone_id).

### Live write path pools ALL patches → one vector, stream discarded
- **Location:** `nomarr/workflows/processing/process_file_wf.py:145,171-175` → `nomarr/components/ml/vectors/ml_vector_persist_comp.py:60-105` → `nomarr/helpers` pooling → `nomarr/services/infrastructure/workers/discovery_worker.py:153-159` → `nomarr/persistence/database/ml_inference_repo.py:34-72,110-133`
- **What:** `compute_backbone_embeddings` returns `(n_patches, embed_dim)` per backbone (ONNXBackboneModel._run, ml_backbone.py:90-122); `persist_backbone_vector` pools ALL patches via `pool_embedding_for_storage` (trimmed_mean, trim 0.1) into one 1280-d vector; payload carried in `DeferredBackboneVectorWrite`; worker calls `db.ml.replace_song_inference_results` per backbone (atomic begin_nested, delete-then-insert scoped to (song, backbone)); `_insert_vector` hardcodes `segmentation_hash=None` (ml_inference_repo.py:126), `tier='hot'` (:129), `model_id` = model_suite_hash stuffing (:119,123).
- **Why it matters:** Patch stream is computed then discarded. Multiple patch vectors are NEVER stored — only their trimmed mean. `num_segments` is populated (= patch count) but `segmentation_hash` is always NULL.

### ml_embedding_streams: full table, zero production callers
- **Location:** `nomarr/persistence/models/ml_embedding_stream.py:13` (UNIQUE `uq_ml_embedding_streams_song_backbone`); `nomarr/persistence/database/embedding_stream_repo.py:55-88` (upsert ON CONFLICT); `nomarr/persistence/api/ml.py:395-438` (4 facade methods); baseline 001:238-255
- **What:** One row per (song, backbone): id, song_id, backbone_id, `patches_emb` LargeBinary, created_at. Only callers are the facade/repo/tests — grep shows zero production components, workflows, or services reference `replace/get/list/remove_embedding_stream*`. No `DeferredEmbeddingStreamWrite` dataclass exists (processing_dto.py:134-159 has only raw_output_streams + backbone_vectors).
- **Why it matters:** ADR-038's canonical int8 stream storage is scaffolded but unwired. Schema ALSO lacks the Arango-era metadata columns (embed_dim, num_segments, embed_scale, model_suite_hash) — restoring the feature needs a schema change.

### ml_output_streams: no unique constraint, dedupe only in component
- **Location:** `nomarr/persistence/models/ml_output_stream.py:16-26`; baseline 001:223-236; `nomarr/components/ml/inference/ml_output_stream_store_comp.py:25-35` (`_normalize_streams` last-wins per output_id)
- **What:** song_id FK, output_id str(255), output_index nullable, values JSONB. Multiple rows per song ALLOWED by schema; replace_song_inference_results deletes ALL song streams then re-inserts the deduped batch, so steady state ≈ 1 row per (song, output_id).
- **Why it matters:** Cardinality here is NOT schema-enforced — it relies on the aggregate's replace contract + component dedupe.

### Broken vector read/consumer paths
- **Location:** `nomarr/components/navidrome/taste_profile_comp.py:97,145`; `nomarr/components/navidrome/playlist_builder_comp.py:244`; `nomarr/services/domain/vector_search_svc.py:94,105`
- **What:** All three read keys absent from the DTOs: `doc["embedding"]` KeyError (EmbeddingRecord has NO embedding field — vector_repo_dto.py:13-26, `_row_to_embedding_record` vector_repo.py:30-45); `vector_doc["vector_n"]` KeyError; `result.get("score", 0.0)` filters on SimilarResult.distance (never "score") — min_score>0 returns empty results. Also `list_song_vectors` defaults `tier='cold'` (ml.py:171, vector_repo.py:187-201), so hot-tier rows are invisible to these consumers.
- **Why it matters:** Navidrome taste profiles and playlist building silently fail (KeyError) or return empty — the only live vector consumers besides search are broken.

### Research-script translation gap
- **Location:** `scripts/embedding_research/CONTRACTS.md` (pooled_vecs PK (song,backbone,strategy); binned_vecs/binned_ctp_vecs per (song,backbone,...,bin_id); patch sidecars on disk); `scripts/embedding_research/pooling.py:15-23`
- **What:** Research stores MULTIPLE pooled vectors per song (one per strategy) plus per-bin segmented vectors; pooling is norm-based trim+mean. Nomarr stores ONE pooled vector (per-dimension value-trim) with no strategy/bin/segment dimension, and `segment_waveform` (ml_embed_comp.py:29-80) has zero production callers (deadcode_allowlist.py:596-597).
- **Why it matters:** The research's post-hoc segmentation / strategy comparisons cannot be reproduced in production — the data required (patch stream) is discarded.

## Critical Invariants
- `embeddings` UNIQUE(song_id, backbone_id) — never insert 2 rows for the same (song, backbone); the aggregate deletes scoped by (song, backbone) before re-inserting.
- `_insert_vector` writes segmentation_hash=None — any code reading segmentation_hash gets NULL for live-written rows.
- All vector writes go through `db.ml.replace_song_inference_results` (the single aggregate); no facade/repo bypasses it for live writes (AR-SDR-4).
- `find_nearest` only searches tier='cold' (partial HNSW) — hot rows are invisible to ANN.
- Only ONE alembic migration exists (001 baseline) — tests assert no others.

## Sources
- Files: process_file_wf.py, ml_vector_persist_comp.py, ml_vector_pool_comp.py, ml_inference_repo.py, vector_repo.py, embedding_stream_repo.py, ml.py (facade), ml_embedding_stream.py, ml_output_stream.py, embedding.py, ml_output_stream_store_comp.py, ml_backbone_embed_comp.py, ml_embed_comp.py, vector_search_svc.py, taste_profile_comp.py, playlist_builder_comp.py, discovery_worker.py, library_song_query_comp.py, alembic/versions/001_current_schema_baseline.py, tests (test_ml_db.py, test_ml_inference_repo.py, test_embedding_stream_repo.py, test_current_schema_baseline.py, test_process_file_wf.py, test_ml_vector_persist_comp.py)
- ADRs: ADR-038 (canonical int8 streams), ADR-040 (PG migration)
- Research scripts: scripts/embedding_research/CONTRACTS.md, common/embed.py, pooling.py
- Prior research logs: L135, L129, L127, L66, L65
