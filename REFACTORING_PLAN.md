# Nomarr Architecture Refactoring Plan

## Current Problems
1. **Confusing folder structure** - `core/` and `data/` don't reflect their actual purpose
2. **Duplicated business logic** - CLI reimplements what API has in helpers
3. **Interfaces too thick** - CLI/API/Web doing business logic instead of just presentation
4. **Mixed concerns** - Queue orchestration in `data/`, ML + DB mixed in `core/`

## Goals
1. Clear, semantic folder structure
2. Shared business logic (service layer)
3. Thin interfaces (just presentation)
4. Class-based services for better organization

---

## Phase 1: Folder Structure Reorganization
**Goal:** Clear, semantic folder names that match their purpose

### Target Structure
```
nomarr/
├── tagging/         # Tag processing rules (opinionated logic)
│   └── aggregation.py
│
├── ml/              # Machine learning (models, inference, embeddings)
│   ├── discovery.py
│   ├── inference.py
│   ├── embeddings.py
│   └── heads.py
│
├── services/        # Business operations (orchestration, workflows)
│   ├── processing.py     # Audio processing pipeline
│   ├── queue.py          # Queue management operations
│   ├── library.py        # Library scanning operations
│   ├── cache.py          # Model cache management
│   ├── analytics.py      # Tag analysis/stats
│   └── workers/
│       ├── tagger.py     # TaggerWorker (processes queue)
│       └── scanner.py    # LibraryScanWorker (scans library)
│
├── data/            # Data access & persistence (thin DB layer)
│   └── database.py  # Database + Job class
│
├── interfaces/      # Presentation layer (thin - just I/O)
│   ├── web/
│   │   ├── static/       # HTML/CSS/JS files
│   │   └── endpoints.py  # Backend proxy endpoints
│   ├── api/              # Public + Internal HTTP endpoints
│   └── cli/              # Terminal commands
│
├── helpers/         # Shared utilities (cross-cutting)
│   ├── files.py     # File operations
│   ├── db.py        # DB helper functions
│   └── config.py    # Config loading (move util.py here)
│
└── [other existing files]

models/              # Outside nomarr/ - ML weights & sidecars
```

### Migration Steps
- [ ] **Step 1.1:** Create new folder structure (empty)
- [ ] **Step 1.2:** Move `core/tagging/` → `tagging/`
- [ ] **Step 1.3:** Move `models/*.py` → `ml/`
- [ ] **Step 1.4:** Move `core/inference.py` → `ml/`
- [ ] **Step 1.5:** Move `core/processor.py` → `services/processing.py`
- [ ] **Step 1.6:** Move `core/cache.py` → `services/cache.py`
- [ ] **Step 1.7:** Move `core/analytics.py` → `services/analytics.py`
- [ ] **Step 1.8:** Move `data/queue.py` (TaggerWorker) → `services/workers/tagger.py`
- [ ] **Step 1.9:** Move `data/library_worker.py` → `services/workers/scanner.py`
- [ ] **Step 1.10:** Move `data/queue.py` (JobQueue) → `services/queue.py` or keep with DB?
- [ ] **Step 1.11:** Rename `data/db.py` → `data/database.py`
- [ ] **Step 1.12:** Move `util.py` → `helpers/config.py`
- [ ] **Step 1.13:** Colocate web UI: move `interfaces/web/` static files + create `endpoints.py`
- [ ] **Step 1.14:** Update all imports across codebase
- [ ] **Step 1.15:** Run `generate_inits.py`
- [ ] **Step 1.16:** Run tests, verify nothing broke
- [ ] **Step 1.17:** Delete old empty folders

**Estimated Effort:** 4-6 hours of careful find-replace + testing

---

## Phase 2: Service Layer (Class-Based Architecture)
**Goal:** Extract business logic into reusable service classes

### Service Classes to Create

#### QueueService (`services/queue.py`)
```python
class QueueService:
    """Queue management operations - shared by all interfaces."""
    
    def add_files(self, paths: list[str], force: bool, recursive: bool) -> dict:
        """Add audio files to queue. Returns job_ids, queue_depth, etc."""
        
    def remove_jobs(self, job_id=None, status=None, all=False) -> int:
        """Remove jobs from queue. Returns count removed."""
        
    def get_status(self) -> dict:
        """Get queue statistics (pending, running, completed, errors)."""
        
    def flush(self, statuses: list[str] | None = None) -> int:
        """Flush queue by status. Returns count removed."""
```

