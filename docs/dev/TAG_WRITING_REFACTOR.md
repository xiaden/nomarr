# Tag Writing Refactor Plan

## Status: PROPOSED

> **Validation Date**: 2024-12-09
>
> This document was validated against the actual codebase. Key corrections:
> - Calibration is stored **per model/head**, not per library (see Calibration section)
> - `file_write_mode` and `library_auto_tag` are currently **global config**, not per-library
> - Actual calibration API: `load_calibrations_from_db_wf(db)` returns `dict[label, {p5, p95}]`
> - Fields `file_tags_pending`, `auto_write_tags`, per-library `file_write_mode` don't exist yet

## Problem Statement

Currently, `process_file_wf` (called by DiscoveryWorker) does ML inference AND writes tags to files in the same operation. This is problematic because:

1. **Crash risk**: DiscoveryWorker is a spawned multiprocessing process - the most crash-prone execution context. File I/O during crashes can corrupt files.

2. **No user consent**: Tags are written immediately without explicit user permission.

3. **All-or-nothing**: Can't do ML analysis without also writing tags.

4. **No batch control**: Can't preview what will be written before committing.

## Desired Behavior

### Phase 1: Separate ML from Tag Writing

1. **DiscoveryWorker** does ML inference only:
   - Compute embeddings and predictions
   - Store results in database (`file_tags` collection)
   - Does NOT write to audio files
   - Sets `needs_file_write = True` on processed files

2. **Tag Writing** is a separate operation:
   - Triggered by user action OR library auto-tag setting
   - Runs in BackgroundTaskService (threading, not multiprocessing)
   - Reads from database, writes to files
   - Safer execution context for file I/O

### Phase 2: Library-Level Toggle

Add `auto_write_tags` setting to library configuration:

```python
@dataclass
class LibraryDict:
    # ... existing fields ...
    auto_write_tags: bool = False  # If True, write tags after ML processing
    file_write_mode: Literal["none", "minimal", "full"] = "full"
```

- `auto_write_tags=False` (default): ML runs, tags stored in DB, files untouched
- `auto_write_tags=True`: After ML completes, queue file for tag writing

---

## Tag Writing Modes

There are **two operational modes** for writing tags to files:

### 1. Explicit Batch Mode (Static)

- **Trigger**: User action (e.g., clicking "Write Tags" button in frontend)
- **Scope**: Tags all eligible files that can be tagged **at that moment**
- **Behavior**:
  - Ignores files still pending ML discovery
  - Ignores files missing required calibration (see Calibration Requirements)
  - Writes are deterministic and user-controlled
  - Returns summary of success/skipped/failed counts
- **Use case**: User reviews pending tags, then commits when ready

### 2. Discovery Mode (Dynamic)

- **Trigger**: Per-library config toggle (`auto_write_tags=True`)
- **Scope**: Each file is tagged automatically after ML processing completes
- **Behavior**:
  - Tag writer runs as persistent background worker or queue consumer
  - Files are written as soon as they become eligible
  - Respects calibration requirements (skips mood-tier if uncalibrated)
- **Use case**: "Set and forget" libraries where user wants immediate tagging

---

## Calibration Requirements

Mood-tier tags (e.g., `mood-strict`, `mood-regular`, `mood-loose`) **require calibration vectors** computed from a representative sample of the library.

### Current Calibration Architecture

> **IMPORTANT**: Calibration is stored per **model/head**, NOT per library.
>
> - Collection: `calibration_state`
> - Key: `model_key` + `head_name` (e.g., `effnet-discogs-moods`)
> - Load API: `load_calibrations_from_db_wf(db)` → `dict[label, {p5: float, p95: float}]`
> - Returns empty dict if no calibrations exist
>
> The calibration represents percentile thresholds derived from model predictions,
> not library-specific data. A single calibration applies to ALL libraries.

### Preconditions for Mood-Tier Tags

