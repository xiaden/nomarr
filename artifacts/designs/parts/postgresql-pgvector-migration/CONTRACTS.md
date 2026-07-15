# PostgreSQL + pgvector Migration — Contracts Ledger

**Design doc:** `artifacts/designs/pending/DD-postgresql-pgvector-migration.md`  
**Parts:** `artifacts/designs/parts/postgresql-pgvector-migration/README.md`  
**Last updated:** 2026-07-14 (after Part F planning)

---

## Architectural Rules

Extracted from `AGENTS.md` and `nomarr-layers` skill, relevant to this migration:

- **Dependency direction**: interfaces → services → workflows → components → persistence / helpers
- **No upward imports**: persistence never imports from components/workflows/services/interfaces
- **Persistence layer**: database access only, no business logic, collection-first verbs
- **Models layer**: SQLAlchemy declarative models in `nomarr/persistence/models/` — pure declarations, no session logic
- **Database operations**: Repository classes in `nomarr/persistence/database/` — receive `AsyncSession`, return DTOs or model instances
- **API facades**: `api/library.py`, `api/ml.py`, `api/application.py` — one service call per route, no AQL
- **Engine setup**: `pg_engine.py` — single source of truth for `create_async_engine()` configuration
- **Exceptions**: Engine-agnostic `PersistenceError`, `DuplicateKeyError` from `nomarr.persistence.exceptions` — no PG-specific exceptions at call sites
- **Halfvec constraint**: All embeddings must be L2-normalized before INSERT (no values exceeding ±65504)
- **HNSW partial index**: `WHERE tier = 'cold'` — hot-tier embeddings are never ANN-searched
- **strict_order everywhere**: All ANN queries use `hnsw.iterative_scan = strict_order`
- **Hard cut**: No coexistence with ArangoDB — no shims, no dual-write, no deprecation period
- **Alembic**: One baseline V1 migration from SQLAlchemy metadata; normal migrations from V2 onward
- **psycopg2 for Alembic**: Sync driver for `CREATE INDEX CONCURRENTLY` (autocommit requirement)

---

## Tables & Models

_Populated after each plan's models are created._

| Model | Table | Plan | Fields (key columns) |
| --- | --- | --- | --- |
| `Library` | `libraries` | A | `id` (PK), `name`, `path`, `library_type`, `auto_tag`, `auto_curate`, `created_at`, `updated_at` |
| `LibraryFile` | `library_files` | A | `id` (PK), `library_id` (FK→libraries CASCADE), `folder_id` (FK→library_folders SET NULL), `path`, `normalized_path`, `file_size`, `modified_time`, `duration_seconds`, `chromaprint`, `needs_tagging`, `is_valid`, `tagged`, `calibration_hash`, `write_claimed_by`, `last_tagged_at`, `scanned_at`, `created_at` |
| `LibraryFolder` | `library_folders` | A | `id` (PK), `library_id` (FK→libraries CASCADE), `parent_id` (FK→library_folders CASCADE, self-ref), `path`, `name` |
| `Tag` | `tags` | A | `id` (PK), `name`, `value`, `namespace`, `parent_tag_id` (FK→tags SET NULL, self-ref), `source`, `confidence`, `tier`, `created_at` |
| `FileTag` | `file_tags` | A | `id` (PK), `file_id` (FK→library_files CASCADE), `tag_id` (FK→tags CASCADE), `confidence`, `source`, `created_at` |
| `FileState` | `file_states` | A | `id` (PK), `name` (unique), `description` |
| `FileStateAssignment` | `file_state_assignments` | A | `id` (PK), `file_id` (FK→library_files CASCADE), `state_id` (FK→file_states CASCADE), `created_at` |
| `LibraryScan` | `library_scans` | A | `id` (PK), `library_id` (FK→libraries CASCADE), `scan_type`, `status`, `started_at`, `finished_at`, `files_found`, `files_processed`, `error` |
| `PipelineState` | `pipeline_states` | A | `id` (PK), `library_id` (FK→libraries CASCADE), `state_key`, `state_data` (JSONB), `updated_at` |
| `Meta` | `meta` | A | `key` (PK), `value` (JSONB) |
| `Lock` | `locks` | A | `key` (PK, Text), `value` (JSONB) |
| `Health` | `worker_health` | A | `id` (PK), `worker_id` (indexed), `status`, `last_seen` (BigInteger) |
| `Session` | `sessions` | A | `id` (PK, String), `data` (JSONB), `expires_at` (BigInteger, indexed) |
| `WorkerClaim` | `worker_claims` | A | `id` (PK), `worker_id` (indexed), `key`, `value` (JSONB), `claimed_at` (BigInteger, indexed) |
| `AppliedMigration` | `applied_migrations` | A | `name` (PK), `status`, `migration_version`, `started_at`, `applied_at` (nullable), `duration_ms` (nullable) |
| `VramPromise` | `vram_promises` | A | `id` (PK), `worker_id` (indexed), `pid`, `model_path`, `promised_mb`, `total_mb`, `used_mb` |
| `WorkerRestartPolicy` | `worker_restart_policies` | A | `id` (PK), `component_id` (String(255), indexed), `policy_data` (JSONB) |

---

## Repository Methods

_Populated after Parts C and D. Downstream plans (E, F) reference these signatures._

