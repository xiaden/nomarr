# Task: File State Edges A — Schema, Migration & Persistence Module

## Problem Statement

The `library_files` collection in ArangoDB has become a "God document" — 14 state
fields spanning scan lifecycle, ML tagging, calibration, and tag-write reconciliation
are stored as flat sibling fields on every file document. This causes:

1. **Writer contention:** Scanning, ML tagging, calibration, and reconciliation all
   compete for `_rev` on the same document.
2. **State explosion:** Adding new processing stages means adding more nullable fields
   and updating every query that touches state.
3. **Implicit states:** "Needs tagging" is `needs_tagging == true AND is_valid == true`.
   "Needs reconciliation" is a 5-field compound filter across `tagged`, `last_written_mode`,
   `last_written_calibration_hash`, `write_claimed_by`, `write_claimed_at`, and
   `has_nomarr_namespace`.

### Design: Edge-Based State Model

Replace flat state fields with a graph-native approach:

- **`file_states`** vertex collection with fixed state documents:
  `{_key: "ml_tagged"}`, `{_key: "calibrated"}`, `{_key: "reconciled"}`
- **`file_has_state`** edge collection: `_from: library_files/X → _to: file_states/Y`
  with per-state attributes on the edge document (e.g., `tagged_version`,
  `calibration_hash`, `written_mode`, `timestamp`)
- **Presence of edge = file has reached that state.** Absence = needs processing.
  No negative states, no boolean flags.
- Pushing a file back (e.g., "needs re-tagging") = remove the `ml_tagged` edge.
  The file's existing data is preserved; only the state edge changes.

### What stays on `library_files`:
- Identity: `_key`, `_id`, `library_id`, `path`, `normalized_path`
- Filesystem: `file_size`, `modified_time`, `duration_seconds`, `scanned_at`
- Metadata: `artist`, `album`, `title`
- Audio identity: `chromaprint`

### What moves to edges:
- `tagged`, `tagged_version`, `last_tagged_at`, `needs_tagging` → presence/absence
  of edge to `file_states/ml_tagged` (edge attrs: `version`, `tagged_at`)
- `calibration_hash` → edge to `file_states/calibrated` (edge attr: `hash`)
- `last_written_mode`, `last_written_calibration_hash`, `last_written_at`,
  `has_nomarr_namespace` → edge to `file_states/reconciled` (edge attrs: `mode`,
  `calibration_hash`, `written_at`, `has_namespace`)
- `is_valid` → deprecated, files are hard-deleted (no edge needed)
- `write_claimed_by`, `write_claimed_at` → use existing `worker_claims` collection
  pattern (already used for ML worker claims)

### Edge attribute schemas:

**`ml_tagged` edge:** `{_from, _to, version: str, tagged_at: int}`

**`calibrated` edge:** `{_from, _to, hash: str, calibrated_at: int}`

**`reconciled` edge:** `{_from, _to, mode: str, calibration_hash: str | null, written_at: int, has_namespace: bool}`

This plan (Part A) creates the schema, migration, and new persistence module.
Parts B and C rewrite callers.

## Phases

### Phase 1: Discovery & Validation
- [x] Audit all callers of `mark_file_tagged`, `get_files_needing_tagging`, `discover_next_unprocessed_file`, `library_has_tagged_files` in workflows/services to catalog return value field access patterns — document which fields callers read from returned file dicts
    **Notes:** Callers analysis: mark_file_tagged returns None (2 callers: file_sync_comp wrapper + tests, no field access). get_files_needing_tagging has ZERO callers outside definition (dead code). discover_next_unprocessed_file has 1 caller (worker_discovery_comp.discover_file_for_processing) reading only _id from returned dict. library_has_tagged_files returns bool, callers use only bool. mark_file_invalid/bulk_mark_invalid have 0 callers in workflows/services (dead code candidates).
- [x] Audit all callers of `claim_files_for_reconciliation`, `set_file_written`, `count_files_needing_reconciliation`, `update_nomarr_namespace_flag`, `infer_last_written_mode` in workflows/services to catalog return value field access patterns
    **Notes:** Callers analysis: claim_files_for_reconciliation has 1 caller (tagging_svc.reconcile_library) — reads _key from returned dicts. set_file_written has 1 caller (file_write_comp.finalize_file_write) — no return value used. release_claim (db.library_files) has 2 callers (tagging_svc.reconcile_library error path, file_write_comp.finalize_file_write error path). count_files_needing_reconciliation has 2 callers in tagging_svc (reconcile_library + get_reconcile_status) — uses int return. update_nomarr_namespace_flag: ZERO callers (dead code). infer_last_written_mode: ZERO callers (dead code).
- [x] Audit all callers of `update_calibration_hash`, `update_calibration_hashes_batch`, `clear_all_calibration_hashes`, `get_calibration_status_by_library`, `get_tagged_paths_needing_calibration` in workflows/services
    **Notes:** Callers analysis: update_calibration_hash has 1 caller (ml_calibration_state_comp.py:95), no return used. update_calibration_hashes_batch has 1 caller (ml_calibration_state_comp.py:110), no return used. clear_all_calibration_hashes has 1 caller (ml_calibration_state_comp.py:227), return int used as files_updated count. get_calibration_status_by_library has 1 caller (tagging_svc.py:313), reads library_id/total_files/current_count/outdated_count from returned dicts. get_tagged_paths_needing_calibration has callers in apply_calibration_wf, reads list[str] (just file paths).
