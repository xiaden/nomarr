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

- [ ] CREATE `analyze_file_wf.py` - Extract ML inference from process_file_wf (audio loading, embedding, prediction, DB storage, NO file I/O)
- [x] CREATE `write_file_tags_wf.py` - Write tags from DB to file based on mode
- [ ] UPDATE `process_file_wf.py` - Make thin wrapper calling analyze → write (backward compat)

**Notes:** `write_file_tags_workflow` exists with correct signature. `analyze_file_wf` not yet extracted - process_file_wf still does both inference and write.

### Phase 3: Service Layer

- [ ] UPDATE `discovery_worker.py` - Replace `process_file_wf` with `analyze_file_wf`
- [x] ADD `reconcile_library()` to `tagging_svc.py`
- [x] ADD `get_reconcile_status()` to `tagging_svc.py`

**Notes:** TaggingService has both methods. DiscoveryWorker still calls process_file_wf (not yet split).

### Phase 4: Interface Layer

- [x] ADD `POST /api/web/libraries/{library_id}/reconcile-tags` endpoint
- [x] ADD `PATCH /api/web/libraries/{library_id}/write-mode` endpoint
- [x] ADD `GET /api/web/libraries/{library_id}/reconcile-status` endpoint

**Notes:** All routes exist in library_if.py.

### Phase 5: Scanning Integration

- [x] ADD `read_nomarr_namespace()` to `tagging_reader_comp.py`
- [x] ADD `infer_write_mode_from_tags()` to `tagging_reader_comp.py`
- [ ] UPDATE scanning workflow to set `has_nomarr_namespace` and infer `last_written_mode` from on-disk keys

**Notes:** Reader component has both functions. Scanning workflow not yet updated to call them.

### Phase 6: Frontend

- [ ] Add write mode dropdown to library config in `LibraryManagement.tsx`
- [ ] Add mode change handler with reconciliation confirmation
- [ ] Add "Reconcile Tags" button showing pending count

**Notes:** No frontend changes detected yet.

---

## Completion Criteria

- [ ] DiscoveryWorker never writes to audio files (calls analyze_file_wf only)
- [ ] After ML, file is mismatched (derived from `last_written_mode` != current state)
- [x] Mode `none` clears namespace, `minimal` writes moods only, `full` writes all
- [x] Reconciliation is idempotent
- [x] Non-Nomarr tags never touched
- [x] All writes use `TagWriter.write_safe()` (atomic copy-modify-verify-replace)
- [x] All supported formats work: MP3, M4A/MP4/M4B, FLAC, OGG, Opus
- [ ] Scanning sets `has_nomarr_namespace` and infers `last_written_mode`
- [ ] Mode change triggers reconciliation prompt when files exist
- [ ] Calibration change triggers reconciliation for files using mood tags
- [x] Claim mechanism prevents duplicate writes
- [ ] Frontend has write mode dropdown and reconcile button
