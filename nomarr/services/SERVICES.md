# Services Layer

The **services layer** owns runtime wiring and long-lived resources (config, DB, ML backends, workers) and exposes a clean, predictable surface for interfaces to call.

Services are:

- **Dependency coordinators** (wire config, DB, ML backends, workers)
- **Thin orchestrators** (call workflows, aggregate results)
- **DTO providers** (shape data for interfaces)

> **⚠️ Persistence Rule:** Services may hold a `Database` reference for DI wiring, but **MUST NOT** call persistence methods (`db.*`) directly. Database access flows through: service → workflow → component → persistence.

> **Rule:** No complex business logic lives here. That belongs in workflows and components.

---

## 1. Position in the Architecture

```
interfaces → services → workflows → components → (persistence / helpers)
```

Services sit **between interfaces and workflows**:

- **Interfaces** call services (the only thing interfaces may call)
- **Services** call workflows and/or components directly for simple operations
- **Services never import** interfaces
- **Services may skip workflows** for simple single-step operations

---

## 2. Directory Structure

### Domain Services (`services/domain/`)

Domain-specific business operations:

```text
services/domain/
├── analytics_svc.py            # Tag analytics, statistics
├── calibration_svc.py          # Calibration generation and application
├── metadata_svc.py             # Metadata entity operations
├── navidrome_svc.py            # Navidrome integration
├── playlist_import_svc.py      # External playlist import
├── tagging_svc.py              # Tag writing operations
├── vector_maintenance_svc.py   # Vector index maintenance
├── vector_search_svc.py        # Vector similarity search
├── _library_mapping.py         # Internal library ID mapping
└── library_svc/                # Library management (multi-file)
    ├── admin.py                # Add/remove libraries
    ├── config.py               # Library configuration
    ├── entities.py             # Artists/albums/tracks
    ├── files.py                # File operations
    ├── query.py                # Search and listing
    └── scan.py                 # Scanning operations
```

### Infrastructure Services (`services/infrastructure/`)

Runtime resource management and system operations:

```text
services/infrastructure/
├── background_tasks_svc.py     # Async task management
├── calibration_download_svc.py # Calibration file downloads
├── cli_bootstrap_svc.py        # CLI initialization
├── config_svc.py               # Configuration loading
├── file_watcher_svc.py         # Filesystem watching
├── health_monitor_svc.py       # Component health monitoring
├── info_svc.py                 # System information
├── keys_svc.py                 # API key management
├── ml_svc.py                   # ML backend management
├── worker_system_svc.py        # Worker lifecycle management
└── workers/                    # Worker implementations
    └── discovery_worker.py     # File discovery worker
```

**Naming rules:**

- Service files: `<domain>_svc.py` (e.g., `analytics_svc.py`, `ml_svc.py`)
- Service classes: `<Domain>Service` (e.g., `AnalyticsService`, `MLService`)
- Large services: split into subpackage directory (e.g., `library_svc/`)
- Workers: single worker type — `discovery_worker.py` handles file discovery

---

## 3. Service Method Naming

Service methods are the primary programmable surface. All public methods use the **verb–noun** pattern:

```
<verb>_<noun>
```

### Allowed Verbs

 | Category | Verbs |
 | --- | --- |
 | **Read** | `get_`, `list_`, `exists_`, `count_`, `fetch_` |
 | **Create/Update/Delete** | `create_`, `update_`, `delete_`, `set_`, `rename_` |
 | **Domain Ops** | `scan_`, `tag_`, `recalibrate_`, `start_`, `stop_`, `sync_`, `reindex_`, `import_`, `export_` |
 | **Boolean Toggles** | `enable_`, `disable_`, `activate_`, `deactivate_` |
 | **Command** | `apply_`, `execute_` |

**Forbidden:** `api_*`, `web_*`, `cli_*`, `for_admin` — no transport semantics in service names.

---

## 4. Responsibilities

A service method should:

1. Gather dependencies (DB, config, ML backends)
2. Call one or more workflows (or components for simple ops)
3. Return a DTO or simple primitive

 | Services DO | Services DON'T |
 | --- | --- |
 | Wire config, DB, ML backends | Parse HTTP/CLI input |
 | Call workflows and components | Raise `HTTPException` |
 | Own long-lived resources | Contain domain rules or heavy branching |
 | Return DTOs | Embed Pydantic models |
 | Skip workflows for simple ops | Call persistence directly |

---

## 5. Complexity Guidelines

### Rule: DI + Orchestration Only

A service method should:

- Collect dependencies
- Call workflow(s) or component(s)
- Return result

**Extract to a workflow when:**

- Multi-step logic with coordination
- Loops or branching over business rules
- Complex transformations

```python
# ✅ Good — thin orchestration
def scan_library(self, library_id: str) -> ScanResult:
    return scan_library_full_workflow(
        db=self.db,
        library_id=library_id,
        models_dir=self.config.models_dir,
    )

# ❌ Bad — too much logic in service
def scan_library(self, library_id: str) -> ScanResult:
    files = find_unprocessed_files(self.db, library_id)
    for f in files:
        embeddings = compute_embeddings(f)  # ← This is a workflow
        tags = run_inference(embeddings)
        write_tags(self.db, f, tags)
```

---

## 6. DTO Policies

 | Scope | Placement |
 | --- | --- |
 | Cross-layer DTOs (used by multiple services/workflows) | `helpers/dto/<domain>.py` |
 | Single-service DTOs (internal to one service) | Local to that service |

Public methods returning structured data **must** return DTOs. DTOs not needed for: `bool`, `int`, `float`, `str`, `None`, or lists of primitives.

---

## 7. Dependency Injection

Use constructor injection:

```python
class LibraryService:
    def __init__(self, db: Database, config: ConfigService):
        self.db = db
        self.config = config
```

Config is loaded once by `ConfigService` and passed via parameters. No global singletons, no runtime imports.

---

## 8. Boundaries & Import Rules

**Allowed:**

- ✅ Workflows (`nomarr.workflows.*`)
- ✅ Components (`nomarr.components.*`) — for simple direct operations
- ✅ Helpers (`nomarr.helpers.*`)
- ✅ Persistence **type only** (`from nomarr.persistence import Database`) — for DI wiring
- ✅ Standard library, third-party

**Forbidden:**

- ❌ Interfaces (`nomarr.interfaces.*`)
- ❌ FastAPI, Pydantic
- ❌ HTTP or CLI frameworks
- ❌ Calling `db.*` methods directly

---

## 9. Anti-Patterns

 | Anti-Pattern | Why It's Wrong | Fix |
 | --- | --- | --- |
 | Business logic in services | Domain rules belong in workflows/components | Extract to workflow |
 | Returning raw dicts | Untyped contracts | Return a DTO |
 | Transport logic (`status_code`, `HTTPException`) | Interface concern | Keep HTTP in interfaces |
 | Calling `db.library.*`, `db.app.*`, or `db.ml.*` directly | Services should route persistence through workflows/components | Route through workflow → component |
 | Global state or singletons | Hidden dependency, test-unfriendly | Use constructor injection |
 | Embedding Pydantic models | Interface concern | Use DTOs from `helpers/dto/` |
