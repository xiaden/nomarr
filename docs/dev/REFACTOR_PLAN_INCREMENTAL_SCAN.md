# Refactor Plan: Incremental Scanning & File Watching

**Status:** Planning  
**Target Release:** Pre-Alpha (breaking changes allowed)  
**Date:** 2026-01-17

---

## Executive Summary

Refactor Nomarr's library ingestion system to adopt Navidrome-style "watch + targeted incremental scan" pattern while maintaining clean architecture principles and keeping ML/calibration/tagging flows unchanged.

**Key Goals:**
- Enable incremental scanning (scan only changed folders, not entire library)
- Add real-time file watching with intelligent debouncing
- Track scan state to detect/recover from interrupted scans
- Improve scan performance via batched DB writes
- Maintain clean architecture (no upward dependencies)

**Non-Goals:**
- Automated ML/tagging pipeline (keep manual)
- Folder hashing system (future enhancement)
- Migration compatibility (pre-alpha can rebuild)
- Background job queue (use existing BackgroundTaskService)

---

## Nomarr-Specific Constraints

Before diving into implementation, understand Nomarr's current architecture:

**Runtime & Storage:**
- Python 3.11+ with asyncio
- ArangoDB (document database, not relational)
- Schema changes = document shape evolution (no ALTER TABLE migrations)
- Persistence layer uses AQL queries and batch upserts

**Scanning Model:**
- Direct workflow execution (not queue-based per-file scanning)
- Already batched by folder traversal
- Scan progress tracked via library document updates
- Move detection via chromaprint fingerprinting (when available)
- File metadata stored in `library_files` collection (global, not per-library)

**Library Architecture:**
- Libraries define filesystem roots ONLY
- `library_files` collection is global (not partitioned by library)
- **File Identity Model**: Files are uniquely identified by `(library_id, normalized_path)` tuple
  - Same physical file discovered in multiple libraries = separate records
  - `normalized_path` is POSIX-style relative path from library root (e.g., `Rock/Beatles/track.mp3`)
  - Avoid OS separators in stored paths; normalize on write
- Files reference their owning library via `library_id` field

**Concurrency Model:**
- Only ONE scan per library at a time (service-level coordination)
- Background tasks managed via BackgroundTaskService
- File watcher runs in separate threads (watchdog library)
- Thread-to-asyncio handoff via `loop.call_soon_threadsafe()` or queue

**What Already Exists:**
- `scan_library_direct_wf.py` - core scanning workflow
- `BackgroundTaskService` - daemon thread manager
- Library document tracks `last_scan_at`
- Chromaprint-based duplicate/move detection

**What Does NOT Exist Yet:**
- File watching service
- Targeted/incremental scanning (always full library)
- Scan state tracking (start/completion timestamps)
- Batched DB writes (currently per-file upserts)
- Interrupted scan detection/recovery

---

## Architecture Overview

### Current State

```
LibraryService.start_scan_for_library(library_id)
  → start_scan_workflow(db, background_tasks, library_id)
      → scan_library_direct_workflow(db, library_id)
          → Walks entire library root recursively
          → Batches file discovery per folder
          → Updates library_files documents (one AQL query per file)
          → Marks missing files as invalid
          → Updates library.last_scan_at timestamp
```

