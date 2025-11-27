# Services Layer

This layer owns runtime wiring and long-lived resources (config, DB, queues, workers).

## Purpose

Services are **dependency coordinators** that:
1. Wire dependencies (config, DB, ML backends, queues)
2. Call workflows with injected dependencies
3. Return DTOs

**No complex business logic lives here.**

## Structure

```
services/
├── config_service.py
├── processing_service.py
├── queue_service.py
├── worker_service.py
├── library_service.py
├── calibration_service.py
├── analytics_service.py
└── workers/
    ├── base.py
    ├── tagger.py
    ├── scanner.py
    └── recalibration.py
```

## Complexity Guidelines

### Rule: DI + Orchestration Only

Service methods should be **simple orchestrators**:
- Gather dependencies
- Call workflows
- Return DTOs

**If a method has noticeable logic (loops, branching, multiple steps), extract to a workflow.**

```python
# ✅ Good - simple orchestration
def process_file(self, file_path: str) -> ProcessFileResult:
    return process_file_workflow(
        db=self.db,
        file_path=file_path,
        models_dir=self.models_dir,
        namespace=self.namespace,
    )

# ✅ Good - gathering config and calling workflow
def start_scan(self, library_id: int) -> StartScanResult:
    library = self.db.libraries.get_by_id(library_id)
    if not library:
        raise ValueError(f"Library {library_id} not found")
    
    return scan_library_workflow(
        db=self.db,
        library_path=library.root_path,
        queue_service=self.queue_service,
    )

# ❌ Bad - too much logic, extract to workflow
def process_batch(self, file_paths: list[str]) -> BatchResult:
    results = []
    for path in file_paths:
        if self._should_process(path):  # ← branching logic
            result = self._run_ml(path)  # ← computation
            results.append(result)
    return self._aggregate(results)  # ← aggregation
```

### When to Extract

**Extract to a workflow if:**
- You have loops over business entities
- You have conditional branching based on domain rules
- You're doing computation or data transformation
- The method is hard to read at a glance

```python
# Service (before)
def process_batch(self, file_paths: list[str]) -> BatchResult:
    results = []
    for path in file_paths:
        if self._should_process(path):
            result = self._run_ml(path)
            results.append(result)
    return self._aggregate(results)

# Service (after) - orchestration only
def process_batch(self, file_paths: list[str]) -> BatchResult:
    return process_batch_workflow(
        db=self.db,
        file_paths=file_paths,
        models_dir=self.models_dir,
    )

# Workflow (new)
def process_batch_workflow(
    db: Database,
    file_paths: list[str],
    models_dir: str,
) -> BatchResult:
    results = []
    for path in file_paths:
        if should_process_file(path, db):  # Component
            result = run_ml_inference(path, models_dir)  # Component
            results.append(result)
    return aggregate_batch_results(results)  # Component
```

## Data Transfer Objects (DTOs)

### DTO Requirements

**Every public service method that returns non-trivial structured data must return a DTO.**

- **Trivial returns** (bool, int, str, None, list of primitives) do NOT require a DTO
- **Private methods** (`_prefixed`) do NOT require a DTO
- **Structured data** (dicts with multiple fields, complex nested data) MUST use a DTO

```python
# ✅ Correct - trivial returns
def is_enabled(self) -> bool: ...
def get_count(self) -> int: ...
def get_job_id(self) -> str | None: ...

# ✅ Correct - private method
def _internal_helper(self) -> dict[str, Any]: ...

# ❌ Wrong - public method returning structured data without DTO
def get_job(self, job_id: int) -> dict[str, Any]: ...

# ✅ Correct - public method returns DTO
def get_job(self, job_id: int) -> JobDict | None: ...
```

### DTO Placement

**Single-service DTOs:**
- Used only within one service module
- Define at top of service file or in nested `_models.py`
- Do not export to `services/__init__.py`

**Cross-layer DTOs:**
- Used by multiple services OR used by interfaces/workflows
- Must live in `helpers/dto/<domain>.py`
- Grouped by domain: `queue.py`, `config.py`, `analytics.py`
- Exported from `helpers/dto/__init__.py`

## Long-Lived Resources

Services own resources that persist across requests:

```python
class ProcessingService:
    def __init__(
        self,
        db: Database,
        config: ProcessorConfig,
        queue_service: QueueService,
    ):
        self.db = db
        self.config = config
        self.queue_service = queue_service
        
        # Services can own long-lived ML backends
        self._ml_backend: MLBackend | None = None
    
    @property
    def ml_backend(self) -> MLBackend:
        """Lazy-load ML backend."""
        if self._ml_backend is None:
            self._ml_backend = load_ml_backend(self.config.models_dir)
        return self._ml_backend
```

## Dependency Injection

Services receive dependencies via constructor:

```python
# ✅ Good - dependencies injected
class LibraryService:
    def __init__(self, db: Database, config: ConfigService):
        self.db = db
        self.config = config

# ❌ Bad - global imports
class LibraryService:
    def __init__(self):
        from nomarr.config import db  # ← No globals
        self.db = db
```

## Allowed Imports

```python
# ✅ Services can import:
from nomarr.workflows import process_file_workflow
from nomarr.persistence import Database
from nomarr.components.ml import load_ml_backend
from nomarr.helpers.dto import ProcessFileResult

# ❌ Services must NOT import:
from nomarr.interfaces.api import router  # ← No interface imports
from pydantic import BaseModel  # ← No Pydantic in services
```

## Anti-Patterns

### ❌ Business Logic in Services
```python
# NEVER do this
def process_file(self, file_path: str) -> ProcessFileResult:
    # ❌ Computing embeddings in service
    embeddings = compute_embeddings(file_path)
    predictions = run_inference(embeddings)
    tags = convert_to_tags(predictions)
    return ProcessFileResult(tags=tags)
```

### ❌ Returning Raw Dicts
```python
# NEVER do this
def get_library(self, library_id: int) -> dict[str, Any]:
    return self.db.libraries.get_by_id(library_id)  # ← Return DTO

# DO THIS
def get_library(self, library_id: int) -> LibraryDict | None:
    row = self.db.libraries.get_by_id(library_id)
    if not row:
        return None
    return LibraryDict(
        id=row["id"],
        name=row["name"],
        root_path=row["root_path"],
        # ...
    )
```

### ❌ Multiple Workflows Without Clear Purpose
```python
# NEVER do this - orchestration should happen in workflow
def complex_operation(self, file_path: str) -> Result:
    workflow1_result = workflow1(...)
    if workflow1_result.success:
        workflow2_result = workflow2(...)
        # ... more branching
```

## Summary

**Services are wiring hubs:**
- Own long-lived resources (DB, config, ML backends, queues)
- Inject dependencies into workflows
- Return DTOs to interfaces
- No complex logic - extract to workflows
