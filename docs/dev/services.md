# Service Layer Reference

**Service Responsibilities, APIs, and Patterns**

---

## Overview

The service layer in Nomarr owns **runtime resources** and **orchestration**. Services are long-lived objects that:

- Own configuration, database connections, queues, and workers
- Wire dependencies together via dependency injection
- Call workflows with injected dependencies
- Return typed DTOs to interfaces
- Contain **no business logic** (push to workflows)

**Key principle:** Services orchestrate, workflows execute.

---

## Service Architecture

### Dependency Flow

```
Startup (app.py)
    ↓
ConfigService (load config)
    ↓
Database (connection pool)
    ↓
QueueService, ProcessingService, etc.
    ↓
Workers (background processes)
```

### Service Initialization Pattern

```python
# Standard service initialization
class LibraryService:
    def __init__(self, db: Database, config: LibraryConfig):
        self.db = db
        self.config = config
    
    def scan_library(self, library_id: int) -> ScanResult:
        # Call workflow with injected dependencies
        return scan_library_workflow(
            library_id=library_id,
            db=self.db,
            config=self.config
        )
```

**Rules:**
- Dependencies passed to `__init__`
- No global state reads
- Public methods return DTOs
- Private methods (`_`) don't require DTOs

---

## Core Services

### ConfigService

**Purpose:** Load, validate, and provide typed configuration.

**Location:** `nomarr/services/config_service.py`

**Responsibilities:**
- Load config from YAML file
- Validate with Pydantic
- Provide typed config objects
- No config mutation after load

**Public API:**

```python
class ConfigService:
    def __init__(self, config_path: str):
        """Load and validate configuration."""
        pass
    
    def get_database_config(self) -> DatabaseConfig:
        """Get database configuration."""
        pass
    
    def get_library_config(self) -> LibraryConfig:
        """Get library configuration."""
        pass
    
    def get_processing_config(self) -> ProcessorConfig:
        """Get processing configuration."""
        pass
    
    def get_ml_config(self) -> MLConfig:
        """Get ML configuration."""
        pass
    
    def get_server_config(self) -> ServerConfig:
        """Get server configuration."""
        pass
```

**Usage:**

```python
# At startup
config_service = ConfigService(config_path="/config/config.yaml")

# Pass config objects to other services
db_config = config_service.get_database_config()
db = Database(db_config)

proc_config = config_service.get_processing_config()
processing_service = ProcessingService(db, proc_config)
```

**Config DTOs:** Defined in `helpers/dataclasses.py`

---

### QueueService

**Purpose:** Manage job queue operations (enqueue, dequeue, status).

**Location:** `nomarr/services/queue_service.py`

**Responsibilities:**
- Enqueue processing jobs
- Get queue statistics
- Clear queues
- Query job status
- Does **not** process jobs (workers do that)

**Public API:**

```python
class QueueService:
    def __init__(self, db: Database):
        self.db = db
    
    def enqueue_file(
        self,
        path: str,
        library_id: int,
        queue_type: QueueType = QueueType.PROCESSING
    ) -> int:
        """Add file to processing queue.
        
        Returns: Job ID
        """
        pass
    
    def enqueue_batch(
        self,
        paths: list[str],
        library_id: int,
        queue_type: QueueType = QueueType.PROCESSING
    ) -> list[int]:
        """Add multiple files to queue.
        
        Returns: List of job IDs
        """
        pass
    
    def get_queue_status(self) -> QueueStatusDict:
        """Get overall queue statistics."""
        pass
    
    def get_queue_depth(self) -> QueueDepthDict:
        """Get per-status counts."""
        pass
    
    def list_jobs(
        self,
        status: JobStatus | None = None,
        queue_type: QueueType | None = None,
        limit: int = 100
    ) -> list[JobDict]:
        """List jobs with optional filtering."""
        pass
    
    def get_job(self, job_id: int) -> JobDict | None:
        """Get single job by ID."""
        pass
    
    def clear_completed(self, queue_type: QueueType | None = None) -> int:
        """Remove completed jobs.
        
        Returns: Number of jobs cleared
        """
        pass
    
    def clear_errors(self, queue_type: QueueType | None = None) -> int:
        """Remove failed jobs.
        
        Returns: Number of jobs cleared
        """
        pass
    
    def retry_errors(self, queue_type: QueueType | None = None) -> int:
        """Requeue all failed jobs.
        
        Returns: Number of jobs requeued
        """
        pass
    
    def requeue_job(self, job_id: int) -> bool:
        """Requeue specific job.
        
        Returns: True if requeued
        """
        pass
```

