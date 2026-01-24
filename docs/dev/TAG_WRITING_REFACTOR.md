# Tag Writing Refactor Plan

## Status: IMPLEMENTATION READY

**Goal**: Decouple ML inference from file tag writing. DB becomes source of truth; files are projections controlled per-library.

---

## Hard Rules

1. **DB is source of truth** - ML writes to DB only; files are projections
2. **TagWriter already supports reconciliation** - `overwrite=True` clears `essentia:*` namespace, then writes provided tags
3. **Mood tags require calibration** - Filter out mood-tier tags (`mood-*`) when calibration is empty, even in `full` mode
4. **Never touch non-Nomarr tags** - Only `essentia:*` namespace is modified ("Nomarr namespace" = `essentia:*` throughout this doc)

---

## Mode Definitions

| Mode | File Result |
|------|-------------|
| `none` | Remove all `essentia:*` tags (call TagWriter with `tags={}`) |
| `minimal` | Only mood-tier tags (`mood-strict`, `mood-regular`, `mood-loose`) - requires calibration |
| `full` | All available tags from DB |

---

## Projection State Model

**Principle**: No explicit "pending work" flag. A file needs reconciliation when its recorded projection state differs from the desired projection state. This is derived at query time.

### Desired State Sources (inputs)
- **Library's `file_write_mode`** - the target mode (`none`, `minimal`, `full`)
- **Current calibration hash** - hash of active calibration state (changes when calibration is created/updated)

### Recorded Projection State (per-file markers)

| Field | Type | Purpose |
|-------|------|---------|
| `last_written_mode` | `"none" \| "minimal" \| "full" \| "unknown" \| null` | Mode used for last write. `null` = never written. `unknown` = inferred from legacy file. |
| `last_written_calibration_hash` | `str \| null` | Calibration hash at time of last write. `null` = never written or pre-hash file. |
| `last_written_at` | `int \| null` | Primitive int, ms since epoch (not DTO) |

### Per-Library Fields (`libraries` collection)
```python
file_write_mode: Literal["none", "minimal", "full"] = "full"
```

### Mismatch Detection Query

A file needs reconciliation when **any** of these conditions is true:

```sql
-- Pseudocode for "find files needing reconciliation"
SELECT f FROM library_files f
JOIN libraries lib ON f.library_id = lib._key
WHERE f.library_id = @library_id
  AND (
    -- Mode mismatch
    f.last_written_mode != lib.file_write_mode
    -- OR calibration mismatch (only matters if mode uses mood tags)
    OR (lib.file_write_mode IN ("minimal", "full") 
        AND f.last_written_calibration_hash != @current_calibration_hash)
    -- OR namespace exists but never tracked (bootstrap case)
    OR (f.has_nomarr_namespace = true AND f.last_written_mode IS NULL)
  )
LIMIT @batch_size
```

**Detection notes**:
- `has_nomarr_namespace` is derived during scanning by checking for namespace key presence (do not hardcode specific tag keys)
- Calibration hash comparison only applies when mode would write mood tags

### Concurrency: Claim Mechanism

Since file selection is derived (no flag to atomically flip), workers must claim files before writing:

| Field | Type | Purpose |
|-------|------|---------|
| `write_claimed_by` | `str \| null` | Worker ID holding claim |
| `write_claimed_at` | `int \| null` | Claim timestamp (ms). Claims expire after configurable lease (e.g., 60s). |

**Claim flow**:
1. Query for mismatched files WHERE `write_claimed_by IS NULL OR write_claimed_at < (now - lease_duration)`
2. Atomically set `write_claimed_by=worker_id, write_claimed_at=now`
3. On write success: clear claim, update `last_written_*` fields
4. On failure: clear claim (file remains mismatched, will be retried)

---

## Existing Assets (Do Not Duplicate)

