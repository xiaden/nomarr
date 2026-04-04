# Task: File State Edges C — Rewrite Reconciliation & Remove Dead Fields

## Problem Statement

Parts A and B established the edge-based state model and migrated status/calibration
queries. This final plan rewrites the **reconciliation** mixin — the most complex
state consumer — and removes the now-dead flat state fields from `library_files`
documents.

The reconciliation mixin has 6 methods that use compound filters across `tagged`,
`is_valid`, `last_written_mode`, `last_written_calibration_hash`, `write_claimed_by`,
`write_claimed_at`, and `has_nomarr_namespace`. These must be rewritten to use:
- `file_has_state` edges for state checks (ml_tagged, reconciled)
- `worker_claims` collection for write claim locking (replacing inline claim fields)

After reconciliation is migrated, all flat state fields are dead and can be removed
from the `upsert_library_file` INSERT/UPDATE templates via a cleanup migration.

**Prerequisite:** TASK-file-state-edges-B-rewrite-status-calibration

## Phases

### Phase 1: Migrate Write Claims to worker_claims
- [x] Extend `worker_claims` collection usage to support reconciliation claims — add a `claim_type` field ("ml" vs "reconcile") to distinguish claim types, update claim creation in `claim_files_for_reconciliation` to use `worker_claims` instead of inline `write_claimed_by`/`write_claimed_at` fields
- [x] Update `set_file_written` to clear the `worker_claims` entry (not inline fields) and call `db.file_states.set_reconciled(file_id, mode, calibration_hash, has_namespace)` to create/update the reconciled edge
- [x] Update `release_claim` to remove the `worker_claims` entry instead of nulling inline fields
- [x] Run `lint_project_backend` on reconciliation.py and all modified callers

### Phase 2: Rewrite Reconciliation Queries
- [x] Rewrite `claim_files_for_reconciliation` to find files with `ml_tagged` edge but no `reconciled` edge (or reconciled edge with wrong `mode`/`calibration_hash`), excluding files with active reconciliation claims in `worker_claims`, instead of the current 5-field compound filter
- [x] Rewrite `count_files_needing_reconciliation` to use the same edge-based filter pattern
- [x] Rewrite `update_nomarr_namespace_flag` to update the `has_namespace` attribute on the `reconciled` edge (or store it as a scan-time attribute on the file document if the file has no reconciled edge yet)
    **Notes:** Dead code (0 callers per Plan A audit). Omitted entirely from the rewritten reconciliation.py.
- [x] Rewrite `infer_last_written_mode` to create a `reconciled` edge with the inferred mode (bootstrap case during scanning)
    **Notes:** Dead code (0 callers per Plan A audit). Omitted entirely from the rewritten reconciliation.py.
- [x] Run `lint_project_backend` on all modified files

### Phase 3: Remove Dead Fields from CRUD
- [x] Remove all dead state fields from `upsert_library_file` INSERT template: `tagged`, `tagged_version`, `needs_tagging`, `last_tagged_at`, `calibration_hash`, `is_valid`, `last_written_mode`, `last_written_calibration_hash`, `last_written_at`, `has_nomarr_namespace`, `write_claimed_by`, `write_claimed_at`; keep only identity and metadata fields
- [x] Remove dead state fields from `upsert_library_file` UPDATE template and `upsert_batch` similarly
    **Notes:** UPDATE template already cleaned in upsert_library_file during P3-S1. `upsert_batch` is a transparent pass-through. Scan workflows (full_wf and quick_wf) updated to pass edge_bootstraps to upsert_scanned_files calls. Accumulator pattern added for truly_new entries across folder batches.
- [x] Update `upsert_library_file` to create initial state edges after insert (e.g., no ml_tagged edge = needs tagging, which is the default); remove `needs_tagging`, `tagged`, `is_valid` params from the method signature
    **Notes:** Edge bootstrap happens in scan_lifecycle_comp.upsert_scanned_files via bootstrap_file_state_edges. upsert_library_file no longer has dead params (needs_tagging, tagged, is_valid removed in P3-S1). The absence of ml_tagged edge inherently means "needs tagging" in the edge model.
- [x] Update `delete_files_for_library` to also cascade-delete `file_has_state` edges for deleted files
    **Notes:** Added file_has_state edge cleanup in delete_files_for_library between song_has_tags and library_files deletions. Updated docstring cascade list to include "4. file_has_state (state edges)".
- [x] Create migration `V017_remove_dead_state_fields.py` that strips the dead flat fields from all existing `library_files` documents (AQL UPDATE to UNSET fields)
    **Warning:** V017 created but has prominent warning: must NOT run until all code paths reading flat fields from library_files documents are migrated to edge queries. Components in file_sync_comp, tagging_writer_comp, write_calibrated_tags_wf, and sync_file_to_library_wf still reference some of these fields. Strips 11 fields using keepNull:false UPDATE pattern.
- [x] Run `lint_project_backend` on all modified files, verify zero errors across the full backend
    **Notes:** All lint clean (only pre-existing navidrome_song_map_aql mypy errors). Full test suite: 388 passed, 2 pre-existing failures (essentia QC + hash collision). Zero new regressions.

## Completion Criteria
- Reconciliation uses `file_has_state` edges and `worker_claims` — no inline claim fields
- All compound state filters replaced with graph-native edge presence/absence queries
- `library_files` documents contain only identity, filesystem, and metadata fields
- Dead state fields removed from all INSERT/UPDATE AQL templates
- Migration V017 strips legacy fields from existing documents
- `lint_project_backend` passes with zero new errors across the full backend
- No persistence method reads or writes any of the 13 removed state fields

## References
- Prerequisite: `plans/TASK-file-state-edges-B-rewrite-status-calibration.md`
- Reconciliation mixin: `nomarr/persistence/database/library_files_aql/reconciliation.py`
- CRUD: `nomarr/persistence/database/library_files_aql/crud.py`
- Worker claims: `nomarr/persistence/database/worker_claims_aql.py`
- FileStatesOperations: `nomarr/persistence/database/file_states_aql.py`
- Part A: `plans/TASK-file-state-edges-A-schema-and-persistence.md`
- Part B: `plans/TASK-file-state-edges-B-rewrite-status-calibration.md`
