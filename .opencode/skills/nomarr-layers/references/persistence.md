# Persistence Layer

**Purpose:** Own all database access. Provide a clean data access API for higher layers.

Persistence is the **data access layer**:
- `Database` owns the connection and exposes instantiated collection wrappers as attributes
- `collections_base.py` defines the shared collection base classes and collection-level verbs
- `base_types.py` defines `Field`, `UniqueField`, and edge metadata/constants
- `accessors.py` defines `FieldAccessor` plus collection/field get/delete helpers
- `collections.py` declares concrete collections
- `constructor/` contains reusable AQL/query helpers (`verbs.py`, `filters.py`, `pagination.py`)

External code accesses persistence via the injected `Database` facade, for example `db.tags.name.get.many(...)` or `db.library_files.path.get(...)`. Persistence returns raw document dicts and query results; higher layers map them to DTOs when needed.

---

## Directory Structure

```
persistence/
├── db.py                   # Database facade and collection instance binding
├── arango_client.py        # ArangoDB client wrapper
├── collections.py          # Concrete collection declarations
├── collections_base.py     # Shared collection wrappers and collection-level verbs
├── accessors.py            # FieldAccessor plus collection/field get/delete helpers
├── base_types.py           # Field criteria, edge metadata, and constants
├── cascade.py              # Cascade compilation helpers
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

## Database Access Pattern

External code should go through the injected `Database` facade:

```python
# ✅ Correct - access via Database instance with collection-first verbs
def some_workflow(db: Database) -> None:
    file = db.library_files.get(path="/music/track.flac")
    tags = db.tags.get(name="genre", limit=100, offset=0)
    db.library_files.insert([{"path": "/music/track.flac", ...}])
    db.library_files.update(path="/music/track.flac", fields={"size_bytes": 12345})

# ⚠️ Compatibility shim only - field accessor chains still work for legacy callers
legacy_file = db.library_files.path.get("/music/track.flac")

# ❌ Wrong - importing persistence internals into higher layers
from nomarr.persistence.collections import LibraryFiles
file = LibraryFiles.path.get("/music/track.flac")
```

---

## ArangoDB ID Fields

**Never rename `_id` or `_key`.** These are ArangoDB-native identifiers.

---

## Collection and Accessor Pattern

When adding a collection:
1. Define or update the collection class in `collections.py`
2. Choose the correct base class (`DocumentCollection`, `EdgeCollection`, `VectorCollection`, or `StateGraphCollection`)
3. Annotate field attributes as `FieldAccessor`
4. Register each field in `__init__` with `self._field("name", unique=True/False)`
5. Use `Field(...)` only for positional collection criteria; `UniqueField[...]` is compatibility-only
6. Add `EDGES` metadata when traversal or cascade behavior is required
7. Expose the collection on `Database` in `db.py` if it belongs on the static facade
8. Add or extend shared AQL helpers in `constructor/` if the existing verbs are insufficient

### Mutation Rules

Collection-level verbs:

| Verb | Input | Return |
|------|-------|--------|
| `insert(docs)` | `list[dict]` | `list[str]` |
| `update(..., fields=...)` | field criteria + update document | `None` |
| `upsert(..., fields=...)` | field criteria + upsert document | `list[str]` |
| `delete(...)` | field criteria | `int` |
| `delete.cascade(ids)` | `list[str]` document IDs | `int` |
| `transition(file_ids, from_state, to_state)` | `list[str]`, `str`, `str` | `None` |
| `truncate()` | *(none)* | `None` |

---

## No Business Logic

Persistence **only** performs data access. No business decisions.

---

## Health Data vs Business Decisions

Persistence **stores and retrieves** health data. It does **not** make liveness decisions.

---

## Size Guidelines

- **Consider splitting** at 400 LOC — review whether queries and mutations have grown independently
- **MUST split** at 600 LOC — no exceptions; separate queries from mutations or split by sub-domain

---

## Validation

- Does this file import from services, workflows, components, or interfaces? **→ Violation**
- Does this code make business decisions? **→ Move to workflow/component**
- Are `_id` and `_key` preserved as-is? **→ Required**
- Is external code bypassing the injected `Database` facade? **→ Access via `Database`**
- Is health/liveness logic here instead of in services? **→ Move to service**
- **Run `lint_project_backend(path="nomarr/persistence")` after every edit.** Zero errors is the only acceptable state.