| Asset | Location | Reuse Notes |
|-------|----------|-------------|
| TagWriter | `nomarr/components/tagging/tagging_writer_comp.py` | Use `write_safe()` for all file writes. Supports MP3, M4A/MP4/M4B, FLAC, OGG, Opus. Clears namespace before writing. |
| SafeWriteComp | `nomarr/components/tagging/safe_write_comp.py` | Called by TagWriter.write_safe(). Atomic copy-modify-verify-replace with chromaprint verification. No changes needed. |
| TagReader | `nomarr/components/tagging/tagging_reader_comp.py` | Extend with `read_nomarr_namespace()` for bootstrap detection. |
| write_calibrated_tags_wf | `nomarr/workflows/calibration/write_calibrated_tags_wf.py` | Reference for tag preparation logic. New `write_file_tags_wf` handles mode filtering; calibration application stays here. |
| Tagging service | `nomarr/services/domain/tagging_svc.py` | Extend with `reconcile_library()`. Keep existing `tag_file()`, `tag_library()`. |
| Process workflow | `nomarr/workflows/processing/process_file_wf.py` | Split into analyze + write. |

---

## Implementation Phases

### Phase 1: Persistence Layer

**1.1** `nomarr/persistence/database/library_files_aql.py`
- Add fields: `last_written_mode`, `last_written_calibration_hash`, `last_written_at`, `has_nomarr_namespace`, `write_claimed_by`, `write_claimed_at`
- Add queries:
  - `claim_files_for_reconciliation(library_id, target_mode, calibration_hash, worker_id, batch_size, lease_ms)` → atomically claim mismatched files
  - `set_file_written(file_key, mode, calibration_hash)` → update `last_written_mode`, `last_written_calibration_hash`, `last_written_at=now_ms()`, clear claim
  - `release_claim(file_key)` → clear `write_claimed_by`, `write_claimed_at`
  - `count_files_needing_reconciliation(library_id, target_mode, calibration_hash)` → count mismatched files

**1.2** `nomarr/persistence/database/libraries_aql.py`
- Add field: `file_write_mode: str = "full"`

**1.3** `nomarr/helpers/dto/library_dto.py`
- Add to `LibraryDict`: `file_write_mode: Literal["none", "minimal", "full"] = "full"`

### Phase 2: Workflow Layer

**2.1** CREATE `nomarr/workflows/processing/analyze_file_wf.py`
- Extract from `process_file_wf`: audio loading, embedding computation, prediction, DB storage
- After storing tags, file becomes mismatched (no flag needed - mismatch is derived from `last_written_mode` vs new DB state)
- **NO file I/O**
- Return `AnalyzeResult(file_key, predictions, embeddings_stored)`

**2.2** CREATE `nomarr/workflows/processing/write_file_tags_wf.py`

Reuse existing TagWriter - do not create new write logic:
```python
def write_file_tags_wf(db, file_key, target_mode, calibration_hash, has_calibration) -> WriteResult:
    file_doc = db.library_files.get_file(file_key)
    db_tags = db.file_tags.get_tags(file_key)
    
    # Filter out mood tags if uncalibrated (applies to all modes)
    if not has_calibration:
        db_tags = {k: v for k, v in db_tags.items() if not k.startswith("mood-")}
    
    if target_mode == "none":
        tags_to_write = {}  # Clears namespace
    elif target_mode == "minimal":
        tags_to_write = {k: v for k, v in db_tags.items() if k.startswith("mood-")}
    else:  # full
        tags_to_write = db_tags
    
    # Resolve LibraryPath from file_doc (existing helper)
    path = resolve_library_path(file_doc, db)  # Returns LibraryPath with validation
    library_root = db.libraries.get_library(file_doc["library_id"])["path"]
    chromaprint = file_doc.get("chromaprint")  # Stored on file_doc, not in tags
    
    # Reuse existing TagWriter with safe atomic writes
    tag_writer = TagWriter(overwrite=True, namespace="nom")
    tag_writer.write_safe(path, tags_to_write, Path(library_root), chromaprint)
    
    db.library_files.set_file_written(file_key, mode=target_mode, calibration_hash=calibration_hash)
    return WriteResult(file_key, len(tags_to_write), len(db_tags) - len(tags_to_write), False)
```