| Repository | Method | Signature | Plan |
| --- | --- | --- | --- |
| `LibraryRepository` | `__init__` | `(session: AsyncSession) -> None` | C |
| `LibraryRepository` | `add_library` | `(payload: dict) -> int` | C |
| `LibraryRepository` | `get_library` | `(library_id: int) -> LibraryRow \| None` | C |
| `LibraryRepository` | `get_library_by_name` | `(name: str) -> LibraryRow \| None` | C |
| `LibraryRepository` | `list_libraries` | `(*, enabled_only: bool = False) -> list[LibraryRow]` | C |
| `LibraryRepository` | `list_library_keys` | `() -> list[int]` | C |
| `LibraryRepository` | `update_library` | `(library_id: int, fields: dict) -> None` | C |
| `LibraryRepository` | `delete_library` | `(library_id: int) -> None` | C |
| `LibraryRepository` | `update_pipeline_axis` | `(library_id: int, axis_field: str, axis_value: str) -> None` | C |
| `LibraryRepository` | `get_pipeline_state` | `(library_id: int) -> dict[str, str] \| None` | C |
| `LibraryRepository` | `get_libraries_in_axis_state` | `(axis_field: str, axis_value: str) -> list[int]` | C |
| `LibraryRepository` | `remove_library` | `(library_id: int) -> None` | C |
| `FileRepository` | `__init__` | `(session: AsyncSession) -> None` | C |
| `FileRepository` | `add_file` | `(payload: dict) -> int` | C |
| `FileRepository` | `get_file` | `(file_id: int) -> LibraryFileRow \| None` | C |
| `FileRepository` | `get_file_by_path` | `(path: str, library_id: int) -> LibraryFileRow \| None` | C |
| `FileRepository` | `get_file_by_path_unscoped` | `(path: str) -> LibraryFileRow \| None` | C |
| `FileRepository` | `get_file_by_normalized_path` | `(library_id: int, normalized_path: str) -> LibraryFileRow \| None` | C |
| `FileRepository` | `upsert_file` | `(payload: dict) -> int` | C |
| `FileRepository` | `upsert_files_for_library` | `(library_id: int, payloads: list[dict]) -> list[int]` | C |
| `FileRepository` | `update_file` | `(file_id: int, fields: dict) -> None` | C |
| `FileRepository` | `delete_file` | `(file_id: int) -> None` | C |
| `FileRepository` | `list_files` | `(*, filters: dict \| None = None, limit: int \| None = None) -> list[LibraryFileRow]` | C |
| `FileRepository` | `count_files` | `() -> int` | C |
| `FileRepository` | `get_files_by_ids` | `(file_ids: list[int]) -> list[LibraryFileRow]` | C |
| `FileRepository` | `get_library_ids_for_files` | `(file_ids: list[int]) -> dict[int, int]` | C |
| `FileRepository` | `list_library_file_ids` | `(library_id: int, *, limit: int \| None = None) -> list[int]` | C |
| `FileRepository` | `list_library_files` | `(library_id: int, *, limit: int \| None = None) -> list[LibraryFileRow]` | C |
| `FileRepository` | `list_existing_file_paths` | `(paths: list[str]) -> list[str]` | C |
| `FileRepository` | `find_by_chromaprint` | `(library_id: int, chromaprint: str) -> LibraryFileRow \| None` | C |
| `FileRepository` | `list_files_for_folder` | `(library_id: int, folder_rel_path: str) -> list[LibraryFileRow]` | C |
| `FileRepository` | `remove_files` | `(file_ids: list[int]) -> None` | C |
| `FileRepository` | `list_orphaned_file_ids` | `() -> list[int]` | E |
| `FileRepository` | `truncate_files` | `() -> None` | E |
| `FileRepository` | `truncate_file_links` | `() -> None` | E |
| `FolderRepository` | `__init__` | `(session: AsyncSession) -> None` | C |
| `FolderRepository` | `add_folder` | `(payload: dict) -> int` | C |
| `FolderRepository` | `add_library_folder` | `(library_id: int, payload: dict) -> int` | C |
| `FolderRepository` | `get_folder` | `(folder_id: int) -> LibraryFolderRow \| None` | C |
| `FolderRepository` | `get_folder_by_path` | `(library_id: int, path: str) -> LibraryFolderRow \| None` | C |
| `FolderRepository` | `list_folders_for_library` | `(library_id: int) -> list[LibraryFolderRow]` | C |
| `FolderRepository` | `get_root_folders` | `(library_id: int) -> list[LibraryFolderRow]` | C |
| `FolderRepository` | `get_by_parent` | `(library_id: int, parent_id: int) -> list[LibraryFolderRow]` | C |
| `FolderRepository` | `remove_library_folder` | `(library_id: int, folder_id: int) -> None` | C |
| `FolderRepository` | `replace_library_folders` | `(library_id: int, payloads: list[dict]) -> None` | C |
| `FolderRepository` | `truncate_folders` | `() -> None` | E |
| `FolderRepository` | `truncate_folder_links` | `() -> None` | E |
| `FileStateRepository` | `__init__` | `(session: AsyncSession) -> None` | C, E |
| `FileStateRepository` | `get_file_state` | `(file_id: int) -> str \| None` | E |
| `FileStateRepository` | `get_file_states_for_files` | `(file_ids: list[int]) -> dict[int, set[str]]` | E |
| `FileStateRepository` | `list_files_in_state` | `(state: str, *, limit: int \| None = None) -> list[int]` | E |
| `FileStateRepository` | `count_files_in_state` | `(state: str) -> int` | E |
| `FileStateRepository` | `assign_state` | `(file_id: int, state: str) -> None` | E |
| `FileStateRepository` | `remove_states_for_files` | `(file_ids: list[int]) -> None` | E |
| `FileStateRepository` | `bootstrap_states` | `(file_ids: list[int]) -> None` | E |
| `FileStateRepository` | `count_for_file_and_state` | `(file_id: int, state_tag_id: int) -> int` | E |
| `FileStateRepository` | `truncate_assignments` | `() -> None` | E |
| `TagRepository` | `__init__` | `(session: AsyncSession) -> None` | C |
| `TagRepository` | `get_tag` | `(tag_id: int) -> TagRow \| None` | C |
| `TagRepository` | `get_tag_by_name` | `(name: str, namespace: str) -> TagRow \| None` | C |
| `TagRepository` | `get_or_create_tag` | `(name: str, value: str, namespace: str) -> int` | C |
| `TagRepository` | `create_tag` | `(payload: dict) -> int` | C |
| `TagRepository` | `delete_tag` | `(tag_id: int) -> None` | C |
| `TagRepository` | `get_tags_for_file` | `(file_id: int) -> list[TagRow]` | C |
| `TagRepository` | `assign_tag_to_file` | `(file_id: int, tag_id: int, confidence: float = 1.0, source: str \| None = None) -> None` | C |
| `TagRepository` | `remove_tag_from_file` | `(file_id: int, tag_id: int) -> None` | C |
| `TagRepository` | `replace_file_tags` | `(file_id: int, tags: list[dict]) -> None` | C |
| `TagRepository` | `get_files_for_tag` | `(tag_id: int, limit: int \| None = None) -> list[LibraryFileRow]` | C |
| `TagRepository` | `list_file_ids_for_tag` | `(tag_id: int, *, limit: int \| None = None, offset: int = 0) -> list[int]` | C |
| `TagRepository` | `get_orphaned_tag_ids` | `() -> list[int]` | C |
| `TagRepository` | `cleanup_orphaned_tags` | `() -> int` | C |
| `TagRepository` | `list_tags` | `(*, name: str \| None = None, value: Any = None, limit: int \| None = None, offset: int = 0) -> list[TagRow]` | C |
| `TagRepository` | `count_tags` | `() -> int` | C |
| `TagRepository` | `get_tags_for_files_batch` | `(file_ids: list[int], *, name_starts_with: str \| None = None, include_edge: bool = False) -> list[dict]` | C |
| `TagRepository` | `get_song_tags` | `(file_id: int, nomarr_only: bool = False) -> list[TagRow]` | C |
| `TagRepository` | `search_files_by_tag` | `(tag_key: str, value: str, *, limit: int \| None = None) -> list[LibraryFileRow]` | C |
| `TagRepository` | `search_files_by_tag_contains` | `(tag_key: str, value: str, *, limit: int \| None = None) -> list[LibraryFileRow]` | C, E |
| `TagRepository` | `get_tag_value_frequencies` | `(tag_name: str, *, limit: int) -> list[tuple[str, int]]` | C |
| `TagRepository` | `replace_tag_references` | `(source_tag_id: int, target_tag_id: int, *, file_ids: list[int] \| None = None) -> None` | C |
| `TagRepository` | `list_all_tag_names` | `(*, limit: int \| None = None) -> list[str]` | E |
| `TagRepository` | `count_tags_filtered` | `(*, name: str \| None = None, search: str \| None = None) -> int` | E |
| `TagRepository` | `list_tags_with_song_count` | `(*, name: str \| None = None, search: str \| None = None, limit: int \| None = None, offset: int = 0) -> list[dict]` | E |
| `TagRepository` | `get_genre_tags_for_files` | `(file_ids: list[int]) -> list[TagRow]` | E |
| `TagRepository` | `search_files_by_tag_pattern` | `(tag_name: str, pattern: str, *, limit: int \| None = None) -> list[LibraryFileRow]` | E |
| `TagRepository` | `truncate_file_tag_assignments` | `() -> None` | E |
| `TagRepository` | `truncate_tags` | `() -> None` | E |
| `ScanRepository` | `__init__` | `(session: AsyncSession) -> None` | C |
| `ScanRepository` | `create_scan` | `(payload: dict) -> int` | C |
| `ScanRepository` | `get_scan_record` | `(library_id: int) -> LibraryScanRow \| None` | C |
| `ScanRepository` | `update_scan` | `(scan_id: int, fields: dict) -> None` | C |
| `ScanRepository` | `delete_scan_record` | `(scan_id: int) -> None` | C |
| `ScanRepository` | `truncate_scans` | `() -> None` | E |
| `AppRepository` | `__init__` | `(session: AsyncSession) -> None` | C |
| `AppRepository` | `insert_lock` | `(payload: dict) -> str` | C |
| `AppRepository` | `upsert_lock` | `(resource_id: str, payload: dict) -> None` | C |
| `AppRepository` | `release_lock` | `(resource_id: str) -> None` | C |
| `AppRepository` | `get_lock` | `(resource_id: str) -> LockRow \| None` | C |
| `AppRepository` | `acquire_lock` | `(resource_id: str, payload: dict) -> bool` | C |
| `AppRepository` | `list_locks` | `() -> list[LockRow]` | C |
| `AppRepository` | `get_health` | `(component_id: str) -> HealthRow \| None` | C |
| `AppRepository` | `count_healthy` | `() -> int` | C |
| `AppRepository` | `list_worker_health` | `() -> list[HealthRow]` | C |
| `AppRepository` | `upsert_health` | `(component_id: str, fields: dict) -> None` | C |
| `AppRepository` | `update_health` | `(component_id: str, fields: dict) -> None` | C |
| `AppRepository` | `get_meta` | `(key: str) -> MetaRow \| None` | C |
| `AppRepository` | `upsert_meta` | `(key: str, payload: dict) -> None` | C |
| `AppRepository` | `delete_meta` | `(key: str) -> None` | C |
| `AppRepository` | `list_meta_keys_by_prefix` | `(prefix: str) -> list[str]` | C |
| `AppRepository` | `insert_session` | `(payloads: list[dict]) -> None` | C |
| `AppRepository` | `delete_session` | `(session_id: str) -> None` | C |
| `AppRepository` | `get_sessions_expiring_before` | `(timestamp_ms: int, limit: int) -> list[SessionRow]` | C |
| `AppRepository` | `get_active_sessions` | `(not_before_ms: int, limit: int) -> list[SessionRow]` | C |
| `AppRepository` | `count_sessions` | `() -> int` | C |
| `AppRepository` | `insert_worker_claim` | `(payload: dict) -> int` | C |
| `AppRepository` | `claim_file` | `(file_id: int, worker_id: str, payload: dict) -> None` | C |
| `AppRepository` | `release_claim` | `(file_id: int) -> None` | C |
| `AppRepository` | `delete_claims_for_workers` | `(worker_ids: list[str]) -> int` | C |
| `AppRepository` | `delete_claims_for_files` | `(file_ids: list[int]) -> int` | C |
| `AppRepository` | `steal_claim` | `(payload: dict, now: int, lease_ms: int) -> bool` | C |
| `AppRepository` | `list_claims` | `() -> list[WorkerClaimRow]` | C |
| `AppRepository` | `upsert_migration` | `(name: str, fields: dict) -> None` | C |
| `AppRepository` | `list_migrations` | `() -> list[dict]` | C |
| `AppRepository` | `upsert_vram_promise` | `(payload: dict) -> None` | C |
| `AppRepository` | `get_vram_promises` | `() -> list[dict]` | C |
| `AppRepository` | `delete_vram_promise` | `(promise_id: int) -> None` | C |
| `AppRepository` | `get_worker_restart_policy` | `(component_id: str) -> dict \| None` | C |
| `AppRepository` | `upsert_worker_restart_policy` | `(component_id: str, fields: dict) -> None` | C |
| `AppRepository` | `truncate_worker_claims` | `() -> None` | E |
| `AppRepository` | `truncate_health` | `() -> None` | E |
| `AppRepository` | `delete_sessions_by_ids` | `(session_ids: list[str]) -> None` | E |
| `PipelineRepository` | `__init__` | `(session: AsyncSession) -> None` | C |
| `PipelineRepository` | `upsert_pipeline_state` | `(library_id: int, state_key: str, state_data: dict) -> None` | C |
| `PipelineRepository` | `get_state` | `(library_id: int, state_key: str) -> PipelineStateRow \| None` | C |
| `PipelineRepository` | `update_pipeline_state` | `(library_id: int, state_key: str, state_data: dict) -> None` | C |
| `PipelineRepository` | `delete_pipeline_state` | `(library_id: int) -> int` | C |
| `PipelineRepository` | `list_libraries_in_pipeline_state` | `(state_key: str, state_value: str) -> list[int]` | C |
| `PipelineRepository` | `count_pipeline_states` | `() -> int` | C |
| `PipelineRepository` | `list_file_docs_in_state` | `(state: str, *, limit: int \| None = None) -> list[LibraryFileRow]` | C |
| `PipelineRepository` | `get_state_edges_for_files` | `(file_ids: list[int]) -> list[dict]` | C |
| `VectorRepo` | `__init__` | `(session: AsyncSession) -> None` | D |
| `VectorRepo` | `insert_embedding` | `(file_id: int, backbone_id: str, model_id: str, embedding_vector: list[float], genres: list[str] \| None = None) -> EmbeddingRecord` | D |
| `VectorRepo` | `find_nearest` | `(embedding: list[float], backbone_id: str, limit: int = 10, ef_search: int = 200) -> list[SimilarResult]` | D |
| `VectorRepo` | `drain_hot_to_cold` | `(backbone_id: str) -> int` | D |
| `VectorRepo` | `get_embeddings_for_file` | `(file_id: int) -> list[EmbeddingRecord]` | D |
| `VectorRepo` | `count_cold_embeddings` | `(backbone_id: str) -> int` | D |
| `VectorRepo` | `get_embedding_stats` | `(backbone_id: str) -> dict[str, int]` | D |
| `VectorRepo` | `delete_all_embeddings` | `() -> None` | D |
| `VectorRepo` | `delete_embeddings_for_file` | `(file_id: int) -> None` | D |
| `VectorRepo` | `truncate_embeddings` | `() -> None` | D |
| `ModelRepo` | `__init__` | `(session: AsyncSession) -> None` | D |
| `ModelRepo` | `get_model` | `(model_id: str) -> ModelRecord \| None` | D |
| `ModelRepo` | `get_model_by_path` | `(path: str) -> ModelRecord \| None` | D |
| `ModelRepo` | `upsert_model` | `(data: dict) -> ModelRecord` | D |
| `ModelRepo` | `delete_model` | `(model_id: str) -> None` | D |
| `ModelRepo` | `list_models` | `() -> list[ModelRecord]` | D |
| `ModelRepo` | `count_models` | `() -> int` | D |
| `ModelRepo` | `get_models_by_ids` | `(model_ids: list[str]) -> list[ModelRecord]` | D |
| `ModelRepo` | `get_enabled_models` | `() -> list[ModelRecord]` | D |
| `ModelRepo` | `get_by_backbone` | `(backbone_id: str) -> list[ModelRecord]` | D |
| `ModelRepo` | `update_model` | `(model_id: str, fields: dict) -> None` | D |
| `OutputRepo` | `__init__` | `(session: AsyncSession) -> None` | D |
| `OutputRepo` | `store_output_stream` | `(file_id: int, model_id: str, status: str) -> OutputStreamRecord` | D |
| `OutputRepo` | `store_model_output` | `(file_id: int, model_id: str, output_data: dict) -> ModelOutputRecord` | D |
| `OutputRepo` | `get_outputs_for_file` | `(file_id: int) -> list[ModelOutputRecord]` | D |
| `OutputRepo` | `list_model_outputs` | `(model_id: str) -> list[ModelOutputRecord]` | D |
| `OutputRepo` | `delete_outputs_for_model` | `(model_id: str) -> int` | D |
| `OutputRepo` | `get_output` | `(output_id: int) -> ModelOutputRecord \| None` | D |
| `OutputRepo` | `delete_outputs_for_file` | `(file_id: int) -> int` | D |
| `OutputRepo` | `delete_output` | `(output_id: int) -> None` | D |
| `CalibrationRepo` | `__init__` | `(session: AsyncSession) -> None` | D |
| `CalibrationRepo` | `get_state` | `(model_id: str) -> CalibrationStateRecord \| None` | D |
| `CalibrationRepo` | `set_state` | `(model_id: str, state_data: dict) -> CalibrationStateRecord` | D |
| `CalibrationRepo` | `record_history` | `(model_id: str, event: str, data: dict) -> CalibrationHistoryRecord` | D |
| `CalibrationRepo` | `get_history` | `(model_id: str) -> list[CalibrationHistoryRecord]` | D |
| `CalibrationRepo` | `list_states` | `() -> list[CalibrationStateRecord]` | D |
| `CalibrationRepo` | `list_states_with_models` | `() -> list[dict]` | D |
| `CalibrationRepo` | `delete_state` | `(calibration_id: int) -> None` | D |
| `CalibrationRepo` | `truncate_states` | `() -> None` | D |
| `CalibrationRepo` | `truncate_history` | `() -> None` | D |
| `NavidromeRepo` | `__init__` | `(session: AsyncSession) -> None` | D |
| `NavidromeRepo` | `upsert_track` | `(nd_id: str, title: str \| None, artist: str \| None, album: str \| None, file_path: str \| None) -> NdTrackRecord` | D |
| `NavidromeRepo` | `map_track_to_file` | `(nd_id: str, file_id: int) -> None` | D |
| `NavidromeRepo` | `get_mapped_file` | `(nd_id: str) -> int \| None` | D |
| `NavidromeRepo` | `resolve_file_to_nd_track` | `(file_id: int) -> str \| None` | D |
| `NavidromeRepo` | `bulk_upsert_tracks` | `(nd_ids: list[str]) -> int` | D |
| `NavidromeRepo` | `bulk_map_tracks` | `(mappings: list[dict[str, str]]) -> int` | D |
| `NavidromeRepo` | `record_play` | `(nd_id: str, user_id: str \| None, played_at: int, file_id: int \| None) -> int` | D |
| `NavidromeRepo` | `get_top_plays` | `(user_id: str, top_n: int) -> list[NdPlayRecord]` | D |
| `NavidromeRepo` | `delete_tracks_for_file` | `(file_id: int) -> int` | D |
| `NavidromeRepo` | `get_track` | `(track_id: str) -> NdTrackRecord \| None` | E |
| `NavidromeRepo` | `list_nd_track_keys` | `() -> list[str]` | E |
| `EmbeddingStreamRepository` | `__init__` | `(session: AsyncSession) -> None` | D |
| `EmbeddingStreamRepository` | `upsert_stream` | `(file_id: int, backbone: str, stream_payload: dict) -> EmbeddingStreamRecord` | D |
| `EmbeddingStreamRepository` | `get_stream` | `(file_id: int, backbone: str) -> EmbeddingStreamRecord \| None` | D |
| `EmbeddingStreamRepository` | `list_by_backbone` | `(backbone: str, *, limit: int \| None = None, offset: int = 0) -> list[EmbeddingStreamRecord]` | D |
| `EmbeddingStreamRepository` | `delete_for_file` | `(file_id: int) -> None` | D |

