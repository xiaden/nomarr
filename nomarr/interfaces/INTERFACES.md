# Interfaces Layer

The **interfaces layer** exposes Nomarr to the outside world via APIs, CLI commands, and web handlers. Interfaces are thin adapters — they validate inputs, call a service method, and serialize outputs.

They are:

- **Transport adapters** (HTTP → service call → JSON response)
- **Input validators** (Pydantic request models live here)
- **Error mappers** (domain exceptions → HTTP status codes)

> **⚠️ Persistence Rule:** Interfaces **MUST NOT** import or access persistence. All data flows through: interface → service → workflow → component → persistence.

> **Rule:** No business logic lives here. Auth → Service → Response. One service call per route.

---

## 1. Position in the Architecture

```
interfaces → services → workflows → components → (persistence / helpers)
```

Interfaces sit at the **top** of the dependency chain:

- **Interfaces** call services (the only layer they may call)
- **Interfaces never import** workflows, components, or persistence
- Pydantic models are confined to this layer

---

## 2. Directory Structure

```text
interfaces/
├── INTERFACE_STATUS.md              # Migration/refactor tracking
│
├── api/
│   ├── api_app.py                   # FastAPI app configuration
│   ├── auth.py                      # Authentication utilities
│   ├── id_codec.py                  # URL-safe ID encoding/decoding
│   │
│   ├── types/                       # Pydantic request/response models
│   │   ├── analytics_types.py       # Analytics types
│   │   ├── api_key_types.py         # API key types
│   │   ├── config_types.py          # Config types
│   │   ├── info_types.py            # System info types
│   │   ├── library_types.py         # Library types
│   │   ├── metadata_types.py        # Metadata types
│   │   ├── ml_types.py              # ML types
│   │   ├── navidrome_types.py       # Navidrome types
│   │   ├── playlist_import_types.py # Playlist import types
│   │   ├── processing_types.py      # Processing types
│   │   └── vector_types.py          # Vector types
│   │
│   ├── v1/                          # API v1 route handlers
│   │   ├── admin_if.py              # Admin endpoints
│   │   ├── navidrome_v1_if.py       # Navidrome v1 endpoints
│   │   └── public_if.py             # Public endpoints
│   │
│   └── web/                         # Web UI route handlers
│       ├── router.py                # Web router aggregation
│       ├── dependencies.py          # FastAPI dependency providers
│       ├── analytics_if.py          # Analytics routes
│       ├── api_key_if.py            # API key management
│       ├── auth_if.py               # Authentication routes
│       ├── calibration_if.py        # Calibration routes
│       ├── config_if.py             # Configuration routes
│       ├── fs_if.py                 # File system routes
│       ├── info_if.py               # System info routes
│       ├── library_if.py            # Library routes
│       ├── metadata_if.py           # Metadata routes
│       ├── ml_if.py                 # ML routes
│       ├── navidrome_if.py          # Navidrome routes
│       ├── playlist_import_if.py    # Playlist import routes
│       ├── processing_if.py         # Processing routes
│       ├── tags_if.py               # Tag routes
│       ├── vectors_if.py            # Vector routes
│       └── worker_if.py             # Worker routes
│
└── cli/
    ├── cli_main.py                  # CLI entry point
    ├── cli_ui.py                    # CLI UI utilities
    └── commands/                    # CLI command implementations
        ├── cleanup_cli.py           # Cleanup commands
        └── manage_password_cli.py   # Password management
```

**Naming rules:**

- Route handlers: `<domain>_if.py` (e.g., `library_if.py`, `ml_if.py`)
- Type files: `<domain>_types.py` (e.g., `library_types.py`, `ml_types.py`)
- CLI commands: `<domain>_cli.py` (e.g., `cleanup_cli.py`)
- Refer to `INTERFACE_STATUS.md` for migration/refactor status of individual interfaces

---

## 3. Data Flow

### Request Flow

```
JSON → Pydantic Request Model → .to_dto() → Service (DTO)
```

### Response Flow

```
Service (DTO) → .from_dto() → Pydantic Response Model → JSON
```

**Key rule:** Pydantic models live exclusively in this layer. Services and workflows use DTOs from `helpers/dto/`.

---

## 4. Route Handler Pattern

Each route handler follows the same pattern: authenticate, call **one** service method, return a Pydantic response.

```python
@router.get("/library/{library_id}")
def get_library(
    library_id: str,
    library_service: LibraryService = Depends(get_library_service),
) -> LibraryResponse:
    library = library_service.get_library(library_id)
    return LibraryResponse.from_dto(library)
```

### When You Need Multiple Service Calls

Extract a service method that orchestrates them:

```python
# ✅ In service
def start_processing(self, library_id: str) -> StartProcessingResult:
    library = self.get_library(library_id)
    return self._start_scan(library)

# ✅ In interface — still one service call
@router.post("/process/{library_id}")
def process(
    library_id: str,
    processing_service: ProcessingService = Depends(...),
) -> ProcessingResponse:
    result = processing_service.start_processing(library_id)
    return ProcessingResponse.from_dto(result)
```

---

## 5. Pydantic Models

- **Request models:** Live in `interfaces/api/types/*_types.py`
- **Response models:** Live in `interfaces/api/types/*_types.py`
- **Never** let Pydantic models leak into services or workflows

```python
# ✅ Good — DTOs in helpers, Pydantic in interfaces
from nomarr.helpers.dto.library import LibraryDict
from nomarr.interfaces.api.types.library_types import LibraryResponse

def get_library(
    library_id: str,
    library_service: LibraryService = Depends(...),
) -> LibraryResponse:
    library_dto = library_service.get_library(library_id)  # Returns LibraryDict
    return LibraryResponse.from_dto(library_dto)           # Converts to Pydantic
```

---

## 6. Error Handling

- Raise `HTTPException` for HTTP endpoints
- Raise `typer.Exit(1)` for CLI commands
- Let domain exceptions propagate from services — catch and map here

```python
@router.get("/library/{library_id}")
def get_library(
    library_id: str,
    library_service: LibraryService = Depends(...),
) -> LibraryResponse:
    library = library_service.get_library(library_id)
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")
    return LibraryResponse.from_dto(library)
```

---

## 7. Boundaries & Import Rules

**Allowed:**
- ✅ Services (`nomarr.services.*`)
- ✅ Helpers (`nomarr.helpers.*`) — DTOs, exceptions
- ✅ FastAPI, Pydantic (this is the only layer that uses them)
- ✅ Standard library

**Forbidden:**
- ❌ Workflows (`nomarr.workflows.*`)
- ❌ Components (`nomarr.components.*`)
- ❌ Persistence (`nomarr.persistence.*`)
- ❌ Direct database access of any kind

---

## 8. Anti-Patterns

| Anti-Pattern | Why It's Wrong | Fix |
|---|---|---|
| Direct DB access (`db.tracks.*`) | Interfaces never touch persistence | Call a service method |
| Calling workflows directly | Skips service wiring/DI | Route through service |
| Business logic in route | Domain rules belong lower | Move to service or workflow |
| Multiple service calls per route | Composition belongs in service | Extract combined service method |
| Pydantic models in services | Leaks interface concern | Use DTOs from `helpers/dto/` |
| Returning raw dicts | Untyped, undocumented response | Return Pydantic response model |
