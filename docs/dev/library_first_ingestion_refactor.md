# Library-First Ingestion Refactor

## Implementation Status

**Status:** COMPLETE - Ready for Testing  
**Started:** January 12, 2026  
**Completed:** January 13, 2026  

### Completed (Phase 1 - Infrastructure)
- ✅ Database Schema: Added scan tracking columns to `libraries` table (scan_status, scan_progress, scan_total, scanned_at, scan_error)
- ✅ Database Schema: Added `needs_tagging`, `content_hash` (UNIQUE), `is_valid` columns to `library_files` table
- ✅ Database Schema: Removed `library_queue` table and references
- ✅ Persistence: Added `update_scan_status()` to LibrariesOperations
- ✅ Persistence: Added `batch_upsert_library_files()`, `bulk_mark_invalid()`, `update_file_path()`, `library_has_tagged_files()`, `get_files_needing_tagging()` to LibraryFilesOperations
- ✅ Persistence: Updated all library SELECT queries to include new scan fields
- ✅ Workflow: Created `scan_library_direct_wf.py` with conditional move detection, batched writes, metadata hashing
- ✅ Service: Created `BackgroundTaskService` for threading-based async scan tasks
- ✅ Infrastructure: Removed `LibraryScanWorker` from worker system (worker_system_svc.py, app.py)
- ✅ Infrastructure: Deleted `library_queue_sql.py` and `scanner.py` files

### Completed (Phase 2 - Services & API)
- ✅ Service: Updated `LibraryService` to use `BackgroundTaskService` and `scan_library_direct_workflow`
- ✅ DTO: Updated `LibraryScanStatusResult` to include scan_status, scan_progress, scan_total, scanned_at, scan_error
- ✅ API: Updated library scan endpoints (removed force parameter, added scan status fields to LibraryResponse)
- ✅ Workflow: Updated ML tagging (`process_file_wf.py`) to compute and write content_hash to file tags

### Remaining (Phase 3 - Testing)
- ⏳ Testing: Validation and integration tests (pytest, mypy, ruff)

---

## Overview

Refactor the music ingestion pipeline to separate library metadata ingestion from ML tagging, and eliminate unnecessary worker/queue overhead for the fast, reliable library scanning process.

**Impact:** High - Core ingestion flow changes, removes library_queue table and LibraryScanWorker

---

## Current Architecture (Over-Engineered)

### Flow
```
1. User triggers: POST /libraries/{id}/scan
2. Workflow discovers files → enqueues to library_queue table
3. LibraryScanWorker processes (10 workers polling queue):
   - Extracts metadata from file
   - Writes to library_files table
   - IF auto_tag=True AND file needs tagging:
     → Enqueues to tag_queue
4. TaggerWorker processes tag_queue jobs:
   - Runs ML inference (GPU-heavy)
   - Writes tags to files
   - Updates library_files.tagged=True
```

### Problems

1. **Worker/Queue Overkill:** Library scanning uses same infrastructure as ML tagging, but:
   - Library scanning is **fast** (milliseconds per file, no ML models)
   - Library scanning is **reliable** (no GPU, no crashes)
   - Library scanning is **I/O bound** (no benefit from parallel workers)
   - Library scanning is **sequential** (must walk entire library anyway)
2. **Massive DB Churn:** Every file creates 3+ DB operations (enqueue, dequeue, mark complete)
3. **Tight Coupling:** Library scanning workflow contains logic to decide when to enqueue for tagging
4. **Implicit Auto-Tagging:** `auto_tag` flag baked into scan workflow
5. **Mixed Responsibilities:** LibraryScanWorker handles both metadata extraction AND tagging orchestration
6. **No Explicit "Tag Library" Operation:** ML tagging happens as side effect of scanning
7. **Library State Ambiguity:** No clear "library is fully scanned" state before tagging begins

---

## Proposed Architecture (Simplified & Decoupled)

### Flow

```
PHASE 1: Library Ingestion (Fast, Direct, No Queue)
1. User triggers: POST /libraries/{id}/scan
2. Service starts background task (asyncio/threading)
3. Background task runs scan workflow:
   a. Count total audio files (pre-scan walk)
   b. Snapshot existing DB paths for this library
   c. Walk filesystem folder-by-folder (batched for memory)
   d. For each file:
      - Validate path
      - Extract metadata + existing tags
      - Write directly to library_files table (using proper arcitecural rules, persistence layer call)
      - Set needs_tagging=True if untagged
      - Update scan_progress counter
   e. After walk complete:
      - Compare discovered files to DB snapshot
      - Detect moved files (same size+duration, different path)
      - Update paths for moved files
      - Mark missing files as invalid or delete
      - Verify final count matches initial count
      - Set library.scanned_at, library.scan_status="complete"
4. Scan progress exposed via SSE or polling endpoint

PHASE 2: ML Tagging (Slow, GPU-Dependent, Optional, Queued)
1. User explicitly triggers: POST /libraries/{id}/tag
2. Service identifies untagged files (needs_tagging=True)
3. Enqueues untagged files to tag_queue
4. TaggerWorker processes tag_queue jobs:
   - Runs ML inference
   - Writes tags to files
   - Updates library_files.tagged=True, needs_tagging=False
```

### Benefits

