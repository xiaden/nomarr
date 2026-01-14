# Calibration System Refactor: Queue → Async Thread + DB Columns

## Key Design Decisions (Addressing Architecture Concerns)

### 1. Hash Computation Lives in Components
- **Problem**: Persistence layer must not import components or do filesystem reads
- **Solution**: `compute_expected_calibration_hash()` lives in `ml_calibration_comp.py`
- **Pattern**: Compute hash in service/workflow, pass as parameter to persistence queries

### 2. Thread-Safe DB Access
- **Problem**: Passing `self._db` to thread executor causes SQLite cross-thread errors
- **Solution**: Service uses `db_factory: Callable[[], Database]` pattern
- **Pattern**: Worker thread calls `db = db_factory()` to create fresh connection

### 3. Index Matches Hot Query
- **Problem**: Index on `included_in_calibration=1` but query is `WHERE included_in_calibration=0`
- **Solution**: Partial index `WHERE included_in_calibration=0` (the hot path for incremental generation)

### 4. Single Source of Truth
- **Problem**: Both `needs_recalibration` and `calibration_hash` is redundant
- **Solution**: Only `calibration_hash` - deterministic, self-healing, no separate flag needed
- **Force recalibration**: Just set `calibration_hash=NULL` for library

### 5. Stateless Progress Tracking
- **Problem**: Storing `_active_recalibration` task is brittle across restarts/multiple processes
- **Solution**: Progress = `COUNT(*) WHERE calibration_hash != expected_hash` (transient `_active_task` for single-process "is running" check only)

---

## ⚠️ Critical: Multi-Process DB Access

### The Real Problem
This refactor assumes **single-process, multi-threaded** execution. Nomarr is actually **multi-process**:
- Multiple worker processes
- Multiple API/interface processes
- Background tasks in separate processes

### SQLite Limitations
SQLite with WAL mode and file locks:
- ✅ Handles concurrent reads well
- ⚠️ Single writer at a time (lock contention)
- ⚠️ Write locks can cause `SQLITE_BUSY` errors
- ⚠️ Cross-process coordination is fragile
- ⚠️ No true concurrent writes

### Two Paths Forward

#### Option A: PostgreSQL (Recommended for Production)
**Pros:**
- True multi-process, multi-threaded concurrency
- Proper MVCC (Multi-Version Concurrency Control)
- No lock contention for typical read/write patterns
- Industry standard for multi-process applications

**Cons:**
- External dependency (not embedded)
- Requires separate installation/configuration
- More complex deployment

**Implementation:**
- Keep SQLite for dev/testing (simple setup)
- Use PostgreSQL for production deployments
- Abstract DB layer already supports this (just swap connection string)

#### Option B: SQLite + WAL + Accept Risk
**Current approach:**
- Enable WAL mode: `PRAGMA journal_mode=WAL`
- Set busy timeout: `PRAGMA busy_timeout=5000`
- Retry on `SQLITE_BUSY` errors
- Use `BEGIN IMMEDIATE` for write transactions

**Accept these risks:**
- Random `SQLITE_BUSY` failures under high concurrency
- Potential database locks during heavy write periods
- No true parallelism for writes
- Edge cases with multi-process coordination

**Good enough if:**
- Small-scale deployments (single user, few processes)
- Occasional writes (not high-throughput)
- Can tolerate occasional lock errors

### Recommendation
- **Dev/Testing**: SQLite (easy setup)
- **Production**: PostgreSQL (proper concurrency)
- **This refactor**: Works with either, but doesn't solve multi-process issues
- **db_factory pattern**: Still correct (creates fresh connections per thread/process)

---

## Current State

### Architecture
- **Queue-based**: `calibration_queue` table with jobs (pending/running/done/error)
- **Worker pool**: `RecalibrationWorker` processes jobs from queue
- **Two operations**:
  1. **Generate calibration**: Compute min/max from library tags → save sidecar files
  2. **Recalibrate files**: Apply new calibration to existing files without re-running ML

