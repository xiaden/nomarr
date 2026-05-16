# Architecture Overview

Nomarr follows a layered architecture with explicit dependency direction, clear responsibilities, and a class-based persistence layer.

---

## Dependency Direction

```text
interfaces → services → workflows → components → (persistence / helpers)
```

Rules:

- Higher layers may depend only on lower layers
- Lateral imports inside the same layer are allowed when they stay coherent
- Persistence and helpers sit at the bottom and must not import upward

---

## Layer Responsibilities

### Interfaces (`interfaces/`)

**Purpose:** External entry points.

**Contains:**

- FastAPI routes and request/response adapters
- CLI commands and command parsers
- Authentication / request validation glue

**Rules:**

- Call services only
- No direct workflow/component/persistence orchestration
- No business logic beyond input/output translation

### Services (`services/`)

**Purpose:** Stable application-facing entry points.

**Contains:**

- Coordination of workflows/components for a domain-facing API
- Dependency wiring for application operations
- Thin single-step operations that do not need a workflow

**Rules:**

- May call workflows and components
- Should not contain deep algorithmic or DB-specific logic
- Expose stable method contracts to interfaces

### Workflows (`workflows/`)

**Purpose:** Multi-step orchestration.

**Contains:**

- Cross-component use cases
- Ordered, transactional, or compensating flows
- Higher-level procedural coordination

**Rules:**

- May call components and other workflows
- Must not import services or interfaces
- Keep orchestration separate from reusable domain logic

### Components (`components/`)

**Purpose:** Reusable domain logic and infrastructure adapters.

**Contains:**

- Library/domain logic
- ML/runtime integrations
- Graph, tagging, calibration, and file-processing primitives

**Rules:**

- Can call persistence and helpers
- No knowledge of services, workflows, or interfaces
- Reusable across multiple workflows/services

### Persistence (`persistence/`)

**Purpose:** ArangoDB access layer.

**Contains:**

- `db.py` — `Database` facade that creates the shared Arango connection, wires the thin AQL operation objects, and exposes intent-level sub-facades
- `database/` — thin AQL operation classes grouped by collection/domain concern (`LibrariesAqlOperations`, `LibraryFilesAqlOperations`, `TagsAqlOperations`, `ScanAqlOperations`, `FileStatesAqlOperations`, `MlStreamsAqlOperations`, `MlModelsAqlOperations`, `VectorsAqlOperations`, `AppAqlOperations`, `NavidromeAqlOperations`)
- `api/` — intent-level sub-facades for higher layers: `db.library` (`LibraryDb`), `db.app` (`AppDb`), and `db.ml` (`MlDb`)

**Access pattern:** Go through the injected `Database` facade and use the intent-level namespaces (`db.library`, `db.app`, `db.ml`). Lower persistence tiers (`nomarr.persistence.database/*_aql.py` and `nomarr.persistence.aql/primitives.py`) are persistence-internal implementation layers, not higher-layer APIs.

```python
# ✅ Preferred: intent-level persistence access
file_doc = db.library.get_file(file_id)
tags_by_file = db.library.list_file_tags_for_files(file_ids)
db.library.replace_file_tags(file_id, tags)

tagged_file_ids = db.app.list_files_in_state(STATE_TAGGED)
vector_namespaces = db.ml.list_vector_namespaces()
vectors = db.ml.add_vector_collection(
    "vectors_track_hot__discogs_effnet__main",
    "vectors_track_hot",
)

# ❌ Do not import `nomarr.persistence.database` or `nomarr.persistence.aql` internals from higher layers
# ❌ Do not treat `db.libraries`, `db.tags`, `db.file_states`, etc. as new caller APIs
```

**Key namespaces (via `db.*`):**

| Namespace | Role | Notes |
| --- | --- | --- |
| `db.library` | Library, file, tag, and scan persistence | Preferred facade for library-domain callers |
| `db.app` | Application state, file states, locks/claims, sessions, health, meta/migrations, and Navidrome-related persistence | Preferred facade for operational/app-state callers |
| `db.ml` | ML models, streams, vectors, and calibration persistence | Preferred facade for ML-domain callers |
| `db.libraries`, `db.library_files`, `db.tags`, `db.scan`, `db.file_states`, `db.ml_streams`, `db.ml_models` | Legacy compatibility aliases | Temporary migration surfaces; not supported higher-layer APIs |

The explicit `*_aql` attributes also still exist inside `Database` as implementation-facing compatibility names. Treat them as persistence-internal or migration/bootstrap-only seams, not normal caller dependencies.

### Helpers (`helpers/`)

**Purpose:** Low-level utilities with no upward imports.

**Contains:**

- Serialization helpers
- File and path utilities
- Generic utility functions

**Rules:**

- Must not import `nomarr.*` from higher layers
- Keep logic generic and reusable

---

## Architectural Notes

- Prefer dependency injection for major resources like DB/config/backends
- Public contracts belong in service and workflow boundaries, not persistence internals
- Breaking internal architecture changes are acceptable in alpha as long as callers and migrations are updated together
- If persistence contracts change, update the callers and keep the intent-level facade docs/examples in sync (`db.library`, `db.app`, `db.ml`)
- Do not solve higher-layer needs by importing Tier 1/Tier 2 persistence modules directly; add or adjust a Tier 3 intent method instead

---

## Database startup lifecycle

1. Open ArangoDB connection
2. Prepare database and run migrations
3. Bind collection classes and expose them through `Database`
4. Start workers, services, and interfaces

Persistence wiring happens after the database is available and before higher layers begin using `db.*` accessors.