1. **No Queue Overhead:** Library scanning writes directly to DB (3+ ops per file → 1 op per file)
2. **No Worker Processes:** Background task handles scanning (10 processes → 0 processes)
3. **Clear Separation:** Library ingestion != ML tagging
4. **Explicit Control:** User chooses when to run ML tagging
5. **Faster Feedback:** Library metadata visible immediately, before tagging
6. **Better Error Handling:** Library scan can complete even if GPU unavailable
7. **Resumability:** Can retry tagging without rescanning library
8. **Library State:** Clear distinction between "scanned" and "tagged"
9. **Progress Tracking:** Real-time scan progress without complex job state
10. **Simpler Code:** Remove entire queue/worker infrastructure for library scanning

### Architecture Comparison

**Old (Over-Engineered):**
```
API → Service → start_library_scan_wf (enqueue files)
                        ↓
            library_queue table (pending jobs)
                        ↓
            LibraryScanWorker × 10 (poll queue)
                        ↓
            scan_single_file_wf (extract + write)
                        ↓
            library_files table
```

**New (Direct):**
```
API → Service → background task → scan_library_wf (walk + write)
                                            ↓
                                    library_files table
```

---

## Changes Required

### 1. Database Schema Changes

**`libraries` table (add scan tracking):**
```sql
ALTER TABLE libraries ADD COLUMN scan_status TEXT DEFAULT 'never_scanned';
-- Values: 'never_scanned', 'scanning', 'complete', 'error'

ALTER TABLE libraries ADD COLUMN scan_progress INTEGER DEFAULT 0;
-- Current progress (files scanned so far)

ALTER TABLE libraries ADD COLUMN scan_total INTEGER DEFAULT 0;
-- Total files to scan (set at start of scan)

ALTER TABLE libraries ADD COLUMN scanned_at INTEGER;
-- Timestamp of last successful scan completion

ALTER TABLE libraries ADD COLUMN scan_error TEXT;
-- Error message if scan_status='error'
```

**`library_files` table:**
```sql
ALTER TABLE library_files ADD COLUMN needs_tagging BOOLEAN DEFAULT FALSE;
-- Track if file needs ML tagging (True for untagged files, False after tagging)

ALTER TABLE library_files ADD COLUMN scanned_at INTEGER;
-- Track when file was last scanned (metadata extracted)

ALTER TABLE library_files ADD COLUMN file_size INTEGER;
-- File size in bytes (used for move detection fallback)

ALTER TABLE library_files ADD COLUMN content_hash TEXT UNIQUE;
-- MD5 hash of: path|duration|artist|album|title|timestamp
-- Computed during first scan, written to file tags during ML tagging
-- Used for move detection when library has tagged files
-- UNIQUE constraint prevents duplicate entries, triggers rehashing on collision

ALTER TABLE library_files ADD COLUMN is_valid BOOLEAN DEFAULT TRUE;
-- False if file no longer exists on disk

-- Note: Keep existing `tagged` column (True after ML tagging completes)
```

**`library_queue` table:**
```sql
-- DELETE THIS TABLE - No longer needed for library scanning
DROP TABLE library_queue;
```

**Purpose:**
- Track scan progress and status at library level, not per-file
- Scan is **read-only** (never writes to user files, only reads metadata)
- `content_hash` computed from metadata, stored in DB immediately
- Hash written to file tags only during ML tagging (explicit user permission)
- Move detection **only enabled** when library has tagged files (preserves ML work)
- Use `is_valid` to mark files that no longer exist without deleting records
- Batched writes by folder provide crash recovery points

**Migration Notes:**
- Pre-alpha: No migration needed, can just recreate DB
- Set `needs_tagging=TRUE` for all existing `tagged=FALSE` files

---

### 2. Remove Library Queue & Workers

**Files to Remove:**
- `nomarr/persistence/database/library_queue_sql.py` - No longer needed
- `nomarr/services/infrastructure/workers/scanner.py` - LibraryScanWorker removed

**Files to Update:**
- `nomarr/services/infrastructure/worker_system_svc.py` - Remove scanner worker creation
- `nomarr/persistence/db.py` - Remove library_queue accessor

---

### 3. New Direct Library Scan Workflow

**File:** `nomarr/workflows/library/scan_library_direct_wf.py` (NEW FILE)

**Purpose:** Walk filesystem and write directly to DB without queue

**Signature:**
```python
def scan_library_direct_workflow(
    db: Database,
    library_id: int,
    paths: list[str] | None = None,
    recursive: bool = True,
    clean_missing: bool = True,
) -> dict[str, Any]:
    """
    Scan library by walking filesystem and writing directly to database.
    
    Args:
        db: Database instance
        library_id: Library to scan
        paths: Specific paths to scan (or None for entire library root)
        recursive: Recursively scan subdirectories
        clean_missing: Mark missing files as invalid, detect moved files via hash matching
    
    Returns:
        Dict with scan results:
        - files_discovered: int (total audio files found)
        - files_added: int (new files)
        - files_updated: int (changed files)
        - files_moved: int (detected via content_hash and path updated)
        - files_removed: int (marked invalid)
        - files_skipped: int (unchanged, not rescanned)
        - files_failed: int (extraction errors)
        - scan_duration_s: float
        - warnings: list[str]
    
    Notes:
        - Batches DB writes by folder for crash recovery
        - Uses content_hash from file tags to detect moved files
        - Crashes intentionally on fatal errors (loud failure for Docker)
        - Progress tracked via library.scan_progress column
    """
```

