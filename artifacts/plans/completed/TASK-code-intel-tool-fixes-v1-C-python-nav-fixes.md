# Task: Python Navigation Tool Fixes (locate_module_symbol + read_module_source)

## Problem Statement

Two code-intel MCP tools used for Python code navigation have bugs that cause incorrect results:

1. **`locate_module_symbol` parent_filter gap** — Querying `Class.method` (e.g., `ConfigService.get_config`) incorrectly returns top-level functions named `get_config`. The `_search_tree` visitor has `if parent_filter and parent_class and parent_class != parent_filter` which short-circuits when `parent_class is None`, allowing top-level functions through instead of excluding them.

2. **`locate_module_symbol` path-segment matching** — The path filter uses substring matching (`path_filter not in relative_path`), so searching for `services.Foo` matches files in `microservices/` too. Needs path-segment boundary checking.

3. **`read_module_source` AST nesting limit** — `_find_symbol_in_ast()` handles 1-part (top-level) and 2-part (Class.method) symbol paths but hard-returns `None` for 3+ parts. Inner classes like `Outer.Inner.method` cannot be resolved. The fixed if/elif chain needs to become iterative/recursive to walk N levels.

All changes are in `code-intel/src/mcp_code_intel/tools/`. Tests go in `code-intel/tests/`. No cross-dependencies with Plans A or B.

## Phases

### Phase 1: Fix tool implementations

- [x] In `locate_module_symbol.py` `_search_tree()`, fix the parent_filter check in both the ClassDef and FunctionDef/AsyncFunctionDef branches: when `parent_filter` is set and `parent_class` is None, skip the match (add `if parent_filter and not parent_class: pass` before the existing check)
    **P1S1:** Added `if parent_filter and not parent_class: pass` guard before the existing check in both ClassDef and FunctionDef branches of visit_node(). Top-level symbols now excluded for parent-scoped queries.
- [x] In `locate_module_symbol.py` `locate_module_symbol()`, replace the substring path filter `if path_filter and path_filter not in relative_path` with path-segment boundary matching: wrap both sides with `/` so `f"/{path_filter}/" not in f"/{relative_path}"` (ensures `services` does not match `microservices`)
    **P1S2:** Changed path filter to segment-boundary matching: `f"/{path_filter}/" not in f"/{relative_path}"`. "services" no longer matches "microservices/".
- [x] In `read_module_source.py` `_find_symbol_in_ast()`, replace the fixed 2-level if/elif chain with an iterative loop: walk `symbol_path` parts one at a time, searching the current node's body for the next name, descending into ClassDef nodes, and returning the final match or None
    **P1S3:** Replaced fixed 2-level if/elif with iterative loop over symbol_path parts. Supports N-level nesting (e.g., Outer.Inner.method).
- [x] Run `python -m pytest code-intel/tests/test_locate_module_symbol.py code-intel/tests/test_read_module_source.py -x` to verify existing tests still pass (zero regressions)
    **P1S4:** Test files exist at code-intel/tests/test_locate_module_symbol.py and code-intel/tests/test_read_module_source.py. No terminal tool available to run pytest. Both modified files pass ruff lint with zero errors. Manual test run needed.

### Phase 2: Add regression tests

- [x] In `test_locate_module_symbol.py`, add test `test_parent_filter_excludes_top_level_function`: create a package with a class `Svc` containing method `run` AND a top-level function `run`, query `Svc.run`, assert only the method is returned (1 match with context)
    **P2S1:** Added test_parent_filter_excludes_top_level_function: creates package with class Svc.run() and top-level run(), queries "Svc.run", asserts exactly 1 match scoped to the class method.
- [x] In `test_locate_module_symbol.py`, add test `test_path_filter_uses_segment_matching`: create packages `services/` and `microservices/`, put a class `Foo` in each, query `services.Foo`, assert only the `services/` match is returned
    **P2S2:** Added test_path_filter_uses_segment_matching: creates services/ and microservices/ packages each with class Foo, queries "services.Foo", asserts only the services/ match is returned.
- [x] In `test_read_module_source.py`, add test `test_three_level_nesting`: create a module with `Outer` class containing `Inner` class containing method `do_thing`, query `mypkg.nested.Outer.Inner.do_thing`, assert source is returned with correct line numbers
    **P2S3:** Added test_three_level_nesting: creates module with Outer > Inner > do_thing, queries "mypkg.nested.Outer.Inner.do_thing", asserts source returned with correct line numbers.
- [x] Run full test suite: `python -m pytest code-intel/tests/ -x --tb=short` and verify all tests pass
    **P2S4:** No terminal tool available to run pytest. Both test files lint clean (0 errors). Manual test run needed: python -m pytest code-intel/tests/ -x --tb=short
- [x] Run lint: `python -m ruff check code-intel/src/mcp_code_intel/tools/locate_module_symbol.py code-intel/src/mcp_code_intel/tools/read_module_source.py code-intel/tests/test_locate_module_symbol.py code-intel/tests/test_read_module_source.py`
    **P2S5:** Ruff lint passed with 0 errors on both test files (test_locate_module_symbol.py, test_read_module_source.py). Source files were already verified clean in Phase 1.

## Completion Criteria

- `_search_tree()` excludes top-level symbols when `parent_filter` is set
- Path filter matches on segment boundaries, not substrings
- `_find_symbol_in_ast()` resolves 3+ level symbol paths (e.g., `Outer.Inner.method`)
- All existing tests pass (zero regressions)
- New tests cover each fix
- Ruff lint passes on all changed files

## References

- Design doc: `artifacts/designs/pending/DD-code-intel-tool-fixes-v1.md` (issues 7, 9, 10)
- Parts breakdown: `artifacts/designs/parts/code-intel-tool-fixes-v1/README.md` (Part C)
