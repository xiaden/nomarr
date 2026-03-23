# Database Query Layer

AQL query modules providing typed operations for every ArangoDB collection in Nomarr.

## Responsibilities

- Encapsulate all ArangoDB AQL queries behind typed Python methods
- Provide one `*Operations` class per collection (or logical grouping)
- Handle upserts, bulk operations, and atomic locking patterns
- Export public operations via `__init__.py` for component consumption

## Key Modules

| Module | Purpose |
|--------|--------|
| `calibration_history_aql.py` | `CalibrationHistoryOperations` — drift tracking snapshots |
| `calibration_state_aql.py` | `CalibrationStateOperations` — histogram-based calibration per label |
| `file_states_aql.py` | `FileStatesOperations` — edge-based ML tagging/calibration/reconciliation state |
| `health_aql.py` | `HealthOperations` — component health, heartbeats, restart tracking |
| `libraries_aql.py` | `LibrariesOperations` — library CRUD, scan status, file watchers |
| `library_folders_aql.py` | `LibraryFoldersOperations` — folder-level scan cache |
| `meta_aql.py` | `MetaOperations` — key-value configuration store, GPU snapshots |
| `migrations_aql.py` | `MigrationOperations` — applied migration tracking, crash recovery |
| `ml_capacity_aql.py` | `MLCapacityOperations` — VRAM probe locks and capacity estimates |
| `ml_model_outputs_aql.py` | `MLModelOutputsOperations` — per-activation output vertices and labels |
| `ml_models_aql.py` | `MLModelsOperations` — ONNX model registration and configuration |
| `navidrome_playcounts_aql.py` | `NavidromePlaycountsOperations` — bucketed play counts and edges |
| `navidrome_tracks_aql.py` | `NavidromeTracksOperations` — track vertices, `has_nd_id` edges, ID resolution |
| `segment_scores_stats_aql.py` | `SegmentScoresStatsOperations` — per-head segment-level statistics |
| `sessions_aql.py` | `SessionOperations` — session CRUD with TTL auto-expiry |
| `tag_model_output_aql.py` | `TagModelOutputOperations` — tag → ML output provenance edges |
| `vector_promotion_lock_aql.py` | `VectorPromotionLockOperations` — exclusive hot→cold promotion leases |
| `vectors_track_aql.py` | `VectorsTrackHotOperations` / `VectorsTrackColdOperations` — hot/cold vector storage and ANN search |
| `vram_promises_aql.py` | `VramPromisesOperations` — fleet-wide GPU VRAM placement coordination |
| `worker_claims_aql.py` | `WorkerClaimsOperations` — file processing claim locks |
| `worker_restart_policy_aql.py` | `WorkerRestartPolicyOperations` — restart count and permanent failure tracking |

## Subfolders

| Folder | Purpose |
|--------|--------|
| `library_files_aql/` | 8-module mixin split for `LibraryFilesOperations` (CRUD, queries, stats, etc.) |
| `tags_aql/` | 6-module mixin split for `TagOperations` (CRUD, queries, mood, analytics, etc.) |

## Patterns

- **One class per collection**: Each `*Operations` class takes a `DatabaseLike` handle and owns all AQL for that collection
- **Mixin composition**: Large operation classes (`LibraryFiles`, `Tags`) split across subfolders using Python mixin inheritance
- **Deterministic keys**: `_make_key()` static methods compute stable `_key` values from domain identifiers (SHA-based)
- **Atomic locking**: Probe locks, VRAM promises, and worker claims use AQL `UPSERT`/`INSERT` with unique key constraints

## Access Rule

**Only components may import these modules.** Services, workflows, interfaces, and helpers must not import from `persistence/database/` directly. All database access flows through components.
