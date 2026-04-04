# Task: Migration Consolidation Part B — Migration Replay Engine

## Problem Statement

The migration consolidation tool needs to replay all migrations (V004–V019) onto a clone of Shape A to produce Shape B, then compare the two shapes for equivalence. Part A (prerequisite) defined the `SchemaShape` data model and the `ensure_schema` parser. Part B implements the replay engine: an AST-based analyzer that parses each migration's `upgrade()` function, recognizes database operations, and applies them to a mutable working copy of the schema.

The replay engine must handle four categories of migrations:
- **Verification-only** (V004–V006): no state change, skip.
- **Static DDL** (V010–V015): create/delete/rename collections, add/delete indexes, create graphs, seed documents.
- **Dynamic/blacklisted** (V007, V008, V018): loop over `db.collections()` to operate on runtime-named vector collections — skip with warning.
- **Data transforms** (V009, V017): AQL-only operations — log as "not validated" but don't fail.
- **Mixed** (V016, V019): DDL operations replayed, AQL/data operations logged.

Key design constraints:
- `SchemaShape` is frozen/immutable. The replayer uses a `MutableSchemaShape` internally, then freezes the result.
- When an operation references something missing (e.g., rename a non-existent collection), create a phantom first, then apply the operation.
- When a rename targets an existing name, merge the items.
- Dynamic collections (loop patterns over `db.collections()`) are detected by AST pattern matching and skipped with a warning.
- AQL data transforms are logged but don't modify the schema shape.

**Prerequisite:** `plans/TASK-migration-consolidation-A-schema-model.md`
**Design doc:** `plans/dev/design-migration-consolidation.md` (sections: Shape B, Phantom Creation Rule, Migration Operations Inventory, Migration Categories)
**Contracts ledger:** architectural rules and data model from Part A.

## Phases

### Phase 1: Mutable Schema + Migration Discovery
- [x] Create `scripts/consolidate_migrations/migration_replayer.py` with module docstring explaining its role: AST-based replay of V004–V019 `upgrade()` functions onto a mutable schema shape
    **Notes:** Created `scripts/consolidate_migrations/migration_replayer.py` with comprehensive module docstring covering all migration categories, design constraints, and the phantom creation rule.
- [x] Define `MutableSchemaShape` class with fields `collections: dict[str, Collection]`, `indexes: set[Index]`, `graphs: dict[str, Graph]`, `seed_documents: set[SeedDocument]` — keyed by name for O(1) lookup during replay operations
    **Notes:** Defined with `__slots__` for memory efficiency. Uses `dict[str, Collection]` keyed by name for collections/graphs, `set[Index]` for indexes, `set[SeedDocument]` for seeds.
- [x] Implement `MutableSchemaShape.from_shape(shape: SchemaShape) -> MutableSchemaShape` classmethod that deep-copies a frozen `SchemaShape` into the mutable form
    **Notes:** Builds dicts from frozensets using name-keyed comprehensions. Frozen dataclasses don't need deepcopy since they're immutable.
- [x] Implement `MutableSchemaShape.freeze() -> SchemaShape` method that converts back to a frozen `SchemaShape` with `frozenset` fields
- [x] Implement `discover_migrations(migrations_dir: Path) -> list[Path]` function that finds all `V{NNN}_*.py` files, sorts by version number, and returns paths for V004–V019
    **Notes:** Uses `_VERSION_RE = re.compile(r"^V(\d+)_.*\.py$")` to extract version numbers, filters to V004--V019 range via `_MIN_VERSION`/`_MAX_VERSION` constants.