**2.3** UPDATE `nomarr/workflows/processing/process_file_wf.py`
- Make thin wrapper: call `analyze_file_wf` then `write_file_tags_wf` (backward compat)

### Phase 3: Service Layer

**3.1** UPDATE `nomarr/services/infrastructure/workers/discovery_worker.py`
- Replace `process_file_wf(...)` with `analyze_file_wf(...)`

**3.2** UPDATE `nomarr/services/domain/tagging_svc.py`
- Add `reconcile_library(library_id, batch_size=100)` → claim and write mismatched files (mode OR calibration mismatch)
- Single method handles all reconciliation (no separate "pending" vs "reconcile" - both are projection mismatches)
- Returns `{processed, remaining, failed}` for progress tracking

### Phase 4: Interface Layer

**4.1** UPDATE `nomarr/interfaces/api/web/libraries_if.py`
- `POST /api/libraries/{library_id}/reconcile` → call `tagging_svc.reconcile_library()` (handles all mismatches: mode, calibration, or new ML results)
- `PATCH /api/libraries/{library_id}/write-mode` → update mode, return `{requires_reconciliation, affected_file_count}`
- `GET /api/libraries/{library_id}/reconcile-status` → return `{pending_count, in_progress}` for UI feedback

**Note**: `/reconcile` may be long-running on large libraries. Pre-alpha: sync is acceptable. If timeouts occur, convert to background task.

### Phase 5: Scanning Integration

**5.1** UPDATE `nomarr/components/tagging/tagging_reader_comp.py`
- Add `read_nomarr_namespace(path) -> set[str]` to read existing namespace keys (do not hardcode specific keys)

**5.2** UPDATE `nomarr/workflows/scanning/scan_file_wf.py`
- Set `has_nomarr_namespace = bool(namespace_keys)` based on namespace presence
- Infer `last_written_mode` from key patterns:
  - No namespace keys → `null`
  - Only mood-tier keys present → `"minimal"`
  - Non-mood keys present (head score keys, embeddings, etc.) → `"full"`
  - Unrecognized key patterns → `"unknown"` (conservative)

### Phase 6: Frontend

**6.1** `frontend/src/features/libraries/` - Add write mode dropdown to library config

**6.2** Mode change handler:
- Call `PATCH /write-mode`
- If `requires_reconciliation`, show confirmation dialog
- On confirm, call `POST /reconcile`

**6.3** `frontend/src/features/libraries/` - Add "Reconcile Tags" button to library actions
- Shows count from `GET /reconcile-status` when mismatches exist
- Calls `POST /reconcile` to sync files to current mode + calibration

---

## Error Handling

| Error | Action |
|-------|--------|
| No calibration | Filter out mood tags, write remaining tags |
| File not found / permission denied | Log, release claim, mark `last_write_error`, continue batch |
| Write exception | Release claim (file remains mismatched, will be retried on next reconcile) |
| `mode="none"` | Clear namespace, set `last_written_mode="none"` (valid reconciliation) |

---

## Verification Checklist

- [ ] DiscoveryWorker never writes to audio files
- [ ] After ML, file is mismatched (derived from `last_written_mode` != current state)
- [ ] Mode `none` clears namespace, `minimal` writes moods only, `full` writes all
- [ ] Reconciliation is idempotent
- [ ] Non-Nomarr tags never touched
- [ ] All writes use `TagWriter.write_safe()` (atomic copy-modify-verify-replace)
- [ ] All supported formats work: MP3, M4A/MP4/M4B, FLAC, OGG, Opus
- [ ] Scanning sets `has_nomarr_namespace` and infers `last_written_mode` from on-disk keys
- [ ] Mode change triggers reconciliation prompt when files exist
- [ ] Calibration change triggers reconciliation for files using mood tags
- [ ] Claim mechanism prevents duplicate writes
