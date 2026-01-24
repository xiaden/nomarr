# Naming Standards

**Naming Conventions for Services, Methods, DTOs, and Modules**

---

## Overview

Nomarr enforces naming rules to ensure:
- **Predictability** - Names indicate purpose and behavior
- **Discoverability** - Tools and developers can find what they need
- **Clean Architecture** - Names reflect layer boundaries

This document defines public-facing naming rules for all code.

**See also:** [architecture.md](architecture.md) for layer responsibilities.

---

## 1. Service Names

### Format

```
<Noun>Service
```

**Rules:**
- End with `Service`
- Singular noun (not plural)
- Describes the domain

**Examples:**
```python
✅ LibraryService
✅ AnalyticsService
✅ QueueService
✅ ProcessingService
✅ CalibrationService
✅ NavidromeService

❌ LibrariesService  # Use singular
❌ ServiceLibrary    # Wrong order
❌ WorkersCoordinator  # Not a service (special case allowed for coordinator)
```

**Special cases:**
- `WorkersCoordinator` - Manages workers (not technically a service)
- `StateBroker` - Manages state (not technically a service)

---

## 2. Service Method Names

### Format

```
<verb>_<noun>
```

**Rules:**
- Snake_case
- Start with allowed verb
- End with noun describing what's operated on
- No transport prefixes (`api_`, `web_`, `cli_`)
- No context suffixes (`_for_admin`, `_internal`)

### Allowed Verbs

**Read Operations:**
```python
get_      # Retrieve single item (get_library, get_job)
list_     # Retrieve multiple items (list_libraries, list_jobs)
exists_   # Check existence (exists_library)
count_    # Count items (count_pending_jobs)
```

**Write Operations:**
```python
create_   # Create new item (create_library)
add_      # Add item (add_library)
update_   # Modify existing item (update_library)
delete_   # Remove item (delete_library)
remove_   # Remove item (remove_library)
set_      # Set value (set_threshold)
```

**Domain Operations:**
```python
scan_     # Scan library (scan_library)
process_  # Process file (process_file)
tag_      # Tag file (tag_file)
enqueue_  # Add to queue (enqueue_file)
dequeue_  # Remove from queue (dequeue_job)
export_   # Export data (export_playlists)
import_   # Import data (import_library)
sync_     # Synchronize (sync_with_navidrome)
```

**State Operations:**
```python
start_    # Start workers (start_workers)
stop_     # Stop workers (stop_workers)
pause_    # Pause workers (pause_workers)
resume_   # Resume workers (resume_workers)
restart_  # Restart workers (restart_workers)
enable_   # Enable feature (enable_calibration)
disable_  # Disable feature (disable_calibration)
```

**Complex Operations:**
```python
generate_ # Generate data (generate_calibration)
apply_    # Apply changes (apply_calibration)
clear_    # Clear data (clear_completed)
retry_    # Retry failed (retry_errors)
requeue_  # Requeue job (requeue_job)
```

### Examples

**Good:**
```python
def get_library(self, library_id: int) -> LibraryDict | None
def list_libraries(self) -> list[LibraryDict]
def scan_library(self, library_id: int) -> ScanResultDict
def enqueue_file(self, path: str, library_id: int) -> int
def pause_workers(self) -> None
def generate_calibration(self) -> CalibrationResultDict
```

**Bad:**
```python
❌ def api_get_library(...)  # No transport prefix
❌ def fetch_library(...)    # Use get_
❌ def libraryGet(...)       # Use snake_case, verb first
❌ def get_library_for_admin(...)  # No context suffix
❌ def internal_get_library(...)   # No visibility prefix
```

### Adding New Verbs

New verbs require:
1. Clear justification (why existing verbs insufficient)
2. Documentation update
3. Consistent usage across codebase

---

## 3. DTO Naming

### Format

```
<Name>Dict
```

**Rules:**
- CamelCase
- End with `Dict` (TypedDict) or `DTO` (dataclass)
- Descriptive name indicating contents
- Place in `helpers/dto/<domain>.py` if cross-layer

### Examples