**Implementation Logic:**
```python
def scan_library_direct_workflow(db, library_id, paths, recursive, clean_missing):
    """Direct filesystem walk → DB write workflow."""
    import time
    from collections import defaultdict
    
    start_time = time.time()
    stats = defaultdict(int)
    warnings = []
    
    # Get library record
    library = db.libraries.get_library(library_id)
    if not library:
        raise ValueError(f"Library {library_id} not found")
    
    scan_paths = paths or [library["root_path"]]
    
    # Update library status to 'scanning'
    db.libraries.update_scan_status(library_id, status="scanning", progress=0, total=0)
    
    try:
        # PHASE 1: Count total files (fast walk for progress tracking)
        logging.info(f"[scan_library] Counting files in {len(scan_paths)} path(s)...")
        total_files = 0
        for root_path in scan_paths:
            total_files += count_audio_files(root_path, recursive=recursive)
        
        db.libraries.update_scan_status(library_id, total=total_files)
        stats["files_discovered"] = total_files
        logging.info(f"[scan_library] Found {total_files} audio files")
        
        # PHASE 2: Check if move detection is needed
        # Only detect moves if library has tagged files (preserves ML work)
        has_tagged_files = db.library_files.library_has_tagged_files(library_id)
        enable_move_detection = has_tagged_files and clean_missing
        
        if enable_move_detection:
            logging.info("[scan_library] Move detection enabled (library has tagged files)")
        else:
            logging.info("[scan_library] Fast mode (no tagged files, simple add/remove)")
        
        # Snapshot existing DB paths and hashes for this library
        existing_files = db.library_files.get_files_for_library(library_id)
        existing_paths = {f["path"] for f in existing_files}
        existing_files_dict = {f["path"]: f for f in existing_files}
        discovered_paths = set()
        
        # Only track for move detection if needed
        files_to_remove = [] if enable_move_detection else None
        new_files = [] if enable_move_detection else None
        
        # PHASE 3: Walk filesystem and process files (batched by folder)
        logging.info(f"[scan_library] Walking filesystem...")
        current_file = 0
        
        for root_path in scan_paths:
            # Walk directory tree, batched by folder to avoid RAM bloat
            for folder_path, files in walk_audio_files_batched(root_path, recursive):
                folder_batch = []  # Batch writes for this folder
                
                for file_path in files:
                    current_file += 1
                    
                    try:
                        # Validate path
                        library_path = build_library_path(file_path, library_id, db)
                        if not library_path.is_valid():
                            warnings.append(f"Invalid path: {file_path} - {library_path.reason}")
                            stats["files_failed"] += 1
                            continue
                        
                        file_path_str = str(library_path.absolute)
                        discovered_paths.add(file_path_str)
                        
                        # Check if file exists in DB
                        existing_file = db.library_files.get_library_file(file_path_str)
                        file_stat = os.stat(file_path_str)
                        modified_time = int(file_stat.st_mtime * 1000)
                        file_size = file_stat.st_size
                        
                        # Skip unchanged files
                        if existing_file and existing_file["modified_time"] == modified_time:
                            stats["files_skipped"] += 1
                            continue
                        
                        # Extract metadata + tags (component call)
                        metadata = extract_metadata_component(file_path_str, namespace="nom")
                        
                        # Compute or read content hash
                        content_hash = metadata.get("nom_tags", {}).get("content_hash")
                        if not content_hash:
                            # First time seeing this file - compute hash from metadata
                            # Hash will be written to file tags during ML tagging, not now (read-only scan)
                            duration = metadata.get("duration", 0)
                            artist = metadata.get("artist", "")
                            album = metadata.get("album", "")
                            title = metadata.get("title", "")
                            timestamp = now_ms()
                            hash_input = f"{file_path_str}|{duration}|{artist}|{album}|{title}|{timestamp}"
                            content_hash = hashlib.md5(hash_input.encode()).hexdigest()
                        
                        # Check if file needs tagging
                        existing_version = metadata.get("nom_tags", {}).get("nom_version")
                        needs_tagging = (
                            existing_file is None
                            or not existing_file.get("tagged")
                            or existing_version != TAGGER_VERSION
                        )
                        
                        # Prepare batch entry
                        file_entry = {
                            "path": file_path_str,
                            "library_id": library_id,
                            "metadata": metadata,
                            "file_size": file_size,
                            "modified_time": modified_time,
                            "content_hash": content_hash,
                            "needs_tagging": needs_tagging,
                            "is_valid": True,
                            "scanned_at": now_ms(),
                        }
                        folder_batch.append(file_entry)
                        
                        # Track new files for move detection (if enabled)
                        if existing_file is None:
                            if enable_move_detection:
                                new_files.append(file_entry)
                        else:
                            stats["files_updated"] += 1
                    
                    except Exception as e:
                        logging.error(f"Failed to process {file_path}: {e}")
                        stats["files_failed"] += 1
                        warnings.append(f"Extraction failed: {file_path} - {str(e)[:100]}")
                        continue
                
                # Batch write folder files to DB (with collision handling)
                if folder_batch:
                    try:
                        db.library_files.batch_upsert_library_files(folder_batch)
                        stats["files_added"] += len([f for f in folder_batch if f["path"] not in existing_paths])
                    except IntegrityError as e:
                        # Hash collision - file was copied
                        # Rehash with new timestamp and retry
                        for file_entry in folder_batch:
                            try:
                                db.library_files.upsert_library_file(file_entry)
                            except IntegrityError:
                                # Collision on this specific file
                                new_hash = hashlib.md5(f"{file_entry['path']}|{now_ms()}".encode()).hexdigest()
                                file_entry["content_hash"] = new_hash
                                db.library_files.upsert_library_file(file_entry)
                                warnings.append(f"Hash collision, rehashed: {file_entry['path']}")
                                stats["files_added"] += 1
                
                # Update progress every folder
                db.libraries.update_scan_status(library_id, progress=current_file)
        
        # PHASE 4: Identify missing files (only if move detection enabled)
        if enable_move_detection:
            missing_paths = existing_paths - discovered_paths
            logging.info(f"[scan_library] Found {len(missing_paths)} missing files")
            
            for missing_path in missing_paths:
                missing_file = existing_files_dict.get(missing_path)
                if missing_file:
                    files_to_remove.append(missing_file)
        elif clean_missing:
            # Fast mode: just mark missing files invalid, no move detection
            missing_paths = existing_paths - discovered_paths
            if missing_paths:
                logging.info(f"[scan_library] Fast mode: marking {len(missing_paths)} missing files invalid")
                db.library_files.bulk_mark_invalid(list(missing_paths))
                stats["files_removed"] += len(missing_paths)
        
        # PHASE 5: Detect moved files using content hashes (only if enabled)
        # Compare new files' hashes (from tags) to removed files' hashes (from DB)
        logging.info(f"[scan_library] Checking {len(new_files)} new files for moves...")
        
        matched_moves = set()  # Track which files_to_remove entries were matched
        
        for new_file in new_files:
            new_hash = new_file.get("content_hash")
            if not new_hash:
                continue  # No hash in tags, can't detect move
            
            # Check if this hash exists in files_to_remove
            for idx, removed_file in enumerate(files_to_remove):
                if idx in matched_moves:
                    continue  # Already matched
                
                removed_hash = removed_file.get("content_hash")
                if removed_hash == new_hash:
                    # Match found - update path instead of adding new entry
                    logging.info(f"[scan_library] File moved: {removed_file['path']} → {new_file['path']}")
                    db.library_files.update_file_path(
                        old_path=removed_file["path"],
                        new_path=new_file["path"],
                        file_size=new_file["file_size"],
                        modified_time=new_file["modified_time"],
                    )
                    stats["files_moved"] += 1
                    matched_moves.add(idx)
                    break
            
            # PHASE 6: Bulk remove remaining unmatched missing files
            unmatched_removed = [f for idx, f in enumerate(files_to_remove) if idx not in matched_moves]
            if unmatched_removed:
                logging.info(f"[scan_library] Removing {len(unmatched_removed)} deleted files from library")
                paths_to_remove = [f["path"] for f in unmatched_removed]
                db.library_files.bulk_mark_invalid(paths_to_remove)
                stats["files_removed"] += len(unmatched_removed)
        
        # PHASE 7: Finalize scan
        scan_duration = time.time() - start_time
        
        # Verify count matches (warning only for dev/alpha visibility)
        expected = stats["files_added"] + stats["files_updated"] + stats["files_skipped"] + stats["files_failed"]
        if expected != total_files:
            warning = (
                f"File count mismatch: discovered={total_files}, "
                f"processed={expected} (added={stats['files_added']}, "
                f"updated={stats['files_updated']}, skipped={stats['files_skipped']}, "
                f"failed={stats['files_failed']}). Filesystem may have changed during scan."
            )
            warnings.append(warning)
            logging.warning(f"[scan_library] {warning}")
        
        # Mark scan complete
        db.libraries.update_scan_status(
            library_id,
            status="complete",
            progress=total_files,
            scanned_at=now_ms(),
            scan_error=None,
        )
        
        logging.info(
            f"[scan_library] Scan complete in {scan_duration:.1f}s: "
            f"added={stats['files_added']}, updated={stats['files_updated']}, "
            f"moved={stats['files_moved']}, removed={stats['files_removed']}, "
            f"skipped={stats['files_skipped']}, failed={stats['files_failed']}"
        )
        
        return {
            **stats,
            "scan_duration_s": scan_duration,
            "warnings": warnings,
        }
    
    except Exception as e:
        # Crash is intentional - loud failure in Docker container
        logging.error(f"[scan_library] Scan crashed: {e}")
        db.libraries.update_scan_status(
            library_id,
            status="error",
            scan_error=str(e),
        )
        # Re-raise to crash container (preferred behavior for alpha)
        raise
        
    except Exception as e:
        # Mark scan as error
        db.libraries.update_scan_status(
            library_id,
            status="error",
            scan_error=str(e),
        )
        raise


def count_audio_files(root_path: str, recursive: bool) -> int:
    """Fast count of audio files for progress tracking."""
    from nomarr.helpers.files_helper import collect_audio_files
    files = collect_audio_files(root_path, recursive=recursive)
    return len(files)


def walk_audio_files_batched(root_path: str, recursive: bool):
    """
    Walk filesystem and yield (folder_path, audio_files) batches.
    
    This prevents loading all file paths into RAM at once.
    
    Yields:
        tuple[str, list[str]]: (folder_path, list of audio file paths in that folder)
    """
    import os
    from nomarr.helpers.files_helper import is_audio_file
    
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root_path):
            audio_files = [
                os.path.join(dirpath, f)
                for f in filenames
                if is_audio_file(f)
            ]
            if audio_files:
                yield (dirpath, audio_files)
    else:
        # Non-recursive: only scan root directory
        try:
            filenames = os.listdir(root_path)
            audio_files = [
                os.path.join(root_path, f)
                for f in filenames
                if os.path.isfile(os.path.join(root_path, f)) and is_audio_file(f)
            ]
            if audio_files:
                yield (root_path, audio_files)
        except OSError as e:
            logging.error(f"Error reading directory {root_path}: {e}")


def extract_metadata_component(file_path: str, namespace: str) -> dict:
    """
    Extract metadata from audio file (component call).
    
    This should be a component in nomarr.components.metadata if not already.
    Wraps mutagen/mediafile extraction with error handling.
    """
    from nomarr.components.metadata import extract_file_metadata
    return extract_file_metadata(file_path, namespace=namespace)
```

