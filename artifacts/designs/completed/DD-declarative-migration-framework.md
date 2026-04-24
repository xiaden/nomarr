# Declarative Migration Framework — Design Document

**Status:** Draft  
**Author:** rnd-dd-author  
**Created:** 2026-04-05  

**Related Documents:**

- [Schema Refactor V1 — Graph Normalization]() —
- [Skip ensure_schema on Existing Databases]() —
- [Migration Versioning Overhaul]() —
- [Migration Consolidation Tool]() —
- [Schema Refactor V1]() —

---

## Scope

**Primary file:** `nomarr/components/platform/migration_runner_comp.py` — the migration runner component that owns `discover_migrations()`, `apply_migration()`, and `run_pending_migrations()`. This is where dual-format detection and declarative dispatch must be added.

**New package:** `nomarr/migrations/framework/` — the declarative framework (operations, ordering, executor).

**Thin orchestration (no changes needed):** `nomarr/workflows/platform/prepare_database_wf.py` calls `run_pending_migrations(db)` but owns no migration logic. `nomarr/app.py` calls the workflow at startup.

### Affected Files

 | File | Impact |
 | ------ | -------- |
 | `nomarr/components/platform/migration_runner_comp.py` | **Must update.** Add dual-format detection (`_is_declarative` / `_is_imperative`), relax `_validate_migration_module` to not require `upgrade` when `migration` attribute is present, branch `apply_migration` for declarative dispatch. |
 | `nomarr/migrations/framework/__init__.py` | **New.** Public API re-exports for the framework package. |
 | `nomarr/migrations/framework/operations.py` | **New.** Operation type dataclasses. |
 | `nomarr/migrations/framework/ordering.py` | **New.** Topological sort and ordering rule engine. |
 | `nomarr/migrations/framework/executor.py` | **New.** Executes operations against ArangoDB with idempotency. |
 | `tests/unit/components/platform/test_migration_runner_comp.py` | **Must update.** Currently assumes all modules export `upgrade(db)`. Needs test cases for declarative-only modules, mixed modules, and the detection logic. |
 | `tests/unit/migrations/test_migration_uniqueness.py` | **Review needed.** Imports all `V*.py` modules; verify it doesn't break if a module lacks `upgrade`. |
 | `scripts/consolidate_migrations/walker/discovery.py` | **Review needed.** Parses migration files and assumes `upgrade(db)` function exists. |
 | `scripts/consolidate_migrations/walker/walker.py` | **Review needed.** Uses AST to find `upgrade()` calls; would need update for declarative format. |
 | `docs/dev/migrations.md` | **Must update.** Currently documents imperative-only model; needs new section on declarative format. |
 | `nomarr/migrations/README.md` | **Must update.** Currently states each migration exports only `upgrade(db)`. |
 | `nomarr/migrations/__init__.py` | **No change needed.** This file is empty — no discovery logic is hidden here. Migration discovery is handled entirely by `migration_runner_comp.discover_migrations()`, which globs `V*.py` from `MIGRATIONS_DIR`. |

---

## Problem Statement

Nomarr's migration system uses imperative Python functions (`upgrade(db)`) that hand-authors must write correctly every time. This has produced **five classes of bugs** across V021/V022:

1. **Index ordering bugs (3 incidents)**: V021 initially dropped only exact-match indexes before nullifying `library_id`. Compound indexes containing `library_id` were missed, causing unique constraint violations at runtime. Required iterating to "drop ALL persistent indexes where field appears in the fields array."

2. **AQL ERR 1579 (2 incidents)**: V022 mixed reads and writes to the same collection in single AQL statements — a pattern ArangoDB forbids. One case: `REMOVE + INSERT + INSERT` on `file_has_state` in a single loop. Another: per-row subquery re-reading a collection after writes. Both silent on fresh/empty databases.

