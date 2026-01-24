# Nomarr Architecture Overview

Nomarr is a pre-alpha audio tagging system built on strict Clean Architecture principles and dependency injection. The codebase enforces clear separation of concerns through layered packages with explicit dependency rules, ensuring predictable data flow, testability, and maintainability.

## Package Responsibilities

- **`interfaces/`**: Exposes Nomarr to external consumers via CLI, HTTP API (FastAPI), and Web UI. Contains no business logic—only validates inputs, calls services, and serializes outputs.

- **`services/`**: Owns long-lived application resources and runtime wiring. Manages configuration, database connections, queue abstractions, background workers, and processing coordination. Orchestrates workflows by constructing and injecting dependencies.

- **`workflows/`**: Implements core domain use cases such as library scanning, file processing, and tag recalibration. Pure orchestration functions that receive all dependencies (config, database, ML backends) as parameters. Never imports from `services` or `interfaces`.

- **`ml/`**: Encapsulates model discovery, inference, embeddings, and calibration logic. All Essentia imports are isolated in `ml/backend_essentia.py`—no other modules may import Essentia directly.

- **`tagging/`**: Converts model outputs into tags. Handles tag aggregation, mood tiering, conflict resolution, and writing tags to media files. No knowledge of HTTP, CLI, or application services.

- **`persistence/`**: Database and queue access layer. Organized as `persistence.db.Database` (façade) and `persistence.database.*` (one module per table). Contains only SQL and data access logic—no business rules.

- **`helpers/`**: Pure utilities and shared dataclasses. No I/O operations, no side effects, no imports from other `nomarr.*` packages. Only stdlib and third-party dependencies allowed.

## Dependency Direction Rules

- `interfaces` → `services` → `workflows`
- `workflows` → (`ml`, `tagging`, `persistence`, `helpers`)
- `ml` and `tagging` must NOT depend on `interfaces` or `services`
- `persistence` must NOT depend on `workflows`, `services`, or `interfaces`
- `helpers` must NOT depend on any `nomarr.*` packages
- Workflows NEVER import `services` or application containers

## Architectural Principles

- **Dependency injection**: Configuration, database connections, and ML backends are passed as function parameters—never read from global state or module-level imports.

- **No global state**: Heavy dependencies use lazy imports when optional; avoid module-level side effects.

- **Pure workflows**: Workflows orchestrate domain logic without knowledge of HTTP endpoints, CLI commands, or runtime wiring.

- **Essentia isolation**: Only `ml/backend_essentia.py` imports Essentia libraries; all other code accesses Essentia functionality through that module's interface.

- **Side-effect-free helpers**: Helper functions are pure utilities with no I/O, database access, or stateful behavior.

- **Persistence contains SQL only**: Database modules handle data access exclusively; business rules live in workflows and services.

- **Services own runtime wiring**: Services construct long-lived objects (Database, queues, workers), configure dependencies, and delegate work to workflows.
## Worker Processes (Internal Entrypoints)

Worker processes in `services/infrastructure/workers/` are a special architectural category: **runner processes** spawned by services to execute work in separate subprocesses.

**What they are:**
- `multiprocessing.Process` subclasses that run in isolated subprocesses
- Internal entrypoints (analogous to CLI or API routes, but spawned programmatically)
- Self-contained execution boundaries that bootstrap their own dependencies

**Why they exist separately:**
- Subprocess boundary requires picklability and self-contained initialization
- Must create their own DB connections after fork (can't inherit from parent)
- Contain the main execution loop that would be impractical to fragment

**Architectural rules for workers:**
- Allowed to call workflows, components, and persistence directly (they ARE an entrypoint)
- The "services are thin" rule does NOT apply—they are not services
- Domain logic should move to workflows when reusable; otherwise pragmatic containment is acceptable
- Located in `services/infrastructure/workers/` because they are spawned/managed by `WorkerSystemService`

**Example:**
```
services/infrastructure/
├── worker_system_svc.py          # Service that spawns and manages workers
└── workers/
    └── discovery_worker.py       # DiscoveryWorker(Process) - the runner itself
```

`WorkerSystemService` is a thin service (spawns workers, handles lifecycle). `DiscoveryWorker` is a runner (contains the execution loop, calls workflows directly).