| Condition | Mood-Tier Tags | Raw Scores |
|-----------|----------------|------------|
| Calibration exists | ✅ Written | ✅ Written |
| No calibration, `write_raw_scores=True` | ❌ Skipped | ✅ Written |
| No calibration, `write_raw_scores=False` | ❌ Skipped | ❌ Skipped |
| `file_write_mode="minimal"`, no calibration | ❌ Skipped | ❌ Skipped |

### Tag Writer Calibration Logic

> **NOTE**: The API shown below differs from current code. Actual implementation:
> - `load_calibrations_from_db_wf(db)` returns all calibrations globally
> - Check `if not calibrations:` to determine if ANY calibration exists
> - There is no per-library calibration; it's a global state

```python
from nomarr.workflows.calibration.calibration_loader_wf import load_calibrations_from_db_wf

def has_valid_calibration(db: Database) -> bool:
    """Check if any calibration exists (global, not per-library)."""
    calibrations = load_calibrations_from_db_wf(db)
    return bool(calibrations)  # Empty dict = no calibration

def get_writable_tags(file_tags: dict, config: WriteConfig, db: Database) -> dict:
    """Filter tags based on calibration state and config."""
    has_calibration = has_valid_calibration(db)
    
    writable = {}
    for key, value in file_tags.items():
        if key.startswith("mood-"):
            # Mood-tier tags require calibration
            if has_calibration:
                writable[key] = value
            # else: skip mood-tier tag
        elif key.startswith("raw_"):
            # Raw scores: write if configured and no calibration
            if config.write_raw_scores and not has_calibration:
                writable[key] = value
        else:
            # Other tags (version, chromaprint, etc.): always write
            writable[key] = value
    
    return writable
```

### Calibration-Gated Behavior

- **Explicit Batch Mode**: Before writing, check calibration. If missing:
  - Log warning: "Library {name} has no calibration - mood-tier tags will be skipped"
  - Proceed with non-mood tags only (or raw scores if configured)

- **Discovery Mode**: Same check per-file. Files tagged before calibration get partial tags; can be re-tagged after calibration via explicit batch.

---

## Configuration Implications

### Current State vs Proposed

> **Current code (as of validation)**:
> - `library_auto_tag`: Global config in `config.yaml` (default: `True`)
> - `file_write_mode`: Global config AND in `ProcessorConfig` (default: `"full"`)
> - `overwrite_tags`: Global config AND in `ProcessorConfig` (default: `True`)
> - No per-library config fields for these settings
>
> **Decision needed**: Keep global or move to per-library?

### Proposed: New Library Fields

```python
@dataclass
class LibraryDict:
    # ... existing fields ...
    auto_write_tags: bool = False      # Enable Discovery Mode (NEW FIELD)
    file_write_mode: str = "full"      # "none" | "minimal" | "full" (MOVE FROM GLOBAL)
    write_raw_scores: bool = False     # Write raw model scores if no calibration (NEW FIELD)
```

### Tag Writer Config Validation

Tag writer must validate before writing:

1. **file_write_mode check**:
   - `"none"`: No file writes, ever
   - `"minimal"`: Only write if calibration exists (mood-tiers only)
   - `"full"`: Write all available tags

2. **Calibration check**:
   - Query via `load_calibrations_from_db_wf(db)`
   - If empty dict returned → no calibration exists
   - Gate mood-tier tags on calibration presence

3. **Fallback behavior**:
   - If `write_raw_scores=True` and no calibration: write raw scores instead of mood-tiers
   - If `write_raw_scores=False` and no calibration: skip mood-related tags entirely

---

## Error Handling

### Calibration Errors

| Scenario | Behavior |
|----------|----------|
| No calibration exists | Skip mood-tier tags, log info, continue with other tags |
| Calibration expired/invalid | Treat as "no calibration" |
| Calibration loading fails | Log error, skip file, continue batch |

### File Write Errors

| Scenario | Behavior |
|----------|----------|
| File not found | Log error, mark as failed, continue batch |
| Permission denied | Log error, mark as failed, continue batch |
| Corrupt file (mutagen error) | Log error, mark as failed, continue batch |
| Disk full | Log error, abort batch (critical) |