---

## Engine Contracts

_To be populated after Part A._

| Contract | Details | Plan |
| --- | --- | --- |
| `create_pg_engine(database_url: str) -> AsyncEngine` | pool_size=5, max_overflow=10, pool_pre_ping=True, statement_timeout=30000ms, command_timeout=30s | A |
| `async_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]` | expire_on_commit=False | A |
| `get_session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession, None]` | async generator with asyncio.shield() on close to prevent connection leaks | A |
| `Base` (declarative base) | SQLAlchemy 2.x declarative base in `nomarr.persistence.models.base` | A |

---

## SQL Primitives (Tier 1)

_Populated after Part B. These are the engine-agnostic CRUD building blocks used by all Tier 2 repositories (Parts C, D)._

| Function | Signature | Notes | Plan |
| --- | --- | --- | --- |
| `select_by_key` | `(table: Table, key_val: Any, *, session: AsyncSession, key_col: str = "id") -> Row \| None` | Returns `None` when no match | B |
| `select_many_by_keys` | `(table: Table, keys: list, *, session: AsyncSession, key_col: str = "id") -> list[Row]` | Empty keys → `[]`; missing keys silently omitted | B |
| `insert_one` | `(table: Table, data: dict, *, session: AsyncSession) -> Row` | Raises `DuplicateKeyError` on constraint violation | B |
| `upsert_by_field` | `(table: Table, field: str, match_val: Any, data: dict, *, session: AsyncSession) -> Row` | `ON CONFLICT (field) DO UPDATE SET ...` | B |
| `update_by_field` | `(table: Table, field: str, match_val: Any, data: dict, *, session: AsyncSession) -> Row \| None` | Returns `None` when no match | B |
| `delete_by_key` | `(table: Table, key_val: Any, *, session: AsyncSession, key_col: str = "id") -> None` | No error when key missing | B |
| `batch_upsert` | `(table: Table, data_list: list[dict], conflict_fields: list[str], *, session: AsyncSession) -> list[Row]` | Transactional; empty list → `[]` | B |
| `is_table_empty` | `(table: Table, *, session: AsyncSession) -> bool` | `True` when count == 0 | B |
| `map_sqlalchemy_error` | `(exc: SQLAlchemyError) -> PersistenceError` | `IntegrityError` → `DuplicateKeyError`; other → `PersistenceError` | B |