**DTOs:**
- `QueueStatusDict` - Overall queue stats (pending, running, completed, errors)
- `QueueDepthDict` - Per-status counts
- `JobDict` - Single job details (id, path, status, error, results)

Defined in `helpers/dto/queue.py`

**Usage:**

```python
# Enqueue files
job_id = queue_service.enqueue_file("/music/track.flac", library_id=1)

# Check status
status = queue_service.get_queue_status()
print(f"Pending: {status['pending']}, Running: {status['running']}")

# Retry failed jobs
retried = queue_service.retry_errors()
print(f"Requeued {retried} jobs")
```

---

### ProcessingService

**Purpose:** Own processing workers and coordinate processing operations.

**Location:** `nomarr/services/processing_service.py`

**Responsibilities:**
- Start/stop worker processes
- Pause/resume processing
- Restart crashed workers
- Monitor worker health
- Does **not** process files directly (workers do that)

**Public API:**

```python
class ProcessingService:
    def __init__(
        self,
        db: Database,
        config: ProcessorConfig,
        ml_backends: dict[str, Any]
    ):
        self.db = db
        self.config = config
        self.ml_backends = ml_backends
        self.workers: list[WorkerProcess] = []
    
    def start_workers(self) -> None:
        """Spawn worker processes."""
        pass
    
    def stop_workers(self, timeout: int = 30) -> None:
        """Stop all workers gracefully."""
        pass
    
    def pause_workers(self) -> None:
        """Pause workers (finish current jobs, don't start new)."""
        pass
    
    def resume_workers(self) -> None:
        """Resume paused workers."""
        pass
    
    def restart_workers(self) -> None:
        """Stop and restart all workers."""
        pass
    
    def get_worker_status(self) -> list[WorkerStatusDict]:
        """Get status of all workers."""
        pass
    
    def is_paused(self) -> bool:
        """Check if workers are paused."""
        pass
```

**DTOs:**
- `WorkerStatusDict` - Worker health (component, status, pid, current_job, restart_count)

Defined in `helpers/dto/queue.py`

**Usage:**

```python
# Start workers
processing_service.start_workers()

# Pause before maintenance
processing_service.pause_workers()

# Check status
workers = processing_service.get_worker_status()
for worker in workers:
    print(f"{worker['component']}: {worker['status']}")

# Resume after maintenance
processing_service.resume_workers()
```

**Worker lifecycle:** See [workers.md](workers.md) for details.

---

### LibraryService

**Purpose:** Manage music library operations (add, scan, remove).

**Location:** `nomarr/services/library_service.py`

**Responsibilities:**
- Register libraries in database
- Scan directories for audio files
- Enqueue found files for processing
- Get library statistics

**Public API:**

```python
class LibraryService:
    def __init__(self, db: Database, queue_service: QueueService):
        self.db = db
        self.queue_service = queue_service
    
    def list_libraries(self) -> list[LibraryDict]:
        """Get all registered libraries."""
        pass
    
    def get_library(self, library_id: int) -> LibraryDict | None:
        """Get single library by ID."""
        pass
    
    def add_library(self, name: str, path: str) -> LibraryDict:
        """Register new library."""
        pass
    
    def remove_library(self, library_id: int) -> bool:
        """Unregister library (does not delete files)."""
        pass
    
    def scan_library(self, library_id: int) -> ScanResultDict:
        """Scan library for audio files and enqueue."""
        pass
    
    def get_library_stats(self, library_id: int) -> LibraryStatsDict:
        """Get statistics for library."""
        pass
```

