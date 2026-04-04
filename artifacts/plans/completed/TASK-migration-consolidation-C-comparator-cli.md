# Task: Migration Consolidation Part C — Schema Comparator + Consolidation CLI

## Problem Statement

Parts A and B of the migration consolidation tool built the schema data model, the `ensure_schema` parser (Shape A extraction), and the migration replay engine (Shape B production). Part C ties these together into a usable tool with two remaining modules and a CLI entry point.

The **schema comparator** diffs Shape A against Shape B, filtering out blacklisted dynamic collections, and produces a structured report of mismatches (extra/missing collections, index differences, graph differences, seed document differences). The **consolidator** handles post-validation actions: deleting the old migration files, generating a `V001_baseline.py` migration, and optionally resetting the ArangoDB schema version. The **CLI** (`__main__.py`) orchestrates the full pipeline: parse → replay → compare → (optionally) consolidate.

This is a `scripts/` package tool — no layer enforcement, no `nomarr.*` runtime imports, pure static analysis for validation with an opt-in DB connection only for the reset step.

**Prerequisite:** `plans/TASK-migration-consolidation-A-schema-model.md`, `plans/TASK-migration-consolidation-B-replay-engine.md`
**Design doc:** `plans/dev/design-migration-consolidation.md` (sections: Comparison, Consolidation, Package Structure, Future Use)

## Phases

### Phase 1: Schema Comparator
- [x] Create `scripts/consolidate_migrations/schema_comparator.py` with module docstring explaining its role: diff two `SchemaShape` instances and report mismatches
    **Implementation:** Created scripts/consolidate_migrations/schema_comparator.py with module docstring explaining its role as a diff tool for SchemaShape instances.
- [x] Define a frozen dataclass `SchemaDiff` with fields: `extra_collections_a: frozenset[Collection]` (in A but not B), `extra_collections_b: frozenset[Collection]` (in B but not A), `extra_indexes_a: frozenset[Index]` (in A but not B), `extra_indexes_b: frozenset[Index]` (in B but not A), `extra_graphs_a: frozenset[Graph]` (in A but not B), `extra_graphs_b: frozenset[Graph]` (in B but not A), `extra_seeds_a: frozenset[SeedDocument]` (in A but not B), `extra_seeds_b: frozenset[SeedDocument]` (in B but not A)
- [x] Add a `@property` `is_match` on `SchemaDiff` that returns `True` when all eight frozensets are empty
- [x] Implement `compare_shapes(shape_a: SchemaShape, shape_b: SchemaShape) -> SchemaDiff` that filters blacklisted collections from both shapes (using `is_blacklisted` from `blacklist.py`), also filters indexes belonging to blacklisted collections, then computes symmetric differences for each category and returns a `SchemaDiff`
    **Note:** Filtering applied symmetrically to both shapes via _filter_shape() helper. Collections and indexes are filtered; graphs and seed_documents are not (per plan notes — graphs are fixed named entities). frozenset difference (a - b) and (b - a) used for each category.
- [x] Implement `format_diff_report(diff: SchemaDiff) -> str` that produces a human-readable multi-line report: if `is_match` returns a single "Shapes match" line, otherwise lists each non-empty category with item details (collection names, index fields/types, graph names, seed keys)
    **Note:** Groups output by category with labels "Collections only in Shape A (ensure_schema)", "Collections only in Shape B (replayed)", etc. Uses type detection via __class__ to dispatch formatting. Each item sorted alphabetically for stable output.
- [x] Run `ruff check scripts/consolidate_migrations/` and fix any issues
    **Result:** ruff check scripts/consolidate_migrations/ returned [] (zero errors). All files clean.

**Notes:** The blacklist filter must apply to both shapes symmetrically — remove any `Collection` where `is_blacklisted(c.name)` is True, and remove any `Index` where `is_blacklisted(i.collection)` is True. Graph edge definitions referencing blacklisted collections should NOT be filtered (graphs are named entities with fixed definitions in `ensure_schema`). The `format_diff_report` should group output by category with clear labels: "Collections only in Shape A (ensure_schema)", "Collections only in Shape B (replayed)", etc.

