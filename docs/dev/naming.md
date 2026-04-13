# Naming Standards

**Naming Conventions for Services, Methods, DTOs, and Modules**

---

## Overview

Nomarr enforces naming rules to ensure:
- **Predictability** — Names indicate purpose and behavior
- **Discoverability** — Tools and developers can find what they need
- **Clean Architecture** — Names reflect layer boundaries

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
- Describes the domain or infrastructure concern

**Domain services** (in `services/domain/`):
```python
✅ LibraryService
✅ AnalyticsService
✅ CalibrationService
✅ MetadataService
✅ NavidromeService
✅ TaggingService
✅ VectorSearchService
✅ VectorMaintenanceService

❌ LibrariesService  # Use singular
❌ ServiceLibrary    # Wrong order
```

**Infrastructure services** (in `services/infrastructure/`):
```python
✅ ConfigService
✅ HealthMonitorService
✅ InfoService
✅ KeyManagementService
✅ MLService
✅ WorkerSystemService

❌ WorkersCoordinator  # Use <Noun>Service pattern
❌ ConfigManager       # Use Service suffix
```

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
get_      # Retrieve single item (get_library, get_config)
list_     # Retrieve multiple items (list_libraries, list_models)
exists_   # Check existence (exists_library)
count_    # Count items (count_pending_files)
```

**Write Operations:**
```python
create_   # Create new item (create_library)
add_      # Add item (add_library)
update_   # Modify existing item (update_library)
delete_   # Remove item (delete_library)
remove_   # Remove item (remove_library_file)
set_      # Set value (set_threshold)
```

**Domain Operations:**
```python
scan_     # Scan library (scan_library)
process_  # Process file (process_file)
tag_      # Tag file (tag_file)
export_   # Export data (export_playlists)
import_   # Import data (import_library)
sync_     # Synchronize (sync_with_navidrome)
promote_  # Promote vectors (promote_and_rebuild)
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
rebuild_  # Rebuild index or cache (rebuild_vector_index)
```

### Examples

**Good:**
```python
def get_library(self, library_id: str) -> LibraryDict | None
def list_libraries(self) -> list[LibraryDict]
def scan_library(self, library_id: str) -> ScanResultDict
def generate_calibration(self, library_id: str) -> CalibrationResultDict
def pause_workers(self) -> None
def promote_and_rebuild(self, backbone: str) -> PromoteResultDict
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
    _key: str
    name: str
    path: str
    created_at: int

class HealthStatusDict(TypedDict):
    """Component health report."""
    component: str
    status: str
    last_heartbeat: float

class CalibrationResultDict(TypedDict):
    """Calibration operation result."""
    tags_calibrated: int
    tracks_updated: int
```

**Dataclass (for DTOs with methods or defaults):**
```python
@dataclass
class MLModelConfig:
    """ML model configuration."""
    backbone: str
    batch_size: int = 8
    device: str = "cpu"
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
├── analytics_dto.py      # Analytics-related DTOs
├── calibration_dto.py    # Calibration-related DTOs
├── health_dto.py         # Health monitoring DTOs
├── library_dto.py        # Library-related DTOs
├── ml_dto.py             # ML pipeline DTOs
├── navidrome_dto.py      # Navidrome integration DTOs
├── processing_dto.py     # File processing DTOs
└── tagging_dto.py        # Tagging-related DTOs
```

---

## 4. Module Naming

### Services

**Format:** `<domain>_svc.py` (simple) or `<domain>_svc/` (package)

```python
✅ analytics_svc.py
✅ calibration_svc.py
✅ config_svc.py
✅ health_monitor_svc.py
✅ library_svc/         # Package for complex service

❌ library.py           # Too generic
❌ svc_library.py       # Wrong order
❌ library_service.py   # Use _svc suffix
```

### Workflows

**Format:** `<domain>/<operation>_wf.py`

```python
✅ library/scan_library_full_wf.py
✅ calibration/generate_calibration_wf.py
✅ processing/process_file_wf.py
✅ navidrome/sync_navidrome_wf.py

❌ process.py           # Too generic, missing _wf suffix
❌ workflow_process.py   # Wrong order
```

### Components

**Format:** `<domain>/<component>_comp.py`

```python
✅ analytics/tag_stats_comp.py
✅ tagging/aggregation_comp.py
✅ ml/audio/ml_audio_comp.py

❌ utils.py  # Too generic
```

### Helpers

**Format:** `<name>.py` (descriptive, no suffix)

```python
✅ audio.py
✅ files.py
✅ logging_config.py

