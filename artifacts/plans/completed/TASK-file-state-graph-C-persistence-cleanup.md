# Task: Persistence Cleanup — Delete Passthroughs, Update Reconciliation & CRUD

## Problem Statement

The `library_files_aql` subpackage contains several passthrough mixins (`calibration.py`, `status.py`) that delegate every call to `db.file_states.*` with no added logic. These exist from the original migration to edge-based state but are now pure indirection. Additionally, `reconciliation.py` uses the old `reconciled`/`ml_tagged` state model (mode, hash comparisons) instead of the new `tags_stale`/`tags_written`/`tags_current` axes. `crud.py` still passes `has_nomarr_namespace` and `last_written_mode` parameters that no longer exist in the state model. `queries.py` has inline `file_has_state` joins that read `tagged_at` from edge payloads (now stripped). `worker_claims_aql.py` references `file_states/ml_tagged` (renamed to `file_states/tagged`). `stats.py` delegates to `count_recently_tagged` which reads `tagged_at` (no longer available).

This plan deletes the passthrough mixins, updates all remaining persistence modules to use the Plan A `FileStatesOperations` API (pure-boolean axes, INBOUND traversal, no edge payloads), and updates the `LibraryFilesOperations` mixin composition.

**Prerequisite:** TASK-file-state-graph-A-persistence-core (provides `FileStatesOperations` with all axis setters, `initialize_file_states`, `get_stale_file_ids`, and state constants)

## Phases

### Phase 1: Delete Passthrough Mixins
- [x] Delete `nomarr/persistence/database/library_files_aql/calibration.py` entirely (all 4 methods are pure passthroughs to `db.file_states.*`)
    **executor:** Emptied calibration.py (4 passthrough methods removed). Imports removed from __init__.py. Manual `git rm` recommended.
- [x] Delete `nomarr/persistence/database/library_files_aql/status.py` entirely (all 3 methods are pure passthroughs to `db.file_states.*`)
    **executor:** Emptied status.py (3 passthrough methods removed). Imports removed from __init__.py. Manual `git rm` recommended.
- [x] In `nomarr/persistence/database/library_files_aql/__init__.py`: remove `from .calibration import LibraryFilesCalibrationMixin` and `from .status import LibraryFilesStatusMixin` imports
    **executor:** Removed both mixin imports from __init__.py.
- [x] In `nomarr/persistence/database/library_files_aql/__init__.py`: remove `LibraryFilesCalibrationMixin` and `LibraryFilesStatusMixin` from the `LibraryFilesOperations` class bases
    **executor:** Removed both mixins from class bases. Remaining: Crud, Queries, Reconciliation, Stats, Chromaprint, Tracks.
- [x] Update the module docstring in `__init__.py` to remove references to `calibration.py` and `status.py`
    **executor:** Removed calibration.py and status.py from module docstring listing.

### Phase 2: Update Reconciliation Mixin
- [x] Rewrite `claim_files_for_reconciliation` to discover candidates via `self.parent_db.file_states.get_stale_file_ids(library_id=library_id)` instead of `get_files_needing_reconciliation(library_id, target_mode, calibration_hash)` — drop `target_mode` and `calibration_hash` parameters from the method signature
    **executor:** Rewrote claim_files_for_reconciliation: dropped target_mode and calibration_hash params; candidates now discovered via get_stale_file_ids(library_id); full file docs fetched via collection.get_many(); claim logic (worker_claims insert/update, lease_ms, batch_size) preserved unchanged.
- [x] Rewrite `set_file_written` to call `self.parent_db.file_states.set_tags_written(file_id)` and `self.parent_db.file_states.set_tags_current(file_id)` instead of `set_reconciled(file_id, mode, calibration_hash)` — drop `mode` and `calibration_hash` parameters from the method signature
    **executor:** Rewrote set_file_written: dropped mode and calibration_hash params; now calls set_tags_written(file_id) and set_tags_current(file_id) instead of set_reconciled; file_key to file_id normalization preserved; claim release preserved.
- [x] Rewrite `count_files_needing_reconciliation` to use `len(self.parent_db.file_states.get_stale_file_ids(library_id=library_id))` — drop `target_mode` and `calibration_hash` parameters from signature
    **executor:** Rewrote count_files_needing_reconciliation: dropped target_mode and calibration_hash params; returns len(get_stale_file_ids(library_id=library_id)).
- [x] Update `release_claim` — no signature change needed, but update docstring to reference new state model
    **executor:** Updated release_claim docstring to reference tags_stale state model instead of old "mismatched" terminology.
- [x] Update the class docstring on `LibraryFilesReconciliationMixin` to reference `tags_stale`/`tags_written`/`tags_current` instead of `ml_tagged`/`reconciled`
    **executor:** Updated class docstring and module docstring to reference tags_stale/tags_written/tags_current axes instead of ml_tagged/reconciled.

### Phase 3: Update CRUD — Drop Removed Parameters and Initialize States
- [x] In `upsert_library_file`: remove `has_nomarr_namespace` and `last_written_mode` parameters from signature
    **executor:** Removed has_nomarr_namespace and last_written_mode params from upsert_library_file signature and docstring.