### Discovery Mode Errors

- Failed file writes do NOT block other files
- Failed files remain with `file_tags_pending=True`
- Retry on next explicit batch or periodic retry (future enhancement)

## Implementation Plan

### Step 1: Split `process_file_wf` into Two Workflows

**New workflow structure:**

```
workflows/processing/
├── analyze_file_wf.py      # ML inference only → writes to DB
├── write_file_tags_wf.py   # Reads DB → writes to file
└── process_file_wf.py      # Legacy: calls both (for CLI compatibility)
```

#### `analyze_file_wf.py`
- All current ML logic from `process_file_wf`
- Writes predictions to `file_tags` collection
- Sets `file_tags_pending = True` flag on file record
- Returns `AnalyzeFileResult` with tag preview

#### `write_file_tags_wf.py`
- Loads tags from `file_tags` collection
- **Checks calibration state for library** (gates mood-tier tags)
- Applies `file_write_mode` filtering
- Falls back to raw scores if configured and uncalibrated
- Writes to audio file via `TagWriter`
- Clears `file_tags_pending` flag
- Returns `WriteFileTagsResult` with written/skipped counts

### Step 2: Update DiscoveryWorker

```python
# discovery_worker.py - BEFORE
result = process_file_workflow(path=file_path, config=config, db=db)

# discovery_worker.py - AFTER
result = analyze_file_workflow(path=file_path, config=config, db=db)
# No file writing - just ML and DB
```

### Step 3: Create Tag Writing Service

**New service:** `nomarr/services/domain/tag_writer_svc.py`

```python
class TagWriterService:
    def __init__(self, db: Database, background_tasks: BackgroundTaskService):
        self._db = db
        self._bg = background_tasks
    
    def write_pending_tags_for_library(self, library_id: str) -> str:
        """Queue background task to write all pending tags for library (Explicit Batch Mode)."""
        task_id = f"write_tags_{library_id}_{now_ms()}"
        self._bg.start_task(
            task_id=task_id,
            task_fn=self._write_library_tags,
            library_id=library_id,
        )
        return task_id
    
    def write_tags_for_file(self, file_id: str) -> WriteFileTagsResult:
        """Synchronously write tags for single file (respects calibration)."""
        return write_file_tags_wf(db=self._db, file_id=file_id)
    
    def _write_library_tags(self, library_id: str) -> dict:
        """Background task: write all pending tags for library."""
        # Check calibration state upfront (GLOBAL, not per-library)
        from nomarr.workflows.calibration.calibration_loader_wf import load_calibrations_from_db_wf
        calibrations = load_calibrations_from_db_wf(self._db)
        has_calibration = bool(calibrations)
        
        library = self._db.libraries.get_library(library_id)
        write_raw = library.get("write_raw_scores", False)
        
        if not has_calibration:
            logger.info(
                "No calibration exists - mood-tier tags will be skipped%s",
                " (writing raw scores instead)" if write_raw else "",
            )
        
        files = self._db.library_files.get_files_with_pending_tags(library_id)
        results = {"success": 0, "skipped": 0, "failed": 0, "errors": []}
        
        for file_doc in files:
            try:
                result = write_file_tags_wf(
                    db=self._db,
                    file_id=file_doc["_key"],
                    has_calibration=has_calibration,
                    write_raw_scores=write_raw,
                )
                if result.tags_written > 0:
                    results["success"] += 1
                else:
                    results["skipped"] += 1
            except Exception as e:
                results["failed"] += 1
                results["errors"].append({"file": file_doc["path"], "error": str(e)})
        
        return results
```

### Step 4: Add Library Toggle

1. Add `auto_write_tags` field to library schema
2. After DiscoveryWorker completes a file:
   - If library has `auto_write_tags=True`:
     - Queue file for tag writing via TagWriterService
   - If `auto_write_tags=False`:
     - Tags stay in DB only, file untouched

### Step 5: Add API Endpoints