**Key Features:**
1. **Pre-count for progress:** Fast walk to count total files before processing
2. **Batched writes by folder:** Minimizes DB operations, provides crash recovery points
3. **Metadata-based hash:** MD5 of path|duration|artist|album|title|timestamp for uniqueness
4. **Read-only scan:** Never writes to user files, only computes and stores hash in DB
5. **Conditional move detection:** Only enabled when library has tagged files (preserves ML work)
6. **Fast mode:** Simple add/remove for libraries without ML work (no hash matching overhead)
7. **Collision handling:** UNIQUE constraint on hash, rehash with new timestamp on collision
8. **Per-file error handling:** Failed extractions don't crash entire scan
9. **Direct DB writes:** No queue, writes directly to library_files
10. **Progress tracking:** Updates library.scan_progress after each folder
11. **Loud failure:** Scan crash intentionally crashes container (alpha behavior)

---

### 4. New: Background Task Runner

**File:** `nomarr/services/infrastructure/background_tasks_svc.py` (NEW FILE)

**Purpose:** Manage long-running background tasks (like library scanning) using threading

**Implementation:**
```python
import logging
import threading
from collections.abc import Callable
from typing import Any

class BackgroundTaskService:
    """Manages background tasks using threading with same DB connection."""
    
    def __init__(self):
        self._tasks: dict[str, threading.Thread] = {}
        self._task_results: dict[str, dict] = {}
        self._lock = threading.Lock()
    
    def start_task(
        self,
        task_id: str,
        task_fn: Callable,
        *args,
        **kwargs
    ) -> str:
        """Start a background task and return task_id."""
        
        def wrapper():
            try:
                result = task_fn(*args, **kwargs)
                with self._lock:
                    self._task_results[task_id] = {
                        "status": "complete",
                        "result": result,
                        "error": None,
                    }
            except Exception as e:
                logging.error(f"Task {task_id} failed: {e}")
                with self._lock:
                    self._task_results[task_id] = {
                        "status": "error",
                        "result": None,
                        "error": str(e),
                    }
                # Re-raise to crash container (loud failure)
                raise
        
        thread = threading.Thread(target=wrapper, daemon=True)
        thread.start()
        
        with self._lock:
            self._tasks[task_id] = thread
            self._task_results[task_id] = {"status": "running", "result": None, "error": None}
        
        return task_id
    
    def get_task_status(self, task_id: str) -> dict | None:
        """Get task status (running, complete, error)."""
        with self._lock:
            return self._task_results.get(task_id)
```