---

## DTOs

_Populated as DTOs are created or adapted._

| DTO | Module | Fields | Plan |
| --- | --- | --- | --- |
| `LibraryRow` | `nomarr.helpers.dto.repo_dto` | `id: int, name: str, path: str, library_type: str, auto_tag: int, auto_curate: int, created_at: int, updated_at: int` | C |
| `LibraryFileRow` | `nomarr.helpers.dto.repo_dto` | `id: int, library_id: int, folder_id: int \| None, path: str, normalized_path: str, file_size: int, modified_time: int, duration_seconds: float \| None, chromaprint: str \| None, needs_tagging: int, is_valid: int, tagged: int, calibration_hash: str \| None, write_claimed_by: str \| None, last_tagged_at: int \| None, scanned_at: int \| None, created_at: int` | C |
| `LibraryFolderRow` | `nomarr.helpers.dto.repo_dto` | `id: int, library_id: int, parent_id: int \| None, path: str, name: str \| None` | C |
| `TagRow` | `nomarr.helpers.dto.repo_dto` | `id: int, name: str, value: str, namespace: str, parent_tag_id: int \| None, source: str, confidence: float \| None, tier: int \| None, created_at: int` | C |
| `FileTagRow` | `nomarr.helpers.dto.repo_dto` | `id: int, file_id: int, tag_id: int, confidence: float, source: str, created_at: int` | C |
| `LibraryScanRow` | `nomarr.helpers.dto.repo_dto` | `id: int, library_id: int, scan_type: str, status: str, started_at: int, finished_at: int \| None, files_found: int, files_processed: int, error: str \| None` | C |
| `FileStateRow` | `nomarr.helpers.dto.repo_dto` | `id: int, name: str, description: str \| None` | C |
| `FileStateAssignmentRow` | `nomarr.helpers.dto.repo_dto` | `id: int, file_id: int, state_id: int, created_at: int` | C |
| `LockRow` | `nomarr.helpers.dto.repo_dto` | `key: str, value: dict` | C |
| `HealthRow` | `nomarr.helpers.dto.repo_dto` | `id: int, worker_id: str, status: str, last_seen: int` | C |
| `MetaRow` | `nomarr.helpers.dto.repo_dto` | `key: str, value: dict` | C |
| `SessionRow` | `nomarr.helpers.dto.repo_dto` | `id: str, data: dict, expires_at: int` | C |
| `WorkerClaimRow` | `nomarr.helpers.dto.repo_dto` | `id: int, worker_id: str, key: str, value: dict, claimed_at: int` | C |
| `PipelineStateRow` | `nomarr.helpers.dto.repo_dto` | `id: int, library_id: int, state_key: str, state_data: dict, updated_at: int` | C |
| `EmbeddingRecord` | `nomarr.helpers.dto.vector_repo_dto` | `id: int, file_id: int, backbone_id: str, tier: str, embed_dim: int, model_suite_hash: str \| None, num_segments: int \| None, segmentation_hash: str \| None, genres: list[str] \| None, created_at: int, updated_at: int` | D |
| `SimilarResult` | `nomarr.helpers.dto.vector_repo_dto` | `file_id: int, backbone_id: str, distance: float` | D |
| `ModelRecord` | `nomarr.helpers.dto.model_repo_dto` | `id: str, model_type: str, backbone_id: str, enabled: int, created_at: int, updated_at: int` | D |
| `OutputStreamRecord` | `nomarr.helpers.dto.output_repo_dto` | `id: int, file_id: int, model_id: str, status: str, created_at: int` | D |
| `ModelOutputRecord` | `nomarr.helpers.dto.output_repo_dto` | `id: int, file_id: int, model_id: str, output_data: dict, created_at: int` | D |
| `CalibrationStateRecord` | `nomarr.helpers.dto.calibration_repo_dto` | `id: int, model_id: str, state_data: dict, updated_at: int` | D |
| `CalibrationHistoryRecord` | `nomarr.helpers.dto.calibration_repo_dto` | `id: int, model_id: str, event: str, data: dict, created_at: int` | D |
| `NdTrackRecord` | `nomarr.helpers.dto.navidrome_repo_dto` | `id: str, title: str \| None, artist: str \| None, album: str \| None, file_path: str \| None, created_at: int` | D |
| `NdPlayRecord` | `nomarr.helpers.dto.navidrome_repo_dto` | `nd_id: str, file_id: int \| None, playcount: int, last_played: int` | D |
| `EmbeddingStreamRecord` | `nomarr.helpers.dto.embedding_stream_repo_dto` | `id: int, file_id: int, backbone: str, patches_emb: bytes, created_at: int, updated_at: int` | D |

