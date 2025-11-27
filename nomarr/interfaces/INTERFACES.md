# Interfaces Layer

This layer exposes Nomarr to the outside world via APIs, CLI commands, and web handlers.

## Purpose

Interfaces are **thin adapters** that:
1. Validate inputs
2. Call a service method
3. Serialize outputs

**No business logic lives here.**

## Structure

```
interfaces/
├── api/        # FastAPI REST endpoints
├── cli/        # Click CLI commands
└── web/        # Web UI handlers (future)
```

## Complexity Guidelines

### Rule: 1 Service Call Per Route

Each route handler should:
- Authenticate/authorize (if needed)
- Call **one** service method
- Return a Pydantic response model

```python
# ✅ Good
@router.get("/library/default")
def get_default_library(library_service: LibraryService = Depends(...)) -> LibraryResponse:
    library = library_service.get_default_library()
    if not library:
        raise HTTPException(404)
    return LibraryResponse.from_dto(library)

# ❌ Bad - multiple service calls
@router.post("/process")
def process(library_service: LibraryService = Depends(...)):
    library = library_service.get_default_library()
    queue_service.enqueue_files(library.root_path)  # ← extract to service method
    return {"status": "ok"}
```

### When to Extract

**If you need > 1 service call:**
Extract a service method that orchestrates them:

```python
# Service
def start_processing(self) -> StartProcessingResult:
    library = self.library_service.get_default_library()
    return self.queue_service.enqueue_library(library.id)

# Interface
@router.post("/process")
def process(processing_service: ProcessingService = Depends(...)):
    result = processing_service.start_processing()
    return ProcessingResponse.from_dto(result)
```

## Data Flow

### Request Flow
```
JSON → Pydantic Request Model → .to_dto() → Service (DTO)
```

### Response Flow
```
Service (DTO) → .from_dto() → Pydantic Response Model → JSON
```

## Patterns

### Pydantic Models

- **Request models**: Live in `interfaces/api/types/*_types.py`
- **Response models**: Live in `interfaces/api/types/*_types.py`
- **Never** let Pydantic models leak into services/workflows

```python
# ✅ Good - DTOs stay in helpers, Pydantic in interfaces
from nomarr.helpers.dto.library import LibraryDict
from nomarr.interfaces.api.types.library_types import LibraryResponse

def get_library(library_service: LibraryService = Depends(...)) -> LibraryResponse:
    library_dto = library_service.get_default_library()  # Returns LibraryDict
    return LibraryResponse.from_dto(library_dto)  # Converts to Pydantic

# ❌ Bad - Pydantic in service
def get_library(library_service: LibraryService = Depends(...)) -> LibraryResponse:
    return library_service.get_default_library()  # Service returns Pydantic ❌
```

### Error Handling

- Raise `HTTPException` for HTTP endpoints
- Raise `typer.Exit(1)` for CLI commands
- Let services/workflows raise domain exceptions, catch here

```python
@router.get("/job/{job_id}")
def get_job(job_id: int, queue_service: QueueService = Depends(...)) -> JobResponse:
    job = queue_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse.from_dto(job)
```

## Anti-Patterns

### ❌ Direct DB Access
```python
# NEVER do this in an interface
@router.get("/tracks")
def get_tracks(db: Database = Depends(...)):
    return db.tracks.get_all()  # ← Should call a service
```

### ❌ Business Logic
```python
# NEVER do this in an interface
@router.post("/process")
def process(library_service: LibraryService = Depends(...)):
    library = library_service.get_default_library()
    # ❌ Computing things here
    if library.is_enabled and check_some_condition():
        do_something()
```

### ❌ Calling Workflows Directly
```python
# NEVER do this in an interface
from nomarr.workflows.processing import process_file_workflow

@router.post("/process/{file_id}")
def process(file_id: int, db: Database = Depends(...)):
    return process_file_workflow(db=db, file_id=file_id)  # ← Call service instead
```

## Summary

**Interfaces are dumb pipes:**
- Auth → Service → Response
- No loops, no branching, no computation
- One service call per route
- Pydantic models only in this layer
