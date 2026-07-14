# Task: Domain Repositories — ML & Navidrome (Part D)

## Problem Statement

Replace five ArangoDB AQL operation packages with SQLAlchemy repository classes for the ML and Navidrome domains. These repos form Tier 2 of the PostgreSQL persistence layer, sitting between intent facades (Tier 3) and SQL primitives (Tier 1).

**ArangoDB packages replaced** (not modified — Part F deletes them):
- `nomarr/persistence/database/vectors_aql.py` → `vector_repo.py`
- `nomarr/persistence/database/ml_models_aql.py` → `model_repo.py` + `output_repo.py` + `calibration_repo.py`
- `nomarr/persistence/database/ml_embedding_streams_aql.py` → `embedding_stream_repo.py`
- `nomarr/persistence/database/navidrome_aql.py` → `navidrome_repo.py`

**Key simplifications**:
- Dynamic per-backbone-per-library vector collections → single `embeddings` table with `backbone_id` column
- Runtime DDL (`register_vector_collection()`) → eliminated entirely
- Edge collections (`file_has_vectors`, `model_has_output`, `model_has_calibration`, `has_nd_id`, `has_plays`, `file_has_embedding_stream`) → FK columns and junction tables
- 147+ lines of AQL cascade logic → `ON DELETE CASCADE`

**Dependencies**: Part A (SQLAlchemy models, engine), Part B (SQL primitives)

## Phases

### Phase 1: DTOs & VectorRepo — Embedding Storage & ANN Search

DTOs are created first so that all repository steps can import them without forward-reference issues. VectorRepo is the highest-complexity repo, replacing `VectorsAqlOperations` (322 lines) with a clean repository operating on the single `embeddings` table. The hot/cold tier lifecycle, partial HNSW index, and strict-order ANN search are the critical behaviors.

- [ ] Step 1: Create `nomarr/helpers/dto/vector_repo_dto.py` with TypedDicts: `EmbeddingRecord` (fields: `id: int`, `file_id: int`, `backbone_id: str`, `tier: str`, `embed_dim: int`, `model_suite_hash: str | None`, `num_segments: int | None`, `segmentation_hash: str | None`, `genres: list[str] | None`, `created_at: int`, `updated_at: int`) and `SimilarResult` (fields: `file_id: int`, `backbone_id: str`, `distance: float`). Follow existing DTO pattern: `from __future__ import annotations`, `from typing import TypedDict`, no `nomarr.*` imports.
  **Notes:** `EmbeddingRecord.model_suite_hash`, `num_segments`, and `segmentation_hash` are `Optional` (nullable) because these values are not available at insert time — they are populated by later pipeline stages (model suite tracking, segmentation analysis). `embed_dim` is computed automatically from `len(embedding_vector)` at insert time.