---

## API Contracts (Unchanged)

All existing API contracts preserved. No new endpoints, no changed request/response shapes. Internal delegation changes only.

---

## Decisions Made

| Decision | Rationale | Plan |
| --- | --- | --- |
| halfvec for embeddings | Saves 50% storage, identical recall (0.987) in pgvector 0.7.0 benchmarks | DD |
| strict_order for all ANN | Exact distance ordering required per user decision (Q2) | DD |
| dual-driver (asyncpg + psycopg2) | psycopg2 needed for Alembic `CREATE INDEX CONCURRENTLY` autocommit | DD |
| one baseline Alembic migration | V1 schema as single baseline; normal migrations from V2 onward | DD |
| no SQLite for repo tests | Repo layer depends on PG-specific types (ARRAY, JSONB, halfvec, HNSW operators) | DD |
| ON DELETE CASCADE for all FKs | Replaces manual cascade AQL in `remove_library()` | DD |
| single embeddings table | `backbone_id` + `tier` columns replace dynamic per-backbone collections | DD |
| GIN trigram indexes on path and tag name | pg_trgm fuzzy search for music library queries | DD |
| maintenance_work_mem = 2 GB | Prevent disk-fallback during HNSW builds; formula: 60% RAM / (1 + workers) | DD |

---