#### ProcessingService (`services/processing.py`)
```python
class ProcessingService:
    """Audio processing operations - shared by all interfaces."""
    
    def process_file(self, path: str, force: bool) -> dict:
        """Process single audio file. Returns results."""
        
    def process_batch(self, paths: list[str], force: bool) -> dict:
        """Process multiple files. Returns batch results."""
```

#### LibraryService (`services/library.py`)
```python
class LibraryService:
    """Library scanning operations."""
    
    def scan_library(self, library_path: str) -> dict:
        """Scan library directory. Returns scan results."""
        
    def get_library_files(self, filters: dict) -> list[dict]:
        """Get library files with filters."""
```

#### WorkerService (`services/workers/manager.py`)
```python
class WorkerService:
    """Worker management operations."""
    
    def pause_workers(self) -> None:
        """Pause background workers."""
        
    def resume_workers(self) -> None:
        """Resume background workers."""
        
    def get_worker_status(self) -> dict:
        """Get worker status (enabled, count, etc.)."""
```

### Implementation Steps
- [ ] **Step 2.1:** Create `QueueService` class
- [ ] **Step 2.2:** Extract `queue_file_for_tagging()` logic into `QueueService.add_files()`
- [ ] **Step 2.3:** Update API endpoints to use `QueueService`
- [ ] **Step 2.4:** Update CLI commands to use `QueueService`
- [ ] **Step 2.5:** Remove duplicated queue logic from CLI
- [ ] **Step 2.6:** Create `ProcessingService` class
- [ ] **Step 2.7:** Create `LibraryService` class
- [ ] **Step 2.8:** Create `WorkerService` class
- [ ] **Step 2.9:** Update `state.py` to instantiate services
- [ ] **Step 2.10:** Update all interfaces to use services
- [ ] **Step 2.11:** Run tests, verify behavior unchanged

**Estimated Effort:** 6-8 hours

---

## Phase 3: DRY Interfaces
**Goal:** Thin interfaces that only handle presentation

### Changes Needed

#### CLI Commands Pattern
**Before:**
```python
def cmd_queue(args):
    audio_files = collect_audio_files(args.paths, args.recursive)
    q = JobQueue(db)
    for file in audio_files:
        job_id = q.add(file, args.force)
    # Display with Rich
```

**After:**
```python
def cmd_queue(args):
    result = queue_service.add_files(args.paths, args.force, args.recursive)
    # Display result with Rich UI
    InfoPanel.show("Queue Summary", format_result(result))
```

#### API Endpoints Pattern
**Before:**
```python
async def tag_audio(req: TagRequest):
    result = queue_file_for_tagging(...)  # Helper function
    return result
```

**After:**
```python
async def tag_audio(req: TagRequest):
    result = state.queue_service.add_files(req.path, req.force, True)
    return result
```

### Implementation Steps
- [ ] **Step 3.1:** Update all CLI commands to use services
- [ ] **Step 3.2:** Remove duplicated logic from CLI commands
- [ ] **Step 3.3:** Update API endpoints to use services
- [ ] **Step 3.4:** Remove helper functions that are now in services
- [ ] **Step 3.5:** Update Web endpoints to use services
- [ ] **Step 3.6:** Verify all three interfaces produce same results
- [ ] **Step 3.7:** Run integration tests

**Estimated Effort:** 4-6 hours

---

## Phase 4: Cleanup
**Goal:** Remove dead code, update docs, verify quality

### Tasks
- [ ] **Step 4.1:** Remove unused helper functions
- [ ] **Step 4.2:** Remove dead code (like old `get_status_counts`)
- [ ] **Step 4.3:** Run `ruff check --fix .`
- [ ] **Step 4.4:** Run `ruff format .`
- [ ] **Step 4.5:** Update `README.md` with new structure
- [ ] **Step 4.6:** Update `.github/copilot-instructions.md`
- [ ] **Step 4.7:** Update API documentation
- [ ] **Step 4.8:** Run full test suite
- [ ] **Step 4.9:** Test in Docker container
- [ ] **Step 4.10:** Verify Lidarr integration still works

**Estimated Effort:** 2-3 hours

---

## Total Estimated Effort
**16-23 hours of focused work**

