# Services Layer

**Purpose:** Own runtime wiring and long-lived resources (config, DB, workers) and expose a clean API for interfaces.

Services are:
- **Dependency coordinators** (wire config, DB, ML backends, workers)
- **Thin orchestrators** (call workflows, aggregate results)
- **DTO providers** (shape data for interfaces using helpers DTOs)

**No complex business logic lives here.** That belongs in workflows.

**Private helpers in services** are only acceptable for managing the service's own infrastructure state (threading locks, caching, connection lifecycle). If a private method contains domain logic, iteration over data, or algorithmic work — it belongs in a workflow or component, not a service helper.

---

## File and Package Naming

### Single-File Services

For simple services, use a single file ending in `_svc.py`:

```
nomarr/services/domain/processing_svc.py  → ProcessingService
nomarr/services/domain/analytics_svc.py   → AnalyticsService
```

### Service Packages

For complex services with multiple concerns, use a **package** (folder) ending in `_svc`:

```
nomarr/services/domain/library_svc/
├── __init__.py      # Exports LibraryService
├── admin.py         # LibraryAdminMixin
├── scan.py          # LibraryScanMixin
├── query.py         # LibraryQueryMixin
├── files.py         # LibraryFilesMixin
└── config.py        # LibraryServiceConfig dataclass
```

**Rules for service packages:**
- Package folder must end in `_svc`
- Internal files do NOT need `_svc.py` suffix
- The `__init__.py` exports the composed `<Domain>Service` class
- Internal classes (mixins, config) don't follow `<Domain>Service` pattern

### Infrastructure Packages

Some folders in `services/infrastructure/` are support packages, not services. These are exempt from `_svc.py` naming.

---

## Worker Processes (Runners)

`services/infrastructure/workers/` contains **runner processes** — `multiprocessing.Process` subclasses that execute work in separate subprocesses.

**Why they live here:**
- Spawned and managed by `WorkerSystemService` (co-location with their manager)
- Not components (they call workflows, which components cannot do)
- Not workflows (they contain the execution loop, not just orchestration)
- They are **internal entrypoints**, similar to CLI or API routes

Workers classified as services follow the same thin persistence-facade caller rule as other services (ADR-046): they may call the injected public `Database` intent facade for thin single-atomic-intent operations, but must not reconstruct intents by sequencing lower-level calls.

**Architectural exemptions for workers:**

| Normal Service Rule | Worker Exemption |
|---|---|
| Services are thin orchestrators | Workers contain execution loops |
| Services call workflows, not components directly | Workers may call both |
| Files must end in `_svc.py` | Worker files end in `_worker.py` |
| Classes must end in `Service` | Worker classes end in `Worker` |

---

## Allowed Imports

```python
# ✅ Allowed
from nomarr.workflows import scan_library_workflow, process_file_workflow
from nomarr.persistence.db import Database  # public intent facade, thin single-intent calls
from nomarr.components.ml import MLBackend
from nomarr.helpers.dto import LibraryDict, ProcessResult
```

## Forbidden Imports

```python
# ❌ NEVER import these in services
from nomarr.interfaces import ...     # Services don't know about HTTP/CLI
from fastapi import HTTPException     # No HTTP semantics
from pydantic import BaseModel        # No Pydantic models
```

---

## Persistence Rule

Services may call the public `Database` intent facade for **thin, single-atomic-intent operations** — one facade method on `db.library`, `db.app`, or `db.ml` (or a public nested sub-facade the facade exposes).

```python
# ✅ Allowed — one thin single-intent facade call
assignments = db.library.list_tags_for_song(song_identity)

# ❌ Not allowed — reconstructing an intent by sequencing multiple facade calls
#    (business logic / multi-call choreography belongs in a component)
song_id = ...
identity = db.library.resolve_song_identity(song_id)
first = db.library.list_tags_for_song(identity)
second = ...  # more facade calls chained to rebuild a multi-step intent
```

A service facade call must be thin: it must not sequence lower-level calls, implement business rules or state-machine transitions, manage collection-level writes, or perform multi-call persistence choreography. Side-effectful reads (e.g. hydration) are treated as commands for review. Such behavior belongs in a component or an intent-complete facade method.

Import `Database` from `nomarr.persistence.db` and reach the sub-facades through the injected instance. Services must not import persistence implementation internals — repositories (`nomarr.persistence.database`), SQL primitives, mappers, models, or `nomarr.persistence.api` implementation modules — nor open raw sessions/transactions. Only the composition root constructs `Database`.

---

## Service Method Naming

All public methods use `<verb>_<noun>`:

**Allowed verbs:**
- **Read:** `get_`, `list_`, `exists_`, `count_`, `fetch_`
- **Write:** `create_`, `update_`, `delete_`, `set_`, `rename_`
- **Domain:** `scan_`, `tag_`, `start_`, `stop_`, `sync_`, `import_`, `export_`
- **Boolean:** `enable_`, `disable_`

---

## Complexity Rule: DI + Orchestration Only

A service method should:
1. Collect dependencies
2. Call workflow(s)
3. Return result

**Extract to workflow when you see:** loops, branching logic, multi-step operations, data transformations.

---

## DTO Requirements

**Public methods returning structured data must return DTOs.**
- **Single-service DTOs:** Define in the service file
- **Cross-layer DTOs:** Must live in `helpers/dto/<domain>.py`

---

## Long-Lived Resources

Services own: DB connections (`Database`), Config snapshots (`ConfigService`), ML backends, Worker managers. Use constructor injection.

---

## Size Guidelines

- **Consider splitting** at 300 LOC — review whether the service owns more than one bounded domain concern
- **MUST split** at 500 LOC — no exceptions; split by bounded domain

---

## Validation

- Does this file import from interfaces? **→ Violation**
- Does this file import FastAPI, HTTPException, or Pydantic? **→ Violation**
- Does this method contain loops, branching, or computation? **→ Extract to workflow**
- Does this method sequence multiple `db.*` facade calls to reconstruct an intent? **→ Extract to component**
- Does this method call components directly? **→ Should call workflow instead**
- Are public methods returning DTOs for structured data? **→ Required**
- Is the method name `<verb>_<noun>`? **→ Required**
- **Run `lint_project_backend(path="nomarr/services")` after every edit.** Zero errors is the only acceptable state.