**Note:** DB is WAL mode, thread uses same connection/writer. This is acceptable for alpha. Future refactor will address proper connection pooling.

**Usage in LibraryService:**
```python
def start_scan_for_library(self, library_id: int, paths: list[str], recursive: bool, clean_missing: bool):
    """Start library scan as background task."""
    task_id = f"scan_library_{library_id}_{now_ms()}"
    
    self.background_tasks.start_task(
        task_id=task_id,
        task_fn=scan_library_direct_workflow,
        db=self.db,
        library_id=library_id,
        paths=paths,
        recursive=recursive,
        clean_missing=clean_missing,
    )
    
    return {"task_id": task_id, "status": "started"}
```

---

### 5. New Persistence Methods

**File:** `nomarr/persistence/database/libraries_sql.py`

**New methods:**
```python
class LibrariesOperations:
    def update_scan_status(
        self,
        library_id: int,
        status: str | None = None,
        progress: int | None = None,
        total: int | None = None,
        scanned_at: int | None = None,
        scan_error: str | None = None,
    ) -> None:
        """Update library scan status and progress."""
        updates = []
        params = []
        
        if status is not None:
            updates.append("scan_status=?")
            params.append(status)
        if progress is not None:
            updates.append("scan_progress=?")
            params.append(progress)
        if total is not None:
            updates.append("scan_total=?")
            params.append(total)
        if scanned_at is not None:
            updates.append("scanned_at=?")
            params.append(scanned_at)
        if scan_error is not None:
            updates.append("scan_error=?")
            params.append(scan_error)
        
        params.append(library_id)
        
        self.conn.execute(
            f"UPDATE libraries SET {', '.join(updates)} WHERE id=?",
            params
        )
        self.conn.commit()
```

**File:** `nomarr/persistence/database/library_files_sql.py`

