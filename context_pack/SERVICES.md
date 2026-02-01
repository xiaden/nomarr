## Services Layer

The **services layer** owns runtime wiring and long-lived resources (config, DB, queues, workers) and exposes a clean, predictable surface for the rest of the application.

Services are:

- **Dependency coordinators** (wire config, DB, ML backends, queues, workers)
- **Thin orchestrators** (call workflows, aggregate results)
- **DTO providers** (shape data for interfaces and other callers)

**No complex business logic lives here.** That belongs in workflows.

---

## 1. Purpose of Services

A service answers the question:

> “Given these dependencies, how do I perform this operation in this domain?”

Concretely, a service method should:

1. Gather dependencies (DB handles, config values, queue objects, ML backends, etc.).
2. Call one or more workflows (or leaf helpers) with those dependencies.
3. Return a DTO (or simple primitive) that callers can use directly.

Services **do not**:
- Know about HTTP or CLI specifics.
- Embed Pydantic models.
- Own domain rules or heavy branching logic.

They are the **wiring hubs** between interfaces and workflows.

---

## 2. Structure of the Services Layer

The services layer lives under `nomarr/services/` and is organized into two categories:

### Domain Services (`services/domain/`)

Domain-specific business operations:

```
services/domain/
├── analytics_svc.py        # Tag analytics, statistics
├── calibration_svc.py      # Calibration generation and application
├── library_svc/            # Library management (multi-file)
│   ├── admin.py            # Add/remove libraries
│   ├── config.py           # Library configuration
│   ├── entities.py         # Artists/albums/tracks
│   ├── files.py            # File operations
│   ├── query.py            # Search and listing
│   └── scan.py             # Scanning operations
├── metadata_svc.py         # Metadata entity operations
├── navidrome_svc.py        # Navidrome integration
├── tagging_svc.py          # Tag writing operations
└── _library_mapping.py     # Internal library ID mapping
```

### Infrastructure Services (`services/infrastructure/`)

Runtime resource management and system operations:

```
services/infrastructure/
├── background_tasks_svc.py     # Async task management
├── calibration_download_svc.py # Calibration file downloads
├── cli_bootstrap_svc.py        # CLI initialization
├── config_svc.py               # Configuration loading
├── events_svc.py               # SSE event streaming
├── file_watcher_svc.py         # Filesystem watching
├── health_monitor_svc.py       # Component health monitoring
├── info_svc.py                 # System information
├── keys_svc.py                 # API key management
├── ml_svc.py                   # ML backend management
├── queue_svc.py                # Job queue operations
├── worker_system_svc.py        # Worker lifecycle management
└── workers/                    # Worker implementations
    ├── base.py                 # Base worker class
    └── tagger.py               # Tag processing worker
```

Guidelines:
- One service per domain or infrastructure concern.
- Large services can split into sub-modules (like `library_svc/`).
- Workers under `services/infrastructure/workers/` as background processes.

---

## 3. Service Method Naming & Surface

Service methods are the primary programmable surface. They must be:

- Predictable
- Discoverable
- Stable

### 3.1. Verb–Noun Pattern

All **public** service methods must use:

```
<verb>_<noun>
```

Example:
- `get_library`
- `list_libraries`
- `scan_library`
- `tag_file`
- `queue_file_for_tagging`

### 3.2. Allowed Verbs

**Read:** get_, list_, exists_, count_, fetch_

**Create/Update/Delete:** create_, update_, delete_, set_, rename_

**Domain Ops:** scan_, tag_, recalibrate_, queue_, start_, stop_, sync_, reindex_, import_, export_

**Boolean Toggles:** enable_, disable_, activate_, deactivate_

**Command:** apply_, execute_

### 3.3. Forbidden Name Patterns

- No "api_", "web_", "cli_"
- No "for_admin"
- No HTTP or transport semantics

---

## 4. Responsibilities of Services

### 4.1. Services

- Accept Python types and DTOs
- Orchestrate workflows
- Own long-lived resources
- Provide stable domain-centric methods

They do **not**:
- Parse HTTP
- Raise HTTPException
- Depend on FastAPI or Pydantic

### 4.2. Workflows

Workflows contain domain logic:
- Loops
- Branching
- Transformations

Services should delegate complex logic to workflows.

### 4.3. Interfaces

Interfaces:
- Map transport → services
- Apply auth, HTTP status codes

---

## 5. Complexity Guidelines

### Rule: DI + Orchestration Only

A service method should:
- Collect dependencies
- Call workflow(s)
- Return result

Extract workflow when:
- Multi-step logic
- Loops
- Branching
- Transformations

---

## 6. DTO Policies

### When DTOs Are Required

Public methods must return DTOs when returning structured data.

DTOs **not needed** for:
- bool, int, float, str, None
- Lists of primitives

### DTO Placement

Service-local DTOs:
- If used only within the service.

Cross-layer DTOs:
- Must live under `helpers/dto/`.

---

## 7. Long-Lived Resources

Allowed to own:
- DB connections
- Config snapshots
- ML model backends
- Queues / workers

Avoid globals.

---

## 8. Dependency Injection

Use constructor injection:

```
class LibraryService:
    def __init__(self, db: Database, config: ConfigService):
        ...
```

Avoid runtime imports or globals.

---

## 9. Allowed Imports

### Allowed

- Workflows
- Persistence abstractions
- DTOs
- Helpers

### Forbidden

- FastAPI
- HTTPException
- Pydantic
- Interface modules

---

## 10. Anti-Patterns

### 10.1. Business Logic in Services

Complex logic belongs in workflows.

### 10.2. Returning Raw Dicts

Use DTOs.

### 10.3. API/Transport Logic in Services

No status codes, HTTP semantics, or auth inside services.
