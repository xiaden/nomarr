# Task: Migration Consolidation Part A — Schema Model + ensure_schema Parser

## Problem Statement

Nomarr's migration consolidation tool needs to statically analyze `arango_bootstrap_comp.py` to extract the current database schema ("Shape A") without executing the code or connecting to a database. This is the foundation for comparing against replayed migrations in later parts.

Part A defines the data model for representing database schemas (`SchemaShape`) and implements an AST parser that reads the bootstrap source file and produces a `SchemaShape`. It also defines a blacklist of dynamic collection prefix patterns that cannot be resolved statically.

**Design doc:** `plans/dev/design-migration-consolidation.md`
**Contracts ledger:** architectural rules and decisions in the user request that initiated this plan.

## Phases

### Phase 1: Package Scaffold + Schema Data Model
- [x] Create `scripts/consolidate_migrations/__init__.py` (empty or with package docstring)
- [x] Define frozen dataclasses in `scripts/consolidate_migrations/schema_model.py`: `Collection(name: str, edge: bool)`, `Index(collection: str, index_type: str, fields: tuple[str, ...], unique: bool, sparse: bool, expire_after: int | None)`, `Graph(name: str, edge_definitions: tuple[EdgeDefinition, ...])` with helper `EdgeDefinition(edge_collection: str, from_vertex_collections: tuple[str, ...], to_vertex_collections: tuple[str, ...])`, `SeedDocument(collection: str, key: str)`, and `SchemaShape(collections: frozenset[Collection], indexes: frozenset[Index], graphs: frozenset[Graph], seed_documents: frozenset[SeedDocument])`
- [x] Create `scripts/consolidate_migrations/blacklist.py` defining `DYNAMIC_COLLECTION_PREFIXES: tuple[str, ...] = ("vectors_track_hot__", "vectors_track_cold__")` and a helper function `is_blacklisted(name: str) -> bool` that checks if a collection name starts with any prefix
- [x] Run `ruff check scripts/consolidate_migrations/ --select E,W,F,I,N,UP,B,C4,SIM,RUF,TID,ERA,PERF,ASYNC,PIE,RET,LOG,FURB,TC,ARG` and fix any issues
    **Notes:** Zero ruff errors on first run.

**Notes:** All dataclasses must be `frozen=True` for hashability (needed for frozenset membership and later shape comparison in Part B). Use `tuple` instead of `list` for immutable field types. `SchemaShape` uses `frozenset` for order-independent equality. The fields on `Index` mirror the `_ensure_index` signature: `collection`, `index_type`, `fields`, `unique`, `sparse`, `expire_after` (snake_case, not camelCase).

### Phase 2: AST Parser — Extract Schema from Bootstrap Source
- [x] Create `scripts/consolidate_migrations/ensure_schema_parser.py` with a public function `parse_ensure_schema(source_path: Path) -> SchemaShape` that reads the file, parses AST, locates the four target functions, and delegates to private extraction helpers
- [x] Implement `_extract_collections(func_node: ast.FunctionDef) -> list[Collection]` that finds the `document_collections = [...]` and `edge_collections = [...]` list-literal assignments in `_create_collections`, extracts string constants from each, and returns `Collection(name, edge=False)` / `Collection(name, edge=True)` respectively
- [x] Implement `_extract_indexes(func_node: ast.FunctionDef) -> list[Index]` that walks all `_ensure_index(db, collection, index_type, fields, ...)` calls in `_create_indexes`, resolving positional and keyword arguments to produce `Index` instances — must handle both inline `fields=[...]` and keyword forms like `unique=True`, `sparse=True`, `expireAfter=0`
- [x] Implement `_extract_graphs(func_node: ast.FunctionDef) -> list[Graph]` that finds `db.create_graph(name=..., edge_definitions=[...])` calls in `_create_graphs`, resolving graph name from either a keyword arg or a variable assignment (e.g., `graph_name = "tag_graph"` then `name=graph_name`), and parsing the edge_definitions list-of-dicts literal into `EdgeDefinition` tuples
- [x] Implement `_extract_seed_documents(func_node: ast.FunctionDef) -> list[SeedDocument]` that finds the `for key in (...)` loop in `_seed_file_states`, extracts the tuple of string constants, and pairs each with the collection name from the `db.collection("file_states")` call to produce `SeedDocument` instances
- [x] Implement `_find_function(module: ast.Module, name: str) -> ast.FunctionDef` helper that locates a top-level function by name in the AST, raising `ValueError` if not found
- [x] Run `ruff check scripts/consolidate_migrations/` and fix any issues
    **Notes:** Fixed 3 ruff issues: TC003 (Path import to TYPE_CHECKING), ERA001 (comment resembling code), SIM102 (collapsible if).

**Notes:** The parser targets four specific functions: `_create_collections`, `_create_indexes`, `_create_graphs`, `_seed_file_states`. It does NOT parse `_create_vectors_track_collections` (those are dynamic/blacklisted). Variable resolution in `_extract_graphs` only needs single-assignment lookup within the same function scope (e.g., `graph_name = "tag_graph"` on a preceding line). The parser must not import or execute `arango_bootstrap_comp` — it reads the `.py` file as text and parses the AST.

### Phase 3: Smoke Test + Final Verification
- [x] Add a `if __name__ == "__main__"` block to `ensure_schema_parser.py` that parses the actual `nomarr/components/platform/arango_bootstrap_comp.py`, prints summary counts (N collections, N indexes, N graphs, N seed docs), and lists all extracted items for manual inspection
- [x] Run the parser against the real bootstrap file and verify it extracts: 27 document collections, 5 edge collections, ~40 indexes, 2 graphs (tag_graph with 1 edge def, navidrome_graph with 2 edge defs), 3 seed documents (ml_tagged, calibrated, reconciled)
    **Notes:** Actual counts: 22 document + 5 edge = 27 total collections (plan said "27 document" but meant 27 total), 41 indexes, 2 graphs, 3 seed docs. All correct.
- [x] Run `ruff check scripts/consolidate_migrations/` — zero errors required
    **Notes:** Zero ruff errors. All phases complete.

**Notes:** Expected counts are derived from reading the current `arango_bootstrap_comp.py` source. The exact index count may vary slightly if comments or formatting cause ambiguity — the smoke test is a sanity check, not a hard assertion. The `__main__` block is for development convenience and will be useful during Part B/C integration.

## Completion Criteria

- `scripts/consolidate_migrations/` package exists with `__init__.py`, `schema_model.py`, `ensure_schema_parser.py`, `blacklist.py`
- All dataclasses are frozen and use immutable field types (tuple, frozenset)
- `parse_ensure_schema(path)` produces a `SchemaShape` from the real bootstrap file with correct collection, index, graph, and seed document counts
- `is_blacklisted("vectors_track_hot__effnet__abc")` returns `True`; `is_blacklisted("library_files")` returns `False`
- `ruff check scripts/consolidate_migrations/` passes with zero errors
- No imports from `nomarr.*` at runtime — only `ast`, `pathlib`, `dataclasses`, stdlib

## References

- Design doc: `plans/dev/design-migration-consolidation.md` (Shape Model, Shape A Extraction, Dynamic/Blacklisted Collections sections)
- Source file being parsed: `nomarr/components/platform/arango_bootstrap_comp.py`
- Existing single-file script (to be superseded by package): `scripts/consolidate_migrations.py`
- Part B plan (future): migration replay — consumes `SchemaShape` from this plan
- Part C plan (future): comparator + CLI — consumes both Shape A and Shape B
