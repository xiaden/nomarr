# Persistence Layer

The **persistence layer** owns all database access for Nomarr.

It is a schema-driven data access layer built around the `Database` facade and
constructor-backed namespaces. The constructor reads `schema.py` at import time
and dynamically exposes collection and field accessors such as
`db.tags.rel.get.many(...)` and `db.library_files.insert([...])`.

Persistence is:

- **Pure data access** — no business logic, orchestration, or policy decisions
- **Schema-driven** — collection capabilities come from `SCHEMA`, not hand-written operation classes
- **Injected** — higher layers receive `Database` instances rather than importing persistence internals directly

> **Access rule:** Higher layers use persistence through the injected `Database`
> facade. External code should not import from `nomarr.persistence.database`.

---

## 1. Position in the Architecture

```text
interfaces → services → workflows → components → (persistence / helpers)
```

Persistence sits at the bottom of the application architecture:

- **Components** may call persistence directly
- **Persistence** may import helpers and low-level database utilities
- **Persistence never imports** components, services, workflows, or interfaces

Its job is to store and retrieve data cleanly. If a function is making domain
choices, coordinating multiple use cases, or deciding what should happen next,
it belongs in a higher layer.

---

## 2. Current Directory Structure

The persistence package is centered on the constructor-backed API. The core
layout is:

```text
persistence/
├── arango_client.py          # ArangoDB connection factory
├── db.py                     # Database facade (connection + namespace wiring)
├── schema.py                 # Collection schema definitions (SCHEMA dict)
├── constructor/              # Schema-driven namespace builder
│   ├── builder.py            # SchemaConstructor
│   ├── namespaces.py         # CollectionNamespace, FieldNamespace, GetModifierNamespace
│   ├── verbs.py              # AQL verb templates (25 public functions)
│   ├── cascade.py            # CascadeEngine for graph cleanup
│   ├── filters.py            # Filter/pagination helpers
│   └── pagination.py
├── stubs/                    # Type stubs (*Namespace Protocols) for IDE + mypy
│   ├── _base.pyi             # Base protocols
│   └── *.pyi                 # One .pyi per collection
└── database/                 # Empty legacy namespace stub (kept for import compat)
    └── __init__.py
```

Key points:

- The old `*_aql.py` and `*Operations` pattern has been removed.
- `persistence/database/__init__.py` remains only as an empty compatibility stub.
- Constructor verbs live in `persistence/constructor/verbs.py` and are surfaced
  through dynamic namespaces rather than hand-written collection classes.
- Type stubs in `persistence/stubs/` provide IDE and mypy visibility for the
  dynamically constructed namespaces.

---

## 3. Using the Database Facade

`db.py` exposes the application-facing `Database` facade. It owns the ArangoDB
connection and wires schema-backed namespaces onto the `Database` instance.

### Collection access

Each collection becomes an attribute on `Database`:

```python
file = db.library_files.path.get("/music/track.flac")
tags = db.tags.rel.get.many("genre", limit=100, offset=0)
```

### Collection-level verbs

Collection-level methods act on the collection as a whole:

```python
db.library_files.insert([
    {"path": "/music/track.flac", "normalized_path": "/music/track.flac"}
])
db.worker_claims.delete(["worker_claims/abc123"])
```

### Field chains

Field namespaces expose field-scoped verbs and modifiers:

```python
# Field accessor: db.<collection>.<field>.get(value)
file = db.library_files.path.get("/music/track.flac")
tags = db.tags.rel.get.many("genre", limit=100, offset=0)

# Collection-level verbs (always-list)
db.library_files.insert([{"path": "/music/track.flac", "normalized_path": "/music/track.flac"}])
db.worker_claims.delete(["worker_claims/abc123"])

# Field-level delete (scalar, returns count)
db.song_has_tags._from.delete(file_id)  # returns int
```

Common shapes include:

- `db.<collection>.get(<id>)`
- `db.<collection>.<field>.get(<value>)`
- `db.<collection>.<field>.get.many(<value>, limit=..., offset=...)`
- `db.<collection>.<field>.get.in_(<values>, limit=..., offset=...)`
- `db.<collection>.insert([...])`
- `db.<collection>.delete([...])`

The constructor validates the schema at import time and attaches only the verbs
that the collection or field actually supports.

---

## 4. Always-List Rule

All **collection-level mutation verbs** accept `list[...]` inputs only.

Pass `[item]` for single-item operations. There are no scalar overloads, and no
separate `_batch` or `bulk_` variants for these collection verbs.

 | Verb | Input | Return |
 | ------ | ------- | -------- |
 | `insert(docs)` | `list[dict]` | `list[str]` |
 | `upsert(docs, match_field)` | `list[dict]` | `list[str]` |
 | `delete(ids)` | `list[str]` | `None` |
 | `cascade(ids)` | `list[str]` | `int` |
 | `transition(ids, from_edge_target, to_edge_target)` | `list[str]` | `None` |
 | `truncate()` | *(none)* | `None` |

Field-level deletion is intentionally different:

 | Scope | Form | Return |
 | ------ | ------ | -------- |
 | Collection-level | `db.worker_claims.delete(["worker_claims/abc123"])` | `None` |
 | Field-level | `db.song_has_tags._from.delete(file_id)` | `int` |

That distinction matters:

- **Collection-level `delete(...)`** deletes by `_id` list
- **Field-level `<field>.delete(value)`** deletes matching rows and returns the deleted count

---

## 5. What Belongs in Persistence

Persistence owns **data access** and nothing more.

 | Belongs here | Examples |
 | --- | --- |
 | CRUD and lookup verbs | `insert`, `delete`, `get`, `count`, `upsert` |
 | Field-scoped queries | `db.tags.rel.get.many(...)`, `db.library_files.path.get(...)` |
 | Collection traversal and ANN access | `traversal(...)`, `ann_search(...)` |
 | Graph cleanup primitives | `cascade(...)`, field-level edge deletion |
 | Import-time schema validation and namespace construction | `SchemaConstructor`, schema-backed namespace wiring |

 | Does **not** belong here | Why |
 | --- | --- |
 | Business rules | Those belong in components/workflows/services |
 | Cross-step orchestration | Persistence should not coordinate use cases |
 | API/interface concerns | Interfaces format requests and responses |
 | Higher-layer imports | Dependency direction forbids it |

A good persistence function answers **how to read or mutate data**, not **what
business outcome should happen next**.

---

## 6. ArangoDB Identifier Rules

**Never rename `_id` or `_key`.**

These fields are ArangoDB-native identifiers and must remain intact across the
entire codebase.

- `_key`: document key, unique within a collection
- `_id`: full document identifier in the form `collection/_key`

```python
# Correct
{"_key": "abc123", "_id": "tracks/abc123", "title": "Example Track"}

# Wrong
{"id": "abc123", "uuid": "abc123", "title": "Example Track"}
```

If calling code needs a derived identifier shape, that mapping belongs outside
persistence. The stored database fields remain `_id` and `_key`.

---

## 7. Practical Guidance

When working in persistence:

- Add capabilities to `schema.py`
- Implement reusable verb behavior in `constructor/verbs.py` and supporting helpers
- Expose behavior through constructor namespaces rather than ad hoc query classes
- Preserve the always-list rule for collection-level mutations
- Keep examples and call sites focused on the `Database` facade

When using persistence from higher layers:

- Accept `db: Database` via dependency injection
- Call constructor-backed namespaces such as `db.tags.rel.get.many(...)`
- Avoid direct imports from `nomarr.persistence.database`
- Treat `database/__init__.py` as legacy compatibility scaffolding, not an API surface

The persistence layer is no longer a pile of hand-written AQL modules. It is a
schema-driven constructor system that exposes a consistent, discoverable
namespace API across collections.