3. **ensure_schema conflict (1 incident, 3 fix attempts)**: After V021 ran, `ensure_schema` recreated indexes V021 had intentionally dropped (it ran on every startup). This caused recurring crash loops. Fixed by ADR-016 (skip ensure_schema on existing DBs), but the root cause was lack of "source of truth" coordination.

4. **Stale query drift**: Post-migration, caller code still referenced dropped fields/indexes (`delete_library_file` filtering on dead `file_id` data). While outside the runner, the imperative migration format provides no structured metadata to detect this.

5. **Two known unfixed AQL issues**: V022 still has mixed read/write AQL statements tagged `needs-review`. The imperative format makes these invisible — they're buried in string literals.

All five bug classes share a root cause: **the migration system is opaque**. The runner sees `upgrade(db)` as a black box. It cannot enforce ordering rules, detect AQL safety violations, or verify that index drops precede field nullification. The migration author must remember every rule manually. This is a solved problem in other migration frameworks — declarative operation lists with runner-enforced ordering.

### References

- ADR-004: Schema Refactor V1 — established the operation types (CreateCollection, DropIndex, NullifyField, etc.)
- ADR-016: Skip ensure_schema on existing DBs — fixed the ensure_schema conflict class
- `rnd-dd-author#L9`: Research findings from codebase analysis
- `support-debugger#L1`: ERR 1579 root cause analysis
- `exec-executor#L15`: Index ordering bug diagnosis
- `support-researcher#L11`: Stale index crash audit

---

## Architecture

## Architecture Overview

The framework has three layers:

```
Migration File (authored)
  └─ Declares: operations list + metadata
       │
Operation Model (nomarr/migrations/framework/operations.py)
  └─ Typed dataclasses: CreateCollection, DropIndex, DataMigration, etc.
       │
Runner Engine (nomarr/components/platform/migration_runner_comp.py)
  └─ Loads operations → validates → topological sort → execute with idempotency
```

### Layer Mapping

 | Component | Layer | Responsibility |
 | ----------- | ------- | ---------------- |
 | `nomarr/migrations/framework/operations.py` | helpers | Operation type definitions (pure data, no DB calls) |
 | `nomarr/migrations/framework/ordering.py` | helpers | Topological sort and ordering rule engine |
 | `nomarr/migrations/framework/executor.py` | components | Executes operations against ArangoDB with idempotency |
 | `nomarr/migrations/framework/__init__.py` | helpers | Public API re-exports |
 | `nomarr/components/platform/migration_runner_comp.py` | components | Extended to detect and dispatch declarative migrations |

### Operation Type Taxonomy

All operations are frozen dataclasses. Each has a `kind` discriminator for the ordering engine and an `execute(db)` method for the executor.

#### Schema Operations (DDL)

```python
@dataclass(frozen=True)
class CreateCollection:
    """Create a document collection. Idempotent — skips if exists."""
    name: str
    kind: ClassVar[str] = "create_collection"

@dataclass(frozen=True)
class CreateEdgeCollection:
    """Create an edge collection. Idempotent — skips if exists."""
    name: str
    kind: ClassVar[str] = "create_edge_collection"

@dataclass(frozen=True)
class DropCollection:
    """Drop a collection. Idempotent — skips if not exists."""
    name: str
    kind: ClassVar[str] = "drop_collection"

@dataclass(frozen=True)
class CreateGraph:
    """Create a named graph with edge definitions."""
    name: str
    edge_definitions: list[EdgeDefinition]
    kind: ClassVar[str] = "create_graph"

@dataclass(frozen=True)
class DropGraph:
    """Drop a named graph (not its collections)."""
    name: str
    kind: ClassVar[str] = "drop_graph"
```

#### Index Operations

