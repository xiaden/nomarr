# Design: Migration Consolidation Tool

## Problem

Nomarr is alpha software with one developer and 16 migration files (V004–V019) that collectively represent the evolution from schema version 3 to 19. Many of these migrations revert previous changes (V010 adds a TTL index, V011 drops it), create intermediate collections that later get dropped (V015 creates `navidrome_song_map`, V019 drops it), or perform data transforms that only made sense historically. This accumulated cruft serves no purpose for a codebase with no external users.

The goal is a **reusable consolidation tool** that validates safety before acting, then collapses all migrations into a single baseline. This tool will be run between major version changes in the future.

## Safety Requirement: Shape Validation

The core safety invariant:

> **Shape A** (target) = `ensure_schema()` parsed via AST
> **Shape B** (replay) = `ensure_schema()` + all migrations replayed via AST
> **Shape A must equal Shape B after replay.**

### Shape Model

A "shape" represents the database schema as a set of:
- **Collections**: name, edge (bool)
- **Indexes**: collection name, index type (persistent/ttl/vector), fields, unique, sparse, extra params
- **Graphs**: name, edge definitions (edge collection → from/to vertex collections)
- **Seed documents**: collection name, document _key (for idempotent seeds like `file_states`)

### Shape A: Extract from ensure_schema()

Parse `nomarr/components/platform/arango_bootstrap_comp.py` via Python AST. Walk calls to:
- `db.create_collection(name)` / `db.create_collection(name, edge=True)` → collection
- `_ensure_index(db, collection, type, fields, **kwargs)` → index
- `db.create_graph(name, edge_definitions=[...])` → graph
- `coll.insert({"_key": ...})` → seed document

This is a static, limited extraction — the helper functions `_create_collections`, `_create_indexes`, `_create_graphs`, `_seed_file_states` call a small set of known patterns.

### Shape B: Clone + Replay Migrations

1. Deep-copy Shape A into Shape B
2. For each migration V004–V019, parse the `upgrade()` function via AST
3. For each recognized operation, apply it to Shape B:

| Operation | Replay Action |
|---|---|
| `db.create_collection(name)` | Add collection (skip if exists) |
| `db.delete_collection(name)` | Remove collection (create-then-remove if missing) |
| `coll.rename(new_name)` | Rename; if old doesn't exist, create phantom then rename; if new exists, merge |
| `add_persistent_index(coll, fields, ...)` | Add index |
| `add_ttl_index(coll, fields, ...)` | Add index |
| `delete_index(coll, ...)` | Remove index (create phantom if missing) |
| `db.create_graph(name, ...)` | Add graph |
| AQL UPDATE/INSERT/REMOVE | Track field-level document changes (best-effort) |

#### Phantom Creation Rule

When a migration references something not in Shape B (rename a collection that doesn't exist, delete an index that doesn't exist), the replay engine:
1. Creates a phantom entry for the missing item
2. Applies the operation
3. If the result merges into an existing item (rename to existing name), merge them

This ensures that things migrations touched but `ensure_schema()` created under a different name still appear in the final shape.

#### Dynamic/Blacklisted Collections

Some collections are created dynamically at runtime based on ML model discovery and library configuration:
- `vectors_track_hot__{backbone}__{library_key}`
- `vectors_track_cold__{backbone}__{library_key}`

These follow a prefix pattern and should be blacklisted from shape comparison, since their existence depends on runtime state.

Similarly, migrations V007, V008, V018 operate on dynamically-named vector collections discovered via `db.collections()` at runtime. The replay engine should recognize these loop patterns and skip them with a warning rather than attempting to resolve dynamic names.

### Comparison

After replay, diff Shape A and Shape B:
- Collections in A but not B (or vice versa)
- Index differences per collection
- Graph definition differences
- Seed document differences

If shapes match → safe to consolidate. If not → report differences and abort.

## Migration Operations Inventory

Based on static analysis of V004–V019:

### DDL Operations Used
```
db.has_collection(name)      — conditional guard
db.create_collection(name)   — create doc collection
db.create_collection(n, edge=True) — create edge collection
db.delete_collection(name)   — drop collection
coll.rename(new_name)        — rename collection
coll.add_persistent_index(fields, unique, sparse)
coll.add_ttl_index(fields, expiry_time)
coll.add_index({type, fields, params})  — generic (vector indexes)
coll.delete_index(id)
coll.indexes()               — list indexes
db.has_graph(name)
db.create_graph(name, edge_definitions)
```

### Data Operations (not replayed for schema shape, but logged)
```
db.aql.execute(...)  — various INSERT/UPDATE/REMOVE queries
coll.insert(doc)     — document inserts
coll.count()         — read-only
```

### Migration Categories

| Category | Migrations | Replay Strategy |
|---|---|---|
| Verification-only | V004, V005, V006 | Skip (no state change) |
| DDL-only | V007, V010, V011, V012, V013, V014, V015 | Full AST replay |
| Data-transform | V009, V017 | Log as "data transform, not validated" |
| Mixed (DDL + data) | V008, V016, V018, V019 | Replay DDL ops, log data ops |

## Consolidation (Post-Validation)

Once shapes match:

1. Delete all V004–V019 migration files
2. Create `V001_baseline.py` — verifies all collections exist (no data transforms)
3. Reset schema version: print AQL to set `schema_version=0`, clear `applied_migrations`
4. Optional `--execute-db-reset` flag to run the AQL against a live ArangoDB

The baseline migration:
- `SCHEMA_VERSION_BEFORE = 0`, `SCHEMA_VERSION_AFTER = 1`
- `upgrade()` checks all expected collections exist (from Shape A)
- Future migrations start at V002

## Package Structure

```
scripts/consolidate_migrations/
├── __init__.py
├── __main__.py            # CLI entry point
├── schema_model.py        # SchemaShape, Collection, Index, Graph data classes
├── ensure_schema_parser.py  # AST extraction of Shape A from bootstrap
├── migration_replayer.py  # AST replay of migrations onto Shape B
├── schema_comparator.py   # Diff Shape A vs Shape B
├── consolidator.py        # File deletion + baseline creation
└── blacklist.py           # Dynamic collection patterns to skip
```

## Future Use

This tool is designed to be run between major version changes:
1. Run shape validation to confirm all migrations are captured in ensure_schema
2. If valid, consolidate to reset the migration counter
3. Continue development with a clean slate

## Non-Goals

- Running against a live database for validation (pure static analysis)
- Replaying AQL data transforms at the field level (too complex, diminishing returns)
- Supporting rollback migrations (alpha, forward-only)
- Handling migrations that import runtime-dependent code (blacklist instead)