## Recommended Approach

### Option A: All at once (risky)
- Do all phases in one big PR
- High risk of breaking things
- Hard to debug if issues arise

### Option B: One phase at a time (safer)
1. Week 1: Phase 1 (folder structure)
2. Week 2: Phase 2 (service classes)
3. Week 3: Phase 3 (DRY interfaces)
4. Week 4: Phase 4 (cleanup)

### Option C: Incremental (safest)
- Do one service at a time
- E.g., Start with `QueueService`
- Verify it works in all interfaces
- Move to next service

## My Recommendation
**Option C - Incremental**
1. Start with QueueService (most duplicated)
2. Keep folder structure as-is for now
3. Once services proven, do folder refactor
4. Less risk, easier to validate each step

---

## Decision Points

### 1. Folder Structure
- [ ] Approve target structure above
- [ ] Any naming changes? (`tagging/` vs `rules/` vs other?)
- [ ] Colocate web frontend+backend or keep separate?

### 2. Service Architecture
- [ ] Approve service class pattern
- [ ] Where should services live? (`services/` vs `core/services/`?)
- [ ] Keep JobQueue as-is or wrap in QueueService?

### 3. Approach
- [ ] Which option? (A/B/C or custom)
- [ ] Start with folder refactor or services first?
- [ ] Do everything or just critical parts?

---

## Next Steps
1. Review this plan
2. Make decisions on open questions
3. Choose approach
4. Start with first phase/increment

---

## Progress Tracking

### Phase 2: Service Layer (IN PROGRESS ✅)

**Decision:** User chose services-first (Option C - Incremental)

**Status:** Started 2025-11-03

**Completed:**
- ✅ Created `nomarr/services/queue.py` with QueueService class
  - Methods: add_files(), remove_jobs(), get_status(), get_job(), reset_jobs(), cleanup_old_jobs(), get_depth()
  - All business logic extracted from interfaces
- ✅ Added QueueService to global state (`nomarr/interfaces/api/state.py`)
- ✅ Re-exported queue_service from `nomarr/interfaces/api/__init__.py`
- ✅ Updated API endpoints to use QueueService:
  - `/internal/admin/reset` - Uses reset_jobs() (2 flags: --stuck, --errors)
  - `/api/v1/tag` - Uses add_files() for queueing
  - `/admin/queue/remove` - Uses remove_jobs(job_id=...)
  - `/admin/queue/flush` - Uses remove_jobs(status=...) in loop
  - `/admin/queue/cleanup` - Uses cleanup_old_jobs()
- ✅ Updated CLI commands to use QueueService directly (NO HTTP!):
  - `queue` - Uses add_files() to queue files
  - `remove` - Uses remove_jobs() with job_id/status/all modes
  - `cleanup` - Uses cleanup_old_jobs()
  - `admin-reset` - Uses reset_jobs() with --stuck/--errors flags
- ✅ Created `nomarr/services/processing.py` with ProcessingService class
  - Methods: process_file(), process_batch(), get_worker_count(), is_available(), shutdown()
  - Wraps ProcessingCoordinator for clean API
  - Initialized in app.py startup, shutdown on teardown
- ✅ Created `nomarr/services/library.py` with LibraryService class
  - Methods: start_scan(), cancel_scan(), get_status(), get_scan_history()
  - **CRITICAL**: Coordinates between CLI (synchronous) and API (background worker)
  - Prevents race conditions on library_scans table
  - Ensures only ONE scan runs at a time across all interfaces
- ✅ Created `nomarr/services/worker.py` with WorkerService class
  - Methods: start_workers(), stop_all_workers(), enable(), disable(), pause(), resume(), get_status()
  - **CRITICAL**: All three interfaces (CLI + API + Web) manage same worker pool
  - Shared worker_enabled flag in DB meta = needs consistency
  - Prevents conflicts when CLI/API/Web all control workers
- ✅ All linters passing (ruff check + auto-fix)

**In Progress:**
- 🔄 Need to integrate services into all interfaces

**Next Steps:**
1. Add LibraryService to API state and wire up endpoints
2. Add WorkerService to API state and wire up endpoints
3. Update CLI to use LibraryService and WorkerService
4. Update Web proxy endpoints to use services
5. Test cross-interface coordination (start in CLI, see in Web, etc.)
