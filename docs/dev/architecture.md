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
- `database/` — repository classes grouped by domain concern: library-domain (`LibraryRepository`, `SongRepository`, `FolderRepository`, `TagRepository`, `ScanRepository`, `SongStateRepository`, `SongTagRepository`) and ML-domain (`VectorRepo`, `ModelRepo`, `OutputRepo`, `CalibrationRepo`, `EmbeddingStreamRepository`)
- `api/` — intent-level sub-facades for higher layers: `db.library` (`LibraryDb`, a namespaced forwarder over four sub-facades: `db.library.songs`/`LibrarySongsDb`, `db.library.tags`/`LibraryTagsDb`, `db.library.scans`/`LibraryScansDb`, `db.library.regions`/`LibraryRegionsDb`), `db.app` (`AppDb`), and `db.ml` (`MlDb`)

**Access pattern:** Go through the injected `Database` facade and use the intent-level namespaces (`db.library`, `db.app`, `db.ml`). Lower persistence tiers are persistence-internal implementation layers, not higher-layer APIs.

```python
# ✅ Preferred: intent-level persistence access
# READ methods use SQLAlchemy autobegin — no explicit transaction required.
song = db.library.get_song(song_id)
tags_by_song = db.library.list_song_tags_for_songs(song_ids)

# WRITE methods execute directly (AR-SDR-4) — no transaction() context,
# no caller-managed transaction contract. Repos own short internal
# transactions (begin_nested + commit), so just call the intent method.
db.library.replace_song_tags(song_id, tags)

tagged_song_ids = db.app.list_songs_in_state(STATE_TAGGED)
model = db.ml.get_model(model_id)
outputs = db.ml.list_model_outputs(model_id)
similar = db.ml.search_vectors("discogs_effnet", query_vector, limit=10)

# ❌ Do not import `nomarr.persistence.database` internals from higher layers
```

**Key namespaces (via `db.*`):**

| Namespace | Role | Notes |
| --- | --- | --- |
| `db.library` | Library, song, tag, and scan persistence; thin forwarder over `db.library.songs`, `db.library.tags`, `db.library.scans`, `db.library.regions` | Preferred facade for library-domain callers |
| `db.app` | Application state, song states, locks/claims, sessions, health, meta/migrations, and Navidrome-related persistence | Preferred facade for operational/app-state callers |
| `db.ml` | ML models, streams, vectors, and calibration persistence | Preferred facade for ML-domain callers |

**`LibraryDb` sub-facades (via `db.library.*`):**

| Sub-facade | Namespace | Domain |
| --- | --- | --- |
| `LibrarySongsDb` | `db.library.songs` | Song/folder domain (incl. `list_orphaned_song_ids`, `truncate_songs`, `truncate_song_links`, `truncate_folder_links`, `truncate_folders`) |
| `LibraryTagsDb` | `db.library.tags` | Tag/song-tag domain (incl. `list_orphaned_tag_ids`, `delete_tags_by_ids`, `truncate_tags`, `truncate_song_tag_edges`) |
| `LibraryScansDb` | `db.library.scans` | Scan lifecycle (incl. `truncate_scan_records`) |
| `LibraryRegionsDb` | `db.library.regions` | Library/pipeline-state domain |

**Write discipline (AR-SDR-4):**

- **WRITE methods** (`add_*`, `replace_*`, `remove_*`, `delete_*`, `truncate_*`, ...) execute directly on the facade — there is no `transaction()` context and no caller-managed transaction contract. The former `FacadeMisuseError`/`FacadeMisuseWarning` and `_require_transaction` guard were removed.
- **READ methods** use SQLAlchemy autobegin — explicit transactions are not required for reads.
- Repositories own short internal transactions (`begin_nested` + `commit`) around individual writes. Callers must not open their own transactions around facade methods; just call the intent method and let the repo commit internally.

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