- [ ] Step 2: Create `nomarr/helpers/dto/model_repo_dto.py` with `ModelRecord` TypedDict (fields: `id: str`, `model_type: str`, `backbone_id: str`, `enabled: int`, `created_at: int`, `updated_at: int`). Follow existing DTO pattern.
- [ ] Step 3: Create `nomarr/helpers/dto/output_repo_dto.py` with `OutputStreamRecord` (fields: `id: int`, `file_id: int`, `model_id: str`, `status: str`, `created_at: int`) and `ModelOutputRecord` (fields: `id: int`, `file_id: int`, `model_id: str`, `output_data: dict`, `created_at: int`). Follow existing DTO pattern.
- [ ] Step 4: Create `nomarr/helpers/dto/calibration_repo_dto.py` with `CalibrationStateRecord` (fields: `id: int`, `model_id: str`, `state_data: dict`, `updated_at: int`) and `CalibrationHistoryRecord` (fields: `id: int`, `model_id: str`, `event: str`, `data: dict`, `created_at: int`). Follow existing DTO pattern.
- [ ] Step 5: Create `nomarr/helpers/dto/navidrome_repo_dto.py` with `NdTrackRecord` (fields: `id: str`, `title: str | None`, `artist: str | None`, `album: str | None`, `file_path: str | None`, `created_at: int`) and `NdPlayRecord` (fields: `nd_id: str`, `file_id: int | None`, `playcount: int`, `last_played: int`). Follow existing DTO pattern.
- [ ] Step 6: Create `nomarr/helpers/dto/embedding_stream_repo_dto.py` with `EmbeddingStreamRecord` (fields: `id: int`, `file_id: int`, `backbone: str`, `patches_emb: bytes`, `created_at: int`, `updated_at: int`). Follow existing DTO pattern.
- [ ] Step 7: Create `nomarr/persistence/database/vector_repo.py` with `VectorRepo` class skeleton. Accept `AsyncSession` in constructor. Import `Embedding` model from `nomarr.persistence.models.embedding` (created by Part A). Import `SimilarResult` and `EmbeddingRecord` TypedDicts from `nomarr.helpers.dto.vector_repo_dto` (created in Step 1).
- [ ] Step 8: Implement `insert_embedding(self, file_id: int, backbone_id: str, model_id: str, embedding_vector: list[float], genres: list[str] | None = None) -> EmbeddingRecord`. INSERT into `embeddings` with `tier='hot'`, `created_at`/`updated_at` set to current unix timestamp. **Compute `embed_dim = len(embedding_vector)` automatically.** Set `model_suite_hash=None`, `num_segments=None`, `segmentation_hash=None` — these fields are deferred to later pipeline stages and will be populated by update methods in Plan E or downstream components. Use SQLAlchemy `insert(Embedding).values(...)`. Return inserted row as `EmbeddingRecord`.
- [ ] Step 9: Implement `find_nearest(embedding: list[float], backbone_id: str, limit: int = 10, ef_search: int = 200) -> list[SimilarResult]`. Set session-level `hnsw.iterative_scan = strict_order` via `SET LOCAL`. Build query: `SELECT file_id, backbone_id, embedding <=> :query AS distance FROM embeddings WHERE tier = 'cold' AND backbone_id = :backbone_id ORDER BY embedding <=> :query LIMIT :limit`. Set `hnsw.ef_search` via `SET LOCAL`. Return list of `SimilarResult`. This is the only ANN search surface — partial HNSW index covers `tier='cold'` rows only.
- [ ] Step 10: Implement `drain_hot_to_cold(backbone_id: str) -> int`. Single UPDATE statement: `UPDATE embeddings SET tier = 'cold', updated_at = :now WHERE backbone_id = :backbone_id AND tier = 'hot'`. Commit. Return `result.rowcount`. No document copying — the partial HNSW index picks up newly-cold rows on next VACUUM. Also implement `count_cold_embeddings(backbone_id: str) -> int` using `SELECT COUNT(*) FROM embeddings WHERE tier = 'cold' AND backbone_id = :backbone_id`. Also implement `get_embeddings_for_file(file_id: int) -> list[EmbeddingRecord]` returning all embeddings (all backbones) for a file. Also implement `get_embedding_stats(backbone_id: str) -> dict[str, int]` returning `{"hot_count": N, "cold_count": M}` via two COUNT queries or a single GROUP BY. Also implement `delete_all_embeddings() -> None` (DELETE FROM embeddings — used by reset/maintenance workflows). Also implement `delete_embeddings_for_file(file_id: int) -> None` (DELETE FROM embeddings WHERE file_id = :file_id). Also implement `truncate_embeddings() -> None` (DELETE FROM embeddings — full table truncate for reset workflows; distinct from `delete_all_embeddings` only in semantic intent — both clear the table, but `truncate_embeddings` uses `TRUNCATE TABLE` for performance on full resets).

### Phase 2: ML Repos, NavidromeRepo, EmbeddingStreamRepo

Five repositories plus their DTOs (DTOs already created in Step 1). Each replaces AQL operations with SQLAlchemy session-based CRUD. Includes delete/truncate methods previously attributed to Plan E — these are repo-layer operations that belong with the repo that owns the table.

