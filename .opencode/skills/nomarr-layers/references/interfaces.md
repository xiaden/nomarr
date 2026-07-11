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

Interfaces must never access the database. All data flows through services.

---

## The One Service Call Rule

Each route handler should call **exactly one** service method.

If you need multiple service calls: extract a service method that orchestrates them.

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

## Authentication Rules

**MANDATORY: All API endpoints require authentication except login.**

### Web API (`/api/web/*`)
- Uses `verify_session` for session token authentication
- All routes MUST include `dependencies=[Depends(verify_session)]` or `_session: dict = Depends(verify_session)` as a parameter
- **Exception:** `/api/web/authentication/login` is the only unauthenticated endpoint

### v1 API (`/api/v1/*`)
- Uses `verify_key` for API key authentication
- All routes MUST include `dependencies=[Depends(verify_key)]`
- **Exception:** `/api/v1/public/*` is intentionally public (version info)

### API Consumer Separation — DO NOT MIX

| Router | Auth Method | Consumer | Frontend Calls? |
|--------|-------------|----------|-----------------|
| `/api/web/*` | Session token (`verify_session`) | Web frontend | **YES** |
| `/api/v1/*` | API key (`verify_key`) | External tools (Navidrome, scripts) | **NEVER** |

**The web frontend MUST ONLY call `/api/web/*` endpoints.**

---

## Error Handling

- HTTP routes: Raise `HTTPException`
- CLI commands: Raise `typer.Exit(1)`
- Let services/workflows raise domain exceptions, catch them here

---

## Size Guidelines

- **Consider splitting** at 300 LOC — review whether multiple resource types or route groups are coexisting
- **MUST split** at 500 LOC — no exceptions; split by resource type or route group

---

## Validation

- Does this file import from workflows, components, or persistence? **→ Violation**
- Does this route call more than one service method? **→ Extract to service**
- Does this route contain business logic (loops, branching, computation)? **→ Move to service**
- Are Pydantic models staying in this layer only? **→ Services return DTOs**
- Is the DTO-to-Pydantic conversion explicit? **→ Use `.from_dto()`**
- Does this route have authentication? **→ Add `verify_session` (web) or `verify_key` (v1)**
- Is the frontend calling `/api/v1/*`? **→ Create web API route instead**
- **Run `lint_project_backend(path="nomarr/interfaces")` after every edit.** Zero errors is the only acceptable state.