```python
@dataclass(frozen=True)
class CreateIndex:
    """Create an index on a collection. Idempotent — 409 conflict suppressed."""
    collection: str
    index_type: Literal["persistent", "ttl", "hash", "geo", "fulltext"]
    fields: list[str]
    unique: bool = False
    sparse: bool = False
    expire_after: int | None = None  # TTL indexes only
    kind: ClassVar[str] = "create_index"

@dataclass(frozen=True)
class DropIndex:
    """Drop indexes from a collection.

    Two modes:
    - fields_containing: drops ALL indexes where this field appears in the fields array
    - fields_exact: drops only the index with this exact field list

    The fields_containing mode prevents the V021 bug class where compound indexes
    were missed.
    """
    collection: str
    fields_containing: str | None = None  # Drop all indexes containing this field
    fields_exact: list[str] | None = None  # Drop the index with exactly these fields
    index_type: str | None = None  # Optional filter by type (e.g., "persistent")
    kind: ClassVar[str] = "drop_index"

    def __post_init__(self) -> None:
        if not self.fields_containing and not self.fields_exact:
            raise ValueError("DropIndex requires either fields_containing or fields_exact")
        if self.fields_containing and self.fields_exact:
            raise ValueError("DropIndex cannot specify both fields_containing and fields_exact")
```

#### Field Operations

```python
@dataclass(frozen=True)
class AddField:
    """Add a field with a default value to all documents in a collection."""
    collection: str
    field: str
    default: Any
    kind: ClassVar[str] = "add_field"

@dataclass(frozen=True)
class DropField:
    """Remove a field from all documents. Uses UPDATE with keepNull: false."""
    collection: str
    field: str
    kind: ClassVar[str] = "drop_field"

@dataclass(frozen=True)
class NullifyField:
    """Set a field to null on all documents (before dropping indexes or the field itself)."""
    collection: str
    field: str
    kind: ClassVar[str] = "nullify_field"

@dataclass(frozen=True)
class RenameField:
    """Rename a field on all documents. Copies value, then nullifies old field."""
    collection: str
    old_name: str
    new_name: str
    kind: ClassVar[str] = "rename_field"
```

#### Data Operations

```python
@dataclass(frozen=True)
class SeedDocument:
    """Insert a document if it doesn't exist (idempotent seed)."""
    collection: str
    key: str
    document: dict[str, Any] | None = None  # Additional fields beyond _key
    kind: ClassVar[str] = "seed_document"

@dataclass(frozen=True)
class DataMigration:
    """Imperative escape hatch for complex data transformations.

    The callable receives the raw ArangoDB database handle.
    read_collections and write_collections enable AQL safety validation:
    the runner warns if any collection appears in both sets.
    """
    description: str
    fn: Callable[[DatabaseLike], None]
    read_collections: frozenset[str] = frozenset()
    write_collections: frozenset[str] = frozenset()
    kind: ClassVar[str] = "data_migration"
```

#### Potential Future Operations (NOT in v1)

- `RenameCollection(old_name, new_name)` — rarely needed, complex with graph refs
- `TruncateCollection(name)` — dangerous, better as explicit DataMigration
- `EnsureIndex` — semantically identical to CreateIndex (which is already idempotent)
- `AlterGraph(name, add_edges, remove_edges)` — graph evolution; complex, defer

### Runner Ordering Rules

The ordering engine arranges operations within a single migration into a safe execution order using a dependency graph (topological sort). Operations are nodes; ordering rules are directed edges.