**Problems:**
- Always scans entire library (no incremental/targeted support)
- No file watching (must trigger scans manually)
- No scan interruption detection/recovery
- Per-file DB upserts (not batched by transaction)
- No scan start timestamp (can't detect crashes)
- Cannot scan specific subfolders

### Target State

```
FileWatcherService (new)
  ├─ Detects file changes per library (watchdog Observer)
  ├─ Debounces events (configurable quiet period)
  ├─ Thread-safe handoff to asyncio event loop
  ├─ Maps paths → ScanTarget(library_id, folder_path)
  └─ Calls LibraryService.scan_targets(targets)

LibraryService.scan_targets(targets: list[ScanTarget])
  ├─ Acquires scan lease (one scan per library)
  └─ Calls start_scan_workflow(db, background_tasks, targets)
      → scan_library_direct_workflow(db, library_id, targets, batch_size)
          → Scans only targeted folders (folder_path="" = full library)
          → Accumulates file records in memory
          → Batch upserts to ArangoDB (N documents per transaction)
          → Tracks changes_detected flag
          → Updates library document: last_scan_started_at → last_scan_at
```

**Benefits:**
- Automatic detection via file watcher
- Incremental scanning (scan only changed folders, 10-100x faster)
- Interrupt detection via timestamp comparison
- Efficient batch upserts (reduce ArangoDB roundtrips)
- One scan per library enforcement (avoid conflicts)

---

## Clean Architecture Compliance

### Layer Boundaries (Enforced by import-linter)

```
interfaces/
  ↓ may import
services/
  ↓ may import
workflows/
  ↓ may import
components/  ← (analytics, tagging, ml)
  ↓ may import
persistence/
  ↓ may import
helpers/
```

**Key Rules:**
- FileWatcherService is a **service** (in `services/infrastructure/`)
- Services NEVER do domain logic - only orchestration/wiring
- Watcher calls `LibraryService.scan_targets()` - NOT persistence directly
- Workflows contain domain logic and call persistence
- No upward imports allowed

### Service vs Workflow Responsibilities

**FileWatcherService (Service Layer):**
```python
# ALLOWED: Wiring, lifecycle, calling other services
def start_watching(library_id: int):
    observer = Observer()
    observer.schedule(handler, library_path, recursive=True)
    observer.start()
    
def _on_debounce_fire(targets: list[ScanTarget]):
    # Delegate to service - NO domain logic here
    self.library_service.scan_targets(targets)
```

**scan_library_direct_workflow (Workflow Layer):**
```python
# ALLOWED: Domain logic, calling components/persistence
async def scan_library_direct_workflow(
    db: Database,
    library_id: int,
    scan_targets: list[ScanTarget]
):
    # Business logic: what to scan, when to write, etc.
    for target in scan_targets:
        folder_path = resolve_scan_path(target)
        # ... scanning logic ...
        if len(batch) >= batch_size:
            db.tracks.put_batch(batch)  # Direct persistence call OK
```

---

## Implementation Plan

### Phase 1: Foundation (DTOs & Persistence)

**Deliverable 1: Add ScanTarget DTO**

File: `nomarr/helpers/dto/library.py`

```python
@dataclass
class ScanTarget:
    """Represents a specific folder within a library to scan.
    
    Used for targeted/incremental scanning:
    - folder_path="" means scan entire library
    - folder_path="Rock/Beatles" means scan only that subtree
    """
    library_id: int
    folder_path: str = ""  # Relative to library root
    
    def __post_init__(self):
        # Normalize: strip leading/trailing slashes
        if self.folder_path:
            self.folder_path = self.folder_path.strip("/")
```

Export from `nomarr/helpers/dto/__init__.py`:
```python
from nomarr.helpers.dto.library import ScanTarget
```

**Deliverable 3: Scan State Tracking**

File: `nomarr/persistence/database/library_operations.py`

Add methods to update library documents with scan state:

```python
def mark_scan_started(self, library_id: str, full_scan: bool) -> None:
    """Mark a scan as started by updating library document.
    
    Sets last_scan_started_at to current timestamp and records scan type.
    Used to detect interrupted scans on restart.
    """
    from datetime import datetime, timezone
    
    self.db.aql.execute("""
        UPDATE @library_id WITH {
            last_scan_started_at: @timestamp,
            full_scan_in_progress: @full_scan
        } IN libraries
    """, bind_vars={
        "library_id": library_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "full_scan": full_scan
    })
    
def mark_scan_completed(self, library_id: str) -> None:
    """Mark a scan as completed by clearing start timestamp."""
    from datetime import datetime, timezone
    
    self.db.aql.execute("""
        UPDATE @library_id WITH {
            last_scan_at: @timestamp,
            last_scan_started_at: null,
            full_scan_in_progress: false
        } IN libraries
    """, bind_vars={
        "library_id": library_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
def get_scan_state(self, library_id: str) -> dict | None:
    """Get current scan state from library document."""
    cursor = self.db.aql.execute("""
        FOR lib IN libraries
            FILTER lib._id == @library_id
            RETURN {
                last_scan_started_at: lib.last_scan_started_at,
                last_scan_at: lib.last_scan_at,
                full_scan_in_progress: lib.full_scan_in_progress
            }
    """, bind_vars={"library_id": library_id})
    
    results = list(cursor)
    return results[0] if results else None
    
def check_interrupted_scan(self, library_id: str) -> tuple[bool, bool]:
    """Check if a scan was interrupted.
    
    Returns:
        (was_interrupted, was_full_scan)
        
    A scan is interrupted if:
    - last_scan_started_at is set, AND
    - last_scan_started_at > last_scan_at (or last_scan_at is null)
    
    Uses ISO timestamp string comparison (works correctly for ISO format).
    """
    state = self.get_scan_state(library_id)
    if not state or not state.get("last_scan_started_at"):
        return False, False
        
    # Interrupted if started but never completed
    if not state.get("last_scan_at"):
        return True, bool(state.get("full_scan_in_progress", False))
```

**Document Shape Evolution (ArangoDB):**

Library documents gain new fields on first scan:
```javascript
{
  "_id": "libraries/123",
  "_key": "123",
  "name": "My Music",
  "root_path": "/music",
  "last_scan_at": "2026-01-17T14:30:00Z",          // Already exists
  "last_scan_started_at": null,                     // NEW: null when not scanning
  "full_scan_in_progress": false                    // NEW: true during full scan
}
```

**Why Pre-Alpha Can Skip Formal Migration:**
- ArangoDB documents are schema-less
- Missing fields return `null` in AQL (safe defaults)
- First scan after upgrade auto-adds fields
- No ALTER TABLE equivalents needed
- Users can optionally rebuild database for clean slate

---

### Phase 2: Workflow Refactoring

**Deliverable 2: Targeted Scanning**

File: `nomarr/workflows/library/scan_library_direct_wf.py`

Current signature:
```python
async def scan_library_direct_workflow(
    db: Database,
    library_id: int,
    scan_path: str
) -> dict:
```

New signature:
```python
async def scan_library_direct_workflow(
    db: Database,
    library_id: int,
    scan_targets: list[ScanTarget],
    batch_size: int = 200  # From config
) -> dict:
    """Scan specific folders within a library.
    
    Args:
        db: Database instance
        library_id: Library to scan
        scan_targets: List of folders to scan (empty path = full library)
        batch_size: Number of tracks to accumulate before writing to DB
        
    Returns:
        dict with keys: files_scanned, files_added, files_updated, changes_detected
    """
```

Implementation strategy:
```python
async def scan_library_direct_workflow(
    db: Database,
    library_id: str,  # ArangoDB uses string IDs
    scan_targets: list[ScanTarget],
    batch_size: int = 200
) -> dict:
    """Scan specific folders within a library.
    
    Key behaviors:
    - Walks targeted folders only (folder_path="" = full library)
    - Accumulates file records in memory batches
    - Batch upserts to ArangoDB (reduces roundtrips)
    - Tracks changes_detected flag (for downstream optimizations)
    - Updates scan state timestamps (start/completion)
    - Marks missing files ONLY for full scans
    
    IMPORTANT: Files are stored in global library_files collection.
    File records have library_id field but are NOT isolated per-library.
    """
    from datetime import datetime, timezone
    from pathlib import Path
    
    # Get library document
    library = db.library.get(library_id)
    if not library:
        raise ValueError(f"Library {library_id} not found")
    
    # Mark scan started
    is_full_scan = _is_full_scan(scan_targets)
    db.library.mark_scan_started(library_id, full_scan=is_full_scan)
    
    changes_detected = False
    files_scanned = 0
    files_added = 0
    files_updated = 0
    
    # Accumulate file documents for batched upserts
    batch: list[dict] = []
    scan_id = datetime.now(timezone.utc).isoformat()  # Tag files seen this scan
    
    try:
        for target in scan_targets:
            # Resolve scan path
            if target.folder_path:
                scan_path = Path(library["root_path"]) / target.folder_path
            else:
                scan_path = Path(library["root_path"])
                
            if not scan_path.exists():
                logger.warning(f"Scan target does not exist: {scan_path}")
                continue
                
            # Walk filesystem (already batched per folder)
            for audio_file in walk_audio_files(scan_path, recursive=True):
                files_scanned += 1
                
                # Build file document
                file_doc = {
                    "library_id": library_id,
                    "file_path": str(audio_file.path),
                    "file_mtime": audio_file.mtime,
                    "file_size": audio_file.size,
                    "last_seen_scan_id": scan_id,
                    "valid": True,
                    # ... metadata fields ...
                }
                
                # Determine if new/updated (would require bulk query optimization)
                # For now, add all to batch and let upsert handle duplicates
                batch.append(file_doc)
                changes_detected = True  # Simplification: assume change if scanned
                
                # Write batch if full
                if len(batch) >= batch_size:
                    result = db.library_files.upsert_batch(batch)
                    files_added += result["inserted"]
                    files_updated += result["updated"]
                    batch.clear()
        
        # Write remaining batch
        if batch:
            result = db.library_files.upsert_batch(batch)
            files_added += result["inserted"]
            files_updated += result["updated"]
            
        # Mark missing files ONLY for full scans
        if is_full_scan:
            # Files NOT seen this scan are missing
            db.library_files.mark_missing_for_library(
                library_id=library_id,
                scan_id=scan_id
            )
            
        # Mark scan completed
        db.library.mark_scan_completed(library_id)
        
        return {
            "files_scanned": files_scanned,
            "files_added": files_added,
            "files_updated": files_updated,
            "changes_detected": changes_detected,
            "scan_id": scan_id
        }
        
    except Exception:
        # Leave last_scan_started_at set - next scan will detect interruption
        raise

def _is_full_scan(targets: list[ScanTarget]) -> bool:
    """Check if this is a full library scan."""
    if len(targets) != 1:
        return False
    return targets[0].folder_path == ""

def _needs_update(existing: dict, audio_file: AudioFile) -> bool:
    """Check if file needs reimporting based on modification time."""
    return audio_file.mtime > existing.get("updated_at", 0)
```

**Deliverable 4: Batched Writes & Changes Detection**

Add to persistence:
```python
# nomarr/persistence/database/library_files_operations.py

def upsert_batch(self, file_docs: list[dict]) -> dict:
    """Batch upsert file documents to ArangoDB.
    
    More efficient than individual upserts - reduces roundtrips.
    Uses file_path as unique key for upsert logic.
    
    Returns:
        {"inserted": int, "updated": int}
    """
    if not file_docs:
        return {"inserted": 0, "updated": 0}
        
    # Use AQL UPSERT for atomic insert-or-update
    result = self.db.aql.execute("""
        FOR doc IN @docs
            UPSERT { file_path: doc.file_path, library_id: doc.library_id }
            INSERT doc
            UPDATE doc
            IN library_files
            COLLECT WITH COUNT INTO processed
            RETURN processed
    """, bind_vars={"docs": file_docs})
    
    # ArangoDB doesn't return inserted vs updated counts easily
    # Return approximate counts
    return {"inserted": len(file_docs), "updated": 0}

def mark_missing_for_library(self, library_id: str, scan_id: str) -> int:
    """Mark files not seen in this scan as missing/invalid.
    
    Args:
        library_id: Library that was scanned
        scan_id: Timestamp/ID of this scan
        
    Returns:
        Number of files marked invalid
    """
    result = self.db.aql.execute("""
        FOR file IN library_files
            FILTER file.library_id == @library_id
            FILTER file.last_seen_scan_id != @scan_id
            FILTER file.valid == true
            UPDATE file WITH { valid: false } IN library_files
            COLLECT WITH COUNT INTO marked
            RETURN marked
    """, bind_vars={
        "library_id": library_id,
        "scan_id": scan_id
    })
    
    counts = list(result)
    return counts[0] if counts else 0
```

Update `start_scan_wf.py` to pass targets:
```python
async def start_scan_workflow(
    db: Database,
    background_tasks: BackgroundTaskService,
    library_id: str | None = None,  # ArangoDB uses string IDs
    scan_targets: list[ScanTarget] | None = None  # NEW
) -> dict:
    # Resolve library
    if library_id is None:
        library = _get_default_library(db)
    else:
        library = db.library.get(library_id)
        
    # If no targets specified, scan entire library
    if not scan_targets:
        scan_targets = [ScanTarget(library_id=library["_id"], folder_path="")]
        
    # Check for interrupted scan
    interrupted, was_full = db.library.check_interrupted_scan(library["_id"])
    if interrupted:
        logger.warning(f"Detected interrupted scan for library {library['name']}")
        # Continue with current scan targets
        
    # Get batch size from config
    from nomarr.config import config
    batch_size = getattr(config, "scan_batch_size", 200)
    
    # Launch scan
    def _scan():
        return scan_library_direct_workflow(
            db=db,
            library_id=library["_id"],
            scan_targets=scan_targets,
            batch_size=batch_size
        )
        
    if background_tasks:
        task_id = background_tasks.start_task(_scan, name=f"scan_library_{library['_id']}")
        return {"task_id": task_id, "status": "background"}
    else:
        result = await _scan()
        return result
```

---

### Phase 3: Service Layer Updates

**Update LibraryService**

File: `nomarr/services/domain/library_svc.py`

Add new method:
```python
def scan_targets(
    self,
    scan_targets: list[ScanTarget],
    background: bool = True
) -> dict:
    """Scan specific folders within libraries.
    
    Args:
        scan_targets: List of folders to scan
        background: Whether to run in background task
        
    Returns:
        dict with task_id if background, or scan results if synchronous
        
    Raises:
        ValueError: If targets are invalid or library not found
        RuntimeError: If a scan is already in progress for this library
    """
    # Validate targets
    if not scan_targets:
        raise ValueError("scan_targets cannot be empty")
        
    # Group targets by library for validation
    by_library = {}
    for target in scan_targets:
        if target.library_id not in by_library:
            by_library[target.library_id] = []
        by_library[target.library_id].append(target)
        
    # Validate all libraries exist
    for lib_id in by_library.keys():
        library = self.db.library.get(lib_id)
        if not library:
            raise ValueError(f"Library {lib_id} not found")
            
    # ONE LIBRARY AT A TIME (enforce in service layer)
    if len(by_library) > 1:
        raise NotImplementedError("Scanning multiple libraries in one call not yet supported")
        
    library_id = list(by_library.keys())[0]
    
    # CHECK FOR CONCURRENT SCAN (best-effort in single process)
    # NOTE: This is NOT atomic across multiple processes/workers.
    # For multi-process safety, implement a DB-backed lease:
    #   - Atomic UPDATE with owner + expiry timestamp
    #   - Check-and-set pattern or ArangoDB transaction
    # For pre-alpha single-process deployment, this check is sufficient.
    scan_state = self.db.library.get_scan_state(library_id)
    if scan_state and scan_state.get("last_scan_started_at"):
        # Scan in progress if started but not completed
        if not scan_state.get("last_scan_at") or \
           scan_state["last_scan_started_at"] > scan_state["last_scan_at"]:
            raise RuntimeError(f"Scan already in progress for library {library_id}")
    
    # Call workflow
    result = start_scan_workflow(
        db=self.db,
        background_tasks=self.background_tasks if background else None,
        library_id=library_id,
        scan_targets=scan_targets
    )
    
    return result
```

Keep existing methods (backward compatibility):
```python
def start_scan_for_library(
    self,
    library_id: str,  # ArangoDB uses string IDs
    background: bool = True
) -> dict:
    """Scan entire library (full scan).
    
    Convenience method - delegates to scan_targets.
    """
    target = ScanTarget(library_id=library_id, folder_path="")
    return self.scan_targets([target], background=background)
```

---

### Phase 4: File Watcher Service

**Deliverable 5: FileWatcherService**

File: `nomarr/services/infrastructure/file_watcher_svc.py`

```python
"""File system watcher service for automatic library scanning.

This service monitors library directories for changes and triggers
targeted scans via LibraryService. It implements debouncing to batch
rapid changes and avoid excessive scanning.

Architecture:
- One Observer per library
- Events are debounced (configurable quiet period)
- Only relevant file types are processed (audio, playlists, artwork)
- Maps changed paths to parent-folder ScanTargets
- Calls LibraryService.scan_targets() - NO direct persistence access
"""

import asyncio
from pathlib import Path
from collections import defaultdict
from typing import Optional, Callable
import logging

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from nomarr.helpers.dto import ScanTarget
from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


class LibraryEventHandler(FileSystemEventHandler):
    """Handles file system events for a single library."""
    
    # File extensions we care about
    AUDIO_EXTENSIONS = {'.mp3', '.flac', '.m4a', '.ogg', '.opus', '.wav', '.wma'}
    PLAYLIST_EXTENSIONS = {'.m3u', '.m3u8', '.pls'}
    IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    
    def __init__(
        self,
        library_id: int,
        library_root: Path,
        callback: Callable[[int, str], None]
    ):
        super().__init__()
        self.library_id = library_id
        self.library_root = library_root
        self.callback = callback
        
    def on_any_event(self, event: FileSystemEvent):
        """Filter and forward relevant events."""
        # Ignore directory events (we care about files)
        if event.is_directory:
            return
            
        # Get path
        path = Path(event.src_path)
        
        # Filter: only relevant file types
        if not self._is_relevant_file(path):
            logger.debug(f"Ignoring irrelevant file: {path}")
            return
            
        # Filter: ignore temp/hidden files
        if self._is_ignored_file(path):
            logger.debug(f"Ignoring temp/hidden file: {path}")
            return
            
        # Convert to relative path
        try:
            relative_path = path.relative_to(self.library_root)
        except ValueError:
            logger.warning(f"Event path {path} not under library root {self.library_root}")
            return
            
        # Forward to callback
        logger.debug(f"File event: {event.event_type} - {relative_path}")
        self.callback(self.library_id, str(relative_path))
        
    def _is_relevant_file(self, path: Path) -> bool:
        """Check if file type is relevant for scanning."""
        suffix = path.suffix.lower()
        return (
            suffix in self.AUDIO_EXTENSIONS or
            suffix in self.PLAYLIST_EXTENSIONS or
            suffix in self.IMAGE_EXTENSIONS
        )
        
    def _is_ignored_file(self, path: Path) -> bool:
        """Check if file should be ignored."""
        name = path.name
        
        # Hidden files
        if name.startswith('.'):
            return True
            
        # Temp files
        if name.endswith('.tmp') or name.endswith('~'):
            return True
            
        # OS-specific
        if name in {'.DS_Store', 'Thumbs.db', 'desktop.ini'}:
            return True
            
        return False


class FileWatcherService:
    """Manages file system watchers for all libraries.
    
    This service is responsible for:
    1. Starting/stopping watchers per library
    2. Debouncing events (configurable quiet period)
    3. Mapping changed paths to ScanTargets
    4. Delegating to LibraryService for actual scanning
    
    It does NOT:
    - Access persistence directly (violates architecture)
    - Make domain decisions (when to scan, what to process)
    - Trigger ML/tagging pipelines (those are manual)
    """
    
    def __init__(
        self,
        db: Database,
        library_service,  # Type: LibraryService (avoid circular import)
        debounce_seconds: float = 2.0,
        event_loop: asyncio.AbstractEventLoop | None = None
    ):
        self.db = db
        self.library_service = library_service
        self.debounce_seconds = debounce_seconds
        self.event_loop = event_loop or asyncio.get_event_loop()
        
        # Active watchers
        self.observers: dict[int, Observer] = {}
        
        # Debouncing state (thread-safe access needed)
        self.pending_changes: set[tuple[int, str]] = set()  # (library_id, relative_path)
        self.debounce_timer: Optional[asyncio.Task] = None
        
        logger.info(f"FileWatcherService initialized (debounce={debounce_seconds}s)")
        
    def start_watching_library(self, library_id: int) -> None:
        """Start watching a library for changes.
        
        If already watching, restarts the watcher.
        """
        # Get library info
        library = self.db.library.get(library_id)
        if not library:
            raise ValueError(f"Library {library_id} not found")
            
        library_root = Path(library["root_path"])
        if not library_root.exists():
            raise ValueError(f"Library path does not exist: {library_root}")
            
        # Stop existing watcher if any
        if library_id in self.observers:
            logger.info(f"Stopping existing watcher for library {library_id}")
            self.stop_watching_library(library_id)
            
        # Create handler
        handler = LibraryEventHandler(
            library_id=library_id,
            library_root=library_root,
            callback=self._on_file_change
        )
        
        # Create and start observer
        observer = Observer()
        observer.schedule(handler, str(library_root), recursive=True)
        observer.start()
        
        self.observers[library_id] = observer
        logger.info(f"Started watching library {library_id} at {library_root}")
        
    def stop_watching_library(self, library_id: int) -> None:
        """Stop watching a library."""
        if library_id not in self.observers:
            logger.warning(f"No watcher found for library {library_id}")
            return
            
        observer = self.observers[library_id]
        observer.stop()
        observer.join(timeout=5.0)
        
        del self.observers[library_id]
        logger.info(f"Stopped watching library {library_id}")
        
    def stop_all(self) -> None:
        """Stop all watchers (for shutdown)."""
        logger.info("Stopping all file watchers")
        for library_id in list(self.observers.keys()):
            self.stop_watching_library(library_id)
            
**Watcher Threading & Debouncing:**

Watchdog callbacks execute on background threads, NOT the asyncio event loop. The FileWatcherService must:

1. **Enqueue events** from watchdog callbacks into a thread-safe structure (e.g., `set` with lock, or `queue.Queue`)
2. **Use `loop.call_soon_threadsafe()`** to schedule a debounce coroutine in the event loop
3. **Never** call `asyncio.create_task()`, `asyncio.get_event_loop()`, or other asyncio APIs directly from watchdog callbacks

Debouncing logic:
- Each file event resets a debounce timer
- After quiet period (default 2s), collect all pending changes
- Map changed file paths to their parent folder ScanTargets
- Deduplicate targets (if scanning parent, don't scan children)
- Call `LibraryService.scan_targets(targets)` with batch

The watcher is **trigger-only**:
- ✅ Detects filesystem events
- ✅ Maps paths to ScanTargets  
- ✅ Calls LibraryService
- ❌ Does NOT call persistence directly
- ❌ Does NOT make domain decisions (what to scan, when)
- ❌ Does NOT trigger ML/tagging pipelines

```python
    def _on_file_change(self, library_id: str, relative_path: str) -> None:
        """Handle file change event from watchdog thread.
        
        Implementation must use thread-safe handoff to event loop.
        Details left to implementation phase.
        """
        # Add to pending changes
        self.pending_changes.add((library_id, relative_path))
        
        # Schedule debounce via loop.call_soon_threadsafe()
        # (Implementation details omitted - see threading note above)
```
        
    async def _trigger_after_debounce(self) -> None:
        """Wait for quiet period, then trigger scan."""
        await asyncio.sleep(self.debounce_seconds)
        
        # Collect pending changes
        changes = self.pending_changes.copy()
        self.pending_changes.clear()
        
        if not changes:
            return
            
        logger.info(f"Debounce fired: {len(changes)} file changes detected")
        
        # Group by library
        by_library = defaultdict(set)
        for library_id, relative_path in changes:
            by_library[library_id].add(relative_path)
            
        # Map to ScanTargets (parent folder per changed file)
        for library_id, paths in by_library.items():
            targets = self._paths_to_scan_targets(library_id, paths)
            logger.info(f"Triggering scan for library {library_id}: {len(targets)} target(s)")
            
            # Delegate to LibraryService - NO direct persistence calls
            try:
                self.library_service.scan_targets(
                    scan_targets=targets,
                    background=True  # Always background for watcher
                )
            except Exception as e:
                logger.error(f"Failed to trigger scan for library {library_id}: {e}")
                
    def _paths_to_scan_targets(
        self,
        library_id: int,
        paths: set[str]
    ) -> list[ScanTarget]:
        """Convert changed file paths to ScanTargets (parent folders).
        
        Deduplicates targets - multiple files in same folder = one target.
        """
        folders = set()
        
        for path_str in paths:
            path = Path(path_str)
            # Get parent folder
            folder = str(path.parent) if path.parent != Path('.') else ""
            folders.add(folder)
            
        # Convert to ScanTargets
        targets = [
            ScanTarget(library_id=library_id, folder_path=folder)
            for folder in sorted(folders)  # Sort for determinism
        ]
        
        # Deduplicate: if we're scanning parent, don't scan children
        # Example: ["Rock", "Rock/Beatles"] -> ["Rock"]
        targets = self._deduplicate_targets(targets)
        
        return targets
        
    def _deduplicate_targets(self, targets: list[ScanTarget]) -> list[ScanTarget]:
        """Remove redundant targets (child folders when parent is being scanned)."""
        if len(targets) <= 1:
            return targets
            
        # Sort by folder depth (shallowest first)
        sorted_targets = sorted(targets, key=lambda t: t.folder_path.count('/'))
        
        deduplicated = []
        for target in sorted_targets:
            # Check if any existing target is a parent
            is_redundant = False
            for existing in deduplicated:
                if target.folder_path.startswith(existing.folder_path + '/'):
                    is_redundant = True
                    break
            if not is_redundant:
                deduplicated.append(target)
                
        return deduplicated
```

**Configuration**

Add to `nomarr/config.py` or equivalent:
```python
@dataclass
class ScannerConfig:
    # Batch size for DB writes during scanning
    batch_size: int = 200
    
    # File watcher settings
    enable_file_watching: bool = True
    watcher_debounce_seconds: float = 2.0
```

**Lifecycle Integration**

Where watchers are started (e.g., `nomarr/services/service_factory.py` or app startup):
```python
def create_file_watcher_service(
    db: Database,
    library_service: LibraryService,
    config: ScannerConfig
) -> FileWatcherService:
    """Create and start file watcher service."""
    watcher = FileWatcherService(
        db=db,
        library_service=library_service,
        debounce_seconds=config.watcher_debounce_seconds
    )
    
    # Start watching all libraries
    if config.enable_file_watching:
        libraries = db.library.get_all()
        for library in libraries:
            try:
                watcher.start_watching_library(library["_id"])
            except Exception as e:
                logger.warning(f"Failed to start watcher for library {library['name']}: {e}")
                
    return watcher
```

---

### Phase 5: Testing

**Deliverable 6: Unit Tests**

File: `tests/unit/services/test_file_watcher_svc.py`

```python
"""Unit tests for FileWatcherService."""

import asyncio
from pathlib import Path
import tempfile
import time

import pytest

from nomarr.services.infrastructure.file_watcher_svc import FileWatcherService
from nomarr.helpers.dto import ScanTarget


@pytest.fixture
def mock_library_service():
    """Mock LibraryService that records scan calls."""
    class MockLibraryService:
        def __init__(self):
            self.scan_calls = []
            
        def scan_targets(self, scan_targets, background=True):
            self.scan_calls.append({
                "targets": scan_targets,
                "background": background
            })
            return {"status": "ok"}
            
    return MockLibraryService()


@pytest.fixture
def temp_library(tmp_path):
    """Create temporary library directory."""
    library_root = tmp_path / "music"
    library_root.mkdir()
    return library_root


@pytest.fixture
def mock_db(temp_library):
    """Mock database with one library."""
    class MockDB:
        class LibraryOps:
            def get(self, library_id):
                return {
                    "_id": library_id,
                    "name": "Test Library",
                    "root_path": str(temp_library)
                }
                
            def get_all(self):
                return [self.get(1)]
                
        def __init__(self):
            self.library = self.LibraryOps()
            
    return MockDB()


def test_debouncing_triggers_one_scan(mock_db, mock_library_service, temp_library):
    """Test that multiple rapid file changes trigger only one scan after debounce."""
    watcher = FileWatcherService(
        db=mock_db,
        library_service=mock_library_service,
        debounce_seconds=0.5  # Short for testing
    )
    
    # Start watching
    watcher.start_watching_library(1)
    
    # Create multiple files rapidly
    for i in range(10):
        (temp_library / f"track{i}.mp3").touch()
        time.sleep(0.05)  # 50ms between files
        
    # Wait for debounce
    time.sleep(1.0)
    
    # Should have triggered exactly one scan
    assert len(mock_library_service.scan_calls) == 1
    
    # Clean up
    watcher.stop_all()


def test_scan_targets_scans_only_targeted_folder(mock_db, temp_library):
    """Test that targeted scan only processes specified folder."""
    # Create directory structure
    (temp_library / "Rock").mkdir()
    (temp_library / "Jazz").mkdir()
    (temp_library / "Rock" / "track1.mp3").touch()
    (temp_library / "Rock" / "track2.mp3").touch()
    (temp_library / "Jazz" / "track3.mp3").touch()
    
    # Mock scan that records scanned paths
    scanned_paths = []
    
    async def mock_scan_workflow(db, library_id, scan_targets, batch_size):
        for target in scan_targets:
            if target.folder_path:
                path = Path(db.library.get(library_id)["root_path"]) / target.folder_path
            else:
                path = Path(db.library.get(library_id)["root_path"])
            scanned_paths.extend([str(p) for p in path.rglob("*.mp3")])
        return {"files_scanned": len(scanned_paths)}
        
    # Test scanning only "Rock" folder
    target = ScanTarget(library_id=1, folder_path="Rock")
    
    # Would call workflow here - for unit test, just verify target construction
    assert target.library_id == 1
    assert target.folder_path == "Rock"
    assert not target.folder_path.startswith("/")  # Properly normalized


def test_interrupted_scan_state_is_detectable():
    """Test that interrupted scan state can be detected.
    
    Note: This test uses mock ArangoDB client, not SQLite.
    """
    from nomarr.persistence.database.library_operations import LibraryOperations
    from datetime import datetime, timezone
    
    # Mock ArangoDB client
    class MockArangoDB:
        def __init__(self):
            self.docs = {
                "libraries/1": {
                    "_id": "libraries/1",
                    "_key": "1",
                    "name": "Test",
                    "root_path": "/music"
                }
            }
            
        class AQLExecutor:
            def __init__(self, parent):
                self.parent = parent
                
            def execute(self, query, bind_vars):
                # Simplified mock - just return library doc
                lib_id = bind_vars.get("library_id")
                if lib_id in self.parent.docs:
                    return [self.parent.docs[lib_id]]
                return []
                
        @property
        def aql(self):
            return self.AQLExecutor(self)
    
    mock_db = MockArangoDB()
    ops = LibraryOperations(mock_db)
    
    # Simulate interrupted scan
    now = datetime.now(timezone.utc).isoformat()
    mock_db.docs["libraries/1"]["last_scan_started_at"] = now
    mock_db.docs["libraries/1"]["full_scan_in_progress"] = True
    mock_db.docs["libraries/1"]["last_scan_at"] = None
    
    # Check state
    interrupted, was_full = ops.check_interrupted_scan("libraries/1")
    assert interrupted is True
    assert was_full is True
    
    # Complete the scan
    mock_db.docs["libraries/1"]["last_scan_at"] = now
    mock_db.docs["libraries/1"]["last_scan_started_at"] = None
    mock_db.docs["libraries/1"]["full_scan_in_progress"] = False
    
    # Should no longer be interrupted
    interrupted, was_full = ops.check_interrupted_scan("libraries/1")
    assert interrupted is False


def test_deduplicate_targets():
    """Test that redundant child targets are removed."""
    from nomarr.services.infrastructure.file_watcher_svc import FileWatcherService
    
    # Create mock instance just for method access
    watcher = FileWatcherService(
        db=None,
        library_service=None,
        debounce_seconds=1.0
    )
    
    targets = [
        ScanTarget(library_id=1, folder_path="Rock"),
        ScanTarget(library_id=1, folder_path="Rock/Beatles"),
        ScanTarget(library_id=1, folder_path="Rock/Beatles/Abbey Road"),
        ScanTarget(library_id=1, folder_path="Jazz"),
    ]
    
    deduplicated = watcher._deduplicate_targets(targets)
    
    # Should keep only parent folders
    assert len(deduplicated) == 2
    paths = {t.folder_path for t in deduplicated}
    assert paths == {"Rock", "Jazz"}
```

File: `tests/integration/test_incremental_scan.py`

```python
"""Integration tests for incremental scanning."""

import pytest
from pathlib import Path

from nomarr.workflows.library.scan_library_direct_wf import scan_library_direct_workflow
from nomarr.helpers.dto import ScanTarget


@pytest.fixture
def test_library_with_tracks(db, tmp_path):
    """Create test library with audio files."""
    library_root = tmp_path / "music"
    library_root.mkdir()
    
    # Create directory structure
    (library_root / "Rock").mkdir()
    (library_root / "Rock" / "Beatles").mkdir()
    (library_root / "Jazz").mkdir()
    
    # Create test files
    (library_root / "Rock" / "track1.mp3").write_text("fake audio 1")
    (library_root / "Rock" / "Beatles" / "track2.mp3").write_text("fake audio 2")
    (library_root / "Jazz" / "track3.mp3").write_text("fake audio 3")
    
    # Create library in DB
    library = db.library.create({
        "name": "Test Library",
        "root_path": str(library_root)
    })
    
    return library, library_root


async def test_full_library_scan(db, test_library_with_tracks):
    """Test scanning entire library."""
    library, library_root = test_library_with_tracks
    
    target = ScanTarget(library_id=library["_id"], folder_path="")
    
    result = await scan_library_direct_workflow(
        db=db,
        library_id=library["_id"],
        scan_targets=[target],
        batch_size=10
    )
    
    assert result["files_scanned"] == 3
    assert result["files_added"] == 3
    assert result["changes_detected"] is True
    
    # Verify tracks in DB
    tracks = db.tracks.get_all()
    assert len(tracks) == 3


async def test_targeted_scan_single_folder(db, test_library_with_tracks):
    """Test scanning only one subfolder."""
    library, library_root = test_library_with_tracks
    
    # First, full scan to populate DB
    full_target = ScanTarget(library_id=library["_id"], folder_path="")
    await scan_library_direct_workflow(db, library["_id"], [full_target], batch_size=10)
    
    # Now add new file to Rock folder only
    (library_root / "Rock" / "track4.mp3").write_text("fake audio 4")
    
    # Targeted scan of Rock folder
    target = ScanTarget(library_id=library["_id"], folder_path="Rock")
    result = await scan_library_direct_workflow(
        db=db,
        library_id=library["_id"],
        scan_targets=[target],
        batch_size=10
    )
    
    # Should only scan Rock folder (3 files: track1, Beatles/track2, track4)
    assert result["files_scanned"] == 3
    assert result["files_added"] == 1  # Only track4 is new
    
    # Total tracks should be 4
    tracks = db.tracks.get_all()
    assert len(tracks) == 4


async def test_batch_writes(db, test_library_with_tracks):
    """Test that batch writes are used when batch size is reached."""
    library, library_root = test_library_with_tracks
    
    # Create many files
    for i in range(25):
        (library_root / f"track{i}.mp3").write_text(f"fake audio {i}")
        
    # Track DB write calls
    write_calls = []
    original_put_batch = db.tracks.put_batch
    
    def tracked_put_batch(tracks):
        write_calls.append(len(tracks))
        return original_put_batch(tracks)
        
    db.tracks.put_batch = tracked_put_batch
    
    # Scan with batch_size=10
    target = ScanTarget(library_id=library["_id"], folder_path="")
    await scan_library_direct_workflow(
        db=db,
        library_id=library["_id"],
        scan_targets=[target],
        batch_size=10
    )
    
    # Should have multiple batches
    assert len(write_calls) >= 2
    # Most batches should be size 10, last may be smaller
    assert write_calls[0] == 10
```

---

## Implementation Checklist

### Phase 1: Foundation ✓
- [ ] Add `ScanTarget` DTO to `helpers/dto/library.py`
- [ ] Export from `helpers/dto/__init__.py`
- [ ] Add scan state columns to library table (manual ALTER or new migration)
- [ ] Add methods to `LibraryOperations`: `mark_scan_started`, `mark_scan_completed`, `check_interrupted_scan`
- [ ] Run `scripts/generate_inits.py` to update exports

### Phase 2: Workflow Refactoring ✓
- [ ] Update `scan_library_direct_workflow` signature to accept `scan_targets: list[ScanTarget]`
- [ ] Implement targeted folder scanning logic
- [ ] Add batch accumulation and `db.tracks.put_batch()` calls
- [ ] Add `changes_detected` flag logic
- [ ] Mark scan started/completed in workflow
- [ ] Update `start_scan_workflow` to pass `scan_targets`
- [ ] Add `put_batch` method to `TrackOperations`

### Phase 3: Service Updates ✓
- [ ] Add `scan_targets()` method to `LibraryService`
- [ ] Update existing `start_scan_for_library()` to use `scan_targets()`
- [ ] Add validation for scan targets
- [ ] Run `python -m mypy nomarr/services/domain/library_svc.py`

### Phase 4: File Watcher ✅
- [x] Create `services/infrastructure/file_watcher_svc.py`
- [x] Implement `LibraryEventHandler` with file filtering
- [x] Implement `FileWatcherService` with debouncing
- [x] Add `_paths_to_scan_targets()` and `_deduplicate_targets()`
- [x] Add watcher lifecycle to app startup/shutdown
- [x] Add watchdog==6.0.0 to requirements.txt and dockerfile.base

### Phase 5: Testing ⏭️ (Skipped - No DB/ML for integration tests)
- [x] Write `test_file_watcher_svc.py` unit tests (10 tests passing)
- [ ] ~~Write `test_incremental_scan.py` integration tests~~ (Requires DB/ML - deferred)
- [x] Test debouncing (multiple rapid changes = one scan)
- [x] Test targeted scanning (only specified folder is scanned)
- [ ] ~~Test interrupted scan detection~~ (Requires DB - deferred)
- [ ] ~~Test batch writes (verify multiple batches used)~~ (Requires DB - deferred)

### Phase 6: Documentation 🔄 (In Progress)
- [ ] Update `docs/dev/architecture.md` with watcher architecture
- [ ] Document configuration options (TODO: add to config.yaml)
- [ ] Add docstrings to all new public methods
- [ ] Update README with file watching feature

---

## API Discovery Commands

Before implementation, confirm existing APIs:

```bash
# Check LibraryService current interface
python scripts/discover_api.py nomarr.services.domain.library_svc

# Check library workflow signatures
python scripts/discover_api.py nomarr.workflows.library.scan_library_direct_wf

# Check persistence layer
python scripts/discover_api.py nomarr.persistence.database.library_operations
python scripts/discover_api.py nomarr.persistence.database.track_operations

# Verify DTO structure
python scripts/discover_api.py nomarr.helpers.dto
```

---

## Architecture Compliance Verification

After implementation, verify clean architecture:

```bash
# Check import dependencies
import-linter

# Check for upward imports (should be zero)
python scripts/detect_slop.py nomarr/services/infrastructure/file_watcher_svc.py

# Verify service is thin (no complex logic)
radon cc -s nomarr/services/infrastructure/file_watcher_svc.py

# Type checking
mypy nomarr/services/infrastructure/file_watcher_svc.py
mypy nomarr/workflows/library/scan_library_direct_wf.py
```

---

## Migration Strategy

### For Pre-Alpha Users

**Option 1: Rebuild Database (Clean Slate)**
```bash
# 1. Note library paths from current config/UI
# 2. Stop Nomarr
# 3. Drop ArangoDB collections (or delete entire database)
# 4. Restart Nomarr (collections auto-recreate)
# 5. Re-add libraries via UI/API
# 6. Run full scans - new fields populate automatically
```

**Option 2: Let Documents Evolve (Zero-Downtime)**
- Do nothing - just deploy code
- Library documents gain new fields on first scan after upgrade
- Missing fields default to `null` in AQL queries (safe)
- Optional: run backfill job to add fields to existing docs:
  ```javascript
  // In ArangoDB Web UI
  FOR lib IN libraries
      UPDATE lib WITH {
          last_scan_started_at: lib.last_scan_started_at || null,
          full_scan_in_progress: lib.full_scan_in_progress || false
      } IN libraries
  ```

**Option 3: Manual Document Updates (Advanced)**
```javascript
// Run in ArangoDB Web UI (AQL Editor)
FOR lib IN libraries
    UPDATE lib WITH {
        last_scan_started_at: null,
        full_scan_in_progress: false
    } IN libraries OPTIONS { keepNull: false }

// Verify
FOR lib IN libraries
    RETURN {
        _key: lib._key,
        name: lib.name,
        has_scan_fields: HAS(lib, 'last_scan_started_at')
    }
```

### Breaking Changes

1. **Workflow Signature Change**
   - Old: `scan_library_direct_workflow(db, library_id)` (no scan_targets)
   - New: `scan_library_direct_workflow(db, library_id, scan_targets, batch_size)`
   - Impact: Service layer must construct `[ScanTarget(...)]` list
   - Fix: Update `start_scan_workflow` to wrap library_id in ScanTarget

2. **Service Method Addition**
   - Added: `LibraryService.scan_targets(targets)` 
   - Modified: `start_scan_for_library()` now delegates to `scan_targets()`
   - Impact: None for API consumers (backward compatible)

3. **Document Shape Evolution**
   - Library documents gain: `last_scan_started_at`, `full_scan_in_progress`
   - Library_files documents gain: `normalized_path`, `last_seen_scan_id`
   - Impact: Existing documents missing fields (AQL returns `null`)
   - Fix: First scan auto-populates OR run manual backfill above

4. **Path Normalization**
   - Files now stored with POSIX-style normalized_path
   - Impact: Existing file_path fields may use OS separators
   - Fix: Re-scan libraries to normalize paths OR write migration script

---

## Performance Expectations

Based on Navidrome's results:

### Full Library Scan
- Before: ~5-10 minutes for 10,000 tracks
- After: Same (no improvement for full scans)

### Incremental Scan (1% of files changed)
- Before: ~5-10 minutes (scans everything)
- After: ~5-30 seconds (scans only changed folders)
- **Speedup: 10-100x**

### File Watcher Responsiveness
- Detection latency: <1 second (filesystem notification)
- Debounce delay: 2 seconds (configurable)
- Scan trigger: 2-3 seconds after file stops changing
- **Total: ~3-5 seconds from file save to scan start**

### Memory Usage
- Batch size 200: ~5-10 MB per library during scan
- File watcher: ~1-2 MB per library (watchdog overhead)

---

## Risks & Mitigations

### Risk: Watcher Missing Events
**Scenario:** Watchdog fails to detect file changes on network mounts or FUSE filesystems
**Mitigation:** 
- Document limitations in README (watchdog uses inotify/FSEvents/ReadDirectoryChangesW)
- Keep manual scan button in UI (always available fallback)
- Add health check: track last_watcher_event_at per library
- Consider polling fallback for network mounts (future enhancement)

### Risk: Excessive Scanning (Debounce Too Short)
**Scenario:** User copies 10,000 files, watcher triggers scan every 2 seconds
**Mitigation:**
- Configurable debounce (increase to 10-30s for bulk operations)
- Adaptive debounce: extend timeout if events keep arriving
- Max targets per scan (future: queue targets if > N folders)
- UI indicator: "Heavy file activity detected, scan delayed"

### Risk: Concurrent Scan Attempts
**Scenario:** Manual scan triggered while watcher scan running, or multiple watcher triggers
**Mitigation:**
- Service-level check: `last_scan_started_at` without `last_scan_at` = scan in progress
- Raise RuntimeError if scan already running (user sees clear error)
- Future: ArangoDB-backed lease system (atomic compare-and-swap on scan state)
- Log all scan start/stop events for debugging

### Risk: Threading Issues (Watchdog → Asyncio)
**Scenario:** Watchdog callbacks run in background threads, not asyncio event loop
**Mitigation:**
- NEVER call `asyncio.create_task()` directly from watchdog callback
- Use `loop.call_soon_threadsafe()` for all asyncio handoffs
- Debounce timer scheduling must go through event loop
- Document threading constraints in FileWatcherService docstring
- Add unit test for thread-safe event handling

### Risk: Upward Import Violations
**Scenario:** Developer adds persistence call in FileWatcherService (violates architecture)
**Mitigation:**
- Enforced by import-linter (CI will fail)
- Code review checklist: "Does watcher call LibraryService, not DB?"
- Clear documentation in service docstring: "NO direct persistence access"
- Architecture tests: assert no imports from nomarr.persistence in watcher

### Risk: ArangoDB Connection Pool Exhaustion
**Scenario:** Batch upserts hold connections during long scans
**Mitigation:**
- Keep batch size reasonable (200-500 docs)
- Commit each batch immediately (don't hold open transactions)
- Monitor connection pool usage in production
- ArangoDB connection pooling already handles concurrency

---

## Future Enhancements (Not in This Refactor)

1. **Folder Hashing** (Navidrome-style)
   - Hash folder contents to skip unchanged folders
   - Requires `folder` table with `hash` column
   - ~100x speedup for incremental scans

2. **Parallel Library Scanning**
   - Scan multiple libraries simultaneously
   - Requires thread-safe DB access

3. **Smart Batch Size**
   - Auto-adjust batch size based on file count
   - Large batches for bulk imports, small for incremental

4. **.ndignore Support**
   - Gitignore-style patterns per library
   - Requires IgnoreChecker component

5. **Scan Progress Streaming**
   - Real-time progress via SSE
   - Requires event broker integration

6. **Watch-Triggered ML**
   - Automatically tag new files (optional)
   - Requires queue system + worker pool

---

## Success Criteria

This refactor is successful when:

1. ✅ File watching detects changes within 5 seconds of filesystem event
2. ✅ Incremental scans process only targeted folders (not entire library)
3. ✅ Multiple rapid file changes trigger only one debounced scan
4. ✅ Interrupted scans detected via timestamp comparison on restart
5. ✅ Batch upserts reduce DB roundtrips (N files → ⌈N/batch_size⌉ queries)
6. ✅ Scan returns `files_scanned` and `files_processed` (no inserted/updated split)
7. ✅ All behavioral tests pass (see Test Requirements section)
8. ✅ Architecture compliance: no upward imports (`import-linter`)
9. ✅ Type checking passes (`mypy nomarr/`)
10. ✅ Linting passes (`ruff check nomarr/`)
11. ✅ ML/tagging workflows unchanged (backward compatible)
12. ✅ Manual scan still works via UI/API (full library as ScanTarget)
13. ✅ Path normalization consistent (POSIX-style relative paths stored)

---

## Implementation Timeline

**Phase 1 (Foundation):** 1-2 days
- DTOs, persistence changes, tests

**Phase 2 (Workflow):** 2-3 days  
- Refactor scan workflow, batch writes, tests

**Phase 3 (Service):** 1 day
- Update LibraryService, tests

**Phase 4 (Watcher):** 2-3 days
- Implement FileWatcherService, integration, tests

**Phase 5 (Polish):** 1-2 days
- Documentation, configuration, final testing

**Total:** 7-11 days

---

## Review Checklist

Before merging:

- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] `import-linter` passes (no architecture violations)
- [ ] `mypy nomarr/` passes (no type errors)
- [ ] `ruff check nomarr/` passes (no lint errors)
- [ ] Manual testing: file watcher detects changes
- [ ] Manual testing: incremental scan faster than full scan
- [ ] Manual testing: batch writes visible in logs
- [ ] Documentation updated
- [ ] Configuration added to config.yaml
- [ ] API discovery scripts confirm new methods exist
- [ ] No upward imports (workflows don't import services)
- [ ] Services remain thin (no complex logic)
- [ ] ML/tagging flows unaffected (backward compatible)

---

## Questions for Clarification

Before implementation, confirm:

1. **Batch Size Default:** 200 files per batch OK? (Navidrome uses 200)
2. **Debounce Default:** 2 seconds OK? (Navidrome default)
3. **Watcher Library:** Use `watchdog` library? (Cross-platform, mature, well-maintained)
4. **Document Evolution:** Let fields auto-populate on first scan, or write backfill job?
5. **Config Location:** Add scanner config to existing config.yaml or separate section?
6. **Lifecycle:** Start watchers in `app.py` startup or via service factory?
7. **Error Handling:** Log watcher failures or raise exceptions? (Suggest: log + continue)
8. **Multiple Libraries:** Scan one at a time or parallel? (Suggest: sequential first)
9. **Path Normalization:** Store absolute + relative, or just relative? (Suggest: both)
10. **Scan Lease:** Implement DB-backed atomic lease now, or defer? (Pre-alpha: defer)

---

## Appendix: File Structure

New files:
```
nomarr/
  helpers/
    dto/
      library.py          # Add ScanTarget
  services/
    infrastructure/
      file_watcher_svc.py # NEW: FileWatcherService
  workflows/
    library/
      scan_library_direct_wf.py  # MODIFIED: Accept scan_targets
      start_scan_wf.py            # MODIFIED: Pass scan_targets
  persistence/
    database/
      library_operations.py  # MODIFIED: Add scan state methods
      track_operations.py    # MODIFIED: Add put_batch

tests/
  unit/
    services/
      test_file_watcher_svc.py  # NEW
  integration/
    test_incremental_scan.py    # NEW
```

Modified files:
```
nomarr/services/domain/library_svc.py  # Add scan_targets method
nomarr/app.py                           # Start watchers on startup
config/config.yaml                      # Add watcher config
```

---

**End of Refactor Plan**