### Current Flow
```
User triggers recalibration
  → Service enqueues all library files to calibration_queue
  → Worker pool dequeues jobs
  → Each worker runs recalibrate_file_workflow(path)
  → Worker marks job done/error
```

### Problems
1. **Queue overhead**: Separate queue table, job management, status tracking
2. **Worker complexity**: Multiprocessing, picklable backends, spawn compatibility
3. **No real parallelism needed**: Recalibration reads DB → applies math → writes tags
4. **Similar to library scanning**: Batch operation over all library files

---

## Proposed State

### Architecture  
- **No queue**: Direct async execution with progress tracking via COUNT(*) queries
- **DB columns**: 
  - `included_in_calibration INTEGER` (0=not counted, 1=counted)
  - `calibration_hash TEXT` (hash of applied calibration versions)
- **Background task**: Async thread walks library, recalibrates files with hash mismatch
- **DB factory**: Thread-safe DB connection creation (fresh connection in worker thread)
- **Hash computation**: Component layer (ml_calibration_comp.py), not persistence
- **Progress tracking**: Stateless COUNT(*) queries, no stored task state
- **Similar to scan_library_direct_wf**: Direct iteration, batch DB operations

### Proposed Flow

#### Generate Calibration (incremental)
```
User triggers calibration generation
  → Service calls generate_calibration_workflow()
  → Workflow:
    - Query: SELECT * FROM library_files WHERE included_in_calibration=0 (NOT YET included)
    - Load existing calibration sidecars (running stats)
    - For each file:
      * Add predictions to running statistics
      * Mark: included_in_calibration=1 (prevent double-counting)
    - Save updated calibration sidecars with incremented stats
  → Return immediately (no queue)
  
Note: Prevents bias - each file contributes exactly once to calibration
```

#### Apply Recalibration (hash-based)
```
Calibration changes (new version)
  → Compute expected_hash = MD5("head1:v5|head2:v5|...")
  
User triggers recalibration
  → Service spawns async thread
  → Thread runs recalibrate_library_direct_wf()
  → Workflow:
    - Query: SELECT id, path, calibration_hash 
             FROM library_files 
             WHERE calibration_hash IS NULL OR calibration_hash != ?
             (expected_hash)
    - For each file:
      - Run recalibrate_file_workflow(path)
      - Update: SET calibration_hash=? WHERE id=?
    - Track progress: completed_count / total_count
  → Returns task_id for progress polling
```

---

## Database Changes

### Add Columns to library_files
```sql
-- Track if file has been included in calibration computation
ALTER TABLE library_files ADD COLUMN included_in_calibration INTEGER DEFAULT 0;
CREATE INDEX idx_library_files_included_in_calibration 
  ON library_files(included_in_calibration) 
  WHERE included_in_calibration = 1;

-- Track which calibration versions have been applied (hash for deterministic check)
ALTER TABLE library_files ADD COLUMN calibration_hash TEXT DEFAULT NULL;
CREATE INDEX idx_library_files_calibration_hash 
  ON library_files(calibration_hash);
```

**Two separate concerns:**

1. **`included_in_calibration`**: Has this file been counted in calibration statistics?
   - Boolean: 0 = not yet counted, 1 = already counted
   - Prevents double-counting: each file contributes exactly once to calibration
   - Query WHERE included_in_calibration=0 to get new files for incremental generation
   - After adding file's predictions to running stats, mark as 1

2. **`calibration_hash`**: Which calibration versions are currently applied?
   - Hash of `"head_name:version|head_name:version|..."`
   - Example: `MD5("effnet_mood_happy:v5|effnet_mood_sad:v5|musicnn_genre:v3")`
   - If file's hash ≠ current expected hash → needs recalibration
   - Deterministic: hash tells you exactly which calibrations were applied

### Remove calibration_queue Table
```sql
DROP TABLE calibration_queue;
```

---

## Code Changes

### 1. New Workflow: `recalibrate_library_direct_wf.py`

