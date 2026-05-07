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

- `db.py` — `Database` facade and one-time collection binding via `bind_all_collections()`
- `base.py` — collection base types, field declarations, and verb descriptors
- `collections.py` — concrete collection declarations
- `constructor/` — shared AQL helpers (`verbs.py`, `filters.py`, `pagination.py`)

**Access pattern:** Always go through the injected `Database` facade and use the descriptor-bound collection API.

```python
# ✅ Via Database facade
file_doc = db.library_files.path.get("/music/track.flac")
rows = db.library_files.get.many(library_key="main", limit=100, offset=0)

# ✅ Dynamic vector collections when a physical name is resolved at runtime
vectors = db.register("vectors_track_hot__discogs_effnet__main", "vectors_track_hot")

# ❌ Do not import persistence internals from higher layers
```

**Key collections (via `db.*`):**

| Accessor | Collection(s) | Domain |
| --- | --- | --- |
| `db.libraries` | `libraries` | Library |
| `db.library_files` | `library_files` | Library |
| `db.library_folders` | `library_folders` | Library |
| `db.tags` | `tags` | Tagging |
| `db.tag_model_output` | `tag_model_output` | Tagging |
| `db.ml_models` | `ml_models` | ML |
| `db.ml_model_outputs` | `ml_model_outputs` | ML |
| `db.calibration_state` | `calibration_state` | ML / Calibration |
| `db.calibration_history` | `calibration_history` | ML / Calibration |
| `db.segment_scores_stats` | `segment_scores_stats` | ML |
| `db.worker_claims` | `worker_claims` | Workers |
| `db.worker_restart_policy` | `worker_restart_policy` | Workers |
| `db.health` | `health` | Infrastructure |
| `db.file_states` | `file_states` | Library |
| `db.navidrome_tracks` | `navidrome_tracks` | Navidrome |
| `db.navidrome_playcounts` | `navidrome_playcounts` | Navidrome |
| `db.sessions` | `sessions` | Infrastructure |
| `db.meta` | `meta` | Infrastructure |
| `db.vram_promises` | `vram_promises` | ML / Resources |
| `db.ml_capacity` | `ml_capacity_estimates` | ML / Resources |
| `db.migrations` | `applied_migrations` | Platform |

Dynamic vector collections use `db.register(resolved_name, template_name)` and return the runtime-wired collection instance.

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
- If persistence contracts change, update the callers and keep the descriptor-based docs/examples in sync

---

## Database startup lifecycle

1. Open ArangoDB connection
2. Prepare database and run migrations
3. Bind collection classes and expose them through `Database`
4. Start workers, services, and interfaces

Persistence wiring happens after the database is available and before higher layers begin using `db.*` accessors.