- [ ] Step 11: Create `nomarr/persistence/database/model_repo.py` with `ModelRepo` class. Accept `AsyncSession`. Implement: `get_model(model_id: str) -> ModelRecord | None` (by string PK), `get_model_by_path(path: str) -> ModelRecord | None`, `upsert_model(data: dict) -> ModelRecord` (ON CONFLICT on `id` PK), `update_model(model_id: str, fields: dict) -> None` (UPDATE with arbitrary field dict; raises `PersistenceError` if model not found), `delete_model(model_id: str) -> None` (CASCADE handles outputs/calibration), `list_models() -> list[ModelRecord]`, `count_models() -> int`, `get_models_by_ids(model_ids: list[str]) -> list[ModelRecord]`, `get_enabled_models() -> list[ModelRecord]` (filter `enabled=1`), `get_by_backbone(backbone_id: str) -> list[ModelRecord]`. DTO `ModelRecord` already created in Step 2.
- [ ] Step 12: Create `nomarr/persistence/database/output_repo.py` with `OutputRepo` class. Accept `AsyncSession`. Implement: `store_output_stream(file_id: int, model_id: str, status: str) -> OutputStreamRecord` (INSERT into `ml_output_streams`), `store_model_output(file_id: int, model_id: str, output_data: dict) -> ModelOutputRecord` (INSERT into `ml_model_outputs`), `get_outputs_for_file(file_id: int) -> list[ModelOutputRecord]`, `list_model_outputs(model_id: str) -> list[ModelOutputRecord]`, `delete_outputs_for_model(model_id: str) -> int` (returns count deleted; CASCADE from ml_models handles this automatically but explicit method for direct use), `get_output(output_id: int) -> ModelOutputRecord | None` (lookup by PK), `delete_outputs_for_file(file_id: int) -> int` (DELETE FROM ml_model_outputs WHERE file_id = :file_id; returns count deleted), `delete_output(output_id: int) -> None` (DELETE single row by PK). DTOs `OutputStreamRecord` and `ModelOutputRecord` already created in Step 3.
- [ ] Step 13: Create `nomarr/persistence/database/calibration_repo.py` with `CalibrationRepo` class. Accept `AsyncSession`. Implement: `get_state(model_id: str) -> CalibrationStateRecord | None` (lookup by FK `model_id`), `set_state(model_id: str, state_data: dict) -> CalibrationStateRecord` (upsert: INSERT ON CONFLICT (model_id) DO UPDATE), `record_history(model_id: str, event: str, data: dict) -> CalibrationHistoryRecord` (INSERT into `calibration_history`), `get_history(model_id: str) -> list[CalibrationHistoryRecord]` (ORDER BY created_at DESC), `list_states() -> list[CalibrationStateRecord]`, `list_states_with_models() -> list[dict]` (JOIN with ml_models to include backbone and embedder_release_date), `delete_state(calibration_id: int) -> None` (DELETE single calibration state by PK), `truncate_states() -> None` (DELETE FROM calibration_states — full table clear for reset workflows), `truncate_history() -> None` (DELETE FROM calibration_history — full table clear for reset workflows). DTOs `CalibrationStateRecord` and `CalibrationHistoryRecord` already created in Step 4.
- [ ] Step 14: Create `nomarr/persistence/database/navidrome_repo.py` with `NavidromeRepo` class. Accept `AsyncSession`. Implement: `upsert_track(nd_id: str, title: str | None, artist: str | None, album: str | None, file_path: str | None) -> NdTrackRecord` (INSERT ON CONFLICT on PK `id`), `map_track_to_file(nd_id: str, file_id: int) -> None` (INSERT into `navidrome_track_maps` ON CONFLICT do nothing), `get_mapped_file(nd_id: str) -> int | None` (lookup via junction table), `resolve_file_to_nd_track(file_id: int) -> str | None` (reverse lookup), `bulk_upsert_tracks(nd_ids: list[str]) -> int` (batch INSERT ... ON CONFLICT DO NOTHING, return count), `bulk_map_tracks(mappings: list[dict[str, str]]) -> int` (batch INSERT into junction, return count inserted), `record_play(nd_id: str, user_id: str | None, played_at: int, file_id: int | None) -> int` (INSERT into `navidrome_plays` + optional `navidrome_play_maps` junction, return play_id), `get_top_plays(user_id: str, top_n: int) -> list[NdPlayRecord]` (JOIN plays → play_maps → files, ORDER BY playcount DESC), `delete_tracks_for_file(file_id: int) -> int` (DELETE FROM navidrome_track_maps WHERE file_id; DELETE FROM navidrome_tracks WHERE id IN (orphans); return count). DTOs `NdTrackRecord` and `NdPlayRecord` already created in Step 5.
- [ ] Step 15: Create `nomarr/persistence/database/embedding_stream_repo.py` with `EmbeddingStreamRepository` class. Accept `AsyncSession`. Import `MlEmbeddingStream` model from `nomarr.persistence.models.ml` (created by Part A). Import `EmbeddingStreamRecord` from `nomarr.helpers.dto.embedding_stream_repo_dto` (created in Step 6). Implement: `upsert_stream(self, file_id: int, backbone: str, stream_payload: dict) -> EmbeddingStreamRecord` (INSERT ON CONFLICT on composite unique `(file_id, backbone)` DO UPDATE; `patches_emb` extracted from `stream_payload`), `get_stream(self, file_id: int, backbone: str) -> EmbeddingStreamRecord | None` (lookup by `(file_id, backbone)` composite key), `list_by_backbone(self, backbone: str, *, limit: int | None = None, offset: int = 0) -> list[EmbeddingStreamRecord]` (WHERE backbone = :backbone, ORDER BY id, with optional pagination), `delete_for_file(self, file_id: int) -> None` (DELETE FROM ml_embedding_streams WHERE file_id = :file_id). This repo replaces `MlEmbeddingStreamsAqlOperations` — the deterministic `_key` from ArangoDB is replaced by the `(file_id, backbone)` composite unique constraint in PostgreSQL.
- [ ] Step 16: Add `__init__.py` exports. Update `nomarr/persistence/database/__init__.py` to export `VectorRepo`, `ModelRepo`, `OutputRepo`, `CalibrationRepo`, `NavidromeRepo`, `EmbeddingStreamRepository`. Update `nomarr/helpers/dto/__init__.py` to export all new DTO TypedDicts: `EmbeddingRecord`, `SimilarResult`, `ModelRecord`, `OutputStreamRecord`, `ModelOutputRecord`, `CalibrationStateRecord`, `CalibrationHistoryRecord`, `NdTrackRecord`, `NdPlayRecord`, `EmbeddingStreamRecord`.
- [ ] Step 17: Run `ruff check` on all new files: `nomarr/persistence/database/vector_repo.py`, `nomarr/persistence/database/model_repo.py`, `nomarr/persistence/database/output_repo.py`, `nomarr/persistence/database/calibration_repo.py`, `nomarr/persistence/database/navidrome_repo.py`, `nomarr/persistence/database/embedding_stream_repo.py`, `nomarr/helpers/dto/vector_repo_dto.py`, `nomarr/helpers/dto/model_repo_dto.py`, `nomarr/helpers/dto/output_repo_dto.py`, `nomarr/helpers/dto/calibration_repo_dto.py`, `nomarr/helpers/dto/navidrome_repo_dto.py`, `nomarr/helpers/dto/embedding_stream_repo_dto.py`. Fix any lint errors. Run `mypy --strict` on the same files. Fix any type errors. Verify zero errors.
- [ ] Step 18: Verify no imports from `nomarr.persistence.aql`, `nomarr.persistence.arango_client`, or `nomarr.persistence.schema` in any new file. Verify no imports from components/services/workflows/interfaces layers (persistence must not import upward). Confirm all new files follow the repository pattern: accept `AsyncSession`, return TypedDict DTOs, no business logic.