**Purpose**: Walk library and recalibrate flagged files (like `scan_library_direct_wf.py`)

```python
def recalibrate_library_direct_wf(
    db: Database,
    library_id: int,
    expected_hash: str,  # Computed by component, passed in
    models_dir: str,
    namespace: str,
    version_tag_key: str,
    calibrate_heads: bool,
) -> dict[str, Any]:
    """
    Recalibrate all files needing recalibration in library.
    
    Args:
        db: Database instance
        library_id: Library to recalibrate
        models_dir: Path to models directory
        namespace: Tag namespace
        version_tag_key: Version key for tags
        calibrate_heads: Use versioned calibrations
        
    Returns:
        Stats: {files_recalibrated, files_failed, duration_s}
    """
    # Get files needing recalibration (hash mismatch or NULL)
    files = db.library_files.get_files_needing_recalibration(
        library_id, expected_hash
    )
    
    stats = {"files_recalibrated": 0, "files_failed": 0}
    
    for file_row in files:
        try:
            params = RecalibrateFileWorkflowParams(
                file_path=file_row["path"],
                models_dir=models_dir,
                namespace=namespace,
                version_tag_key=version_tag_key,
                calibrate_heads=calibrate_heads,
            )
            recalibrate_file_workflow(db=db, params=params)
            
            # Update calibration hash after successful recalibration
            db.library_files.update_calibration_hash(file_row["id"], expected_hash)
            stats["files_recalibrated"] += 1
            
        except Exception as e:
            logger.error(f"Recalibration failed for {file_row['path']}: {e}")
            stats["files_failed"] += 1
    
    return stats
```

### 2. Update CalibrationService

**Remove**: Queue/worker management  
**Add**: Background task spawning (like BackgroundTaskService)

```python
class CalibrationService:
    def __init__(self, db_factory: Callable[[], Database], cfg: CalibrationConfig):
        self._db_factory = db_factory  # Factory for thread-safe DB creation
        self.cfg = cfg
        self._active_task: asyncio.Task | None = None
    
    def generate_calibration_and_flag_library(self) -> GenerateCalibrationResult:
        """Generate calibration incrementally."""
        db = self._db_factory()
        result = generate_calibration_workflow(
            db=db,
            models_dir=self.cfg.models_dir,
            namespace=self.cfg.namespace,
            thresholds=self.cfg.thresholds,
        )
        return result
    
    def start_recalibration_async(self, library_id: int) -> None:
        """Start async recalibration in background thread."""
        if self._active_task and not self._active_task.done():
            raise RuntimeError("Recalibration already in progress")
        
        # Spawn async task
        self._active_task = asyncio.create_task(
            self._run_recalibration_async(library_id)
        )
    
    async def _run_recalibration_async(self, library_id: int):
        """Background thread for recalibration."""
        def _blocking_work():
            # Create fresh DB connection in worker thread (thread-safe)
            db = self._db_factory()
            
            # Compute expected hash from current calibration sidecars
            from nomarr.components.ml.ml_calibration_comp import compute_expected_calibration_hash
            expected_hash = compute_expected_calibration_hash(
                models_dir=self.cfg.models_dir,
                calibrate_heads=self.cfg.calibrate_heads,
            )
            
            return recalibrate_library_direct_wf(
                db=db,
                library_id=library_id,
                expected_hash=expected_hash,
                models_dir=self.cfg.models_dir,
                namespace=self.cfg.namespace,
                version_tag_key="nom_version",
                calibrate_heads=self.cfg.calibrate_heads,
            )
        
        # Run in thread pool (blocking DB/file I/O)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _blocking_work)
    
    def get_recalibration_progress(self, library_id: int) -> dict[str, int]:
        """Get recalibration progress (no stored state, just COUNT(*) queries)."""
        db = self._db_factory()
        
        from nomarr.components.ml.ml_calibration_comp import compute_expected_calibration_hash
        expected_hash = compute_expected_calibration_hash(
            models_dir=self.cfg.models_dir,
            calibrate_heads=self.cfg.calibrate_heads,
        )
        
        total = db.library_files.count_files_in_library(library_id)
        remaining = db.library_files.count_files_needing_recalibration(
            library_id, expected_hash
        )
        
        return {
            "total": total,
            "remaining": remaining,
            "completed": total - remaining,
        }
    
    def is_recalibration_active(self) -> bool:
        """Check if recalibration task is running."""
        return self._active_task is not None and not self._active_task.done()
```

