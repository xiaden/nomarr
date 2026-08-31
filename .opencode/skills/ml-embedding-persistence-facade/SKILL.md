---
name: ml-embedding-persistence-facade
description: The MlDb embedding/vector/stream persistence facade contract in Nomarr — the embeddings, ml_output_streams, ml_embedding_streams, ml_model_outputs, ml_models table set, every facade method and its delegate, every production caller, the known contract gaps (EmbeddingRecord lacks the embedding vector; SimilarResult exposes distance not score; vector_n/score Arango-era field names still read at runtime), atomicity state, and the R4 record-compatibility boundary for the full facade migration. Load when working on db.ml vector/stream/inference-aggregate methods, embedding persistence, vector search/retrieval, output-stream resolution, or the persistence-intent-facade migration DD.
---

# ML Embedding Persistence Facade

## Mental Model

`db.ml` (`nomarr/persistence/api/ml.py`, class `MlDb` L47-634) is the single persistence boundary for five tables: `embeddings` (vector store), `ml_output_streams` (canonical activation streams), `ml_embedding_streams` (int8 patch streams, currently unwired), `ml_model_outputs` (output metadata registry), `ml_models` (model registry). Tier-2 repos (VectorRepo, OutputRepo, MlInferenceRepo, EmbeddingStreamRepository, ModelRepo, CalibrationRepo) each own short `begin_nested()`+`commit()` transactions; the facade never begins transactions (AR-SDR-4, enforced by `test_facade_transaction_contract_absent`). The single live aggregate write is `replace_song_inference_results` → `MlInferenceRepo.replace_song_inference_results` (ml_inference_repo.py:34-72), one repository-owned transaction scoped to `(song_id, backbone)` — already atomic and backbone-scope-correct.

## Coverage

**Documented:** full MlDb embedding-related method inventory with line numbers; caller map; EmbeddingRecord/SimilarResult contract gaps; R4 compatibility classification (no schema change needed); atomicity gaps (N+1 deletes, per-index registry writes); test/enforcement state.
**Not yet documented:** final post-migration state; the restore-int8 embedding-stream wiring (see `ml-embedding-stream-wiring` skill); calibration facade details (separate tables).
**Last extended:** 2026-08-31

## Key Findings

### Finding 1: `list_song_vectors` returns the storage-row shape and omits the vector
- **Location:** `nomarr/persistence/api/ml.py:153-160` → `VectorRepo.get_embeddings_for_song` (vector_repo.py:187-201) → `EmbeddingRecord` (helpers/dto/vector_repo_dto.py:13-26).
- **What:** The DTO has id/song_id/backbone_id/tier/embed_dim/model_suite_hash/num_segments/segmentation_hash/genres/created_at/updated_at — NO embedding vector values. `get_embeddings_for_song` selects the full row (`select(_T)`), so the values are available; the mapper just drops them.
- **Why it matters:** Callers needing vector values crash at runtime: `taste_profile_comp.py:97,145` and `playlist_builder_comp.py:244` read `doc["embedding"]` (KeyError; comment at taste_profile:86-88 calls it "a known persistence-layer gap tracked in S2 scope"); `vector_search_svc.py:94` reads `doc["vector_n"]` (Arango-era name, KeyError). Adding the vector to a domain read object is mapping-only — no schema/record change (R4-safe).

### Finding 2: search result contract is `distance`, callers filter on `score`
- **Location:** `ml.py:162-180` → `VectorRepo.find_nearest` (vector_repo.py:115-159) → `SimilarResult` {song_id, backbone_id, distance} (vector_repo_dto.py:29-34).
- **What:** `vector_search_svc.py:105` does `result.get("score", 0.0) >= min_score` — "score" is never present, so the filter always passes with the default. Docstring (vector_search_svc.py:68-72) promises file_id/score/vector keys that the shape never has.
- **Why it matters:** min_score is silently a no-op. Distance→score conversion (cosine: score = 1 - distance) is mapping-only, R4-safe.

### Finding 3: Embedding-stream facade methods have zero production callers
- **Location:** `ml.py:353-396` (replace/get/list/remove_embedding_stream) → `EmbeddingStreamRepository` (embedding_stream_repo.py:55-121), table `ml_embedding_streams` (baseline 001:246-263, uq_ml_embedding_streams_song_backbone, only id/song_id/backbone_id/patches_emb/created_at — no metadata columns).
- **What:** Only `test_ml_db.py` calls them. The restore-int8 wiring (DD-restore-int8-embedding-streams) is the owning scope; the migration must keep this facade surface intact but does not need caller migration.