**DTOs:**
- `LibraryDict` - Library metadata (id, name, path, created_at)
- `ScanResultDict` - Scan results (files_found, files_added, files_updated, errors)
- `LibraryStatsDict` - Statistics (total_tracks, unique_artists, unique_albums, total_duration_seconds)

Defined in `helpers/dto/library.py`

**Usage:**

```python
# Add library
library = library_service.add_library(
    name="My Music",
    path="/music"
)

# Scan for files
result = library_service.scan_library(library['id'])
print(f"Found {result['files_found']} files")

# Get stats
stats = library_service.get_library_stats(library['id'])
print(f"Artists: {stats['unique_artists']}")
```

---

### CalibrationService

**Purpose:** Generate and apply tag calibration thresholds.

**Location:** `nomarr/services/calibration_service.py`

**Responsibilities:**
- Generate calibration data from processed tracks
- Apply calibration thresholds
- Clear calibration
- Get calibration status

**Public API:**

```python
class CalibrationService:
    def __init__(self, db: Database, queue_service: QueueService):
        self.db = db
        self.queue_service = queue_service
    
    def generate_calibration(self) -> CalibrationResultDict:
        """Analyze processed tracks and generate thresholds."""
        pass
    
    def apply_calibration(self) -> CalibrationResultDict:
        """Apply generated thresholds to all tracks."""
        pass
    
    def clear_calibration(self) -> bool:
        """Remove all calibration data."""
        pass
    
    def get_calibration_status(self) -> CalibrationStatusDict:
        """Get calibration progress."""
        pass
    
    def is_calibrated(self) -> bool:
        """Check if calibration has been applied."""
        pass
```

**DTOs:**
- `CalibrationResultDict` - Result of calibration operation (tags_calibrated, tracks_updated)
- `CalibrationStatusDict` - Status (completed, errors, total, is_calibrated)

Defined in `helpers/dto/calibration.py`

**Usage:**

```python
# Generate thresholds
result = calibration_service.generate_calibration()
print(f"Calibrated {result['tags_calibrated']} tags")

# Apply to tracks
result = calibration_service.apply_calibration()
print(f"Updated {result['tracks_updated']} tracks")

# Check status
status = calibration_service.get_calibration_status()
if status['is_calibrated']:
    print("Calibration applied")
```

**Calibration details:** See [calibration.md](calibration.md)

---

### AnalyticsService

**Purpose:** Generate tag analytics and statistics.

**Location:** `nomarr/services/analytics_service.py`

**Responsibilities:**
- Compute tag frequency statistics
- Calculate tag correlations
- Generate co-occurrence matrices
- Provide tag insights

**Public API:**

```python
class AnalyticsService:
    def __init__(self, db: Database):
        self.db = db
    
    def get_tag_stats(self) -> list[TagStatsDict]:
        """Get statistics for all tags."""
        pass
    
    def get_tag_distribution(self, tag_name: str) -> TagDistributionDict:
        """Get score distribution for specific tag."""
        pass
    
    def get_tag_correlations(
        self,
        tag_name: str,
        min_correlation: float = 0.3
    ) -> list[TagCorrelationDict]:
        """Get tags correlated with given tag."""
        pass
    
    def get_tag_cooccurrence(
        self,
        tag_name: str,
        min_count: int = 10
    ) -> list[TagCooccurrenceDict]:
        """Get tags that co-occur with given tag."""
        pass
    
    def get_library_overview(self) -> LibraryOverviewDict:
        """Get high-level library statistics."""
        pass
```

