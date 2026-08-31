# Persistence Layer

**Purpose:** Own all database access. Provide a clean data access API for higher layers.

Persistence is a **3-tier PostgreSQL data access layer**:

- **Tier 1 — `sql/primitives.py`:** 8 raw SQLAlchemy Core CRUD functions (`select_by_key`, `select_many_by_keys`, `insert_one`, `upsert_by_field`, `update_by_field`, `delete_by_key`, `batch_upsert`, `is_table_empty`). No exceptions caught here — errors propagate to the Tier 2 boundary.
- **Tier 2 — `database/*_repo.py`:** 15 table-scoped, **sync** repository classes. Each repo wraps its public methods with `map_persistence_exceptions()` (exception translation) and `session.begin_nested()` (SAVEPOINT per operation).
- **Tier 3 — `api/*.py`:** 3 intent facades (`LibraryDb`, `AppDb`, `MlDb`) exposed on the `Database` facade as `db.library`, `db.app`, `db.ml`. **This is the ONLY supported caller boundary.**

All persistence methods are **sync** (post ADR-040 — asyncpg/psycopg2 → sync-first). Higher layers call the intent facades synchronously.

External code accesses persistence via the injected `Database` facade, for example `db.library.get_song(song_id)` or `db.app.list_claims()`. Higher layers map repository/TypedDict rows to DTOs or domain dataclasses as needed (ADR-041 mandates domain dataclasses as the component contract).

---

## Directory Structure

```
persistence/
├── db.py                   # Database facade; wires repos and exposes db.library / db.app / db.ml
├── pg_engine.py            # PostgreSQL engine / session factory
├── sql/                    # Tier 1
│   ├── primitives.py       # 8 raw SQLAlchemy Core CRUD functions (no exception handling)
│   └── exceptions.py       # map_persistence_exceptions() sync context manager
├── database/               # Tier 2
│   ├── {domain}_repo.py    # 15 table-scoped sync repository classes
│   └── repo_helpers.py     # Shared repository helpers
├── api/                    # Tier 3 intent facades
│   ├── library.py          # LibraryDb (db.library)
│   ├── application.py      # AppDb (db.app)
│   ├── ml.py               # MlDb (db.ml)
│   └── library_{songs,tags,scans,regions}.py   # LibraryDb sub-facades
└── models/                 # SQLAlchemy ORM models (one per table)
```

---

## Allowed Imports

```python
# ✅ Allowed
from nomarr.helpers.dto import SongRow, LibraryRow
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

External code goes through the injected `Database` facade and the intent namespaces. **Do not** import Tier 1 or Tier 2 internals from higher layers (enforced by architecture QC).

```python
# ✅ Correct - access via the Database facade intent namespaces
def some_workflow(db: Database) -> None:
    song = db.library.get_song(song_id)             # sync
    tags = db.library.list_tags_for_song(song_id)
    db.library.replace_song_tags(song_id, tags)     # sync write, repo commits internally
    acquired = db.app.add_claim(WorkerClaim(...))   # sync worker claim; returns bool
    models = db.ml.list_models()

# ❌ Wrong - importing persistence Tier 1/Tier 2 internals into higher layers
from nomarr.persistence.database.song_repo import SongRepository
song = SongRepository(session).get_song(song_id)
```

**Transaction discipline:** WRITE methods execute directly — there is no `transaction()` context and no caller-managed transaction contract. Repos own short internal transactions (`begin_nested()` SAVEPOINT + `commit`) around individual writes; callers just call the intent method.

---

## Primary Key Fields

**Use `id` as the primary key column.** PostgreSQL tables use auto-incrementing integer primary keys. Never rename or transform primary key fields — they are the authoritative row identifiers.

---

## Repository Pattern (Tier 2)

Repositories are **table-scoped** and **sync**. When adding a repo or method:

1. Define a new `{domain}_repo.py` in `database/`, or extend an existing one.
2. Scope the repo to a single table (via the ORM model or a `Table`).
3. Wrap each public method with `map_persistence_exceptions()` (exception translation) and `session.begin_nested()` (SAVEPOINT).
4. Use the Tier 1 primitives (`insert_one`, `update_by_field`, etc.) rather than raw `session.execute` where possible.
5. Expose the repo on the matching intent facade in `api/*.py` if it belongs on the public boundary.
6. Register wiring in `db.py`.

### Mutation Rules

Repo methods are sync and follow standard CRUD verbs:

| Verb | Input | Return |
|------|-------|--------|
| `insert_one` | row dict | inserted row |
| `upsert_by_field` | row dict + key field | upserted row |
| `update_by_field` | key field + fields dict | updated row / count |
| `delete_by_key` | key value | deleted count |

## Exception Translation (Boundary)

All Tier 2 repo methods translate SQLAlchemy errors at the repo boundary via `map_persistence_exceptions()` (a **sync** `@contextmanager` in `sql/exceptions.py`), discriminating by **pgcode**:

| pgcode | Raised exception |
|--------|------------------|
| `23505` unique_violation | `DuplicateEntityError` |
| `23503` foreign_key_violation | `ReferentialIntegrityError` |
| `02000` no_data | `EntityNotFoundError` |
| unknown / operational | `DatabaseStateError` |

The four domain exceptions live in `nomarr/helpers/exceptions.py`. Tier 1 primitives do not catch `SQLAlchemyError` — errors propagate to the repo-level context manager.

---

## No Business Logic

Persistence **only** performs data access. No business decisions.

---

## Health Data vs Business Decisions

Persistence **stores and retrieves** health data. It does **not** make liveness decisions.

---

## No ArangoDB Terminology Outside Persistence

There is **no `_id`/`_key`/`_rev`** outside persistence. Field names use `id`, `key`, `rev`. ArangoDB-era `collections.py`, `accessors.py`, `FieldAccessor`, `DocumentCollection`/`EdgeCollection`/`VectorCollection`/`StateGraphCollection` do **not** exist. This is enforced by `tests/sabotage/test_no_arango_naming.py` plus architecture QC tier bans in `tests/test_architecture_qc.py` and import-linter contracts (ADR-042).

---

## Size Guidelines

- **Consider splitting** at 400 LOC — review whether queries and mutations have grown independently
- **MUST split** at 600 LOC — no exceptions; separate queries from mutations or split by sub-domain

---

## Validation

- Does this file import from services, workflows, components, or interfaces? **→ Violation**
- Does this code make business decisions? **→ Move to workflow/component**
- Are primary key columns properly handled (no renaming, no transformation)? **→ Required**
- Is external code bypassing the injected `Database` facade / Tier 3 intent namespace? **→ Access via `Database`**
- Does higher-layer code import Tier 1/Tier 2 persistence internals directly? **→ Add a Tier 3 intent method instead**
- Are ArangoDB field names (`_id`/`_key`/`_rev`) used outside persistence? **→ Violation (sabotage test)**
- Is health/liveness logic here instead of in services? **→ Move to service**
- **Run `lint_project_backend(path="nomarr/persistence")` after every edit.** Zero errors is the only acceptable state.