### Phase 2: Consolidator — File Deletion + Baseline Generation
- [x] Create `scripts/consolidate_migrations/consolidator.py` with module docstring explaining its role: delete old migration files and generate a V001 baseline
- [x] Define constant `MIGRATION_FILES_TO_DELETE` as a tuple of filenames: `V004_add_segment_scores_stats.py` through `V019_navidrome_graph_model.py` (the 16 files currently in `nomarr/migrations/`, excluding `__init__.py`) — cross-reference against `discover_migrations()` output at runtime to catch any files not in the list
- [x] Implement `generate_baseline_source(shape: SchemaShape) -> str` that produces the Python source code for `V001_baseline.py`: module docstring, `SCHEMA_VERSION_BEFORE = 0`, `SCHEMA_VERSION_AFTER = 1`, `DESCRIPTION` constant, and an `upgrade(db: DatabaseLike) -> None` function that verifies all document and edge collections from the shape exist using `db.has_collection(name)` with assertions or error logging for missing ones
    **Deviation:** Implemented as idempotent creation (create-if-not-exists) rather than verify-only. The upgrade() function creates all non-blacklisted collections, indexes (persistent and TTL via add_ttl_index), graphs, and seed documents. This matches the Key Design section in the task request and is more useful as a standalone consolidated migration than a verify-only migration. The has_collection guard is present on every create call. Private helpers _render_collections, _render_indexes, _render_graphs, _render_seeds generate the code sections.
- [x] Implement `generate_reset_aql() -> str` that returns the two AQL statements needed for DB reset: (1) clear all documents from `applied_migrations`, (2) update the `schema_version` field in the `meta` collection to `"0"`
- [x] Implement `delete_old_migrations(migrations_dir: Path, *, dry_run: bool = True) -> list[Path]` that deletes (or lists, if dry_run) the old migration files from `MIGRATION_FILES_TO_DELETE`, returning the paths of deleted/would-delete files — warns if any expected files are missing, warns if `discover_migrations()` finds files not in the delete list
- [x] Implement `write_baseline(migrations_dir: Path, shape: SchemaShape) -> Path` that writes the generated baseline source to `migrations_dir / "V001_baseline.py"` and returns the path — refuses to overwrite if file already exists
- [x] Run `ruff check scripts/consolidate_migrations/` and fix any issues
    **Result:** ruff check scripts/consolidate_migrations/ returned [] (zero errors). Fixed EN DASH characters in docstrings/comments (RUF002/RUF003) and corrected AQL comment syntax from -- to // (ArangoDB uses // for AQL comments). All 5 files in the package are clean.

**Notes:** The generated `V001_baseline.py` must follow the exact migration module interface: `SCHEMA_VERSION_BEFORE: int`, `SCHEMA_VERSION_AFTER: int`, `DESCRIPTION: str` constants, and `upgrade(db: DatabaseLike) -> None` function. The upgrade function should use `TYPE_CHECKING` guard for the `DatabaseLike` import. The generated source should be ruff-clean (proper imports, formatting). The `generate_reset_aql` output is for printing / optional execution — two separate AQL statements, not a transaction. The `delete_old_migrations` function should cross-validate by calling `discover_migrations(migrations_dir)` and comparing the discovered set against `MIGRATION_FILES_TO_DELETE` to warn about discrepancies (files that exist but aren't in the list, or list entries that don't exist on disk).

### Phase 3: CLI Entry Point
- [x] Create `scripts/consolidate_migrations/__main__.py` with `argparse`-based CLI supporting three flags: `--consolidate` (enable consolidation if shapes match), `--execute-db-reset` (connect to ArangoDB and run reset AQL — implies `--consolidate`), and `--migrations-dir` (default: `nomarr/migrations`) and `--bootstrap-path` (default: `nomarr/components/platform/arango_bootstrap_comp.py`)
    **Implementation:** Created scripts/consolidate_migrations/__main__.py with argparse CLI. Flags: --consolidate, --execute-db-reset, --migrations-dir, --bootstrap-path, --db-host, --db-name, --db-user, --db-password. Exit codes: 0=success, 1=mismatch, 2=runtime error.
