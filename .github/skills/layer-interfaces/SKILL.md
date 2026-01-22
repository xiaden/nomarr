---
name: layer-interfaces
description: Use when creating or modifying code in nomarr/interfaces/. Covers API routes, CLI commands, and web handlers. Interfaces are thin adapters that validate inputs, call services, and serialize outputs.
---

# Interfaces Layer

**Purpose:** Expose Nomarr to the outside world via HTTP (FastAPI), CLI (Typer), and web handlers.

Interfaces are **thin adapters**. They do three things:
1. Validate inputs
2. Call **one** service method
3. Serialize outputs

**No business logic lives here.**

---

## Allowed Imports

```python
# ✅ Allowed
from nomarr.services import LibraryService, TaggingService
from nomarr.helpers.dto import LibraryDict, FileDict
from nomarr.interfaces.api.types import LibraryResponse  # Pydantic models
```

## Forbidden Imports

```python
# ❌ NEVER import these in interfaces
from nomarr.workflows import ...      # Call services, not workflows
from nomarr.components import ...     # Call services, not components
from nomarr.persistence import ...    # No direct DB access
```

---

## The One Service Call Rule

Each route handler should call **exactly one** service method.

```python
# ✅ Good - one service call
@router.get("/library/default")
def get_default_library(library_service: LibraryService = Depends(...)) -> LibraryResponse:
    library = library_service.get_default_library()
    if not library:
        raise HTTPException(404)
    return LibraryResponse.from_dto(library)

# ❌ Bad - multiple service calls
@router.post("/process")
def process(library_service: LibraryService = Depends(...), tagging_service: TaggingService = Depends(...)):
    library = library_service.get_default_library()
    tagging_service.tag_library(library.key)  # ← Extract to service method
    return {"status": "ok"}
```

**If you need multiple service calls:** Extract a service method that orchestrates them.

---

## Data Flow

### Request Flow
```
JSON → Pydantic Request Model → .to_dto() → Service (DTO)
```

### Response Flow
```
Service (DTO) → .from_dto() → Pydantic Response Model → JSON
```

Pydantic models live **only** in interfaces. Never let them leak into services.

---

## Error Handling

- HTTP routes: Raise `HTTPException`
- CLI commands: Raise `typer.Exit(1)`
- Let services/workflows raise domain exceptions, catch them here

```python
@router.get("/file/{file_key}")
def get_file(file_key: str, library_service: LibraryService = Depends(...)) -> FileResponse:
    file = library_service.get_file(file_key)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse.from_dto(file)
```

---

## Validation Checklist

Before committing interface code, verify:

- [ ] Does this file import from workflows, components, or persistence? **→ Violation**
- [ ] Does this route call more than one service method? **→ Extract to service**
- [ ] Does this route contain business logic (loops, branching, computation)? **→ Move to service**
- [ ] Are Pydantic models staying in this layer only? **→ Services return DTOs**
- [ ] Is the DTO-to-Pydantic conversion explicit? **→ Use `.from_dto()`**
