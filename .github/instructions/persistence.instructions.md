---
name: Persistence Layer
description: Auto-applied when working with nomarr/persistence/ - Database access
applyTo: nomarr/persistence/**
---

# Persistence Layer

**Purpose:** Own all database access. Provide a clean data access API for higher layers.

Persistence is the **data access layer**:

- `Database` class owns the connection and exposes collection namespaces
- `constructor/` builds `*Namespace` objects dynamically from the collection schema
- External code accesses via constructor-backed namespaces: `db.tags.name.get.many(...)`, `db.library_files.path.get(...)`
- Returns [DTOs defined in helpers](./helpers.instructions.md)

---

## Directory Structure

```
persistence/
├── db.py                   # Database facade (connection + namespace wiring)
├── arango_client.py        # ArangoDB client wrapper
├── constructor/            # Schema-driven namespace builder
│   ├── builder.py          # SchemaConstructor (reads schema, builds namespaces)
│   ├── namespaces.py       # CollectionNamespace, FieldNamespace, GetModifierNamespace
│   ├── verbs.py            # AQL verb templates (insert, delete, get_one_by_field, etc.)
│   ├── cascade.py          # CascadeEngine for graph cleanup
│   ├── filters.py          # Filter/pagination helpers
│   └── pagination.py
├── stubs/                  # Type stubs (*Namespace Protocols) for IDE + mypy
│   ├── _base.pyi           # Base protocols (GetModifierProtocol, CollectionGetProtocol, AggResult)
│   ├── library_files.pyi
│   ├── tags.pyi
│   └── ...                 # One .pyi per collection
├── database/               # Empty legacy namespace stub (no modules, kept for import compat)
│   └── __init__.py
└── schema.py               # Collection schema definitions (SCHEMA dict, CollectionType, Op enums)
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

- `read_module_api(module_name)` - See constructor namespace API before reading full files
- `locate_module_symbol(symbol_name)` - Find where database operations are defined
- `read_module_source(qualified_name)` - Get exact constructor or verb source with line numbers

**Before modifying database operations, run `read_module_api` to understand the interface.**

---

## Database Access Pattern

External code **never** imports from `persistence/database/` directly:

```python
# ✅ Correct - access via Database instance and constructor-backed namespaces
def some_workflow(db: Database):
    # Field accessor chain: db.<collection>.<field>.get(value)
    file = db.library_files.path.get("/music/track.flac")
    tags = db.tags.name.get.many("genre", limit=100, offset=0)

    # Collection-level verbs
    db.library_files.insert([{"path": "/music/track.flac", ...}])
    db.worker_claims.delete(["claims/abc123"])

# ❌ Wrong - rebuilding constructor-backed collections inside workflow code
from nomarr.persistence.collections import LibraryFiles
from nomarr.persistence.constructor.builder import Builder

files = Builder(db).construct(LibraryFiles)
```

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

## Constructor Pattern

The constructor builds namespace objects from the schema at import time.
Each collection is accessible as an attribute of the `Database` instance.
There are no hand-written `*AQL` classes.

### Always-List Rule

All **collection-level** mutation verbs accept `list[...]` inputs — never a scalar, never a union.
Pass `[item]` for single values. No separate `_batch` or `bulk_` variants.

 | Verb | Input | Return |
 | ------ | ------- | -------- |
 | `insert(docs)` | `list[dict]` | `list[str]` |
 | `upsert(docs, match_field)` | `list[dict]` | `list[str]` |
 | `delete(ids)` | `list[str]` | `None` |
 | `cascade(ids)` | `list[str]` | `int` |
 | `transition(ids, from_edge, to_edge)` | `list[str]` | `None` |
 | `truncate()` | *(none)* | `None` |

**Field-level** `delete(value) -> int` is different — it takes a single field value (WHERE clause) and returns a count. This is not subject to the always-list rule.

```python
# ✅ Correct — always-list for collection-level verbs
db.worker_claims.delete(["claims/abc123"])
db.library_files.insert([{"path": "/music/track.flac", ...}])

# ✅ Correct — field-level delete takes a single value
db.song_has_tags._from.delete(file_id)  # returns int (count deleted)

# ❌ Wrong — scalar at collection-level
db.ml_models.delete(model_id)  # Must be db.ml_models.delete([model_id])
```

---

## No Business Logic

Persistence **only** performs data access. No business decisions:

```python
# ✅ Correct - pure data access via constructor-backed verbs
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

Constructor modules (`verbs.py`, `namespaces.py`) may grow large due to method coverage. If a constructor module exceeds 600 LOC, review whether it can be split by concern (e.g., edge verbs vs. document verbs).

---

## Validation Checklist

Before committing persistence code, verify:

- [ ] Does this file import from services, workflows, components, or interfaces? **→ Violation**
- [ ] Does this code make business decisions? **→ Move to workflow/component**
- [ ] Are `_id` and `_key` preserved as-is? **→ Required**
- [ ] Is external code importing from `database/*` directly? **→ Access via `Database`**
- [ ] Is health/liveness logic here instead of in services? **→ Move to service**
- [ ] **Does `lint_project_backend(path="nomarr/persistence")` pass with zero errors?** **→ MANDATORY**

---

## Validation

**Run `lint_project_backend(path="nomarr/persistence")` after every edit.** Zero errors is the only acceptable state.

This MCP tool runs ruff, mypy, and import-linter — covering style, types, and layer boundary enforcement.