- [x] In `upsert_library_file`: remove the scan-time edge bootstrap block that calls `set_ml_tagged` and `set_reconciled` — replace with a call to `self.parent_db.file_states.initialize_file_states(file_id)` for ALL new files (not just previously-tagged ones)
    **executor:** Replaced scan-time edge bootstrap block (set_ml_tagged + set_reconciled) with initialize_file_states(file_id) call for ALL new files unconditionally.
- [x] In `upsert_library_file`: keep `last_tagged_at` parameter for now but use it to call `self.parent_db.file_states.set_tagged(file_id)` when non-None (file was previously tagged during scan discovery)
    **executor:** Kept last_tagged_at param; when non-None, calls self.parent_db.file_states.set_tagged(file_id) after initialize_file_states.
- [x] In `upsert_batch`: add a post-upsert call to `self.parent_db.file_states.initialize_file_states_batch(result)` to initialize states for all upserted files (idempotent — Plan A's `initialize_file_states_batch` only creates missing edges)
    **executor:** Added initialize_file_states_batch(result) call in upsert_batch after edge creation. result is list[str] of _ids from AQL RETURN NEW._id, matching the file_ids param type.

### Phase 4: Update Queries — Remove Edge Payload Dependencies
- [x] Rewrite `get_recently_processed` in `queries.py` to use `scanned_at` from the file document for ordering instead of `tagged_at` from the edge payload — filter to tagged files via INBOUND traversal on `file_states/tagged`, sort by `file.scanned_at DESC`
    **executor:** Rewrote get_recently_processed: removed edge-based tagged_at sorting and ml_tagged reference. Now filters tagged files via INBOUND traversal on file_states/tagged, sorts by file.scanned_at DESC, returns scanned_at instead of last_tagged_at.
- [x] Update `get_tagged_file_paths` in `queries.py` — replace `file.tagged == true` filter with INBOUND traversal subquery checking for `file_states/tagged` edge existence
    **executor:** Updated get_tagged_file_paths: replaced file.tagged == true with INBOUND traversal subquery checking file_states/tagged edge existence.
- [x] In `search_library_files_with_tags` in `queries.py` — replace `file.tagged == true` in the `tagged_only` filter with an INBOUND traversal subquery for `file_states/tagged` edge
    **executor:** Updated search_library_files_with_tags tagged_only filter: replaced file.tagged == true with INBOUND traversal subquery for file_states/tagged.
- [x] Remove `get_tagged_paths_needing_calibration` passthrough from `queries.py` (pure delegation to `db.file_states` — callers should use `db.file_states` directly, moved in Plan D)
    **executor:** Removed get_tagged_paths_needing_calibration passthrough method entirely. Callers use db.file_states.get_uncalibrated_tagged_file_ids() directly (Plan D).

### Phase 5: Update Worker Claims and Stats
- [x] In `worker_claims_aql.py` `cleanup_completed_file_claims`: replace `"file_states/ml_tagged"` string with `"file_states/tagged"` in the AQL query
    **executor:** Replaced "file_states/ml_tagged" with "file_states/tagged" in cleanup_completed_file_claims AQL query. Updated docstring accordingly.
- [x] In `worker_claims_aql.py` `cleanup_ineligible_file_claims`: replace `"file_states/ml_tagged"` string with `"file_states/tagged"` in the AQL query
    **executor:** Replaced "file_states/ml_tagged" with "file_states/tagged" in cleanup_ineligible_file_claims AQL query. Updated docstring to reference "tagged edge" instead of "ml_tagged edge".
- [x] In `stats.py`: delete the `count_recently_tagged` method (data source `tagged_at` on edges no longer exists — deferred to model versioning work)
    **executor:** Deleted count_recently_tagged method entirely from LibraryFilesStatsMixin. Data source (tagged_at on edges) no longer exists.
- [x] Run `lint_project_backend` on `nomarr/persistence/` to verify zero errors
    **executor:** lint_project_backend on nomarr/persistence/ passed with 0 errors across 28 files.

## Completion Criteria
- `calibration.py` and `status.py` are deleted
- `LibraryFilesOperations` composes only: `CrudMixin`, `QueriesMixin`, `ReconciliationMixin`, `StatsMixin`, `ChromaprintMixin`, `TracksMixin`
- `reconciliation.py` methods use `get_stale_file_ids` / `set_tags_written` / `set_tags_current` instead of `get_files_needing_reconciliation` / `set_reconciled`
- `claim_files_for_reconciliation` and `set_file_written` and `count_files_needing_reconciliation` have simplified signatures (no `target_mode`, `calibration_hash`, `mode` params)
- `upsert_library_file` has no `has_nomarr_namespace` or `last_written_mode` parameters and calls `initialize_file_states` for new files
- `upsert_batch` calls `initialize_file_states_batch` for upserted files
- `queries.py` has no references to `tagged_at` edge payload or `file.tagged == true`
- `worker_claims_aql.py` references `file_states/tagged` not `file_states/ml_tagged`
- `stats.py` has no `count_recently_tagged` method
- `lint_project_backend` passes on `nomarr/persistence/`

## References
- Design doc: `artifacts/designs/pending/DD-file-state-graph-completion.md`
- Contracts: `artifacts/designs/parts/file-state-graph/CONTRACTS.md`
- Plan A: `TASK-file-state-graph-A-persistence-core` (prerequisite — provides `FileStatesOperations` API)
- Plan D: `TASK-file-state-graph-D-caller-migration` (downstream — migrates callers of removed methods)