### 3. New Component: `ml_calibration_comp.py`

**Purpose**: Compute expected calibration hash from current sidecar files (domain logic, not persistence)

```python
def compute_expected_calibration_hash(
    models_dir: str,
    calibrate_heads: bool
) -> str:
    """
    Compute expected calibration hash from current sidecar files.
    
    Hash format: MD5("head1_name:v5|head2_name:v3|...")
    Sorted by head name for determinism.
    
    This is domain/application logic (ML discovery + filesystem read),
    NOT persistence logic.
    """
    import hashlib
    import json
    import os
    from nomarr.components.ml.ml_discovery_comp import discover_heads
    
    heads = discover_heads(models_dir)
    
    # Build sorted list of "head_name:version"
    calibration_entries = []
    for head in heads:
        # Load calibration file to get version
        calib_file = f"{head.name}-calibration"
        if calibrate_heads:
            calib_file += f"-v{head.calibration_version}"
        calib_file += ".json"
        
        calib_path = os.path.join(models_dir, head.model, "heads", calib_file)
        if os.path.exists(calib_path):
            with open(calib_path) as f:
                calib_data = json.load(f)
                version = calib_data.get("version", 0)
                calibration_entries.append(f"{head.name}:v{version}")
    
    # Sort for determinism
    calibration_entries.sort()
    
    # Hash
    hash_input = "|".join(calibration_entries)
    return hashlib.md5(hash_input.encode()).hexdigest()
```

### 4. New Persistence Methods

**Add to `library_files_sql.py`:**

```python
def get_files_for_calibration_generation(self, library_id: int) -> list[dict[str, Any]]:
    """Get files NOT YET included in calibration (for incremental generation)."""
    cur = self.conn.execute(
        """SELECT id, path, calibration 
           FROM library_files 
           WHERE library_id=? AND included_in_calibration=0""",
        (library_id,)
    )
    return [{"id": row[0], "path": row[1], "calibration": row[2]} for row in cur.fetchall()]

def mark_file_included_in_calibration(self, file_id: int) -> None:
    """Mark file as included in calibration dataset (after adding to calibration stats)."""
    self.conn.execute(
        "UPDATE library_files SET included_in_calibration=1 WHERE id=?",
        (file_id,)
    )
    self.conn.commit()

def get_files_needing_recalibration(
    self, 
    library_id: int, 
    expected_hash: str
) -> list[dict[str, Any]]:
    """Get all files needing recalibration (hash mismatch or NULL)."""
    cur = self.conn.execute(
        """SELECT id, path 
           FROM library_files 
           WHERE library_id=? 
             AND (calibration_hash IS NULL OR calibration_hash != ?)""",
        (library_id, expected_hash)
    )
    return [{"id": row[0], "path": row[1]} for row in cur.fetchall()]

def count_files_needing_recalibration(
    self, 
    library_id: int, 
    expected_hash: str
) -> int:
    """Count files needing recalibration (for progress tracking)."""
    cur = self.conn.execute(
        """SELECT COUNT(*) 
           FROM library_files 
           WHERE library_id=? 
             AND (calibration_hash IS NULL OR calibration_hash != ?)""",
        (library_id, expected_hash)
    )
    return cur.fetchone()[0]

def count_files_in_library(self, library_id: int) -> int:
    """Count total files in library."""
    cur = self.conn.execute(
        "SELECT COUNT(*) FROM library_files WHERE library_id=?",
        (library_id,)
    )
    return cur.fetchone()[0]

def update_calibration_hash(self, file_id: int, calibration_hash: str) -> None:
    """Update calibration hash after recalibration."""
    self.conn.execute(
        "UPDATE library_files SET calibration_hash=? WHERE id=?",
        (calibration_hash, file_id)
    )
    self.conn.commit()
```