## Completion Criteria

1. Six new repository files exist in `nomarr/persistence/database/`: `vector_repo.py`, `model_repo.py`, `output_repo.py`, `calibration_repo.py`, `navidrome_repo.py`, `embedding_stream_repo.py`
2. Six new DTO files exist in `nomarr/helpers/dto/`: `vector_repo_dto.py`, `model_repo_dto.py`, `output_repo_dto.py`, `calibration_repo_dto.py`, `navidrome_repo_dto.py`, `embedding_stream_repo_dto.py`
3. `VectorRepo.find_nearest()` uses pgvector `<=>` operator with `tier = 'cold'` filter and `hnsw.iterative_scan = strict_order`
4. `VectorRepo.drain_hot_to_cold()` is a single UPDATE statement (no document copying)
5. No dynamic DDL — `register_vector_collection()` pattern is eliminated
6. All repos accept `AsyncSession` and return TypedDict DTOs
7. `ruff check` and `mypy --strict` pass with zero errors on all new files
8. No upward imports (persistence never imports from components/services/workflows/interfaces)
9. No references to ArangoDB, AQL, `SafeDatabase`, or `CollectionNames` in new files
10. `VectorRepo.insert_embedding()` computes `embed_dim` automatically and defers `model_suite_hash`, `num_segments`, `segmentation_hash` to `None`
11. Delete/truncate methods for all repos are included in Plan D (not deferred to Plan E)

## Contracts

### Created (new method signatures)

**VectorRepo** (`nomarr/persistence/database/vector_repo.py`):
- `__init__(self, session: AsyncSession) -> None`
- `insert_embedding(self, file_id: int, backbone_id: str, model_id: str, embedding_vector: list[float], genres: list[str] | None = None) -> EmbeddingRecord`
- `find_nearest(self, embedding: list[float], backbone_id: str, limit: int = 10, ef_search: int = 200) -> list[SimilarResult]`
- `drain_hot_to_cold(self, backbone_id: str) -> int`
- `get_embeddings_for_file(self, file_id: int) -> list[EmbeddingRecord]`
- `count_cold_embeddings(self, backbone_id: str) -> int`
- `get_embedding_stats(self, backbone_id: str) -> dict[str, int]`
- `delete_all_embeddings(self) -> None`
- `delete_embeddings_for_file(self, file_id: int) -> None`
- `truncate_embeddings(self) -> None`