**New methods:**
```python
class LibraryFilesOperations:
    def mark_file_invalid(self, path: str) -> None:
        """Mark file as no longer existing on disk."""
        self.conn.execute(
            "UPDATE library_files SET is_valid=0 WHERE path=?",
            (path,)
        )
        self.conn.commit()
    
    def update_file_path(self, old_path: str, new_path: str, file_size: int, modified_time: int) -> None:
        """Update file path and metadata (for moved files)."""
        self.conn.execute(
            "UPDATE library_files SET path=?, file_size=?, modified_time=?, is_valid=1 WHERE path=?",
            (new_path, file_size, modified_time, old_path)
        )
        self.conn.commit()
    
    def bulk_mark_invalid(self, paths: list[str]) -> None:
        """Mark multiple files as invalid in one operation."""
        placeholders = ",".join("?" * len(paths))
        self.conn.execute(
            f"UPDATE library_files SET is_valid=0 WHERE path IN ({placeholders})",
            paths
        )
        self.conn.commit()
    
    def batch_upsert_library_files(self, files: list[dict]) -> None:
        """Insert or update multiple library files in one transaction."""
        for file_data in files:
            self.conn.execute(
                """
                INSERT INTO library_files (
                    path, library_id, metadata, file_size, modified_time,
                    content_hash, needs_tagging, is_valid, scanned_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    metadata=excluded.metadata,
                    file_size=excluded.file_size,
                    modified_time=excluded.modified_time,
                    content_hash=excluded.content_hash,
                    needs_tagging=excluded.needs_tagging,
                    is_valid=excluded.is_valid,
                    scanned_at=excluded.scanned_at
                """,
                (
                    file_data["path"],
                    file_data["library_id"],
                    json.dumps(file_data["metadata"]),
                    file_data["file_size"],
                    file_data["modified_time"],
                    file_data.get("content_hash"),
                    file_data["needs_tagging"],
                    file_data["is_valid"],
                    file_data["scanned_at"],
                )
            )
        self.conn.commit()
    
    def library_has_tagged_files(self, library_id: int) -> bool:
        """Check if library has any files with ML tags (for conditional move detection)."""
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM library_files WHERE library_id=? AND tagged=1",
            (library_id,)
        )
        return cur.fetchone()[0] > 0
    
    def get_files_needing_tagging(
        self,
        library_id: int | None,
        paths: list[str] | None = None
    ) -> list[dict]:
        """Get files that need ML tagging (needs_tagging=True, is_valid=True)."""
        query = "SELECT * FROM library_files WHERE needs_tagging=1 AND is_valid=1"
        params = []
        
        if library_id:
            query += " AND library_id=?"
            params.append(library_id)
        
        if paths:
            placeholders = ",".join("?" * len(paths))
            query += f" AND path IN ({placeholders})"
            params.extend(paths)
        
        cur = self.conn.execute(query, params)
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row, strict=False)) for row in cur.fetchall()]
```

**New Service Method:** `LibraryService.start_tagging_for_library(library_id, paths=None, force=False, ignore_patterns=None)`

**Purpose:** Explicitly enqueue untagged files for ML tagging

**Workflow:** `nomarr/workflows/library/start_library_tagging_wf.py` (NEW FILE)

**Logic:**
```python
def start_library_tagging_workflow(db, library_id, paths=None, force=False, ignore_patterns=None):
    """
    Enqueue library files for ML tagging.
    
    Args:
        db: Database instance
        library_id: Library to tag (or None for all libraries)
        paths: Specific paths to tag (or None for entire library)
        force: If True, retag all files (ignore existing tags)
        ignore_patterns: Skip files matching patterns (e.g., "*/Audiobooks/*")
    
    Returns:
        Dict with:
        - files_eligible: int (files that could be tagged)
        - files_queued: int (files actually enqueued)
        - files_ignored: int (skipped due to ignore patterns)
        - job_ids: list[int]
    """
    # Query files that need tagging
    if force:
        # Force retag: get all files in library
        files = db.library_files.get_files_for_library(library_id, paths)
    else:
        # Normal tagging: only get files with needs_tagging=True
        files = db.library_files.get_files_needing_tagging(library_id, paths)
    
    # Apply ignore patterns
    eligible_files = [
        f for f in files
        if not _matches_ignore_pattern(f["path"], ignore_patterns)
    ]
    
    # Enqueue each file to tag_queue
    job_ids = []
    for file in eligible_files:
        job_id = enqueue_file(db, file["path"], force=force, queue_type="tag")
        job_ids.append(job_id)
    
    return {
        "files_eligible": len(files),
        "files_queued": len(eligible_files),
        "files_ignored": len(files) - len(eligible_files),
        "job_ids": job_ids,
    }
```

**New Persistence Method:** `LibraryFilesOperations.get_files_needing_tagging(library_id, paths=None)`
```python
def get_files_needing_tagging(self, library_id: int | None, paths: list[str] | None = None):
    """Get files that need ML tagging (needs_tagging=True)."""
    query = "SELECT * FROM library_files WHERE needs_tagging=1"
    params = []
    
    if library_id:
        query += " AND library_id=?"
        params.append(library_id)
    
    if paths:
        placeholders = ",".join("?" * len(paths))
        query += f" AND path IN ({placeholders})"
        params.extend(paths)
    
    return self.conn.execute(query, params).fetchall()
```

---

### 4. Update Library Scan API

**File:** `nomarr/interfaces/api/web/library_if.py`

**Current Endpoint:** `POST /libraries/{id}/scan`
```python
async def scan_library(
    library_id: int,
    request: ScanLibraryRequest,  # Contains: paths, recursive, force, clean_missing
    ...
) -> StartScanWithStatusResponse:
```