### Finding 4: Aggregate write is atomic; gaps remain elsewhere
- **What:** `replace_song_inference_results` (ml.py:402-446 → ml_inference_repo.py:63-72) = one begin_nested + one commit; backbone-scoped vector delete; validation of payload backbone_id (ml_inference_repo.py:74-82). Pinned by test_ml_db.py:590-618.
- **Gaps:** `remove_vectors_for_songs` (ml.py:458-469) loops `delete_embeddings_for_song` (one commit each, documented TODO); `ensure_model_outputs` (ml_model_registry_comp.py:37-59) does N get+replace round-trips; register_ml_models_wf.py:135-136 prune = remove_model_outputs_for_model + remove_model (two txs, CASCADE would cover); library_song_query_comp.py:633-634 clear_library_data = per-collection clears.

### Finding 5: Persistence concerns in components
- **Location:** `ml_vector_persist_comp.py:26-57` builds row-shaped dict `{backbone_id, model_id, embedding_vector, embed_dim, num_segments}` where `model_id` is *the model-suite hash* (storage-column semantic documented in ml_inference_repo.py:121-126); `ml_vector_registry_comp.py:20-69` iterates `list_vector_collection_names()` and counts-then-deletes per collection (choreography that belongs in persistence); `ml_output_stream_store_comp.py:25-45` dedupes streams by output_id (row-normalization in a component); `process_file_wf.py:204-230` performs output-id mapping via `build_model_output_index_map()` (registry/identity knowledge in the workflow).

### Finding 6: R4 compatibility — no schema or record change is required
- All five tables (baseline `alembic/versions/001_current_schema_baseline.py`: embeddings 396-433, ml_output_streams 231-244, ml_embedding_streams 246-263, ml_model_outputs 265-281, ml_models 204-229) use BigInteger ms timestamps; ALL ML repos (vector, ml_inference, output, model, embedding_stream, calibration) write `now_ms()` — no seconds-vs-ms inconsistency exists in the current tree.
- Preserved-by-default records: `model_suite_hash=""` placeholder + `segmentation_hash=None` (ml_inference_repo.py:124-126), `output_data={}` (ml.py:490-492), `model_id` column holding the suite hash, empty-stream replacement semantics (discovery_worker.py:146-152).
- Approval items (separate, optional): repurposing `model_id` vs writing `model_suite_hash`; `output_data` legacy column; hot/cold tier vocabulary in stats responses.

## Critical Invariants
- The facade must never return storage rows (ADR-032/041): `EmbeddingRecord`/`SimilarResult` are the two remaining violations in the ML facade.
- No facade transaction API (AR-SDR-4); atomicity lives in one repo method per aggregate.
- `ml_output_streams.output_id` is NOT NULL and `ml_model_outputs.output_id` is UNIQUE — the sha256 output identity contract.
- `embeddings.embedding` is HALFVEC(1280) — insert fails for any other embed_dim; do not change under R4.
- Callers must not read Arango-era field names (`vector_n`, `score`, `collection`).

## Sources
- nomarr/persistence/api/ml.py, database/{vector_repo,ml_inference_repo,output_repo,model_repo,embedding_stream_repo,calibration_repo}.py
- helpers/dto/{vector_repo_dto,output_repo_dto,embedding_stream_repo_dto,model_repo_dto}.py; helpers/dataclasses/ml_*_dataclass.py
- alembic/versions/001_current_schema_baseline.py
- Callers: discovery_worker.py, process_file_wf.py, ml_vector_persist_comp.py, ml_vector_registry_comp.py, ml_vector_retrieve_comp.py, ml_vector_maintenance_comp.py, ml_vector_idle_promotion_comp.py, taste_profile_comp.py, playlist_builder_comp.py, ml_output_stream_store_comp.py, ml_model_registry_comp.py, register_ml_models_wf.py, library_song_query_comp.py, vector_search_svc.py, vector_maintenance_svc.py, promote_and_rebuild_vectors_wf.py, rebuild_vector_index_wf.py, idle_promotion_vectors_wf.py
- Tests: test_ml_db.py, test_ml_inference_repo(_scope).py, test_vector_repo.py, test_ml_vector_*_comp.py, test_discovery_worker_private_helpers.py, test_process_file_wf.py, test_facade_domain_boundary.py, test_architecture_qc.py
- ADR-032/038/040/041/046, AR-SDR-4, ASR-0013/14/15
- Research log L123/L127/L129, skills ml-output-identity, persistence-domain-model, ml-embedding-stream-wiring