**DTOs:**
- `TagStatsDict` - Tag statistics (name, count, avg_score, min, max, stddev)
- `TagDistributionDict` - Score distribution (bins, counts)
- `TagCorrelationDict` - Correlation (tag_name, correlation_coefficient)
- `TagCooccurrenceDict` - Co-occurrence (tag_name, count, percentage)
- `LibraryOverviewDict` - Overview (total_tracks, total_tags, processing_complete)

Defined in `helpers/dto/analytics.py`

**Usage:**

```python
# Get all tag stats
stats = analytics_service.get_tag_stats()
for tag in stats:
    print(f"{tag['name']}: {tag['count']} tracks, avg {tag['avg_score']:.2f}")

# Find correlated tags
correlations = analytics_service.get_tag_correlations("electronic")
for corr in correlations:
    print(f"{corr['tag_name']}: r={corr['correlation_coefficient']:.2f}")
```

---

### NavidromeService

**Purpose:** Export smart playlists for Navidrome.

**Location:** `nomarr/services/navidrome_service.py`

**Responsibilities:**
- Generate TOML playlists from tag rules
- Export to configured directory
- Track export status

**Public API:**

```python
class NavidromeService:
    def __init__(self, db: Database, config: NavidromeConfig):
        self.db = db
        self.config = config
    
    def export_playlists(
        self,
        playlist_name: str | None = None
    ) -> NavidromeExportResultDict:
        """Export playlists to TOML files."""
        pass
    
    def get_export_status(self) -> NavidromeStatusDict:
        """Get last export status."""
        pass
    
    def validate_config(self) -> list[str]:
        """Validate playlist configuration.
        
        Returns: List of validation errors (empty if valid)
        """
        pass
```

**DTOs:**
- `NavidromeExportResultDict` - Export result (playlists_exported, tracks_total, errors)
- `NavidromeStatusDict` - Status (last_export, playlists_count, export_dir)

Defined in `helpers/dto/navidrome.py`

**Usage:**

```python
# Export all playlists
result = navidrome_service.export_playlists()
print(f"Exported {result['playlists_exported']} playlists")

# Export specific playlist
result = navidrome_service.export_playlists("Energetic")
```

**Integration guide:** See [../user/navidrome.md](../user/navidrome.md)

---

## Service Patterns

### Dependency Injection

**Always inject dependencies, never create them:**

```python
# ❌ Wrong - creates own dependencies
class LibraryService:
    def __init__(self):
        self.db = Database()  # Creates DB internally

# ✅ Correct - receives dependencies
class LibraryService:
    def __init__(self, db: Database):
        self.db = db  # Injected
```

**Benefits:**
- Testable (mock dependencies)
- Flexible (swap implementations)
- Clear dependencies (explicit parameters)

### Return DTOs

**Public service methods return typed DTOs:**

```python
# ❌ Wrong - returns dict
def get_library(self, library_id: int) -> dict[str, Any]:
    row = self.db.libraries.get(library_id)
    return dict(row)

# ✅ Correct - returns DTO
def get_library(self, library_id: int) -> LibraryDict | None:
    row = self.db.libraries.get(library_id)
    if not row:
        return None
    return LibraryDict(
        id=row['id'],
        name=row['name'],
        path=row['path'],
        created_at=row['created_at']
    )
```

**Exceptions:**
- Trivial returns (bool, int, str, None) don't need DTOs
- Private methods (`_`) don't need DTOs

### Orchestration Only

**Services orchestrate workflows, don't implement logic:**

```python
# ❌ Wrong - service contains business logic
class LibraryService:
    def scan_library(self, library_id: int) -> ScanResultDict:
        library = self.db.libraries.get(library_id)
        files = []
        for root, dirs, filenames in os.walk(library['path']):
            for filename in filenames:
                if filename.endswith(('.flac', '.mp3')):
                    files.append(os.path.join(root, filename))
        # ... more logic
        return result

# ✅ Correct - service calls workflow
class LibraryService:
    def scan_library(self, library_id: int) -> ScanResultDict:
        return scan_library_workflow(
            library_id=library_id,
            db=self.db,
            queue_service=self.queue_service
        )
```