### 4. Remove Files

**Delete:**
- `services/infrastructure/workers/recalibration.py` (RecalibrationWorker)
- `persistence/database/calibration_queue_sql.py` (queue operations)
- `services/domain/recalibration_svc.py` (queue service wrapper)

**Update:**
- Remove calibration_queue references from `db.py` schema
- Remove recalibration worker from `WorkerSystemService`

---

## Benefits

### 1. Simpler Architecture
- No queue table, no job management
- No worker pool, no multiprocessing
- Two columns (included_in_calibration, calibration_hash), clean separation of concerns
- One workflow, one service method

### 2. Consistency with Scanning
- Same pattern as `scan_library_direct_wf`
- Both are batch operations over library files
- Both use DB columns for state tracking

### 3. Better Performance
- No queue overhead (insert → dequeue → update status)
- No pickling overhead for multiprocessing
- Direct DB cursor iteration
- Hash-based recalibration check is deterministic and fast

### 4. Easier Progress Tracking
```python
# Stateless progress tracking - just COUNT(*) queries
from nomarr.components.ml.ml_calibration_comp import compute_expected_calibration_hash

expected_hash = compute_expected_calibration_hash(models_dir, calibrate_heads)
remaining = db.library_files.count_files_needing_recalibration(library_id, expected_hash)

# No stored task state, no task IDs, no separate status table
```

### 5. Crash Recovery
- If recalibration crashes mid-run
- Files already recalibrated: hash updated to expected_hash
- Files not yet processed: hash still NULL or old value
- Just restart recalibration → hash mismatch query picks up where it left off

### 6. Deterministic and Self-Healing
- Hash tells you exactly which calibrations are applied
- If calibration files change, hash comparison immediately shows all files needing update
- Can force recalibration by setting calibration_hash=NULL for specific files/library

---

## Migration Path

### Phase 1: Add DB Columns (Already Done Above)

### Phase 2: Create New Component
- Create `ml_calibration_comp.py` with `compute_expected_calibration_hash()`
- Move hash computation logic out of persistence layer

### Phase 3: Implement New Workflow
- Create `recalibrate_library_direct_wf.py`
- Add persistence methods to `library_files_sql.py` (COUNT queries, hash updates)

### Phase 4: Update CalibrationService
- Change constructor to accept `db_factory` instead of `db` instance
- Add background task management with DB factory pattern
- Add stateless progress tracking methods (COUNT(*) queries)
- Remove queue/worker dependencies

### Phase 5: Remove Old Code
- Delete `RecalibrationWorker`
- Delete `calibration_queue_sql.py`
- Delete `recalibration_svc.py`
- Remove from `WorkerSystemService`

### Phase 6: Drop Queue Table
```sql
DROP TABLE calibration_queue;
```

---

## Open Questions

1. **Library-level progress tracking?**
   - Add `libraries.recalibration_progress` column?
   - Or query `COUNT(*)` on demand?

2. **Per-file error tracking?**
   - Add `library_files.recalibration_error TEXT` column?
   - Or just log errors and retry on next run?

3. **Abort mechanism?**
   - How to cancel in-progress recalibration?
   - Set `_active_recalibration.cancel()`?

4. **Batch commits?**
   - Clear recalibration flag per file or batch?
   - Trade-off: atomicity vs. performance

---

## Summary

Calibration recalibration is a **batch operation over library files**, exactly like library scanning. It doesn't need a queue, workers, or complex job management. A simple **async thread + DB flag** provides:

- Same architecture as scanning (consistency)
- Simpler code (no queue, no workers)
- Better crash recovery (just restart)
- Easier progress tracking (query count)

This refactor aligns calibration with the library-first architecture established in the scanning refactor.
