# Task: Tag Writing Refactor

## Problem Statement

Decouple ML inference from file tag writing. DB becomes source of truth; files are projections controlled per-library.

**Hard Rules:**
- DB is source of truth - ML writes to DB only; files are projections
- TagWriter already supports reconciliation - `overwrite=True` clears namespace, then writes provided tags
- Mood tags require calibration - Filter out mood-tier tags when calibration is empty
- Never touch non-Nomarr tags - Only `nom:*` namespace is modified

**Mode Definitions:**
| Mode | File Result |
|------|-------------|
| `none` | Remove all `nom:*` tags (call TagWriter with `tags={}`) |
| `minimal` | Only mood-tier tags (`mood-strict`, `mood-regular`, `mood-loose`) - requires calibration |
| `full` | All available tags from DB |

---

## Phases

### Phase 1: Persistence Layer

- [x] Add fields to `library_files_aql.py`: `last_written_mode`, `last_written_calibration_hash`, `last_written_at`, `has_nomarr_namespace`, `write_claimed_by`, `write_claimed_at`
- [x] Add `claim_files_for_reconciliation()` query
- [x] Add `set_file_written()` query  
- [x] Add `release_claim()` query
- [x] Add `count_files_needing_reconciliation()` query
- [x] Add `file_write_mode` field to `libraries_aql.py`
- [x] Add `file_write_mode` to `LibraryDict` DTO

**Notes:** All persistence operations implemented. Claims use worker_id + lease_ms for expiration.

### Phase 2: Workflow Layer

- [x] `process_file_wf.py` already does ML-only (audio loading, embedding, prediction, DB storage, NO file I/O)
- [x] CREATE `write_file_tags_wf.py` - Write tags from DB to file based on mode
- [x] Decoupling complete - `process_file_workflow` docstring explicitly states no file I/O

**Notes:** Original plan assumed `process_file_wf` wrote to files. It doesn't. The separation already exists. Rename to `analyze_file_wf` optional (semantic clarity only).

### Phase 3: Service Layer

- [x] `discovery_worker.py` only calls `process_file_workflow` (ML-only, no file writes)
- [x] ADD `reconcile_library()` to `tagging_svc.py`
- [x] ADD `get_reconcile_status()` to `tagging_svc.py`

**Notes:** DiscoveryWorker → process_file_workflow → DB only. File writes handled by separate reconciliation path via TaggingService.

### Phase 4: Interface Layer

- [x] ADD `POST /api/web/libraries/{library_id}/reconcile-tags` endpoint
- [x] ADD `PATCH /api/web/libraries/{library_id}/write-mode` endpoint
- [x] ADD `GET /api/web/libraries/{library_id}/reconcile-status` endpoint

**Notes:** All routes exist in library_if.py.

### Phase 5: Scanning Integration

- [x] ADD `read_nomarr_namespace()` to `tagging_reader_comp.py`
- [x] ADD `infer_write_mode_from_tags()` to `tagging_reader_comp.py`
- [x] `sync_file_to_library_wf.py` sets `has_nomarr_namespace` and `last_written_mode` (single-file path)
- [x] UPDATE `file_batch_scanner_comp.py` batch scanning to set `has_nomarr_namespace` and `last_written_mode`

**Notes:** Single-file sync path complete. Batch scanning in `file_batch_scanner_comp.py` extracts nom_tags and includes fields in file_entry dict.

### Phase 6: Frontend

- [x] Write mode dropdown exists in `LibraryManagement.tsx` (create/edit form)
- [x] Reconcile button exists with pending count badge and hover status fetch
- [x] API functions exist: `reconcileTags()`, `getReconcileStatus()`, `updateWriteMode()`
- [x] Mode change handler with reconciliation confirmation (uses `updateWriteMode()` with confirmation dialog)
- [x] Confirmation dialog when mode change affects files ("X files need reconciliation. Run now?")

**Notes:** All UI elements connected. Mode changes call `updateWriteMode()`, check `requires_reconciliation`, and prompt user. Calibration changes also trigger reconciliation prompt.

---

## Completion Criteria

- [x] DiscoveryWorker never writes to audio files (calls process_file_workflow which is ML-only)
- [x] After ML, file is mismatched (derived from `last_written_mode` != current state)
- [x] Mode `none` clears namespace, `minimal` writes moods only, `full` writes all
- [x] Reconciliation is idempotent
- [x] Non-Nomarr tags never touched
- [x] All writes use `TagWriter.write_safe()` (atomic copy-modify-verify-replace)
- [x] All supported formats work: MP3, M4A/MP4/M4B, FLAC, OGG, Opus
- [x] Single-file sync sets `has_nomarr_namespace` and infers `last_written_mode`
- [x] Batch scanning sets `has_nomarr_namespace` and infers `last_written_mode`
- [x] Mode change triggers reconciliation prompt when files exist
- [x] Calibration change triggers reconciliation for files using mood tags
- [x] Claim mechanism prevents duplicate writes
- [x] Frontend has write mode dropdown and reconcile button