❌ audio_utils.py  # Redundant suffix
❌ helpers.py       # Too generic
```

---

## 5. File Structure

### Service Files

**Simple services: one class per file ending in `_svc.py`:**

```python
# analytics_svc.py

from nomarr.persistence.db import Database
from nomarr.helpers.dto.analytics_dto import TagStatsDict

class AnalyticsService:
    """Manage analytics operations."""

    def __init__(self, db: Database):
        self.db = db

    def get_tag_stats(self, library_id: str) -> TagStatsDict:
        """Get tag statistics."""
        ...
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
├── entities.py      # LibraryEntitiesMixin
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

### Avoid Ad-Hoc Splitting

**Bad — splitting without a package:**
```python
# library_svc.py
class LibraryService:
    def get_library(...): pass

# library_svc_scan.py  # ❌ Splitting same service without package
class LibraryService:
    def scan_library(...): pass
```

**Good — simple service in one file:**
```python
# analytics_svc.py
class AnalyticsService:
    def get_tag_stats(...): pass
    def compute_insights(...): pass
```

**Good — complex service in a package:**
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
- It's in `services/domain/<name>_svc.py` or `services/infrastructure/<name>_svc.py`
- It has a class `<Name>Service`
- Methods follow `<verb>_<noun>` pattern

**Example:**
```python
# I need to scan a library
# → LibraryService → services/domain/library_svc/ → scan_library()
```

### Discoverability

**MCP tools work well with consistent names:**
- `read_module_api` shows exported classes/functions
- `locate_module_symbol` finds any symbol by name
- `lint_project_backend` catches naming violations via import-linter

### Clean Boundaries

**Names encode layer information:**
- `*Service` → Service layer (domain or infrastructure)
- `*Dict` → DTO (crosses layers)
- `db.<collection>` / `*Namespace` → Persistence layer
- `*_wf` → Workflow layer
- `*_comp` → Component layer

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

**`lint_project_backend`** is the primary QC tool:
- **ruff** — linting and formatting
- **mypy** — type checking
- **import-linter** — layer boundary enforcement

```bash
# Via MCP tool (preferred)
lint_project_backend(path="nomarr/services")

# Or run tools directly
ruff check nomarr/
mypy nomarr/
import-linter
```

### Manual Review

**Code review checklist:**
- [ ] Service names end with `Service`
- [ ] Methods use allowed verbs
- [ ] DTOs end with `Dict` or `DTO`
- [ ] No transport prefixes in names
- [ ] No context suffixes in names
- [ ] Module suffixes match layer (`_svc`, `_wf`, `_comp`)

---

## 8. Migration

### Existing Code

**Pre-alpha:** No backward compatibility required. Refactor aggressively.

**When renaming:**
1. Update service/method name
2. Update all call sites (use `find_referencing_symbols`)
3. Update tests
4. Update documentation
5. Run `lint_project_backend` to verify

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
    def get_library(self, library_id: str) -> LibraryDict | None:  # ✅
        pass
```

---

## 9. Quick Reference

```python
# Services
<Noun>Service                       # LibraryService, MLService

# Methods
<verb>_<noun>                       # get_library, scan_library, pause_workers

# DTOs
<Name>Dict                          # LibraryDict, HealthStatusDict
<Name>DTO                           # MLModelConfig (if dataclass)

# Files
services/domain/<domain>_svc.py     # analytics_svc.py
services/infrastructure/<name>_svc.py # config_svc.py
workflows/<domain>/<op>_wf.py       # library/scan_library_full_wf.py
components/<domain>/<name>_comp.py  # ml/audio/ml_audio_comp.py
helpers/<name>.py                   # audio.py
helpers/dto/<domain>_dto.py         # dto/library_dto.py
```

---

## 10. Related Documentation

- [Architecture](architecture.md) — System design and layer rules
- [QC System](qc.md) — Code quality checks
- [Domains](domains.md) — Domain catalog and data ownership

---

## Summary

**Follow these rules for all new code:**
1. Services: `<Noun>Service`
2. Methods: `<verb>_<noun>` (snake_case, allowed verbs only)
3. DTOs: `<Name>Dict` or `<Name>DTO`
4. No transport prefixes (`api_`, `web_`, `cli_`)
5. No context suffixes (`_for_admin`, `_internal`)
6. Module suffixes match layer: `_svc`, `_wf`, `_comp`

**When in doubt:** Choose clarity, consistency, and predictability over brevity.