**ModelRepo** (`nomarr/persistence/database/model_repo.py`):
- `__init__(self, session: AsyncSession) -> None`
- `get_model(self, model_id: str) -> ModelRecord | None`
- `get_model_by_path(self, path: str) -> ModelRecord | None`
- `upsert_model(self, data: dict) -> ModelRecord`
- `update_model(self, model_id: str, fields: dict) -> None`
- `delete_model(self, model_id: str) -> None`
- `list_models(self) -> list[ModelRecord]`
- `count_models(self) -> int`
- `get_models_by_ids(self, model_ids: list[str]) -> list[ModelRecord]`
- `get_enabled_models(self) -> list[ModelRecord]`
- `get_by_backbone(self, backbone_id: str) -> list[ModelRecord]`

**OutputRepo** (`nomarr/persistence/database/output_repo.py`):
- `__init__(self, session: AsyncSession) -> None`
- `store_output_stream(self, file_id: int, model_id: str, status: str) -> OutputStreamRecord`
- `store_model_output(self, file_id: int, model_id: str, output_data: dict) -> ModelOutputRecord`
- `get_outputs_for_file(self, file_id: int) -> list[ModelOutputRecord]`
- `list_model_outputs(self, model_id: str) -> list[ModelOutputRecord]`
- `delete_outputs_for_model(self, model_id: str) -> int`
- `get_output(self, output_id: int) -> ModelOutputRecord | None`
- `delete_outputs_for_file(self, file_id: int) -> int`
- `delete_output(self, output_id: int) -> None`

**CalibrationRepo** (`nomarr/persistence/database/calibration_repo.py`):
- `__init__(self, session: AsyncSession) -> None`
- `get_state(self, model_id: str) -> CalibrationStateRecord | None`
- `set_state(self, model_id: str, state_data: dict) -> CalibrationStateRecord`
- `record_history(self, model_id: str, event: str, data: dict) -> CalibrationHistoryRecord`
- `get_history(self, model_id: str) -> list[CalibrationHistoryRecord]`
- `list_states(self) -> list[CalibrationStateRecord]`
- `list_states_with_models(self) -> list[dict]`
- `delete_state(self, calibration_id: int) -> None`
- `truncate_states(self) -> None`
- `truncate_history(self) -> None`

**NavidromeRepo** (`nomarr/persistence/database/navidrome_repo.py`):
- `__init__(self, session: AsyncSession) -> None`
- `upsert_track(self, nd_id: str, title: str | None, artist: str | None, album: str | None, file_path: str | None) -> NdTrackRecord`
- `map_track_to_file(self, nd_id: str, file_id: int) -> None`
- `get_mapped_file(self, nd_id: str) -> int | None`
- `resolve_file_to_nd_track(self, file_id: int) -> str | None`
- `bulk_upsert_tracks(self, nd_ids: list[str]) -> int`
- `bulk_map_tracks(self, mappings: list[dict[str, str]]) -> int`
- `record_play(self, nd_id: str, user_id: str | None, played_at: int, file_id: int | None) -> int`
- `get_top_plays(self, user_id: str, top_n: int) -> list[NdPlayRecord]`
- `delete_tracks_for_file(self, file_id: int) -> int`

**EmbeddingStreamRepository** (`nomarr/persistence/database/embedding_stream_repo.py`):
- `__init__(self, session: AsyncSession) -> None`
- `upsert_stream(self, file_id: int, backbone: str, stream_payload: dict) -> EmbeddingStreamRecord`
- `get_stream(self, file_id: int, backbone: str) -> EmbeddingStreamRecord | None`
- `list_by_backbone(self, backbone: str, *, limit: int | None = None, offset: int = 0) -> list[EmbeddingStreamRecord]`
- `delete_for_file(self, file_id: int) -> None`

### Called (dependencies from Parts A, B)

- `nomarr.persistence.models.embedding.Embedding` — SQLAlchemy model (Part A)
- `nomarr.persistence.models.ml.MlModel`, `MlOutputStream`, `MlModelOutput`, `MlEmbeddingStream` — SQLAlchemy models (Part A)
- `nomarr.persistence.models.calibration.CalibrationState`, `CalibrationHistory` — SQLAlchemy models (Part A)
- `nomarr.persistence.models.navidrome.NavidromeTrack`, `NavidromeTrackMap`, `NavidromePlay`, `NavidromePlayMap` — SQLAlchemy models (Part A)
- `nomarr.persistence.pg_engine.AsyncSession` — session type (Part A)
- `nomarr.persistence.errors.PersistenceError`, `DuplicateKeyError` — engine-agnostic exceptions (Part B)