**Changes:**
- **Remove** `auto_tag` from `ScanLibraryRequest`
- **Remove** `ignore_patterns` from `ScanLibraryRequest`
- Scan now ONLY discovers and ingests metadata

**New Endpoint:** `POST /libraries/{id}/tag`
```python
@router.post("/{library_id}/tag", dependencies=[Depends(verify_session)])
async def tag_library(
    library_id: int,
    request: TagLibraryRequest,  # Contains: paths, force, ignore_patterns
    library_service: LibraryService = Depends(get_library_service),
) -> StartTaggingResponse:
    """
    Start ML tagging for library files.
    
    Enqueues untagged files (needs_tagging=True) to the tag_queue
    for background processing by TaggerWorker processes.
    
    Args:
        library_id: Library ID to tag
        request: Tagging parameters
            - paths: Optional list of specific paths to tag
            - force: If True, retag all files (ignore existing tags)
            - ignore_patterns: Skip files matching patterns
    
    Returns:
        StartTaggingResponse with:
        - files_eligible: Number of files that could be tagged
        - files_queued: Number of files enqueued
        - files_ignored: Number of files skipped
        - message: Status message
    """
    stats = library_service.start_tagging_for_library(
        library_id=library_id,
        paths=request.paths,
        force=request.force,
        ignore_patterns=request.ignore_patterns,
    )
    
    return StartTaggingResponse.from_dict(stats)
```

**New DTO:** `TagLibraryRequest`
```python
class TagLibraryRequest(BaseModel):
    paths: list[str] | None = None
    force: bool = False
    ignore_patterns: str | None = None
```

---

### 5. Combined "Scan and Tag" Option (Optional Convenience)

For users who want one-click "scan + tag", add convenience endpoint:

**New Endpoint:** `POST /libraries/{id}/scan-and-tag`
```python
@router.post("/{library_id}/scan-and-tag", dependencies=[Depends(verify_session)])
async def scan_and_tag_library(
    library_id: int,
    request: ScanAndTagRequest,
    library_service: LibraryService = Depends(get_library_service),
) -> ScanAndTagResponse:
    """
    Convenience endpoint: Scan library for metadata, then tag untagged files.
    
    This is equivalent to calling:
    1. POST /libraries/{id}/scan
    2. POST /libraries/{id}/tag
    
    But ensures tagging happens after scan completes.
    """
    # Run scan first
    scan_stats = library_service.start_scan_for_library(
        library_id=library_id,
        paths=request.paths,
        recursive=request.recursive,
        force=request.force,
        clean_missing=request.clean_missing,
    )
    
    # Then enqueue tagging for files that need it
    tag_stats = library_service.start_tagging_for_library(
        library_id=library_id,
        paths=request.paths,
        force=request.force,
        ignore_patterns=request.ignore_patterns,
    )
    
    return ScanAndTagResponse(
        scan_stats=scan_stats,
        tag_stats=tag_stats,
    )
```

---

### 6. Update Tagger Worker

**File:** `nomarr/workflows/processing/process_file_wf.py`

**Changes:**
- After successful tagging, update library_files:
  - Set `tagged=True`
  - Set `needs_tagging=False`
  - Set `tagged_at=now_ms()` (new column)

**Current code** (around line 680):
```python
# Update library database if connection provided
if db:
    update_library_from_tags(
        db=db,
        file_path=path,
        metadata={"nom_tags": tags_written},
        namespace=config.namespace,
        tagged_version=config.tagger_version,
        calibration=calibration_version,
        library_id=None,
    )
```

**Updated code:**
```python
# Update library database if connection provided
if db:
    update_library_from_tags(
        db=db,
        file_path=path,
        metadata={"nom_tags": tags_written},
        namespace=config.namespace,
        tagged_version=config.tagger_version,
        calibration=calibration_version,
        library_id=None,
    )
    
    # Mark file as tagged and no longer needing tagging
    db.library_files.update_library_file_tagging_state(
        path=path,
        tagged=True,
        needs_tagging=False,
        tagged_at=now_ms(),
    )
```

**New Persistence Method:** `LibraryFilesOperations.update_library_file_tagging_state()`

---

### 7. Update UI/Frontend

**Current UI Flow:**
- Scan button → triggers scan with auto_tag=True

**New UI Flow:**
- **Scan** button → POST /libraries/{id}/scan (metadata only)
- **Tag** button → POST /libraries/{id}/tag (ML tagging)
- **Scan & Tag** button → POST /libraries/{id}/scan-and-tag (convenience)

**Library Table Columns:**
- Show `scanned_at` timestamp
- Show `tagged_count` / `total_count`
- Show "Needs Tagging" badge if untagged files exist

---

## Migration Strategy (Pre-Alpha)

Since this is pre-alpha, we can break compatibility:

### Option A: Database Recreation (Simplest)
1. Drop existing database
2. Create new schema with `needs_tagging`, `scanned_at` columns
3. Users rescan libraries