**TypedDict (preferred for simple DTOs):**
```python
class LibraryDict(TypedDict):
    """Library metadata."""
    id: int
    name: str
    path: str
    created_at: int

class QueueStatusDict(TypedDict):
    """Queue status counts."""
    pending: int
    running: int
    completed: int
    errors: int

class JobDict(TypedDict):
    """Queue job details."""
    id: int
    path: str
    status: str
    error: str | None
```

**Dataclass (for DTOs with methods):**
```python
@dataclass
class ProcessorConfigDTO:
    """Processing configuration."""
    workers: int
    batch_size: int
    timeout: int
    
    def validate(self) -> list[str]:
        """Validate configuration."""
        errors = []
        if self.workers < 1:
            errors.append("workers must be >= 1")
        return errors
```

**Result DTOs:**
```python
class ScanResultDict(TypedDict):
    """Library scan result."""
    files_found: int
    files_added: int
    files_updated: int
    errors: list[str]

class CalibrationResultDict(TypedDict):
    """Calibration operation result."""
    tags_calibrated: int
    tracks_updated: int
```

### DTO Placement

**Single-service DTOs:**
- Define at top of service file
- Not exported from `helpers/dto/`

**Cross-layer DTOs:**
- Define in `helpers/dto/<domain>.py`
- Export from `helpers/dto/__init__.py`
- Used by multiple services OR used by interfaces

**Example structure:**
```
helpers/dto/
├── __init__.py
├── queue.py          # Queue-related DTOs
├── library.py        # Library-related DTOs
├── calibration.py    # Calibration-related DTOs
├── analytics.py      # Analytics-related DTOs
└── navidrome.py      # Navidrome-related DTOs
```

---

## 4. Module Naming

### Services

**Format:** `<domain>_service.py`

```python
✅ library_service.py
✅ queue_service.py
✅ processing_service.py
✅ calibration_service.py

❌ library.py  # Too generic
❌ svc_library.py  # Wrong order
```

### Workflows

**Format:** `<domain>_workflow.py` or `<domain>/<operation>.py`

```python
✅ processing/process_file.py
✅ library/scan_library.py
✅ calibration/generate_calibration.py

❌ process.py  # Too generic
❌ workflow_process.py  # Wrong order
```

### Components

**Format:** `<domain>/<component>.py`

```python
✅ analytics/tag_stats.py
✅ tagging/aggregation.py
✅ ml/inference.py

❌ utils.py  # Too generic
```

### Helpers

**Format:** `<name>.py` (descriptive, no suffix)

```python
✅ audio.py
✅ files.py
✅ logging.py
✅ dataclasses.py

❌ audio_utils.py  # Redundant suffix
❌ helpers.py  # Too generic
```

---

## 5. File Structure

### Service Files

**Simple services: one class per file ending in `_svc.py`:**

```python
# processing_svc.py

from nomarr.persistence.db import Database
from nomarr.helpers.dto.processing import ProcessingResult

class ProcessingService:
    """Manage file processing operations."""
    
    def __init__(self, db: Database):
        self.db = db
    
    def get_status(self) -> ProcessingResult:
        """Get processing status."""
        pass
```

### Service Packages

**Complex services with multiple concerns use a package (folder) ending in `_svc`:**

```
nomarr/services/domain/library_svc/
├── __init__.py      # Exports LibraryService (composed from mixins)
├── admin.py         # LibraryAdminMixin
├── scan.py          # LibraryScanMixin
├── query.py         # LibraryQueryMixin
├── files.py         # LibraryFilesMixin
└── config.py        # LibraryServiceConfig dataclass
```

**Rules:**
- Package folder ends in `_svc` (e.g., `library_svc/`)
- Internal files do NOT need `_svc.py` suffix
- Internal classes (mixins, config) don't follow `<Domain>Service` pattern
- Only the composed class exported from `__init__.py` is `<Domain>Service`

```python
# library_svc/__init__.py
from .admin import LibraryAdminMixin
from .scan import LibraryScanMixin
from .query import LibraryQueryMixin

class LibraryService(LibraryAdminMixin, LibraryScanMixin, LibraryQueryMixin):
    """Unified library service composed from mixins."""
    pass
```

**Service-local DTOs at top:**