```python
# interfaces/api/web/tags_if.py

@router.post("/api/libraries/{library_id}/write-tags")
async def write_library_tags(library_id: str):
    """Write all pending tags to files in library."""
    task_id = tag_writer_svc.write_pending_tags_for_library(library_id)
    return {"task_id": task_id}

@router.post("/api/files/{file_id}/write-tags")
async def write_file_tags(file_id: str):
    """Write pending tags to single file."""
    result = tag_writer_svc.write_tags_for_file(file_id)
    return result
```

### Step 6: Update CLI

```bash
# Current (unchanged for backward compat)
nomarr process /path/to/file.mp3

# New: analyze only (no file write)
nomarr analyze /path/to/file.mp3

# New: write pending tags
nomarr write-tags --library <id>
nomarr write-tags --file <id>
```

## Database Schema Changes

### `library_files` Collection

Add field (does not exist yet):
```python
file_tags_pending: bool = False  # True if ML complete but file not written
```

### `libraries` Collection

Add fields (none exist yet - these are NEW):
```python
auto_write_tags: bool = False    # Enable Discovery Mode (auto-tag after ML)
file_write_mode: str = "full"    # "none" | "minimal" | "full" (currently global)
write_raw_scores: bool = False   # Write raw scores if no calibration
```

> **Note**: Currently `file_write_mode` is in global config and `ProcessorConfig`.
> This refactor proposes moving it to per-library settings.

## Migration Path

1. **Phase 1** (this refactor):
   - Split workflows
   - Update DiscoveryWorker to use `analyze_file_wf`
   - Add `file_tags_pending` flag
   - Create TagWriterService
   - Default `auto_write_tags=True` for existing libraries (preserve current behavior)

2. **Phase 2** (later):
   - Add frontend UI for tag writing control
   - Add tag preview before writing
   - Add selective tag writing (choose which tags to write)

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Breaking existing behavior | Default `auto_write_tags=True` for backward compat |
| File corruption during write | TagWriter already uses atomic write pattern |
| Lost tags on crash | Tags persist in DB; file write is idempotent |
| Performance regression | Minimal - just splitting existing work |

## Files to Modify

### New Files
- `nomarr/workflows/processing/analyze_file_wf.py`
- `nomarr/workflows/processing/write_file_tags_wf.py`
- `nomarr/services/domain/tag_writer_svc.py`

### Modified Files
- `nomarr/services/infrastructure/workers/discovery_worker.py` - Use analyze_file_wf
- `nomarr/workflows/processing/process_file_wf.py` - Become thin wrapper
- `nomarr/persistence/database/library_files_aql.py` - Add `file_tags_pending` queries
- `nomarr/persistence/database/libraries_aql.py` - Add `auto_write_tags` field
- `nomarr/helpers/dto/library_dto.py` - Add new fields
- `nomarr/interfaces/api/web/tags_if.py` - Add write endpoints

## Success Criteria

1. DiscoveryWorker never writes to files directly
2. Tag writing only happens via explicit action or library toggle
3. Files with pending tags are visible in frontend
4. **Mood-tier tags are only written when calibration exists**
5. **Raw scores fallback works when configured**
6. Backward compatibility: existing behavior preserved with toggle
7. All existing tests pass
8. New tests cover split workflow behavior and calibration gating

## Open Questions

1. Should `auto_write_tags` be a global config OR per-library setting?
   - **Current**: `library_auto_tag` is **global** config
   - **Recommendation**: Per-library (more flexible)
   - **Migration**: Default new per-library field to global value

2. Should `file_write_mode` move from global to per-library?
   - **Current**: Global config (`config.yaml`) + `ProcessorConfig`
   - **Recommendation**: Per-library with global default fallback
   - **Migration**: Add per-library field, use global as default if unset

3. Should we add a queue for tag writing or just background tasks?
   - **Recommendation**: BackgroundTaskService (simpler, safer)

4. Should we batch file writes or write one-at-a-time?
   - **Recommendation**: One-at-a-time (safer, simpler error handling)