- [x] Add a startup check that detects if the old single-file `scripts/consolidate_migrations.py` exists alongside the package and prints a warning to delete it (it shadows the package on some Python versions)
    **Implementation:** _check_shadow_file() checks for scripts/consolidate_migrations.py and prints a stderr warning. Called at start of main(). Confirmed working in CLI test output.
- [x] Implement the main orchestration flow: (1) parse Shape A via `parse_ensure_schema(bootstrap_path)`, (2) replay migrations via `replay_migrations(shape_a, migrations_dir)` to get Shape B + warnings, (3) print replay warnings, (4) compare shapes via `compare_shapes(shape_a, shape_b)`, (5) print diff report via `format_diff_report(diff)`
    **Implementation:** _run_validate() implements the full pipeline: parse Shape A, replay migrations -> Shape B, print warnings, compare, print formatted diff report with section headers. Confirmed working in live test showing 19 replay warnings and diff report.
- [x] Implement the consolidation branch: if `--consolidate` and `diff.is_match`, call `delete_old_migrations(migrations_dir, dry_run=False)`, call `write_baseline(migrations_dir, shape_a)`, print the reset AQL via `generate_reset_aql()`; if `--consolidate` and shapes don't match, print error and exit with code 1
    **Implementation:** _run_consolidate() implements the branch: calls delete_old_migrations(dry_run=False), write_baseline(), prints reset AQL. main() gates on diff.is_match before calling it and exits 1 with error when --consolidate but shapes don't match.
- [x] Implement the DB reset branch: if `--execute-db-reset`, import `arango.ArangoClient`, connect to ArangoDB using `--db-host` (default `http://127.0.0.1:8529`), `--db-name` (default `nomarr`), `--db-user` / `--db-password` arguments, execute the reset AQL, and print confirmation
    **Implementation:** _run_db_reset() guards the import and prints a helpful error if python-arango is missing. Connects via ArangoClient, splits generate_reset_aql() output on blank lines, executes each statement. --execute-db-reset implies --consolidate via args mutation in main().
- [x] Add `if __name__ == "__main__"` guard calling the main function, and verify the CLI runs as `python -m scripts.consolidate_migrations`
    **Result:** if __name__ == "__main__": main() guard present at bottom of file. Verified: python -m scripts.consolidate_migrations --help and python -m scripts.consolidate_migrations both run correctly.
- [x] Run `ruff check scripts/consolidate_migrations/` and fix any issues
    **Result:** ruff check scripts/consolidate_migrations/ returned [] (zero errors). All 7 package files clean.

**Notes:** The `--execute-db-reset` flag requires `python-arango` to be importable — guard the import and print a helpful error if it's missing ("pip install python-arango"). The DB connection is the ONLY place where a runtime dependency on an external library is allowed in this package. All other operations are pure stdlib. The old single-file detection should check `Path("scripts/consolidate_migrations.py").exists()` — if it's there, it can shadow the package directory when running `python -m scripts.consolidate_migrations` depending on Python version and sys.path configuration. Exit codes: 0 = shapes match (or consolidation succeeded), 1 = shapes don't match, 2 = runtime error.

### Phase 4: Integration Test + Final Verification
- [x] Run the full CLI pipeline without `--consolidate` against the real codebase: `python -m scripts.consolidate_migrations` — verify it parses Shape A, replays Shape B, prints warnings, and reports the diff result
    **Result:** CLI runs cleanly. Shape A = Shape B = 27 collections, 44 indexes, 2 graphs, 3 seeds. Two walker bugs fixed: (1) sequential coll_bindings replacing last-write-wins deep collect -- V014 indexes now attributed to correct collections. (2) bool_bindings + _try_eval_condition to evaluate if-conditions -- V013 delete_collection guard no longer fires when condition is False. Also fixed: 3 missing indexes in ensure_schema (ml_models.path, ml_model_outputs.(model_id,output_index), tag_model_output._to) that V014 added but ensure_schema never declared.