## Part F: Database Class & Upstream Layer Contracts

_Populated after Part F planning. These contracts describe the rewritten `Database` class and the upstream layer adaptation._

### Database Class (PostgreSQL-backed)

| Attribute / Method | Old (ArangoDB) | New (PostgreSQL) | Notes |
| --- | --- | --- | --- |
| `Database.__init__` | Creates `SafeDatabase` via `create_arango_client()`, instantiates 11 `*AqlOperations` | Creates `AsyncEngine` via `create_pg_engine()`, creates `async_sessionmaker`, constructs Part E facades (`LibraryDb`, `MlDb`, `AppDb`) from repository classes | Constructor signature unchanged for upstream compatibility |
| `db.library` | `LibraryDb` facade wrapping `LibrariesAqlOperations` | `LibraryDb` facade wrapping `LibraryRepository` + `FileRepository` + `FolderRepository` + `FileStateRepository` + `TagRepository` + `ScanRepository` + `PipelineRepository` | Same public API, different backend |
| `db.ml` | `MlDb` facade wrapping `VectorsAqlOperations` + `MlModelsAqlOperations` + `MlStreamsAqlOperations` + `MlEmbeddingStreamsAqlOperations` | `MlDb` facade wrapping `VectorRepo` + `ModelRepo` + `OutputRepo` + `CalibrationRepo` + `EmbeddingStreamRepository` | Same public API, different backend |
| `db.app` | `AppDb` facade wrapping `AppAqlOperations` | `AppDb` facade wrapping `AppRepository` + `NavidromeRepo` | Same public API, different backend |
| `db.db` | `SafeDatabase` instance | **REMOVED** | Any code accessing `db.db` will break |
| `db.libraries_aql` | `LibrariesAqlOperations` | **REMOVED** | Use `db.library.*` facade methods |
| `db.library_files_aql` | `LibraryFilesAqlOperations` | **REMOVED** | Use `db.library.*` facade methods |
| `db.file_states_aql` | `FileStatesAqlOperations` | **REMOVED** | Use `db.library.*` facade methods |
| `db.tags_aql` | `TagsAqlOperations` | **REMOVED** | Use `db.library.*` facade methods |
| `db.vectors_aql` | `VectorsAqlOperations` | **REMOVED** | Use `db.ml.*` facade methods |
| `db.scan_aql` | `ScanAqlOperations` | **REMOVED** | Use `db.library.*` facade methods |
| `db.navidrome_aql` | `NavidromeAqlOperations` | **REMOVED** | Use `db.app.*` facade methods |
| `db.ml_models_aql` | `MlModelsAqlOperations` | **REMOVED** | Use `db.ml.*` facade methods |
| `db.ml_streams_aql` | `MlStreamsAqlOperations` | **REMOVED** | Use `db.ml.*` facade methods |
| `db.ml_embedding_streams_aql` | `MlEmbeddingStreamsAqlOperations` | **REMOVED** | Use `db.ml.*` facade methods |
| `db.app_aql` | `AppAqlOperations` | **REMOVED** | Use `db.app.*` facade methods |
| `Database.get_version()` | Reads `CollectionNames.META` via AQL | `AppDb.get_meta("version")` via repository | Returns same value |
| `Database.set_version()` | Writes `CollectionNames.META` via AQL | `AppDb.upsert_meta("version", ...)` via repository | Same semantics |
| Adapter: `_MigrationsAdapter` | Wraps `AppAqlOperations` migration methods | Wraps `AppDb` migration methods | Same public API |
| Adapter: `_MlCapacityAdapter` | Wraps `MlModelsAqlOperations` capacity methods | Wraps `MlDb` capacity methods | Same public API |
| Adapter: `_VramPromisesAdapter` | Wraps `AppAqlOperations` VRAM methods | Wraps `AppDb` VRAM methods | Same public API |

