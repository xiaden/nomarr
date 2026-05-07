---
name: Persistence Layer
description: Auto-applied when working with nomarr/persistence/ - Database access
applyTo: nomarr/persistence/**
---

# Persistence Layer

**Purpose:** Own all database access. Provide a clean data access API for higher layers.

Persistence is the **data access layer**:

- `Database` owns the connection and exposes bound collection classes as attributes
- `base.py` defines collection base classes, field declarations, and verb descriptors
- `collections.py` declares concrete collections
- `constructor/` contains reusable AQL/query helpers (`verbs.py`, `filters.py`, `pagination.py`)
- External code accesses persistence via the injected `Database` facade, for example `db.tags.name.get.many(...)` or `db.library_files.path.get(...)`
- Returns [DTOs defined in helpers](./helpers.instructions.md)

---

## Directory Structure

```
persistence/
├── db.py                   # Database facade (connection + one-time binding)
├── arango_client.py        # ArangoDB client wrapper
├── base.py                 # Collection bases, Field/UniqueField, verb descriptors
├── collections.py          # Concrete collection declarations
└── constructor/            # Shared AQL/query helpers
    ├── __init__.py
    ├── verbs.py            # AQL primitives (insert, delete, get_one_by_field, etc.)
    ├── filters.py          # Filter helpers
    └── pagination.py
```

---

## Allowed Imports

```python
# ✅ Allowed
from nomarr.helpers.dto import FileDict, LibraryDict
from nomarr.helpers.time_helper import now_ms
```

## Forbidden Imports

```python
# ❌ NEVER import these in persistence
from nomarr.services import ...      # No services
from nomarr.workflows import ...     # No workflows
from nomarr.components import ...    # No components
from nomarr.interfaces import ...    # No interfaces
```

---

## MCP Server Tools

**Use the Nomarr MCP server to navigate this layer efficiently:**

- `read_module_api(module_name)` - Inspect the live collection/descriptor API before reading full files
- `locate_module_symbol(symbol_name)` - Find collection classes, descriptors, or AQL helpers
- `read_module_source(qualified_name)` - Get exact collection, descriptor, or verb source with line numbers

**Before modifying persistence behavior, run `read_module_api` to understand the interface.**

---

## Database Access Pattern

External code should go through the injected `Database` facade and use the descriptor-bound API:

```python
# ✅ Correct - access via Database instance

def some_workflow(db: Database) -> None:
    # Field accessor chain: db.<collection>.<field>.get(value)
    file = db.library_files.path.get("/music/track.flac")
    tags = db.tags.name.get.many("genre", limit=100, offset=0)

    # Collection-level verbs
    db.library_files.insert([{"path": "/music/track.flac", ...}])
    db.library_files.update(path="/music/track.flac", fields={"size_bytes": 12345})

# ❌ Wrong - importing persistence internals into higher layers
from nomarr.persistence.collections import LibraryFiles

file = LibraryFiles.path.get("/music/track.flac")
```

Persistence wiring happens inside `Database.__init__()` via `bind_all_collections(self.db)`. Higher layers should not bind or rebuild collection classes themselves.

---

## ArangoDB ID Fields

**Never rename `_id` or `_key`.**

These are ArangoDB-native identifiers:

- `_key`: Document key (unique within collection)
- `_id`: Full document ID (`collection/_key`)

```python
# ✅ Correct
{"_key": "abc123", "_id": "tracks/abc123", "title": "..."}

# ❌ Wrong - renaming to generic names
{"id": "abc123", "uuid": "abc123"}  # DON'T DO THIS
```

---

## Descriptor Pattern

Collection behavior is declared in classes, not in per-collection wrapper objects.

When adding a collection:

1. Define or update the collection class in `collections.py`
2. Choose the correct base class (`DocumentCollection`, `EdgeCollection`, `VectorCollection`, or `StateGraphCollection`)
3. Declare fields with `Field[...]` and `UniqueField[...]`
4. Add `EDGES` metadata when traversal or cascade behavior is required
5. Expose the collection on `Database` in `db.py` if it belongs on the static facade
6. Add or extend shared AQL helpers in `constructor/` if the existing verbs are insufficient

### Mutation rules

Collection-level and field-level verbs have different shapes:

| Verb | Input | Return |
| --- | --- | --- |
| `insert(docs)` | `list[dict]` | `list[str]` |
| `update(..., fields=...)` | field criteria + update document | `None` |
| `upsert(..., fields=...)` | field criteria + upsert document | `list[str]` |
| `delete(...)` | field criteria | `int` |
| `delete.cascade(ids)` | `list[str]` document IDs | `int` |
| `transition(file_ids, from_state, to_state)` | `list[str]`, `str`, `str` | `None` |
| `truncate()` | *(none)* | `None` |

Field-level verbs stay anchored to a declared field name:

```python
# ✅ Collection-level mutations
db.library_files.insert([{"path": "/music/track.flac", ...}])
db.library_files.update(path="/music/track.flac", fields={"size_bytes": 12345})
db.tags.upsert(name="genre", fields={"value": "genre"})

# ✅ Field-level mutations
db.song_has_tags._from.delete(file_id)  # returns int (count deleted)
db.worker_claims.file_id.update(file_id, {"worker_id": worker_id})

# ✅ Explicit truncate when you mean "delete everything"
db.worker_claims.truncate()
```

---

## No Business Logic

Persistence **only** performs data access. No business decisions:

```python
# ✅ Correct - pure data access via descriptor-bound verbs
def get_library_files(db: Database, library_key: str, limit: int = 100) -> list[dict[str, object]]:
    return db.library_files.library_key.get.many(library_key, limit=limit, offset=0)

def delete_stale_claims(db: Database, stale_ids: list[str]) -> None:
    db.worker_claims.delete(stale_ids)

# ❌ Wrong - business logic in persistence
def get_files_to_process(db: Database, library_key: str) -> list[dict[str, object]]:
    files = db.library_files.library_key.get.many(library_key, limit=100, offset=0)
    # ❌ Business logic - this belongs in a workflow
    if len(files) > 10 and is_system_overloaded():
        return files[:5]
    return files
```

---

## Health Data vs Business Decisions

Persistence **stores and retrieves** health data. It does **not** make liveness decisions:

```python
# ✅ Correct - persistence reports facts
def get_last_heartbeat(self, component_id: str) -> int | None:
    """Return timestamp of last heartbeat, or None if never seen."""
    ...

# ❌ Wrong - persistence making decisions
def is_component_healthy(self, component_id: str) -> bool:
    """Check if component is healthy."""
    # This logic belongs in a service or component, not persistence
    heartbeat = self.get_last_heartbeat(component_id)
    return heartbeat is not None and (now_ms() - heartbeat) < 30000
```

---

## Size Guidelines

- **Consider splitting** at 400 LOC — review whether queries and mutations have grown independently
- **MUST split** at 600 LOC — no exceptions; separate queries from mutations or split by sub-domain

Shared persistence helpers (especially `constructor/verbs.py`) may grow large due to method coverage. If a helper module exceeds 600 LOC, review whether it can be split by concern (for example, edge verbs vs. document verbs).

---

## Validation Checklist

Before committing persistence code, verify:

- [ ] Does this file import from services, workflows, components, or interfaces? **→ Violation**
- [ ] Does this code make business decisions? **→ Move to workflow/component**
- [ ] Are `_id` and `_key` preserved as-is? **→ Required**
- [ ] Is external code bypassing the injected `Database` facade or importing collection classes directly? **→ Access via `Database`**
- [ ] Is health/liveness logic here instead of in services? **→ Move to service**
- [ ] **Does `lint_project_backend(path="nomarr/persistence")` pass with zero errors?** **→ MANDATORY**

---

## Validation

**Run `lint_project_backend(path="nomarr/persistence")` after every edit.** Zero errors is the only acceptable state.

This MCP tool runs ruff, mypy, and import-linter — covering style, types, and layer boundary enforcement.
