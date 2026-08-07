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

**Purpose:** Database access layer (PostgreSQL for all domains).

**Contains:**

- `db.py` — `Database` facade that creates the shared database connections, wires the repository classes, and exposes intent-level sub-facades
- `database/` — repository classes grouped by domain concern: library-domain (`LibraryRepository`, `FileRepository`, `FolderRepository`, `TagRepository`, `ScanRepository`, `FileStateRepository`) and ML-domain (`VectorRepo`, `ModelRepo`, `OutputRepo`, `CalibrationRepo`, `EmbeddingStreamRepository`)
- `api/` — intent-level sub-facades for higher layers: `db.library` (`LibraryDb`, a namespaced forwarder over four sub-facades: `db.library.files`/`LibraryFilesDb`, `db.library.tags`/`LibraryTagsDb`, `db.library.scans`/`LibraryScansDb`, `db.library.regions`/`LibraryRegionsDb`), `db.app` (`AppDb`), and `db.ml` (`MlDb`)

**Access pattern:** Go through the injected `Database` facade and use the intent-level namespaces (`db.library`, `db.app`, `db.ml`). Lower persistence tiers are persistence-internal implementation layers, not higher-layer APIs.

```python
# ✅ Preferred: intent-level persistence access
# READ methods use SQLAlchemy autobegin — no explicit transaction required.
file_doc = db.library.get_file(file_id)
tags_by_file = db.library.list_file_tags_for_files(file_ids)

# WRITE methods must run inside a per-write transaction() block (AR-2).
# Repos commit internally, so each guarded write needs its own block.
with db.library.transaction():
    db.library.replace_file_tags(file_id, tags)

tagged_file_ids = db.app.list_files_in_state(STATE_TAGGED)
model = await db.ml.get_model(model_id)
outputs = await db.ml.list_model_outputs(model_id)
similar = await db.ml.search_vectors("discogs_effnet", query_vector, limit=10)

# ❌ Do not import `nomarr.persistence.database` internals from higher layers
```

**Key namespaces (via `db.*`):**

| Namespace | Role | Notes |
| --- | --- | --- |
| `db.library` | Library, file, tag, and scan persistence; thin forwarder over `db.library.files`, `db.library.tags`, `db.library.scans`, `db.library.regions` | Preferred facade for library-domain callers |
| `db.app` | Application state, file states, locks/claims, sessions, health, meta/migrations, and Navidrome-related persistence | Preferred facade for operational/app-state callers |
| `db.ml` | ML models, streams, vectors, and calibration persistence | Preferred facade for ML-domain callers |

**`LibraryDb` sub-facades (via `db.library.*`):**

| Sub-facade | Namespace | Domain |
| --- | --- | --- |
| `LibraryFilesDb` | `db.library.files` | File/folder domain (incl. `list_orphaned_file_ids`, `truncate_files`, `truncate_file_links`, `truncate_folder_links`, `truncate_folders`) |
| `LibraryTagsDb` | `db.library.tags` | Tag/file-tag domain (incl. `list_orphaned_tag_ids`, `delete_tags_by_ids`, `truncate_tags`, `truncate_song_tag_edges`) |
| `LibraryScansDb` | `db.library.scans` | Scan lifecycle (incl. `truncate_scan_records`) |
| `LibraryRegionsDb` | `db.library.regions` | Library/pipeline-state domain |

**Transaction discipline (AR-2):**

- **WRITE methods** (`add_*`, `replace_*`, `remove_*`, `delete_*`, `truncate_*`, ...) must be called inside `with db.<facade>.transaction():`. A write outside a transaction raises `FacadeMisuseError` via the `_require_transaction` guard (checks `session.in_transaction()`).
- **READ methods** carry no guard and use SQLAlchemy autobegin — explicit transactions are not required for reads.
- `transaction()` wraps `session.begin()` and must be entered before any facade method. If a read already autobegun a transaction, it warns ("Transaction already active — did you call a read method before entering the context?") and reuses the active transaction via `get_transaction()` instead of ending it.
- **One write per block:** repos commit internally, so a single `transaction()` block may contain at most one guarded write; wrap each write in its own block.

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

1. Open PostgreSQL connection
2. Run Alembic migrations
3. Wire repository classes and expose them through `Database`
4. Start workers, services, and interfaces

Persistence wiring happens after the database is available and before higher layers begin using `db.*` accessors.