### Upstream Layer Changes

| Layer | Files Affected | Changes |
| --- | --- | --- |
| Services | 32 files in `nomarr/services/` | Remove `Database` type annotations where not needed; remove "ArangoDB" from docstrings; verify no direct AQL attribute access |
| Workflows | 37 files in `nomarr/workflows/` | Same as services; replace `arango_bootstrap_comp` imports with PostgreSQL bootstrap |
| Interfaces | `nomarr/interfaces/api/id_codec.py`, `nomarr/interfaces/api/types/library_types.py`, `nomarr/interfaces/api/types/navidrome_types.py`, `nomarr/interfaces/api/types/ml_types.py` | Rewrite `id_codec.py` for integer IDs (no "collection/key" encoding); remove "ArangoDB" from docstrings and type comments |
| Components | 65+ files in `nomarr/components/` | Replace `CollectionNames` references with SQLAlchemy model classes or string table names; replace `DatabaseLike` with `AsyncSession`; remove `schema_types` imports; migrate any direct AQL attribute access to facade methods |
| App bootstrap | `nomarr/app.py` | Replace `wait_for_arango` + `arango_first_run_comp` with PostgreSQL bootstrap (`wait_for_postgres` + `alembic upgrade head`); update `validate_environment()` for `DATABASE_URL` instead of `ARANGO_HOST` |

