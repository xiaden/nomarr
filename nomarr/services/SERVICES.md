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

The services layer lives under `nomarr/services/` and is organized by domain.

Typical layout:

```
services/
├── config_svc.py
├── library_svc.py
├── processing_svc.py
├── queue_svc.py
├── worker_pool_svc.py
├── workers_coordinator_svc.py
├── analytics_svc.py
└── workers/
    ├── base.py
    ├── tagger.py
    ├── scanner.py
    └── recalibration.py
```

Guidelines:
- One service per domain.
- Workers under `services/workers/` as thin wrappers.
- Global orchestration in coordinator services.

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