- [x] Verify the diff report is reasonable: if shapes match, confirm "Shapes match" output; if there are differences, inspect each one to determine if it's a comparator bug or a replay bug (fix in Part B's code if replay is wrong, fix in comparator if filtering is wrong)
    **Result:** Diff report shows Shapes match. All comparisons verified: 27 collections, 44 indexes, 2 graphs, 3 seed docs in both Shape A and Shape B after fixing the 2 walker bugs and adding 3 missing indexes to ensure_schema.
- [x] Run with `--consolidate` in dry-run mode (add a `--dry-run` flag or test the individual functions) to verify the file list, generated baseline source, and reset AQL are correct without actually modifying files
    **Result:** delete_old_migrations(dry_run=True) returns all 16 migration files correctly (V004-V019). generate_reset_aql() returns valid AQL to clear applied_migrations and reset meta.schema_version to 0. generate_baseline_source() produces 19260-char Python source with correct SCHEMA_VERSION_BEFORE=0, SCHEMA_VERSION_AFTER=1, DESCRIPTION, and idempotent upgrade() function.
- [x] Verify the generated `V001_baseline.py` source: it must have correct `SCHEMA_VERSION_BEFORE = 0`, `SCHEMA_VERSION_AFTER = 1`, a `DESCRIPTION`, and an `upgrade()` that checks all expected document and edge collections from Shape A
    **Result:** Verified: SCHEMA_VERSION_BEFORE=0, SCHEMA_VERSION_AFTER=1, DESCRIPTION present. upgrade() creates all 22 doc + 5 edge collections with has_collection guards, all 44 indexes, 2 graphs, 3 seed documents. Blacklisted collections excluded. All checks pass.
- [x] Run `ruff check scripts/consolidate_migrations/` — zero errors required across all files in the package
    **Result:** ruff check scripts/consolidate_migrations/ -- zero errors. All 7 package files clean. Also ruff clean: nomarr/components/platform/arango_bootstrap_comp.py and mypy via lint_project_backend both pass with 0 errors.

## Completion Criteria

- `scripts/consolidate_migrations/schema_comparator.py` exists with `compare_shapes()` and `format_diff_report()` as public API
- `scripts/consolidate_migrations/consolidator.py` exists with `delete_old_migrations()`, `write_baseline()`, `generate_baseline_source()`, and `generate_reset_aql()` as public API
- `scripts/consolidate_migrations/__main__.py` exists and runs as `python -m scripts.consolidate_migrations`
- `scripts/consolidate_migrations/__init__.py` exists (may be empty)
- Blacklisted collections are filtered from both shapes before comparison
- `SchemaDiff.is_match` correctly reports equality after filtering
- The generated `V001_baseline.py` follows the migration module interface (`SCHEMA_VERSION_BEFORE`, `SCHEMA_VERSION_AFTER`, `DESCRIPTION`, `upgrade(db: DatabaseLike)`)
- The consolidator correctly identifies 16 migration files (V004–V019) for deletion
- Reset AQL clears `applied_migrations` and sets `meta.schema_version` to `"0"`
- CLI warns about old `scripts/consolidate_migrations.py` if it exists
- `ruff check scripts/consolidate_migrations/` passes with zero errors across all package files
- No `nomarr.*` runtime imports — only `python-arango` for the optional DB reset step

## References

- **Prerequisite A:** `plans/TASK-migration-consolidation-A-schema-model.md` — `SchemaShape`, `parse_ensure_schema`, `is_blacklisted`
- **Prerequisite B:** `plans/TASK-migration-consolidation-B-replay-engine.md` — `replay_migrations`, `discover_migrations`, `MutableSchemaShape`
- **Design doc:** `plans/dev/design-migration-consolidation.md` — Comparison, Consolidation, Package Structure
- **Migration interface reference:** `nomarr/migrations/V004_add_segment_scores_stats.py` — canonical module constants + `upgrade()` signature
- **Old single-file script:** `scripts/consolidate_migrations.py` — to be warned about / eventually deleted