### Files Deleted in Part F

| Path | Lines | Reason |
| --- | --- | --- |
| `nomarr/persistence/aql/` (entire directory) | ~420 | Replaced by `sql/primitives.py` (Part B) |
| `nomarr/persistence/arango_client.py` | ~188 | Replaced by `pg_engine.py` (Part A) |
| `nomarr/persistence/schema/` (entire directory) | ~370 | Replaced by SQLAlchemy models (Part A) + Alembic |
| `nomarr/persistence/schema_types.py` | ~437 | Replaced by single `Embedding` model (Part A) |
| `nomarr/persistence/models/base.py` | ~50 | ArangoDocument/ArangoEdge Pydantic classes; replaced by SQLAlchemy `Base` (Part A) |
| `nomarr/persistence/models/tag.py` | ~30 | Pydantic Tag/SongHasTagsEdge; replaced by SQLAlchemy `Tag` model (Part A) |
| `nomarr/persistence/database/*_aql.py` (8 files) | ~2,500 | Replaced by `*_repo.py` repository classes (Parts C/D) |
| `nomarr/persistence/database/library_files_aql/` (5 files) | ~1,200 | Replaced by `FileRepository` (Part C) |
| `nomarr/persistence/database/tags_aql/` (6 files) | ~1,000 | Replaced by `TagRepository` (Part C) |
| `nomarr/persistence/database/app_aql/` (5 files) | ~800 | Replaced by `AppRepository` (Part C) |
| `nomarr/components/platform/arango_bootstrap_comp.py` | ~278 | Replaced by Alembic migrations + PostgreSQL bootstrap |
| `nomarr/components/platform/arango_first_run_comp.py` | ~150 | Replaced by Alembic baseline migration |
| `nomarr/migrations/V*.py` (21 files, V001–V038) | ~2,000 | Replaced by Alembic migrations (Part A) |

### Dependencies Removed

| Dependency | File | Reason |
| --- | --- | --- |
| `python-arango>=8.0.0` | `pyproject.toml` line 36 | ArangoDB driver no longer needed |
| `nomarr-arangodb` service | `docker/compose.yaml` lines 40–57 | ArangoDB container no longer needed |
| `ARANGO_*` env vars | `docker/compose.yaml`, `docker/nomarr.env` | Replaced by `DATABASE_URL` |

---

## Test Infrastructure Decisions

_Populated after Part G planning._

| Decision | Details | Plan |
| --- | --- | --- |
| testcontainers for PG fixture | `PostgresContainer("pgvector/pgvector:pg17")` session-scoped, `Base.metadata.create_all()` for schema | G |
| function-scoped rollback | Per-test `AsyncSession` with transaction begin/rollback for isolation | G |
| no SQLite for repo tests | Repos depend on ARRAY, JSONB, halfvec, HNSW `<=>` — SQLite cannot approximate | DD, G |
| `hnsw_build` marker | Heavy HNSW recall tests; excluded locally via `pytest -m "not hnsw_build"` | G |
| `requires_pg` marker | Marks tests needing the ephemeral PostgreSQL container | G |
| CI RAM: 6 GB | `docker-compose.ci.yml` sets `mem_limit: 6g` for HNSW builds | G |
| recall threshold: ≥ 0.95 | At ef_search=200 on 10K synthetic 512-dim vectors vs brute-force | DD, G |
| drain threshold: < 5 seconds | 1K hot→cold drain operation | DD, G |
| pg_trgm threshold: ≥ 0.60 | Typo queries ("Abby Road" → "Abbey Road") | DD, G |
| cascade test scale: 50K files | Single-transaction library deletion with zero orphaned rows | DD, G |