**Why:**
- Services testable by mocking workflows
- Workflows reusable in different contexts
- Logic in one place (workflows)

---

## Testing Services

### Unit Testing Pattern

```python
import pytest
from unittest.mock import Mock
from nomarr.services.library_service import LibraryService

def test_add_library():
    # Arrange
    mock_db = Mock()
    mock_queue = Mock()
    service = LibraryService(mock_db, mock_queue)
    
    # Act
    result = service.add_library("Test Library", "/music")
    
    # Assert
    mock_db.libraries.create.assert_called_once()
    assert result['name'] == "Test Library"

def test_scan_library():
    # Arrange
    mock_db = Mock()
    mock_queue = Mock()
    service = LibraryService(mock_db, mock_queue)
    
    # Mock workflow response
    from nomarr.workflows.library import scan_library_workflow
    scan_library_workflow = Mock(return_value={
        'files_found': 100,
        'files_added': 95,
        'files_updated': 5,
        'errors': []
    })
    
    # Act
    result = service.scan_library(library_id=1)
    
    # Assert
    assert result['files_found'] == 100
```

### Integration Testing

```python
import pytest
from nomarr.services.library_service import LibraryService
from nomarr.persistence.db import Database

@pytest.fixture
def test_db():
    db = Database(":memory:")
    db.init_schema()
    yield db
    db.close()

def test_library_lifecycle(test_db):
    queue_service = QueueService(test_db)
    service = LibraryService(test_db, queue_service)
    
    # Add library
    library = service.add_library("Test", "/tmp/music")
    assert library['id'] > 0
    
    # List libraries
    libraries = service.list_libraries()
    assert len(libraries) == 1
    
    # Remove library
    removed = service.remove_library(library['id'])
    assert removed is True
```

---

## Service Naming Standards

**Service class names:**
- Pattern: `<Noun>Service`
- Examples: `LibraryService`, `QueueService`, `CalibrationService`

**Service method names:**
- Pattern: `<verb>_<noun>` (snake_case)
- Allowed verbs: `get`, `list`, `add`, `remove`, `create`, `delete`, `update`, `scan`, `start`, `stop`, `pause`, `resume`, `restart`, `clear`, `retry`, `enqueue`, `export`, `generate`, `apply`

**Examples:**
- ✅ `get_library()`
- ✅ `list_libraries()`
- ✅ `scan_library()`
- ✅ `enqueue_file()`
- ❌ `api_get_library()` (no transport prefix)
- ❌ `fetch_library()` (use `get`)
- ❌ `do_scan()` (use `scan_library`)

See [naming.md](naming.md) for complete standards.

---

## Creating New Services

### 1. Define Service Purpose

**Ask:**
- What runtime resource does this own?
- What orchestration does this provide?
- What workflows will it call?

### 2. Define DTOs

**Create in `helpers/dto/<domain>.py`:**

```python
from typing import TypedDict

class MyResourceDict(TypedDict):
    """DTO for my resource."""
    id: int
    name: str
    status: str
```

### 3. Implement Service

**Create in `nomarr/services/<name>_service.py`:**

```python
from nomarr.persistence.db import Database
from nomarr.helpers.dto.my_domain import MyResourceDict

class MyResourceService:
    """Manage my resource operations."""
    
    def __init__(self, db: Database):
        self.db = db
    
    def get_resource(self, resource_id: int) -> MyResourceDict | None:
        """Get resource by ID."""
        # Call workflow or database operation
        pass
```

### 4. Register Service

**In `nomarr/services/__init__.py`:**

```python
from nomarr.services.my_resource_service import MyResourceService

__all__ = [
    # ... existing
    "MyResourceService",
]
```

### 5. Wire in Startup

**In `nomarr/app.py`:**

```python
# Create service
my_resource_service = MyResourceService(db)

# Pass to interfaces
app.state.my_resource_service = my_resource_service
```