```python
# queue_service.py

from typing import TypedDict

# Service-local DTO (not exported)
class _QueueInternalState(TypedDict):
    """Internal queue state (not for external use)."""
    lock_acquired: bool
    last_dequeue: int

class QueueService:
    # ... service implementation
```

### Avoid Ad-Hoc Splitting

**Bad - splitting without a package:**
```python
# library_service.py
class LibraryService:
    def get_library(...): pass

# library_service_scan.py  # ❌ Splitting same service without package
class LibraryService:
    def scan_library(...): pass
```

**Good - simple service in one file:**
```python
# analytics_svc.py
class AnalyticsService:
    def get_stats(...): pass
    def compute_insights(...): pass
```

**Good - complex service in a package:**
```
library_svc/
├── __init__.py     # Exports composed LibraryService
├── admin.py        # Create, update, delete operations
├── scan.py         # Scanning operations
└── query.py        # Read operations
```

---

## 6. Why These Standards Exist

### Predictability

**Given a service name, you know:**
- It's in `services/<name>_service.py`
- It has a class `<Name>Service`
- Methods follow `<verb>_<noun>` pattern

**Example:**
```python
# I need to scan a library
# → LibraryService → library_service.py → scan_library()
```

### Discoverability

**Tools work better:**
- Copilot suggests correct names
- `grep` finds all services: `grep "class.*Service"`
- `scripts/discover_api.py` generates accurate docs

### Clean Boundaries

**Names encode layer information:**
- `*Service` → Service layer
- `*Dict` → DTO (crosses layers)
- `*Operations` → Persistence layer
- `*workflow` → Workflow layer

**You can't accidentally:**
- Call workflow from interface (no direct import)
- Mix service and persistence logic (different patterns)

### Refactor Safety

**Consistent names make refactoring easier:**
- Rename service method → all callers found via search
- Move DTO → import paths consistent
- Split service → naming pattern preserved

---

## 7. Enforcement

### Automated

**`scripts/check_naming.py`:**
- Checks service names
- Checks method names against allowed verbs
- Reports violations

**Run:**
```bash
python scripts/check_naming.py
```

### Manual Review

**Code review checklist:**
- [ ] Service names end with `Service`
- [ ] Methods use allowed verbs
- [ ] DTOs end with `Dict` or `DTO`
- [ ] No transport prefixes in names
- [ ] No context suffixes in names

---

## 8. Migration

### Existing Code

**Pre-alpha:** No backward compatibility required. Refactor aggressively.

**When renaming:**
1. Update service/method name
2. Update all call sites
3. Update tests
4. Update documentation
5. Run `check_naming.py` to verify

### Example Refactor

**Before:**
```python
class LibraryManager:  # ❌ Not "Service"
    def api_get_library(self, library_id):  # ❌ api_ prefix
        pass
```

**After:**
```python
class LibraryService:  # ✅
    def get_library(self, library_id: int) -> LibraryDict | None:  # ✅
        pass
```

**Update callers:**
```python
# Before
library = library_manager.api_get_library(1)

# After
library = library_service.get_library(1)
```

---

## 9. Quick Reference

```python
# Services
<Noun>Service                 # LibraryService

# Methods
<verb>_<noun>                 # get_library, scan_library, pause_workers

# DTOs
<Name>Dict                    # LibraryDict, QueueStatusDict
<Name>DTO                     # ProcessorConfigDTO (if dataclass)

# Files
services/<domain>_service.py  # library_service.py
workflows/<domain>/<op>.py    # library/scan_library.py
helpers/<name>.py             # audio.py
helpers/dto/<domain>.py       # dto/library.py
```

---

## 10. Related Documentation

- [Services](services.md) - Service layer patterns
- [Architecture](architecture.md) - System design
- [QC System](qc.md) - Code quality checks

---

## Summary

**Follow these rules for all new code:**
1. Services: `<Noun>Service`
2. Methods: `<verb>_<noun>` (snake_case, allowed verbs only)
3. DTOs: `<Name>Dict` or `<Name>DTO`
4. No transport prefixes (`api_`, `web_`, `cli_`)
5. No context suffixes (`_for_admin`, `_internal`)

**When in doubt:** Choose clarity, consistency, and predictability over brevity.