#### Rule Set

 | Rule | From | To | Rationale |
 | ------ | ------ | ---- | ----------- |
 | R1 | CreateCollection/CreateEdgeCollection | CreateIndex on same collection | Must exist before indexing |
 | R2 | CreateCollection/CreateEdgeCollection | DataMigration writing to same collection | Must exist before inserting |
 | R3 | CreateCollection/CreateEdgeCollection | AddField on same collection | Must exist before field ops |
 | R4 | CreateCollection/CreateEdgeCollection | SeedDocument for same collection | Must exist before seeding |
 | R5 | DropIndex(fields_containing=F) | NullifyField(field=F) on same collection | Index must be gone before null values violate unique constraints |
 | R6 | DropIndex(fields_containing=F) | DropField(field=F) on same collection | Index must be gone before field removal |
 | R7 | NullifyField | DropField for same collection+field | Nullify before dropping (data safety) |
 | R8 | DataMigration | DropIndex (when DataMigration reads the indexed collection) | Don't drop indexes that queries depend on |
 | R9 | DataMigration | NullifyField/DropField (when DataMigration reads the field's collection) | Don't remove data that queries read |
 | R10 | SeedDocument | DataMigration (when DataMigration reads the seeded collection) | Seeds must exist before data transforms reference them |
 | R11 | CreateGraph | DropCollection for any collection in the graph's edge definitions | Don't drop what a graph references |
 | R12 | DropGraph | DropCollection for edge collections in that graph | Drop graph before its edge collections |

#### Topological Sort Algorithm

```
1. Build directed graph: nodes = operations, edges = ordering rules
2. For each pair of operations, check all rules → add edge if rule matches
3. Run Kahn's algorithm (BFS topological sort)
4. If cycle detected → raise MigrationError with the cycle description
5. For operations with no ordering constraint between them, preserve declaration order
```

Stable sort within topological levels preserves the author's declared order as a tiebreaker, giving migration authors predictability when ordering doesn't matter.

### AQL Read/Write Safety Design

**Chosen approach: Option B + C hybrid** — explicit collection declarations with structured read/write separation.

#### Option B: Collection Declarations (required for all DataMigrations)

```python
DataMigration(
    description="Populate edges from FK fields",
    fn=_populate_edges,
    read_collections=frozenset({"library_files"}),
    write_collections=frozenset({"library_contains_file"}),
)
```

The runner validates at load time:

```python
overlap = op.read_collections & op.write_collections
if overlap:
    logger.warning(
        "DataMigration '%s' reads and writes the same collections: %s. "
        "This may cause ArangoDB ERR 1579. Use BatchDataMigration instead.",
        op.description, overlap,
    )
```

This is a **warning**, not a hard error, because some read/write overlap is safe (e.g., `FOR doc IN X UPDATE doc IN X` — the simple self-update pattern). The warning flags it for human review.

#### Option C: BatchDataMigration (structured separation for complex cases)

```python
@dataclass(frozen=True)
class BatchDataMigration:
    """Structurally separated read-then-write data migration.

    The runner:
    1. Executes read_query to collect all data into Python memory
    2. Passes the results to write_fn in batches
    3. Guarantees no AQL statement touches both read and write collections

    This eliminates ERR 1579 by construction.
    """
    description: str
    read_query: str  # AQL read-only query
    read_bind_vars: dict[str, Any] | None = None
    write_fn: Callable[[DatabaseLike, list[dict[str, Any]]], None]
    batch_size: int = 1000
    read_collections: frozenset[str] = frozenset()
    write_collections: frozenset[str] = frozenset()
    kind: ClassVar[str] = "batch_data_migration"
```

The runner executes:

```python
cursor = db.aql.execute(op.read_query, bind_vars=op.read_bind_vars)
rows = list(cursor)
for batch in chunked(rows, op.batch_size):
    op.write_fn(db, batch)
```

This makes ERR 1579 **structurally impossible** for operations that use it. For V021's Phase 6 (edge repointing), this would have prevented the original bug:

```python
# Before (V021 original — triggered ERR 1579):
# Single AQL: REMOVE from file_has_state + INSERT into file_has_state

# After (declarative):
BatchDataMigration(
    description="Repoint ml_tagged → tagged",
    read_query='FOR e IN file_has_state FILTER e._to == "file_states/ml_tagged" RETURN {_key: e._key, _from: e._from}',
    write_fn=_repoint_tagged_edges,  # REMOVE old, INSERT new in separate calls
    read_collections=frozenset({"file_has_state"}),
    write_collections=frozenset({"file_has_state"}),
)
```

### Migration File Format

#### New (declarative) format

```python
"""V023: Drop library_id from files and folders."""
from __future__ import annotations

from nomarr.migrations.framework import (
    BatchDataMigration,
    CreateEdgeCollection,
    CreateIndex,
    DataMigration,
    DropField,
    DropIndex,
    Migration,
    NullifyField,
)
# Note: imports come from the framework *package* (nomarr/migrations/framework/__init__.py),
# which re-exports from operations.py, ordering.py, and executor.py.

MIGRATION_VERSION: str = "0.3.0"
DESCRIPTION: str = "Drop library_id from files and folders"

def _populate_library_edges(db, batch):
    """Write library_contains_file edges from collected FK data."""
    db.aql.execute(
        "FOR item IN @batch INSERT {_from: item.library_id, _to: item._id} "
        "INTO library_contains_file OPTIONS {ignoreErrors: true}",
        bind_vars={"batch": batch},
    )

migration = Migration(
    operations=[
        # 1. Create edge infrastructure
        CreateEdgeCollection("library_contains_file"),
        CreateIndex("library_contains_file", "persistent", ["_from", "_to"], unique=True),
        CreateIndex("library_contains_file", "persistent", ["_from"]),

        # 2. Migrate data (read FK, write edges)
        BatchDataMigration(
            description="Populate library_contains_file from library_files.library_id",
            read_query="FOR f IN library_files FILTER f.library_id != null RETURN {_id: f._id, library_id: f.library_id}",
            write_fn=_populate_library_edges,
            read_collections=frozenset({"library_files"}),
            write_collections=frozenset({"library_contains_file"}),
        ),

        # 3. Drop old indexes and field (runner enforces: drop indexes → nullify → drop field)
        DropIndex("library_files", fields_containing="library_id"),
        NullifyField("library_files", "library_id"),
        DropField("library_files", "library_id"),
    ],
)
```

#### Old (imperative) format — continues working

```python
MIGRATION_VERSION: str = "0.2.1"
DESCRIPTION: str = "Schema refactor v1"

def upgrade(db: DatabaseLike) -> None:
    # ... imperative code ...
```

#### Runner Detection Logic

```python
def _is_declarative(module: ModuleType) -> bool:
    return hasattr(module, "migration") and isinstance(module.migration, Migration)

def _is_imperative(module: ModuleType) -> bool:
    return hasattr(module, "upgrade") and callable(module.upgrade)
```

A module can have both (for gradual migration). If both exist, `migration` takes precedence. The runner logs which path it takes.

### Backwards Compatibility

**Existing migrations V001–V021 are never modified.** The enhanced runner:

1. Discovers all V*.py files (unchanged)
2. For each module, checks: declarative (`migration` attribute) or imperative (`upgrade` function)
3. Imperative modules: calls `module.upgrade(db)` directly (current behavior)
4. Declarative modules: extracts operations → validates → topological sort → execute each operation
5. Version tracking is identical in both paths (MIGRATION_VERSION + meta.version write)

The runner component (`migration_runner_comp.py`) changes in three places:

1. **`_validate_migration_module`** — currently requires `upgrade` as a callable. Must accept modules where `migration` (a `Migration` instance) is present instead. A module is valid if it has `upgrade` OR `migration` (or both).

2. **`apply_migration`** — currently calls `module.upgrade(db.db)` unconditionally. Gains a branch:

```python
if _is_declarative(module):
    execute_declarative_migration(module.migration, db.db)
else:
    module.upgrade(db.db)
```

1. **`discover_migrations`** — no structural change needed (still globs `V*.py` and imports), but validation call must pass through the relaxed validator.

### ensure_schema Relationship

`ensure_schema` is frozen (ADR-016). The framework does not replace it.

**Alignment**: The framework's operation types are semantically equivalent to ensure_schema's internal helpers:

- `CreateCollection` → `db.create_collection(name)` with `CollectionCreateError` suppression
- `CreateEdgeCollection` → `db.create_collection(name, edge=True)`
- `CreateIndex` → `_ensure_index(db, collection, type, fields, ...)` with 409 suppression
- `CreateGraph` → `db.create_graph(name, edge_definitions)` with `GraphCreateError` suppression
- `SeedDocument` → `coll.insert({"_key": ...})` with `DocumentInsertError` suppression

This alignment means the consolidation tool (DD-migration-consolidation) can generate declarative migrations from ensure_schema's shape model, and vice versa.

### Executor Idempotency

Every operation's `execute(db)` method is idempotent by construction:

 | Operation | Idempotency mechanism |
 | ----------- | ---------------------- |
 | CreateCollection | `has_collection()` guard + `CollectionCreateError` suppression |
 | CreateEdgeCollection | Same as CreateCollection |
 | DropCollection | `has_collection()` guard |
 | CreateIndex | `IndexCreateError` 409 suppression (matches ensure_schema) |
 | DropIndex | `coll.indexes()` scan — skips if no matching index found |
 | CreateGraph | `has_graph()` guard + `GraphCreateError` suppression |
 | DropGraph | `has_graph()` guard |
 | AddField | AQL `UPDATE ... OPTIONS {keepNull: false}` — safe to repeat |
 | DropField | AQL `UPDATE {field: null} OPTIONS {keepNull: false}` — no-op if field absent |
 | NullifyField | AQL `UPDATE {field: null}` — idempotent (null → null) |
 | RenameField | Checks if old field exists before copying |
 | SeedDocument | `DocumentInsertError` suppression |
 | DataMigration | Author's responsibility (documented requirement) |
 | BatchDataMigration | Author's responsibility for write_fn |

### Testing Strategy

#### Unit Tests (no DB required)

1. **Ordering engine tests** (`tests/unit/migrations/test_ordering.py`):
   - Given a list of operations, verify topological sort produces correct order
   - Test each rule individually: CreateCollection before CreateIndex, DropIndex before NullifyField, etc.
   - Test cycle detection: operations that form a cycle raise MigrationError
   - Test stable sort: operations with no ordering constraint preserve declaration order

2. **AQL safety validation tests** (`tests/unit/migrations/test_aql_safety.py`):
   - DataMigration with overlapping read/write collections triggers warning
   - DataMigration with disjoint collections passes clean
   - BatchDataMigration validates structurally separated execution

3. **Operation validation tests** (`tests/unit/migrations/test_operations.py`):
   - DropIndex requires exactly one of fields_containing or fields_exact
   - CreateIndex validates index_type is a known type
   - Operation frozen dataclasses are immutable

#### Integration Tests (Docker ArangoDB)

1. **DropIndex broad match test** (`tests/integration/migrations/test_drop_index.py`):
   - Create a collection with compound indexes (e.g., `[library_id, path]`, `[library_id, tagged]`)
   - Execute `DropIndex(collection, fields_containing="library_id")`
   - Verify ALL indexes containing `library_id` are gone, others remain

2. **Full migration round-trip** (`tests/integration/migrations/test_declarative_migration.py`):
   - Define a declarative migration with CreateCollection → CreateIndex → DataMigration → DropIndex → NullifyField → DropField
   - Execute on fresh DB → verify final state
   - Execute again → verify idempotency (no errors, same state)

3. **Mixed old/new migrations** (`tests/integration/migrations/test_backwards_compat.py`):
   - Run V001 (imperative) → new declarative migration → verify both applied correctly

4. **BatchDataMigration test** (`tests/integration/migrations/test_batch_migration.py`):
   - Create collection with data → execute BatchDataMigration → verify read/write separation worked
   - Verify no ERR 1579 on populated collections

---

## Design Goals

### Goals

1. **Prevent index ordering bugs by construction**: The runner automatically orders index drops before field nullification/drops. Migration authors declare operations; the runner computes safe execution order.

2. **Detect AQL read/write violations at definition time**: `DataMigration` operations must declare read and write collections. The runner validates no overlap and warns at migration load time, not at AQL execution time on production data.

3. **Preserve type safety and IDE support**: Migration files remain Python (not YAML/JSON). Operation types are dataclasses or typed constructors with full IDE autocomplete and mypy coverage.

4. **Backwards-compatible with V001–V021**: Existing imperative migrations continue working unchanged. The runner detects whether a module exports `migration = Migration([...])` (new) or `upgrade(db)` (old) and handles both.

5. **Align with ensure_schema primitives**: Operation types use the same ArangoDB API calls that `ensure_schema` uses internally (`_ensure_index`, `create_collection`, `create_graph`), ensuring semantic equivalence between bootstrap and migration paths.

6. **Support the consolidation tool**: Declarative operations are machine-readable, enabling the consolidation tool (DD-migration-consolidation) to extract schema shape from new migrations without AST heuristics.

### Non-Goals

1. **Rollback/downgrade support**: Forward-only, per ADR-004. No `downgrade()` functions.
2. **Replace ensure_schema**: The frozen baseline stays frozen (ADR-016). This framework is for migrations only.
3. **Rewrite existing migrations**: V001–V021 are never touched. They run as-is through the imperative path.
4. **Full AQL analysis**: The framework does not parse AQL strings for safety — it requires explicit collection declarations. Static AQL analysis is a future enhancement, not a launch requirement.
5. **Cross-migration dependency tracking**: Each migration is self-contained. The framework does not track dependencies between different migration files.
6. **GUI or CLI migration generator**: Authors write Python files by hand. Code generation is a separate concern.

---

## Constraints

### Hard Constraints

1. **Forward-only migrations** — no rollback (ADR-004)
2. **ensure_schema is frozen** — not modified by this framework (ADR-016)
3. **Existing migrations untouched** — V001–V021 never rewritten
4. **Idempotent execution** — every operation tolerates re-run after partial failure
5. **Python files only** — no YAML/JSON migration format
6. **Semver versioning** — uses existing MIGRATION_VERSION contract (DD-migration-versioning)

### Performance Constraints

- Topological sort runs at migration load time (not per-execution) — negligible cost
- BatchDataMigration loads full result set into Python memory — unsuitable for migrations touching millions of documents. Large migrations should use DataMigration with manual batching.
- The runner should log execution time per operation (already logs per-migration)

---

## Open Questions

1. **Should the ordering engine be strict or advisory?** Currently designed as strict (auto-reorders). Alternative: validate that the author's declared order satisfies all rules, and error if not. Strict is safer but may surprise authors. Advisory requires authors to know the rules but gives them full control.

2. **BatchDataMigration memory limits**: For collections with millions of documents, loading all results into Python memory is impractical. Should there be a `StreamingDataMigration` that uses cursor pagination? Or is manual DataMigration with explicit batching sufficient for those cases?

3. **AQL safety warning vs error**: Should overlapping read/write collections in DataMigration be a warning (current design) or a hard error? Warning is pragmatic (some overlap is safe), but errors would force authors to use BatchDataMigration for any overlap, eliminating the ambiguity.

4. **Graph operation ordering**: DropGraph before DropCollection is in the rule set, but what about updating a graph's edge definitions (adding/removing edges from an existing graph)? ArangoDB supports this via `graph.create_edge_definition()` and `graph.delete_edge_definition()`. Should `AlterGraph` be added to v1?

5. **Dynamic vector collections**: ensure_schema creates `vectors_track_hot__{backbone}__{library_key}` at runtime. Should the framework have a `CreateDynamicCollection(pattern)` operation, or are dynamic collections always handled outside the migration framework?

6. **Consolidation tool integration**: The consolidation tool (DD-migration-consolidation) currently uses AST parsing to extract schema shape from imperative migrations. Declarative migrations would be trivially machine-readable. Should the consolidation tool be updated as part of this work, or is that a follow-up?

7. **Operation-level retry granularity**: The current runner records migration-level progress (in_progress → applied). Should declarative migrations also track which operations within a migration have completed, enabling operation-level retry? This adds complexity but improves resilience for long migrations like V021.

---