### 6. Use in Interfaces

**In API routes:**

```python
from fastapi import Depends
from nomarr.services import MyResourceService

def get_resource_api(
    resource_id: int,
    service: MyResourceService = Depends(get_my_resource_service)
) -> MyResourceResponse:
    resource = service.get_resource(resource_id)
    if not resource:
        raise HTTPException(404)
    return MyResourceResponse.from_dto(resource)
```

---

## Anti-Patterns to Avoid

### ❌ Don't: Read Config at Import Time

```python
# Wrong - reads config at module import
from nomarr.config import get_config
CONFIG = get_config()

class MyService:
    def __init__(self):
        self.path = CONFIG['path']
```

**Instead:**
```python
# Correct - receives config as parameter
class MyService:
    def __init__(self, config: MyConfig):
        self.path = config.path
```

### ❌ Don't: Create Singletons

```python
# Wrong - singleton pattern
class MyService:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if not cls._instance:
            cls._instance = cls()
        return cls._instance
```

**Instead:**
```python
# Correct - create instance at startup, pass around
service = MyService(db, config)
```

### ❌ Don't: Mix I/O and Business Logic

```python
# Wrong - service contains complex logic
def process_file(self, path: str):
    # 50 lines of audio analysis logic
    waveform = load_audio(path)
    embeddings = compute_embeddings(waveform)
    tags = extract_tags(embeddings)
    # ...
```

**Instead:**
```python
# Correct - service calls workflow
def process_file(self, path: str):
    return process_file_workflow(
        path=path,
        db=self.db,
        ml_backends=self.ml_backends
    )
```

### ❌ Don't: Return Raw Database Documents

```python
# Wrong - returns raw dict from database
def get_library(self, library_id: str) -> dict | None:
    return self.db.libraries.get(library_id)
```

**Instead:**
```python
# Correct - returns DTO
def get_library(self, library_id: str) -> LibraryDict | None:
    doc = self.db.libraries.get(library_id)
    if not doc:
        return None
    return LibraryDict(
        id=doc['_key'],
        name=doc['name'],
        path=doc['path'],
        created_at=doc['created_at']
    )
```

---

## Service Lifecycle

### Startup Sequence

```python
# 1. Load configuration
config_service = ConfigService("/config/config.yaml")

# 2. Create database connection (reads password from config file)
db = Database()  # Connects to ArangoDB using ARANGO_HOST env and arango_password from config

# 3. Initialize services with dependencies
queue_service = QueueService(db)
library_service = LibraryService(db, queue_service)
calibration_service = CalibrationService(db, queue_service)
analytics_service = AnalyticsService(db)

# 4. Start background workers
proc_config = config_service.get_processing_config()
ml_backends = load_ml_backends(config_service.get_ml_config())
processing_service = ProcessingService(db, proc_config, ml_backends)
processing_service.start_workers()

# 5. Start web server
app.state.queue_service = queue_service
app.state.library_service = library_service
# ... register all services
```

### Shutdown Sequence

```python
# 1. Stop workers
processing_service.stop_workers(timeout=30)

# 2. Close database
db.close()

# 3. Cleanup resources
# (Services should not hold resources that need explicit cleanup)
```

---

## Related Documentation

- [Architecture](architecture.md) - Overall system design
- [Workers](workers.md) - Worker process lifecycle
- [Queues](queues.md) - Queue system details
- [Naming Standards](naming.md) - Naming conventions
- [API Reference](../user/api_reference.md) - HTTP endpoints

---

## Summary

**Services are thin orchestration layers:**
- Own runtime resources (DB, workers, queues)
- Inject dependencies
- Call workflows
- Return DTOs
- No business logic

**When adding functionality:**
1. Ask: "Is this orchestration or business logic?"
2. Orchestration → Service method
3. Business logic → Workflow
4. Always inject dependencies
5. Always return DTOs