- [x] Implement `_parse_upgrade_function(source_path: Path) -> ast.FunctionDef` helper that reads a migration file, parses AST, and locates the `upgrade` function definition
    **Notes:** Returns `tuple[ast.Module, ast.FunctionDef]` (expanded from plan's single-return signature) so callers also have access to module-level constants and helper functions needed by Phase 2/3 recognizers.
- [x] Run `ruff check scripts/consolidate_migrations/` and fix any issues
    **Notes:** Had to replace unicode EN DASH and EM DASH characters (from plan copy-paste) with ASCII `--`. Zero errors after fix.

**Notes:** `MutableSchemaShape` is NOT frozen — it's a plain class for in-place mutation during replay. The `collections` dict is keyed by `name` for efficient rename/delete lookup. `indexes` remains a set because index operations are add/remove by value. The `discover_migrations` function uses a regex like `V(\d+)_` to extract version numbers and sorts numerically.

### Phase 2: AST Operation Recognizers
- [x] Implement `_is_dynamic_loop(node: ast.For) -> bool` that detects `for ... in db.collections()` loop patterns (the signal that a migration operates on dynamically-named collections) — matches V007/V008/V018 patterns
    **Notes:** Signature expanded to `(node: ast.For, func_body: list[ast.stmt]) -> bool` — needs func_body to scan for `db.collections()` in preceding statements. Uses `node` via `stmt is node` identity check to limit scan to statements before the loop. Added `_contains_db_collections_call` helper that walks AST subtrees for the `db.collections()` attribute call pattern.
- [x] Implement `_recognize_create_collection(node: ast.Call) -> tuple[str, bool] | None` that matches `db.create_collection(name)` and `db.create_collection(name, edge=True)` calls, returning `(collection_name, is_edge)` or `None`
    **Notes:** Added `constants: dict[str, Any]` parameter for resolving module-level constant names (e.g. V019 patterns). Implemented helper functions: `_extract_module_constants` (handles both ast.Assign and ast.AnnAssign for str/int/bool/list[str] values), `_resolve_str`, `_resolve_bool`.
- [x] Implement `_recognize_delete_collection(node: ast.Call) -> str | None` that matches `db.delete_collection(name)` calls, returning the collection name or `None`
    **Notes:** Added `constants` parameter for name resolution. Straightforward pattern match on `db.delete_collection(name)` with `_resolve_str` for the argument.
- [x] Implement `_recognize_rename(node: ast.Call) -> tuple[str, str] | None` that matches `db.collection(old_name).rename(new_name)` or `coll.rename(new_name)` patterns where `coll` is resolved to a collection name via preceding `coll = db.collection(name)` assignment, returning `(old_name, new_name)` or `None`
    **Notes:** Added `constants` and `coll_bindings` parameters. Handles both inline `db.collection(old).rename(new)` (V013 pattern) and variable-bound `coll.rename(new)` patterns. Added `_build_collection_bindings` helper that scans function body for `var = db.collection("name")` assignments.
- [x] Implement `_recognize_add_index(node: ast.Call) -> Index | None` that matches `coll.add_persistent_index(fields=..., unique=..., sparse=...)` and `coll.add_ttl_index(fields=..., expiry_time=...)` calls, resolving `coll` to a collection name and returning an `Index` instance or `None`
    **Notes:** Added `coll_bindings` and `constants` parameters. Handles both `add_persistent_index` and `add_ttl_index` methods. Added shared `_resolve_collection_receiver` helper (used by add_index, delete_index, insert). Added `_resolve_str_list` and `_resolve_int` helpers for fields/expiry_time extraction.
- [x] Implement `_recognize_delete_index(node: ast.Call) -> tuple[str, str] | None` that matches `coll.delete_index(id)` calls, returning `(collection_name, index_id_or_type_hint)` or `None` — note that V011 finds the index by type+fields from `coll.indexes()` then deletes by id, so the recognizer must handle the pattern of iterating indexes to find the target
    **Notes:** Return type expanded from plan's `tuple[str, str]` to `tuple[str, str, tuple[str, ...]]` — returns (collection, index_type, fields) so Phase 3's `_apply_delete_index` can match by type+fields without further context. Added `func_body`, `coll_bindings`, `constants` parameters. Implemented V011 semantic pattern detection: traces `next(genexpr)` assignment back through `_find_index_filter_assignment` and `_extract_index_filter_info` helpers. Added `_flatten_bool_op` and `_is_dict_get` utilities for condition parsing.
- [x] Implement `_recognize_create_graph(node: ast.Call) -> Graph | None` that matches `db.create_graph(name=..., edge_definitions=[...])` calls, parsing the edge_definitions list-of-dicts into `EdgeDefinition` tuples and returning a `Graph` or `None`
    **Notes:** Added `constants` parameter. Implemented `_parse_edge_definition_dict` helper for parsing `edge_definitions` list-of-dicts into `EdgeDefinition` tuples. Added `_resolve_literal_str_list` for vertex collection lists. Required adding `EdgeDefinition` to schema_model imports.
- [x] Implement `_recognize_insert(node: ast.Call) -> SeedDocument | None` that matches `coll.insert({"_key": ...})` calls, returning `SeedDocument(collection, key)` or `None`
    **Notes:** Added `coll_bindings` and `constants` parameters. Only resolves literal `_key` values — V016's loop-variable keys (`for key in _STATE_KEYS: coll.insert({"_key": key})`) require Phase 3 walker to handle loop unrolling over the `_STATE_KEYS` list constant.
- [x] Implement `_recognize_aql_execute(node: ast.Call) -> str | None` that matches `db.aql.execute(...)` calls, returning a summary string of the AQL query for logging, or `None`
    **Notes:** Handles string literals (plain AQL), f-strings (JoinedStr with `{...}` placeholders), and unknown patterns (fallback `"<AQL query>"`). Normalises whitespace and truncates to 120 chars for warning messages.
- [x] Run `ruff check scripts/consolidate_migrations/` and fix any issues
    **Notes:** Had 5 ruff issues after initial implementation: 1 UP038 (use `X | Y` in isinstance), 4 SIM102 (collapsible nested ifs). All fixed. Final `ruff check` passes clean with zero errors.

**Notes:** All recognizers take an `ast.Call` node (or `ast.For` for loops) and return either a typed result or `None` (no match). Variable resolution is local-scope only: scan the function body for `name = db.collection("...")` assignments to resolve `coll` variables. The rename recognizer must handle the V013 pattern where `_OLD_NAME` and `_NEW_NAME` are module-level constants — resolve them from the module's top-level `ast.Assign` nodes. The `delete_index` recognizer for V011's pattern (find TTL index by type/fields, then delete by id) should recognize the semantic intent: "delete TTL index on fields [last_seen_ms] from collection vram_promises" — the replayer will match by type+fields, not by runtime id.

### Phase 3: Replay Mutators + Migration Walker
- [x] Implement `_apply_create_collection(shape: MutableSchemaShape, name: str, edge: bool, warnings: list[str]) -> None` that adds a `Collection` to the mutable shape, skipping with a log if it already exists (idempotent)
    **Notes:** Added `from .blacklist import is_blacklisted` import. Mutator checks blacklist before creating, skips with warning if dynamic prefix matches. Idempotent: skips if collection already exists. Extra `migration_name` parameter on all mutators for descriptive warnings (consistent pattern across all Phase 3 mutators).
- [x] Implement `_apply_delete_collection(shape: MutableSchemaShape, name: str, warnings: list[str]) -> None` that removes a collection and all its indexes from the mutable shape — if the collection doesn't exist, create a phantom first then remove it (phantom creation rule)
    **Notes:** Phantom creation for missing collections before delete. Also removes all indexes for the deleted collection via set comprehension filter on `idx.collection != name`.
- [x] Implement `_apply_rename_collection(shape: MutableSchemaShape, old_name: str, new_name: str, warnings: list[str]) -> None` that renames a collection: if `old_name` doesn't exist, create phantom; if `new_name` already exists, merge (remove old, keep new); otherwise rename by removing old `Collection` and adding new, plus updating `collection` field on all associated `Index` objects
    **Notes:** Three cases: normal rename (pop old + add new preserving edge flag + rebuild all Index objects with updated collection field), phantom rename (create phantom Collection(edge=False) first), merge rename (old+new both exist: delete old, keep new). Indexes updated via full set rebuild replacing `idx.collection == old_name` entries.
- [x] Implement `_apply_add_index(shape: MutableSchemaShape, index: Index, warnings: list[str]) -> None` that adds an `Index` to the shape — if the index's collection doesn't exist, create a phantom collection first, then add the index
    **Notes:** Phantom collection created with `Collection(name=..., edge=False)` if index's collection not in shape. Then index added to `shape.indexes` set.
- [x] Implement `_apply_delete_index(shape: MutableSchemaShape, collection: str, index_type: str, fields: tuple[str, ...], warnings: list[str]) -> None` that removes an index matching the given collection, type, and fields — if not found, create phantom then remove (logs warning)
    **Notes:** Matches by (collection, index_type, fields) triple via set comprehension. If no match found, warns with phantom skip message and returns (no-op). If found, removes matching indexes via set subtraction (`shape.indexes -= matching`).
- [x] Implement `_apply_create_graph(shape: MutableSchemaShape, graph: Graph, warnings: list[str]) -> None` that adds a `Graph` to the shape, skipping if one with the same name already exists
    **Notes:** Idempotent skip if `graph.name` already in `shape.graphs` dict. Otherwise inserts graph keyed by name.
- [x] Implement `_apply_insert(shape: MutableSchemaShape, seed: SeedDocument, warnings: list[str]) -> None` that adds a `SeedDocument` to the shape
    **Notes:** Simple `shape.seed_documents.add(seed)`. No idempotency check needed since `SeedDocument` is a frozen dataclass and set membership handles deduplication.
- [x] Implement `_walk_upgrade(func_node: ast.FunctionDef, module_node: ast.Module, shape: MutableSchemaShape, migration_name: str, warnings: list[str]) -> None` that walks all statements in `upgrade()`, calls recognizers on each `ast.Call` node, and dispatches to the appropriate mutator — skips `ast.For` nodes that match dynamic loop patterns with a warning, and logs AQL executions as "data transform, not validated"
    **Notes:** Decomposed into helper functions: `_walk_upgrade` (entry, extracts module constants + function defs) → `_walk_function_body` (deep binding via `_deep_collect_bindings` using ast.walk for nested db.collection() assignments inside if/with/try) → `_walk_statements` (handles For loops with dynamic detection + constant unrolling for V016 via `_handle_for_loop`, compound stmts If/With/Try body recursion, Expr+Assign call dispatch). `_process_call` tries 8 recognizers in order (AQL, create_coll, delete_coll, rename, add_idx, del_idx, create_graph, insert) then falls through to `_try_resolve_helper_call` for V019 module-level helper resolution with argument substitution via `_resolve_call_arguments`. Also processes Assign+Call for `result = db.aql.execute(...)`. Added helpers: `_deep_collect_bindings`, `_resolve_arg_value`, `_resolve_call_arguments`. Max recursion depth=10.
- [x] Run `ruff check scripts/consolidate_migrations/` and fix any issues
    **Notes:** `ruff check scripts/consolidate_migrations/` passes with zero errors on first run. No fixes needed.

**Notes:** The walker must handle nested structures: V019 calls helper functions like `_create_collections(db)`, `_create_indexes(db)`, `_create_graph(db)`. The walker should resolve calls to module-level functions (functions defined in the same migration file) and walk their bodies recursively. This is essential for V019 which delegates all work to private helpers. The phantom creation rule ensures that migrations referencing collections that existed historically but don't appear in the current `ensure_schema()` can still be replayed without errors. Warnings should include the migration name and a human-readable description of what was skipped or phantom-created.

### Phase 4: Public API + Integration Smoke Test
- [x] Implement the main public function `replay_migrations(base_shape: SchemaShape, migrations_dir: Path) -> tuple[SchemaShape, list[str]]` that clones `base_shape` into a `MutableSchemaShape`, discovers and sorts migrations, parses and replays each one via `_walk_upgrade`, collects warnings, and returns `(frozen_shape, warnings)`
    **Notes:** Implemented `replay_migrations(base_shape, migrations_dir)` that discovers migrations, converts to MutableSchemaShape, parses and walks each upgrade() function, collects warnings, freezes and returns (SchemaShape, warnings). Error handling wraps _parse_upgrade_function in try/except ValueError for robustness.
- [x] Add a `if __name__ == "__main__"` block that imports `parse_ensure_schema` from Plan A, parses Shape A from the real bootstrap file, calls `replay_migrations` with Shape A and the real migrations directory, prints the resulting Shape B summary (collection count, index count, graph count, seed doc count), and prints all warnings
    **Notes:** Added __main__ block that resolves project root from __file__, parses Shape A via parse_ensure_schema, calls replay_migrations, prints shape summaries (collection/index/graph/seed counts), all warnings, and a diff of collection names between shapes A and B. Exits 0 on success, 2 on missing paths.
- [x] Run the replayer against the real codebase and verify: (a) V004–V006 are skipped as verification-only, (b) V007/V008/V018 are skipped as dynamic with warnings, (c) V009/V017 are logged as data transforms, (d) V010–V016/V019 DDL operations are applied, (e) no crashes on any migration file
    **Notes:** All verified: (a) V004-V006 produce no mutations (verification-only), (b) V007/V008/V018 all show "Skipped dynamic loop" warnings, (c) V009/V017 logged as "AQL data transform (not validated)", (d) V010-V016/V019 DDL operations applied without errors, (e) zero crashes across all 16 migration files. 19 warnings total, all expected.
- [x] Verify Shape B contains the expected items: collections from Shape A plus any created-and-not-deleted by static migrations (e.g., `vram_promises` from V010, collections from V014/V016/V019), minus any deleted (e.g., `gpu_warmup_claims` from V012, `navidrome_song_map` from V019), with renames applied (e.g., `song_tag_edges` → `song_has_tags` from V013)
    **Notes:** Shape B matches Shape A exactly: 27 collections, 41 indexes, 2 graphs, 3 seed documents. Collection name sets are identical. V010 vram_promises (already in baseline), V012 gpu_warmup_claims deleted via phantom, V013 song_tag_edges renamed via phantom (baseline already has song_has_tags), V015 navidrome_song_map created then V019 deleted (net zero). All DDL replay-on-baseline produces the same shape, confirming the migrations and baseline are consistent.
- [x] Run `ruff check scripts/consolidate_migrations/` — zero errors required
    **Notes:** `ruff check scripts/consolidate_migrations/` passes with zero errors.

**Notes:** The expected net effect of static DDL migrations on Shape B relative to Shape A: V010 adds `vram_promises`, V011 removes its TTL index, V012 removes `gpu_warmup_claims`, V013 renames `song_tag_edges` to `song_has_tags`, V014 adds 3 collections + indexes, V015 adds `navidrome_song_map` + index, V016 adds `file_states` + `file_has_state` + indexes + seeds, V019 adds 5 collections + indexes + graph + drops `navidrome_song_map`. Since `ensure_schema()` (Shape A) already reflects the final state, the replay should produce a shape that equals or is very close to Shape A — differences indicate the replayer missed or mishandled an operation.

## Completion Criteria

- `scripts/consolidate_migrations/migration_replayer.py` exists with `replay_migrations(base_shape, migrations_dir)` as the public API
- `MutableSchemaShape` correctly converts to/from frozen `SchemaShape`
- All 16 migration files (V004–V019) are parsed without crashes
- Dynamic migrations (V007, V008, V018) are detected and skipped with warnings
- Data-transform migrations (V009, V017) are logged but don't modify shape
- Static DDL operations (create/delete/rename collection, add/delete index, create graph, insert seed) are correctly applied
- Phantom creation works for operations on missing items
- Rename-to-existing merges correctly
- `ruff check scripts/consolidate_migrations/` passes with zero errors
- No imports from `nomarr.*` at runtime — only `ast`, `pathlib`, `dataclasses`, `re`, `logging`, stdlib
- The `__main__` smoke test runs against the real codebase and produces a reasonable Shape B

## References

- **Prerequisite:** `plans/TASK-migration-consolidation-A-schema-model.md` — defines `SchemaShape`, `Collection`, `Index`, `Graph`, `EdgeDefinition`, `SeedDocument`, `is_blacklisted`
- **Design doc:** `plans/dev/design-migration-consolidation.md` — Shape B, Phantom Creation Rule, Migration Operations Inventory
- **Migration files:** `nomarr/migrations/V004_*.py` through `V019_*.py`
- **Part C plan (future):** comparator + CLI — consumes Shape A and Shape B from this plan