- [x] Verify `worker_claims` collection schema and confirm it can be reused for reconciliation write claims (currently used only for ML tagging claims)
    **Notes:** worker_claims schema: _key = "claim_{file_key}", file_id, worker_id, claimed_at. Can reuse for reconciliation with prefix "claim_reconcile_{file_key}". Key finding: cleanup_completed_file_claims (line 136) filters on file.tagged == true OR file.needs_tagging == false, and cleanup_ineligible_file_claims (line 157) filters on file.needs_tagging == false OR file.is_valid == false. Both will need edge-based rewrites in Plan B/C. The collection itself supports multiple claim types via deterministic key prefixes without schema changes.

### Phase 2: Migration & State Vertices
- [x] Create migration `V016_add_file_state_edges.py` — creates `file_states` vertex collection with fixed documents (`ml_tagged`, `calibrated`, `reconciled`), creates `file_has_state` edge collection with indexes: hash index on `_to` (state lookups), persistent index on `(_from, _to)` unique (one state per file per type), persistent index on `_from` (all states for a file)
    **Notes:** Created V016_add_file_state_edges.py. Creates file_states vertex collection (3 fixed docs: ml_tagged, calibrated, reconciled) and file_has_state edge collection with unique (_from, _to) and _to indexes. Fully idempotent following V015 pattern. Lint clean (5 pre-existing mypy errors in navidrome_song_map_aql.py only).
- [x] In the same migration, populate `file_has_state` edges from existing `library_files` state fields: for each file with `tagged == true`, create edge to `file_states/ml_tagged` with `version` and `tagged_at`; for each file with `calibration_hash != null`, create edge to `file_states/calibrated`; for each file with `last_written_mode != null`, create edge to `file_states/reconciled`
    **Notes:** Added _populate_edges() to V016 migration. Backfills edges from flat fields: tagged==true → ml_tagged edge (version, tagged_at), calibration_hash!=null → calibrated edge (hash, calibrated_at=migration_ts), last_written_mode!=null → reconciled edge (mode, calibration_hash, written_at, has_namespace). Uses INSERT ... OPTIONS { ignoreErrors: true } for idempotency via unique (_from,_to) index. Lint clean.
- [x] Write unit tests for migration idempotency (run twice, verify no duplicates or errors)
    **Notes:** Created tests/unit/persistence/test_migration_v016.py with 13 tests across 3 classes: TestMigrationFreshDB (6 tests), TestMigrationIdempotent (4 tests), TestPopulationQueries (3 tests). All passing. Tests verify collection creation, state vertex insertion, index creation, idempotency with duplicate doc/index errors, and correct field usage in population AQL.

### Phase 3: New Persistence Module
- [x] Create `nomarr/persistence/database/file_states_aql.py` with class `FileStatesOperations` exposing: `set_ml_tagged(file_id, version, tagged_at)` (upsert edge to ml_tagged), `clear_ml_tagged(file_id)` (remove edge), `is_ml_tagged(file_id) -> bool`, `get_ml_tagged_edge(file_id) -> dict | None` (returns edge attrs), `get_untagged_file_ids(library_id, limit) -> list[str]` (files without ml_tagged edge)
    **Notes:** Created file_states_aql.py with FileStatesOperations class. ML methods: set_ml_tagged, clear_ml_tagged, is_ml_tagged, get_ml_tagged, get_untagged_file_ids, library_has_tagged_files. All use edge-based UPSERT/REMOVE/FILTER patterns with @@coll bind vars. Lint clean.
- [x] Add calibration methods to `FileStatesOperations`
    **Notes:** Calibration methods implemented in same file: set_calibrated, set_calibrated_batch, clear_calibrated, clear_all_calibrated, get_calibration_status_by_library. Batch uses FOR doc IN @docs with UPSERT pattern.
- [x] Add reconciliation methods to `FileStatesOperations`
    **Notes:** Reconciliation methods implemented: set_reconciled, clear_reconciled, get_files_needing_reconciliation (with dynamic hash clause), count_files_needing_reconciliation. Also added cross-state utility clear_all_states(file_id) for file deletion cleanup.
- [x] Wire `FileStatesOperations` into `Database` class
    **Notes:** Added import and initialization in db.py. Accessible as db.file_states (FileStatesOperations). Lint clean.
- [x] Write unit tests for `FileStatesOperations`
    **Notes:** Created tests/unit/persistence/database/test_file_states_aql.py with 27 tests across 12 classes covering all state operations. All 27 pass. Full suite: 388 passed, 2 pre-existing failures (essentia import QC + hash collision test), 0 new failures. Lint clean. Plan A complete.

## Completion Criteria
- Migration V016 creates `file_states` vertices and `file_has_state` edge collection with correct indexes
- Migration populates edges from existing flat state fields (data preserved)
- `FileStatesOperations` provides complete CRUD
- Accessible as `db.file_states` from the Database class
- `lint_project_backend` passes with zero new errors
- Unit tests pass for migration and persistence module

## References
- Current state fields: `nomarr/persistence/database/library_files_aql/crud.py` (upsert_library_file INSERT template)
- Status mixin: `nomarr/persistence/database/library_files_aql/status.py`
- Reconciliation mixin: `nomarr/persistence/database/library_files_aql/reconciliation.py`
- Calibration mixin: `nomarr/persistence/database/library_files_aql/calibration.py`
- Worker claims collection: `nomarr/persistence/database/worker_claims_aql.py`
- Part B: `plans/TASK-file-state-edges-B-rewrite-status-calibration.md`
- Part C: `plans/TASK-file-state-edges-C-rewrite-reconciliation-cleanup.md`