### Option B: In-Place Migration (If Preserving Data)
```sql
-- Add new columns
ALTER TABLE library_files ADD COLUMN needs_tagging BOOLEAN DEFAULT FALSE;
ALTER TABLE library_files ADD COLUMN scanned_at INTEGER;
ALTER TABLE library_files ADD COLUMN content_hash TEXT;
ALTER TABLE library_files ADD COLUMN file_size INTEGER;
ALTER TABLE library_files ADD COLUMN is_valid BOOLEAN DEFAULT TRUE;

-- Add scan tracking to libraries
ALTER TABLE libraries ADD COLUMN scan_status TEXT DEFAULT 'never_scanned';
ALTER TABLE libraries ADD COLUMN scan_progress INTEGER DEFAULT 0;
ALTER TABLE libraries ADD COLUMN scan_total INTEGER DEFAULT 0;
ALTER TABLE libraries ADD COLUMN scanned_at INTEGER;
ALTER TABLE libraries ADD COLUMN scan_error TEXT;

-- Set needs_tagging for untagged files
UPDATE library_files SET needs_tagging=1 WHERE tagged=0;

-- Set scanned_at from created_at for existing files
UPDATE library_files SET scanned_at=created_at WHERE scanned_at IS NULL;

-- Drop library_queue table
DROP TABLE IF EXISTS library_queue;
```

---

## Testing Requirements

### Unit Tests
1. `test_scan_library_direct_workflow()` - Verify direct scan with batched writes
2. `test_hash_based_move_detection()` - Verify content_hash matching for moved files
3. `test_per_file_error_handling()` - Verify failed extractions don't crash scan
4. `test_batched_db_writes()` - Verify folder-level batching
5. `test_bulk_mark_invalid()` - Verify bulk operations
6. `test_extract_metadata_component()` - Verify metadata extraction component

### Integration Tests
1. Full scan: Scan large library → Verify all files in DB with correct metadata
2. Rescan with moves: Move files → Rescan → Verify paths updated via hash matching
3. Rescan with deletes: Delete files → Rescan → Verify marked invalid
4. Crash recovery: Kill scan mid-folder → Rescan → Verify picks up correctly
5. Failed extraction: Include corrupted file → Verify scan continues, file in failed count

---

## Rollout Plan

### Phase 1: Database Schema (Breaking Change)
- Add `needs_tagging`, `scanned_at`, `tagged_at` columns
- Update all SQL operations to handle new columns
- **Users must rescan libraries**

### Phase 2: Implement Direct Scan Workflow
- Create `scan_library_direct_wf.py` with hash-based move detection
- Create `extract_metadata_component` in components/metadata
- Add batched write methods to persistence layer
- Remove `force` parameter from all scan-related code

### Phase 3: Remove Worker/Queue Infrastructure
- Delete `library_queue_sql.py`
- Remove LibraryScanWorker from worker_system_svc.py
- Remove library_queue accessor from db.py
- Create BackgroundTaskService for threading

### Phase 4: Update UI
- Add separate "Tag" button
- Add "Scan & Tag" combined button
- Show tagging status in library table

### Phase 5: Documentation
- Update user documentation
- Update API reference
- Add migration guide for existing users

---

## Decisions Made

1. **Removed scan-and-tag combined endpoint**
   - **Decision:** Remove it. Users scan to library first, then tag stable library.
   - **Rationale:** Clean separation of concerns, explicit control

2. **Ignore patterns at tag time only**
   - **Decision:** Apply ignore_patterns during tagging operation, not during scan
   - **Rationale:** Scan ingests everything, user can change ignore patterns without rescanning

3. **Calibration changes and retagging**
   - **Decision:** Defer to ML domain refactor (separate concern)
   - **Rationale:** Out of scope for this ingestion refactor

4. **Tag queue cleanup on rescan**
   - **Decision:** No cleanup needed (separate concern)
   - **Rationale:** Tag queue jobs process and update library_files naturally, old tags get overwritten

5. **Move detection algorithm**
   - **Decision:** Use metadata-based content_hash (MD5 of path|duration|artist|album|title|timestamp)
   - **Rationale:** Fast to compute, unique enough, available immediately during scan
   - **Read-only scan:** Hash computed and stored in DB during scan, written to file tags during ML tagging
   - **Conditional:** Only enabled when library has tagged files (preserves ML work, otherwise simple add/remove)
   - **Collision handling:** UNIQUE constraint on hash, rehash with new timestamp if duplicate detected

6. **Batched writes and crash recovery**
   - **Decision:** Batch DB writes by folder, no explicit recovery mechanism
   - **Rationale:** Folder-level batching provides natural checkpoints, rescan can pick up where left off

7. **Threading vs multiprocessing**
   - **Decision:** Use threading with same DB connection
   - **Rationale:** DB is WAL mode, acceptable for alpha, loud failure crashes container (preferred)

8. **Navidrome sync**
   - **Decision:** No Nomarr-side sync needed
   - **Rationale:** Navidrome has excellent ingest pipeline, handles itself

9. **Force flag**
   - **Decision:** Remove completely (legacy cruft)
   - **Rationale:** Force retagging is now handled in ML tagging pipeline, not scan

10. **Incremental scan support**
    - **Decision:** Not needed
    - **Rationale:** Multiple libraries feature already handles this use case

---

## Related Documents

- `docs/dev/services.md` - Service layer patterns
- `docs/dev/workers.md` - Worker system architecture
- `docs/dev/queues.md` - Queue design and usage
- `LIBRARY_PATH_IMPLEMENTATION_STATUS.md` - Library path tracking status

---

## Conclusion

This refactor creates a clean separation between library metadata ingestion (fast, reliable) and ML tagging (slow, GPU-dependent). It gives users explicit control over when ML tagging happens and makes the system more resilient to GPU unavailability.

The changes are straightforward and align with V1 production readiness goals while setting us up for a cleaner V2 architecture.
